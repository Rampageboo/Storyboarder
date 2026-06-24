"""Spike: can we render a SOLID-shaded viewport frame from a .blend headlessly,
fast enough to stream to the frontend?

This answers the one assumption the "route C" (bpy reads .blend directly, streams a
solid-shading viewport to the frontend) architecture rests on:

  1. RENDER TIME  -- how many ms to produce one solid frame at viewport resolution?
  2. GL CONTEXT   -- can a true offscreen *viewport* draw work without a window
                     (the historically fragile part of headless bpy)?

It runs two independent tests, because they answer different questions:

  Test A -- Workbench render (bpy.ops.render.render, engine=BLENDER_WORKBENCH).
            Workbench *is* solid shading as a render engine. This path is the
            robust headless one; it almost always works and gives a clean
            "ms per solid frame" number. It's a slight over-estimate vs a live
            viewport draw (it spins the full render pipeline each frame).

  Test B -- True viewport offscreen (gpu.types.GPUOffScreen + draw_view3d).
            This is the actual primitive a viewport-streaming server would call.
            It needs a GL context + a 3D view region, which a fully headless
            process may not have. If this FAILS, route C must either run real
            Blender with a (hidden) window / EGL context, or fall back to Test A.

----------------------------------------------------------------------------
HOW TO RUN
----------------------------------------------------------------------------
Option 1 -- bpy as a pip module (Python 3.11 required):

    python -m pip install bpy
    python spikes/bpy_solid_viewport_spike.py [path/to/file.blend] [WIDTHxHEIGHT] [frames]

Option 2 -- via a real Blender install (more representative of a streaming server):

    blender --background path/to/file.blend --python spikes/bpy_solid_viewport_spike.py

Defaults: uses storyboard_tool/assets/scene_template.blend, 1280x720, 30 frames.
Saves one proof PNG next to this script as spike_solid_frame.png.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

try:
    import bpy
except ModuleNotFoundError:
    print(
        "[FATAL] No 'bpy' module.\n"
        "  - Install it:  python -m pip install bpy   (needs Python 3.11)\n"
        "  - Or run via:  blender --background <file.blend> --python "
        + __file__
    )
    sys.exit(2)


HERE = Path(__file__).resolve().parent
REPO = HERE.parent
DEFAULT_BLEND = REPO / "storyboard_tool" / "assets" / "scene_template.blend"
PROOF_PNG = HERE / "spike_solid_frame.png"


def _parse_args(argv: list[str]) -> tuple[Path, int, int, int]:
    """argv may include Blender's own args; we only read trailing extras after '--'."""
    if "--" in argv:
        argv = argv[argv.index("--") + 1 :]
    else:
        # Running under `python script.py ...` -> argv[0] is the script.
        argv = argv[1:] if argv and argv[0].endswith(".py") else argv

    blend = Path(argv[0]) if len(argv) >= 1 and argv[0] else DEFAULT_BLEND
    width, height = 1280, 720
    if len(argv) >= 2 and "x" in argv[1].lower():
        w, h = argv[1].lower().split("x", 1)
        width, height = int(w), int(h)
    frames = int(argv[2]) if len(argv) >= 3 else 30
    return blend, width, height, frames


def _open_blend(blend: Path) -> None:
    # When launched via `blender --background file.blend`, the file is already open
    # and re-opening a missing path would wipe it. Only open if we have a real file
    # and it isn't already the loaded one.
    if blend.is_file():
        already = Path(bpy.data.filepath or "").resolve()
        if already != blend.resolve():
            bpy.ops.wm.open_mainfile(filepath=str(blend))
    print(f"[scene] file       : {bpy.data.filepath or '(unsaved / default)'}")
    print(f"[scene] objects    : {len(bpy.data.objects)}")
    cams = [o for o in bpy.data.objects if o.type == "CAMERA"]
    print(f"[scene] cameras    : {len(cams)}")


def _ensure_visible_geometry() -> None:
    """The bundled template renders empty (objects out of frame). Inject a
    representative triangle load and aim a camera at it, so Test A measures a
    real solid render instead of a blank background."""
    import mathutils

    scene = bpy.context.scene
    # Suzanne = a few thousand tris; a small grid of cubes adds object count
    # (object color shading cost scales with object/material count, not just tris).
    bpy.ops.mesh.primitive_monkey_add(location=(0, 0, 0))
    for ix in range(-2, 3):
        for iy in range(-2, 3):
            bpy.ops.mesh.primitive_cube_add(size=0.6, location=(ix * 1.4, iy * 1.4, -1.2))

    cam = scene.camera
    if cam is None:
        cam_data = bpy.data.cameras.new("SpikeCam")
        cam = bpy.data.objects.new("SpikeCam", cam_data)
        scene.collection.objects.link(cam)
        scene.camera = cam
    cam.location = (6.0, -6.0, 4.5)
    direction = mathutils.Vector((0, 0, 0)) - cam.location
    cam.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    print(f"[scene] injected   : Suzanne + 25 cubes, camera reframed")
    print(f"[scene] objects now : {len(bpy.data.objects)}")


def _configure_solid(width: int, height: int) -> None:
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"  # == solid shading
    scene.render.resolution_x = width
    scene.render.resolution_y = height
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    # Workbench / solid look: flat-ish, single light, object color. No materials.
    try:
        ws = scene.display.shading
        ws.light = "STUDIO"
        ws.color_type = "OBJECT"
        ws.show_shadows = False
        ws.show_cavity = False
    except Exception as exc:  # noqa: BLE001 - shading attrs vary by version
        print(f"[warn ] could not set workbench shading detail: {exc}")
    if scene.camera is None:
        cams = [o for o in bpy.data.objects if o.type == "CAMERA"]
        if cams:
            scene.camera = cams[0]


def test_a_workbench_render(width: int, height: int, frames: int) -> None:
    print("\n=== Test A: Workbench (solid) render via bpy.ops.render.render ===")
    scene = bpy.context.scene
    cam = scene.camera

    # First render is cold (shader/pipeline init) -- report it separately.
    t0 = time.perf_counter()
    bpy.ops.render.render(write_still=False)
    cold_ms = (time.perf_counter() - t0) * 1000.0
    print(f"  cold frame : {cold_ms:8.1f} ms  (one-time init, ignore for streaming)")

    times: list[float] = []
    for i in range(frames):
        # Nudge the camera each frame so we measure real renders, not a cached result.
        if cam is not None:
            cam.rotation_euler[2] += 0.02
        t0 = time.perf_counter()
        bpy.ops.render.render(write_still=False)
        times.append((time.perf_counter() - t0) * 1000.0)

    times.sort()
    warm_avg = sum(times) / len(times)
    p50 = times[len(times) // 2]
    p95 = times[min(len(times) - 1, int(len(times) * 0.95))]
    print(f"  warm avg   : {warm_avg:8.1f} ms")
    print(f"  p50 / p95  : {p50:8.1f} / {p95:.1f} ms")
    print(f"  ~fps (p50) : {1000.0 / p50:8.1f}")

    # Save one frame as visual proof.
    scene.render.filepath = str(PROOF_PNG)
    bpy.ops.render.render(write_still=True)
    print(f"  proof png  : {PROOF_PNG}")
    _verdict("Test A", p50)


def test_b_viewport_offscreen(width: int, height: int, frames: int) -> None:
    print("\n=== Test B: True viewport offscreen (gpu.GPUOffScreen + draw_view3d) ===")
    try:
        import gpu
    except Exception as exc:  # noqa: BLE001
        print(f"  [SKIP] no 'gpu' module: {exc}")
        return

    # draw_view3d needs a real 3D-view region + space, which only exist with a window.
    win = bpy.context.window_manager.windows[0] if bpy.context.window_manager.windows else None
    if win is None:
        print("  [FAIL] no window in this process -> no 3D-view region available.")
        print("         => fully-headless bpy cannot drive draw_view3d directly.")
        print("         => streaming server must run Blender with a (hidden) window")
        print("            or an EGL GL context. Test A is the headless fallback.")
        return

    area = next((a for a in win.screen.areas if a.type == "VIEW_3D"), None)
    if area is None:
        print("  [FAIL] window exists but has no VIEW_3D area.")
        return
    region = next((r for r in area.regions if r.type == "WINDOW"), None)
    space = area.spaces.active
    scene = bpy.context.scene
    view_layer = bpy.context.view_layer
    cam = scene.camera

    try:
        offscreen = gpu.types.GPUOffScreen(width, height)
    except Exception as exc:  # noqa: BLE001
        print(f"  [FAIL] could not create GPUOffScreen (no GL context?): {exc}")
        return

    view_matrix = cam.matrix_world.inverted()
    projection_matrix = cam.calc_matrix_camera(
        bpy.context.evaluated_depsgraph_get(), x=width, y=height
    )

    times: list[float] = []
    try:
        for _ in range(frames):
            t0 = time.perf_counter()
            offscreen.draw_view3d(
                scene, view_layer, space, region, view_matrix, projection_matrix,
                do_color_management=False,
            )
            times.append((time.perf_counter() - t0) * 1000.0)
    except Exception as exc:  # noqa: BLE001
        print(f"  [FAIL] draw_view3d raised: {exc}")
        offscreen.free()
        return
    offscreen.free()

    # Read pixels back and check they actually contain rendered geometry.
    # A headless no-op leaves a uniform/empty buffer at implausible speed,
    # or the texture is invalid the moment we touch it.
    import numpy as np

    spread = -1.0
    readback_error = ""
    try:
        buf = offscreen.texture_color.read()
        buf.dimensions = width * height * 4
        pixels = np.array(buf, dtype=np.float32)
        spread = float(pixels.max() - pixels.min())
    except Exception as exc:  # noqa: BLE001
        readback_error = str(exc)
    finally:
        try:
            offscreen.free()
        except Exception:  # noqa: BLE001 - already invalidated headless
            pass

    times.sort()
    p50 = times[len(times) // 2]
    if readback_error:
        print(f"  warm avg   : {sum(times) / len(times):8.1f} ms, p50 {p50:.2f} ms")
        print(f"  [FAIL] pixel readback invalid: {readback_error}")
        print("         => the offscreen has no real GL backend in headless bpy.")
        print("         => true viewport streaming needs real Blender + hidden")
        print("            window / EGL context. Use Test A's render path headless.")
        return
    if p50 < 2.0 or spread < 1e-4:
        print(f"  warm avg   : {sum(times) / len(times):8.1f} ms, p50 {p50:.2f} ms")
        print(f"  pixel spread: {spread:.4f}  (uniform buffer = nothing drawn)")
        print("  [FAIL] draw_view3d returned a blank/no-op buffer -> NO real GL")
        print("         viewport context in headless bpy. The 'fast' time is fake.")
        print("         => true viewport streaming needs real Blender + hidden")
        print("            window / EGL context. Use Test A's render path headless.")
        return
    print(f"  warm avg   : {sum(times) / len(times):8.1f} ms")
    print(f"  p50        : {p50:8.1f} ms   (~{1000.0 / p50:.0f} fps)")
    print(f"  pixel spread: {spread:.3f}  (non-uniform = real pixels)")
    print("  [OK] true viewport offscreen genuinely rendered in this process.")
    _verdict("Test B", p50)


def _verdict(label: str, p50_ms: float) -> None:
    if p50_ms < 16:
        note = "EXCELLENT -- 60fps+ class, real-time drag will feel native locally."
    elif p50_ms < 33:
        note = "GOOD -- 30fps+ class, smooth enough for orbit/gizmo over loopback."
    elif p50_ms < 66:
        note = "OK -- usable for a pose/compose editor; fast drags will feel soft."
    else:
        note = "POOR -- too slow for real-time; main editor likely stays client-side."
    print(f"  VERDICT [{label}]: p50 {p50_ms:.1f} ms -> {note}")


def main() -> None:
    blend, width, height, frames = _parse_args(list(sys.argv))
    print("=" * 70)
    print(f"bpy {bpy.app.version_string} | background={bpy.app.background}")
    print(f"target {width}x{height}, {frames} warm frames, blend={blend}")
    print("=" * 70)

    _open_blend(blend)
    _ensure_visible_geometry()
    _configure_solid(width, height)
    test_a_workbench_render(width, height, frames)
    test_b_viewport_offscreen(width, height, frames)

    print("\nDone. The two p50 numbers (Test A headless-safe, Test B true-viewport)")
    print("decide whether the scene3D editor can move server-side or stays client-side.")


if __name__ == "__main__":
    main()
