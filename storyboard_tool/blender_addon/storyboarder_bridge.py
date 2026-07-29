"""Session-only Storyboarder bridge injected into externally opened Blender."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
import time
from pathlib import Path
from typing import Any

import bpy
from bpy.app.handlers import persistent


BRIDGE_PATH = Path()
HEARTBEAT_PATH = Path()
SESSION_ID = ""
CONTEXT: dict[str, Any] = {}
REGISTERED = False
PREVIEW_EXPORT_PENDING = False
PREVIEW_EXPORTING = False
PREVIEW_ERROR = ""
PREVIEW_REVISION = 0


def _parse_args() -> argparse.Namespace:
    args = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--storyboarder-bridge", default="")
    parser.add_argument("--storyboarder-heartbeat", default="")
    parser.add_argument("--storyboarder-session", default="")
    options, _unknown = parser.parse_known_args(args)
    return options


def _read_context() -> dict[str, Any]:
    try:
        payload = json.loads(BRIDGE_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict) or str(payload.get("session_id") or "") != SESSION_ID:
        return {}
    return payload


def _write_heartbeat(payload: dict[str, Any]) -> None:
    HEARTBEAT_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = HEARTBEAT_PATH.with_name(
        f".{HEARTBEAT_PATH.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp"
    )
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, HEARTBEAT_PATH)


def _context_allows_write() -> bool:
    if not CONTEXT or str(CONTEXT.get("session_id") or "") != SESSION_ID:
        return False
    if CONTEXT.get("path_mode") != "explicit-assets":
        return True
    return (
        CONTEXT.get("version") == 2
        and bool(str(CONTEXT.get("project_session_id") or ""))
        and isinstance(CONTEXT.get("context_revision"), int)
        and CONTEXT.get("context_revision") >= 0
        and CONTEXT.get("offline_write_allowed") is False
        and CONTEXT.get("write_enabled") is True
    )


def _current_blend_matches_context() -> bool:
    current = str(bpy.data.filepath or "").strip()
    expected = str(CONTEXT.get("blend_path") or "").strip()
    if not current or not expected:
        return False
    try:
        return Path(current).resolve() == Path(expected).resolve()
    except OSError:
        return False


def _export_preview() -> None:
    global PREVIEW_EXPORTING, PREVIEW_ERROR, PREVIEW_REVISION
    preview_value = str(CONTEXT.get("preview_path") or "").strip()
    if not preview_value or not _context_allows_write() or not _current_blend_matches_context():
        return
    preview_path = Path(preview_value).expanduser()
    preview_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = preview_path.with_name(
        f".{preview_path.stem}.{os.getpid()}.{secrets.token_hex(4)}.glb"
    )
    PREVIEW_EXPORTING = True
    PREVIEW_ERROR = ""
    try:
        bpy.ops.export_scene.gltf(
            filepath=str(temporary),
            export_format="GLB",
            export_cameras=True,
            export_animations=True,
            export_lights=True,
        )
        if not temporary.is_file():
            raise RuntimeError("Blender did not create the preview GLB.")
        os.replace(temporary, preview_path)
        PREVIEW_REVISION = preview_path.stat().st_mtime_ns
        print(f"Storyboarder: preview updated at {preview_path}")
    except Exception as exc:  # Blender operator failures vary by version.
        PREVIEW_ERROR = str(exc)
        print(f"Storyboarder: preview export failed: {exc}")
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
    finally:
        PREVIEW_EXPORTING = False


def _preview_export_timer() -> None:
    global PREVIEW_EXPORT_PENDING, CONTEXT
    PREVIEW_EXPORT_PENDING = False
    CONTEXT = _read_context()
    _export_preview()
    return None


def _queue_preview_export(*, delay: float = 0.35) -> None:
    global PREVIEW_EXPORT_PENDING
    PREVIEW_EXPORT_PENDING = True
    if not bpy.app.timers.is_registered(_preview_export_timer):
        bpy.app.timers.register(_preview_export_timer, first_interval=delay)


@persistent
def _on_save_post(_unused: Any) -> None:
    _queue_preview_export()


def _heartbeat() -> float:
    global CONTEXT
    CONTEXT = _read_context()
    filepath = str(bpy.data.filepath or "").strip()
    active_camera = bpy.context.scene.camera
    try:
        saved_mtime_ns = Path(filepath).stat().st_mtime_ns if filepath else 0
    except OSError:
        saved_mtime_ns = 0
    try:
        _write_heartbeat(
            {
                "version": 1,
                "session_id": SESSION_ID,
                "project_session_id": str(CONTEXT.get("project_session_id") or ""),
                "context_revision": CONTEXT.get("context_revision"),
                "blend_path": str(Path(filepath).resolve()) if filepath else "",
                "scene3d_id": str(CONTEXT.get("scene3d_id") or ""),
                "active_camera": active_camera.name if active_camera is not None else "",
                "dirty": bool(bpy.data.is_dirty),
                "saved_mtime_ns": saved_mtime_ns,
                "preview_path": str(CONTEXT.get("preview_path") or ""),
                "preview_revision": PREVIEW_REVISION,
                "preview_exporting": PREVIEW_EXPORTING or PREVIEW_EXPORT_PENDING,
                "preview_error": PREVIEW_ERROR,
                "pid": os.getpid(),
                "seen_at": time.time(),
            }
        )
    except OSError:
        pass
    for area in getattr(bpy.context.screen, "areas", ()) if bpy.context.screen else ():
        if area.type == "PROPERTIES" or area.type == "VIEW_3D":
            area.tag_redraw()
    return 2.0


class STORYBOARDER_PT_external_bridge(bpy.types.Panel):
    bl_label = "Storyboarder Link"
    bl_idname = "STORYBOARDER_PT_external_bridge"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Storyboarder"
    bl_order = 0

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        linked = bool(CONTEXT)
        layout.label(
            text="Connected to Storyboarder" if linked else "Waiting for Storyboarder",
            icon="LINKED" if linked else "UNLINKED",
        )
        if not linked:
            return
        layout.label(text=str(CONTEXT.get("project_name") or "Project"), icon="FILE_FOLDER")
        layout.label(
            text=str(CONTEXT.get("scene3d_title") or CONTEXT.get("scene3d_id") or "Scene 3D"),
            icon="SCENE_DATA",
        )
        selected_shot = str(CONTEXT.get("selected_shot_id") or "")
        if selected_shot:
            layout.label(text=f"Selected shot: {selected_shot}", icon="RESTRICT_SELECT_OFF")
        active_camera = context.scene.camera.name if context.scene.camera else ""
        if active_camera:
            layout.label(text=f"Camera: {active_camera}", icon="CAMERA_DATA")
        if PREVIEW_EXPORTING or PREVIEW_EXPORT_PENDING:
            layout.label(text="Updating Storyboarder preview...", icon="FILE_REFRESH")
        elif PREVIEW_ERROR:
            layout.label(text="Preview export failed", icon="ERROR")
        elif PREVIEW_REVISION:
            layout.label(text="Preview up to date", icon="CHECKMARK")
        linked_shots = [
            item
            for item in CONTEXT.get("shots") or []
            if isinstance(item, dict)
            and active_camera
            and str(item.get("camera_name") or "") == active_camera
        ]
        if linked_shots:
            box = layout.box()
            box.label(text="Boards using this camera")
            for item in linked_shots[:8]:
                label = str(item.get("title") or item.get("shot_id") or "Shot")
                box.label(text=label, icon="IMAGE_DATA")


def register() -> None:
    global BRIDGE_PATH, HEARTBEAT_PATH, SESSION_ID, REGISTERED, CONTEXT, PREVIEW_REVISION
    options = _parse_args()
    bridge_value = str(options.storyboarder_bridge or "").strip()
    heartbeat_value = str(options.storyboarder_heartbeat or "").strip()
    session_value = str(options.storyboarder_session or "").strip()
    if not bridge_value or not heartbeat_value or not session_value:
        return
    BRIDGE_PATH = Path(bridge_value).expanduser()
    HEARTBEAT_PATH = Path(heartbeat_value).expanduser()
    SESSION_ID = session_value
    CONTEXT = _read_context()
    preview_value = str(CONTEXT.get("preview_path") or "").strip()
    if preview_value:
        try:
            PREVIEW_REVISION = Path(preview_value).stat().st_mtime_ns
        except OSError:
            PREVIEW_REVISION = 0
    if not REGISTERED:
        bpy.utils.register_class(STORYBOARDER_PT_external_bridge)
        REGISTERED = True
    if not bpy.app.timers.is_registered(_heartbeat):
        bpy.app.timers.register(_heartbeat, first_interval=0.25, persistent=True)
    if _on_save_post not in bpy.app.handlers.save_post:
        bpy.app.handlers.save_post.append(_on_save_post)
    _queue_preview_export(delay=0.75)


def unregister() -> None:
    global REGISTERED
    if bpy.app.timers.is_registered(_heartbeat):
        bpy.app.timers.unregister(_heartbeat)
    if bpy.app.timers.is_registered(_preview_export_timer):
        bpy.app.timers.unregister(_preview_export_timer)
    if _on_save_post in bpy.app.handlers.save_post:
        bpy.app.handlers.save_post.remove(_on_save_post)
    if REGISTERED:
        bpy.utils.unregister_class(STORYBOARDER_PT_external_bridge)
        REGISTERED = False
