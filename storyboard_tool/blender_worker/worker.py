"""Single-threaded headless Blender worker for Storyboarder's built-in viewport."""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import bpy
from mathutils import Vector


HERE = Path(__file__).resolve().parent
PACKAGE_ROOT = HERE.parent
ADDON_ROOT = PACKAGE_ROOT / "blender_addon"
if str(ADDON_ROOT) not in sys.path:
    sys.path.insert(0, str(ADDON_ROOT))

from storyboarder_camera_path import create_camera_path  # noqa: E402


TEMP_FRAME = Path(tempfile.gettempdir()) / f"storyboarder_bpy_frame_{os.getpid()}.jpg"
INTERNAL_CAMERA_NAME = "SB_InternalViewportCamera"
SERVER: HTTPServer | None = None
TOKEN = ""


def _number(query: dict[str, list[str]], key: str, default: float) -> float:
    try:
        return float(query.get(key, [str(default)])[0])
    except (TypeError, ValueError):
        return default


def _orbit_camera(
    scene: bpy.types.Scene,
    *,
    yaw: float,
    pitch: float,
    distance: float,
    target: Vector,
) -> bpy.types.Object:
    camera = bpy.data.objects.get(INTERNAL_CAMERA_NAME)
    if camera is None or camera.type != "CAMERA":
        camera_data = bpy.data.cameras.new(INTERNAL_CAMERA_NAME)
        camera = bpy.data.objects.new(INTERNAL_CAMERA_NAME, camera_data)
        scene.collection.objects.link(camera)
    camera.location = (
        target.x + distance * math.cos(pitch) * math.sin(yaw),
        target.y - distance * math.cos(pitch) * math.cos(yaw),
        target.z + distance * math.sin(pitch),
    )
    camera.rotation_euler = (target - camera.location).to_track_quat("-Z", "Y").to_euler()
    return camera


def _configure_scene() -> None:
    scene = bpy.context.scene
    try:
        scene.render.engine = "BLENDER_WORKBENCH"
    except TypeError:
        pass
    scene.render.image_settings.file_format = "JPEG"
    scene.render.image_settings.quality = 82
    scene.render.resolution_percentage = 100
    try:
        scene.display.shading.light = "STUDIO"
        scene.display.shading.color_type = "MATERIAL"
        scene.display.shading.show_shadows = True
        scene.display.shading.show_cavity = True
    except (AttributeError, TypeError):
        pass


def _render(query: dict[str, list[str]]) -> tuple[bytes, float]:
    scene = bpy.context.scene
    width = max(64, min(1920, int(_number(query, "w", 960))))
    height = max(64, min(1080, int(_number(query, "h", 540))))
    frame = int(_number(query, "frame", scene.frame_current))
    scene.frame_set(max(scene.frame_start, min(scene.frame_end, frame)))
    requested_camera = query.get("camera", ["orbit"])[0]
    original_camera = scene.camera
    if requested_camera == "scene" and original_camera is not None:
        render_camera = original_camera
    else:
        target = Vector(
            (
                _number(query, "target_x", 0.0),
                _number(query, "target_y", 0.0),
                _number(query, "target_z", 0.0),
            )
        )
        render_camera = _orbit_camera(
            scene,
            yaw=_number(query, "yaw", 0.6),
            pitch=max(-1.45, min(1.45, _number(query, "pitch", 0.5))),
            distance=max(0.1, _number(query, "dist", 9.0)),
            target=target,
        )
    scene.camera = render_camera
    scene.render.resolution_x = width
    scene.render.resolution_y = height
    scene.render.filepath = str(TEMP_FRAME)
    started = time.perf_counter()
    bpy.ops.render.render(write_still=True)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    scene.camera = original_camera if original_camera is not None else render_camera
    return TEMP_FRAME.read_bytes(), elapsed_ms


def _screen_points_to_ground(payload: dict[str, object]) -> list[Vector]:
    scene = bpy.context.scene
    width = max(64, int(payload.get("width", 960)))
    height = max(64, int(payload.get("height", 540)))
    target_values = payload.get("target") or [0.0, 0.0, 0.0]
    target = Vector(tuple(float(value) for value in target_values[:3]))
    camera = _orbit_camera(
        scene,
        yaw=float(payload.get("yaw", 0.6)),
        pitch=max(-1.45, min(1.45, float(payload.get("pitch", 0.5)))),
        distance=max(0.1, float(payload.get("distance", 9.0))),
        target=target,
    )
    scene.render.resolution_x = width
    scene.render.resolution_y = height
    frame = camera.data.view_frame(scene=scene)
    min_x = min(corner.x for corner in frame)
    max_x = max(corner.x for corner in frame)
    min_y = min(corner.y for corner in frame)
    max_y = max(corner.y for corner in frame)
    plane_z = target.z
    world_points: list[Vector] = []
    for raw in payload.get("points") or []:
        if not isinstance(raw, list) or len(raw) < 2:
            continue
        nx = max(0.0, min(1.0, float(raw[0])))
        ny = max(0.0, min(1.0, float(raw[1])))
        local_point = Vector(
            (
                min_x + (max_x - min_x) * nx,
                min_y + (max_y - min_y) * (1.0 - ny),
                frame[0].z,
            )
        )
        direction = camera.matrix_world.to_quaternion() @ local_point.normalized()
        if abs(direction.z) < 1e-8:
            continue
        distance = (plane_z - camera.location.z) / direction.z
        if distance <= 0.0:
            continue
        world_points.append(camera.location + direction * distance)
    return world_points


def _remove_internal_camera() -> None:
    camera = bpy.data.objects.get(INTERNAL_CAMERA_NAME)
    if camera is not None:
        camera_data = camera.data
        bpy.data.objects.remove(camera, do_unlink=True)
        if camera_data is not None and camera_data.users == 0:
            bpy.data.cameras.remove(camera_data)


def _save_scene() -> Path:
    _remove_internal_camera()
    filepath = str(bpy.data.filepath or "").strip()
    if not filepath:
        raise ValueError("The built-in Blender scene has no .blend file path.")
    path = Path(filepath)
    bpy.ops.wm.save_as_mainfile(filepath=str(path))
    return path


class Handler(BaseHTTPRequestHandler):
    server_version = "StoryboarderBpy/0.1"

    def log_message(self, _format: str, *_args: object) -> None:
        pass

    def _authorized(self) -> bool:
        return bool(TOKEN) and self.headers.get("X-Storyboarder-Worker-Token", "") == TOKEN

    def _send(
        self,
        code: int,
        body: bytes,
        content_type: str,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, payload: dict[str, object]) -> None:
        self._send(code, json.dumps(payload).encode("utf-8"), "application/json")

    def _read_json(self) -> dict[str, object]:
        try:
            size = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            size = 0
        if size <= 0 or size > 4 * 1024 * 1024:
            raise ValueError("Invalid request body.")
        payload = json.loads(self.rfile.read(size))
        if not isinstance(payload, dict):
            raise ValueError("Request body must be an object.")
        return payload

    def do_GET(self) -> None:  # noqa: N802
        if not self._authorized():
            self._send(403, b"forbidden", "text/plain")
            return
        parsed = urlparse(self.path)
        if parsed.path == "/healthz":
            self._json(200, {"ok": True, "blender": bpy.app.version_string})
            return
        if parsed.path == "/frame":
            try:
                image, render_ms = _render(parse_qs(parsed.query))
            except Exception as exc:  # noqa: BLE001
                self._json(500, {"error": str(exc)})
                return
            self._send(
                200,
                image,
                "image/jpeg",
                {"X-Render-ms": f"{render_ms:.1f}"},
            )
            return
        self._send(404, b"not found", "text/plain")

    def do_POST(self) -> None:  # noqa: N802
        if not self._authorized():
            self._send(403, b"forbidden", "text/plain")
            return
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/camera-path":
                payload = self._read_json()
                points = _screen_points_to_ground(payload)
                if len(points) < 2:
                    raise ValueError(
                        "The drawn line did not intersect the target plane. Orbit above the plane and try again."
                    )
                target = payload.get("target") or [0.0, 0.0, 0.0]
                result = create_camera_path(
                    bpy.context,
                    points,
                    duration_frames=int(payload.get("duration_frames", 120)),
                    target_location=target,
                )
                path = _save_scene()
                self._json(
                    200,
                    {
                        "ok": True,
                        "path": result["path"].name,
                        "camera": result["camera"].name,
                        "target": result["target"].name,
                        "blend_path": str(path),
                        "point_count": len(points),
                    },
                )
                return
            if parsed.path == "/save":
                path = _save_scene()
                self._json(200, {"ok": True, "blend_path": str(path)})
                return
            if parsed.path == "/shutdown":
                self._json(200, {"ok": True})
                if SERVER is not None:
                    threading.Thread(target=SERVER.shutdown, daemon=True).start()
                return
        except Exception as exc:  # noqa: BLE001
            self._json(400, {"error": str(exc)})
            return
        self._send(404, b"not found", "text/plain")


def _parse_args() -> argparse.Namespace:
    args = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--token", required=True)
    return parser.parse_args(args)


def main() -> None:
    global SERVER, TOKEN
    options = _parse_args()
    TOKEN = str(options.token)
    _configure_scene()
    SERVER = HTTPServer(("127.0.0.1", int(options.port)), Handler)
    try:
        SERVER.serve_forever()
    finally:
        SERVER.server_close()
        try:
            TEMP_FRAME.unlink(missing_ok=True)
        except OSError:
            pass


if __name__ == "__main__":
    main()
