"""Minimal bpy solid-frame render worker (route C, progressive frame streaming).

This is a SEPARATE PROCESS by necessity: bpy pins numpy<2 while the app's opencv
needs numpy>=2, so the render engine can never be imported into the main FastAPI
app. It runs in spikes/.venv-bpy and talks HTTP.

Design:
  - Load the .blend ONCE at startup and keep the scene resident (warm renders stay
    ~20-30ms; the ~500ms cold-start happens only at boot).
  - Single-threaded HTTP server: bpy is NOT thread-safe, so renders must serialize.
    BaseHTTPServer (one request at a time) is exactly the right model here.
  - GET /frame?w=&h=&yaw=&pitch=&dist=  -> image/jpeg of the solid viewport.
  - GET /healthz                        -> readiness probe.
  - GET /                              -> the drag-to-orbit demo page.

Run via spikes/render_server/run.ps1 (or run.sh), which uses the isolated venv.
NOT production code: renders via bpy.ops.render.render to a temp JPEG. A real
server would render to an in-memory buffer and stream over a persistent socket.
"""

from __future__ import annotations

import math
import os
import sys
import tempfile
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import bpy
import mathutils

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
DEFAULT_BLEND = REPO / "storyboard_tool" / "assets" / "scene_template.blend"
INDEX_HTML = HERE / "index.html"
_TEMP_FRAME = Path(tempfile.gettempdir()) / "route_c_frame.jpg"

# Orbit target the camera looks at. The template's content sits near the origin.
TARGET = mathutils.Vector((0.0, 0.0, 0.0))


def _inject_demo_geometry_if_empty() -> None:
    """The bundled template renders blank (objects out of frame). For a runnable
    demo, drop in some geometry so /frame shows something. A real .blend won't
    need this."""
    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    if meshes:
        return
    bpy.ops.mesh.primitive_monkey_add(location=(0, 0, 0))
    for ix in range(-2, 3):
        for iy in range(-2, 3):
            bpy.ops.mesh.primitive_cube_add(size=0.6, location=(ix * 1.4, iy * 1.4, -1.2))


def init_scene(blend: Path) -> None:
    if blend.is_file():
        bpy.ops.wm.open_mainfile(filepath=str(blend))
    _inject_demo_geometry_if_empty()

    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"  # == solid shading
    scene.render.image_settings.file_format = "JPEG"
    scene.render.image_settings.quality = 80
    scene.render.resolution_percentage = 100
    try:
        shading = scene.display.shading
        shading.light = "STUDIO"
        shading.color_type = "OBJECT"
        shading.show_shadows = False
    except Exception as exc:  # noqa: BLE001 - shading attrs vary by version
        print(f"[worker] shading detail skipped: {exc}", file=sys.stderr)

    if scene.camera is None:
        cam_data = bpy.data.cameras.new("RouteCCam")
        cam = bpy.data.objects.new("RouteCCam", cam_data)
        scene.collection.objects.link(cam)
        scene.camera = cam

    # Warm the pipeline so the first real request isn't the cold frame.
    _render(scene, 320, 180, yaw=0.6, pitch=0.5, dist=9.0)
    print("[worker] scene resident & pipeline warm")


def _render(scene, w: int, h: int, yaw: float, pitch: float, dist: float) -> bytes:
    """Position the orbit camera and render one solid JPEG frame -> bytes."""
    cam = scene.camera
    cx = TARGET.x + dist * math.cos(pitch) * math.sin(yaw)
    cy = TARGET.y - dist * math.cos(pitch) * math.cos(yaw)
    cz = TARGET.z + dist * math.sin(pitch)
    cam.location = (cx, cy, cz)
    direction = TARGET - mathutils.Vector(cam.location)
    cam.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()

    scene.render.resolution_x = w
    scene.render.resolution_y = h
    scene.render.filepath = str(_TEMP_FRAME)
    bpy.ops.render.render(write_still=True)
    return _TEMP_FRAME.read_bytes()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args) -> None:  # silence per-request stderr spam
        pass

    def _send(self, code: int, body: bytes, content_type: str, extra: dict | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - http.server API
        parsed = urlparse(self.path)
        if parsed.path == "/healthz":
            self._send(200, b"ok", "text/plain")
            return
        if parsed.path in ("/", "/index.html"):
            html = INDEX_HTML.read_bytes() if INDEX_HTML.is_file() else b"<h1>no demo page</h1>"
            self._send(200, html, "text/html; charset=utf-8")
            return
        if parsed.path == "/frame":
            q = parse_qs(parsed.query)

            def num(key: str, default: float) -> float:
                try:
                    return float(q.get(key, [default])[0])
                except (TypeError, ValueError):
                    return default

            w = max(64, min(1920, int(num("w", 1280))))
            h = max(64, min(1080, int(num("h", 720))))
            t0 = time.perf_counter()
            img = _render(bpy.context.scene, w, h,
                          yaw=num("yaw", 0.6), pitch=num("pitch", 0.5), dist=num("dist", 9.0))
            ms = (time.perf_counter() - t0) * 1000.0
            self._send(200, img, "image/jpeg", {"X-Render-ms": f"{ms:.1f}"})
            return
        self._send(404, b"not found", "text/plain")


def main() -> None:
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    blend = Path(argv[0]) if argv and argv[0] and not argv[0].isdigit() else DEFAULT_BLEND
    port = int(os.environ.get("ROUTE_C_PORT", "8765"))
    for a in argv:
        if a.isdigit():
            port = int(a)

    print(f"[worker] bpy {bpy.app.version_string} | loading {blend}")
    init_scene(blend)
    server = HTTPServer(("127.0.0.1", port), Handler)
    print(f"[worker] serving on http://127.0.0.1:{port}  (GET / for demo, /frame for image)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[worker] bye")


if __name__ == "__main__":
    main()
