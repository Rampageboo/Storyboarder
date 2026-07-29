"""External-Blender ownership bridge for the active Storyboarder Scene3D file."""

from __future__ import annotations

import json
import os
import secrets
import subprocess
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from . import live_bridge, runtime_state, scene3d
from .models import Project


BRIDGE_FILENAME = "storyboard_blender_bridge.json"
HEARTBEAT_FILENAME = "storyboard_blender_heartbeat.json"
HEARTBEAT_MAX_AGE_SECONDS = 7.0


def bridge_file_path() -> Path:
    return live_bridge.global_bridge_dir() / BRIDGE_FILENAME


def heartbeat_file_path() -> Path:
    return live_bridge.global_bridge_dir() / HEARTBEAT_FILENAME


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _resolve(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def _shot_links(project: Project) -> list[dict[str, Any]]:
    links: list[dict[str, Any]] = []
    for index, shot in enumerate(project.shots):
        camera = str((shot.camera_data or {}).get("scene3d_camera") or "").strip()
        links.append(
            {
                "shot_id": shot.shot_id,
                "title": str(shot.title or "").strip(),
                "index": index + 1,
                "camera_name": camera,
                "scene3d_time": (shot.camera_data or {}).get("scene3d_time"),
            }
        )
    return links


def begin_session(
    app: FastAPI,
    project: Project,
    scene: dict[str, Any],
    blend_path: Path,
) -> dict[str, Any]:
    session_id = secrets.token_urlsafe(24)
    resolved_blend = blend_path.resolve()
    app.state.external_blender_session_id = session_id
    app.state.external_blender_blend_path = str(resolved_blend)
    app.state.external_blender_scene3d_id = str(scene.get("id") or "")
    app.state.external_blender_launched_at = time.time()
    app.state.external_blender_process = None
    app.state.external_blender_initial_mtime_ns = (
        resolved_blend.stat().st_mtime_ns if resolved_blend.is_file() else 0
    )
    app.state.external_blender_observed_mtime_ns = app.state.external_blender_initial_mtime_ns
    publish_context(app, project)
    return {
        "session_id": session_id,
        "bridge_path": str(bridge_file_path()),
        "heartbeat_path": str(heartbeat_file_path()),
    }


def attach_process(app: FastAPI, process: subprocess.Popen[Any]) -> None:
    app.state.external_blender_process = process


def cancel_session(app: FastAPI) -> None:
    app.state.external_blender_session_id = ""
    app.state.external_blender_blend_path = ""
    app.state.external_blender_scene3d_id = ""
    app.state.external_blender_launched_at = 0.0
    app.state.external_blender_process = None
    app.state.external_blender_initial_mtime_ns = 0
    app.state.external_blender_observed_mtime_ns = 0


def publish_context(app: FastAPI, project: Project) -> dict[str, Any]:
    session_id = str(getattr(app.state, "external_blender_session_id", "") or "")
    blend_path = str(getattr(app.state, "external_blender_blend_path", "") or "")
    scene_id = (
        str(getattr(app.state, "external_blender_scene3d_id", "") or "")
        if owns_scene
        else ""
    )
    if not session_id or not blend_path:
        return {}
    scene_payload = next(
        (
            item
            for item in scene3d.list_scenes(project).get("scenes", [])
            if str(item.get("id") or "") == scene_id
        ),
        {},
    )
    payload = {
        "version": 1,
        "session_id": session_id,
        "project_name": project.name,
        "project_root": str(project.project_root.resolve()),
        "project_json_path": str(project.json_path.resolve()),
        "scene3d_id": scene_id,
        "scene3d_title": str(scene_payload.get("title") or scene_id),
        "blend_path": blend_path,
        "preview_path": str(
            scene3d.preview_file_path(project, scene_id).resolve()
        ),
        "selected_shot_id": runtime_state.live_selected_shot_id(app),
        "shots": _shot_links(project),
        "updated_at": time.time(),
    }
    _write_json(bridge_file_path(), payload)
    return payload


def _process_running(app: FastAPI) -> bool:
    process = getattr(app.state, "external_blender_process", None)
    if process is None:
        return False
    try:
        return process.poll() is None
    except (AttributeError, OSError):
        return False


def _validated_heartbeat(app: FastAPI) -> tuple[dict[str, Any], float | None]:
    heartbeat_path = heartbeat_file_path()
    heartbeat = _read_json(heartbeat_path)
    try:
        age = max(0.0, time.time() - heartbeat_path.stat().st_mtime)
    except OSError:
        return {}, None
    expected_session = str(getattr(app.state, "external_blender_session_id", "") or "")
    if not expected_session or str(heartbeat.get("session_id") or "") != expected_session:
        return {}, age
    return heartbeat, age


def _adopt_fresh_session(app: FastAPI, project: Project) -> None:
    if str(getattr(app.state, "external_blender_session_id", "") or ""):
        return
    context = _read_json(bridge_file_path())
    heartbeat = _read_json(heartbeat_file_path())
    session_id = str(context.get("session_id") or "")
    if not session_id or str(heartbeat.get("session_id") or "") != session_id:
        return
    try:
        age = max(0.0, time.time() - heartbeat_file_path().stat().st_mtime)
        context_root = _resolve(str(context.get("project_root") or ""))
        blend_path = _resolve(str(context.get("blend_path") or ""))
        heartbeat_blend = _resolve(str(heartbeat.get("blend_path") or ""))
    except (OSError, ValueError):
        return
    project_root = project.project_root.resolve()
    if (
        age > HEARTBEAT_MAX_AGE_SECONDS
        or context_root != project_root
        or blend_path != heartbeat_blend
        or blend_path.suffix.lower() != ".blend"
        or not blend_path.is_file()
        or (blend_path != project_root and project_root not in blend_path.parents)
    ):
        return
    app.state.external_blender_session_id = session_id
    app.state.external_blender_blend_path = str(blend_path)
    app.state.external_blender_scene3d_id = str(context.get("scene3d_id") or "")
    app.state.external_blender_launched_at = float(context.get("updated_at") or time.time())
    app.state.external_blender_process = None
    try:
        observed = blend_path.stat().st_mtime_ns
    except OSError:
        observed = 0
    app.state.external_blender_initial_mtime_ns = observed
    app.state.external_blender_observed_mtime_ns = observed


def status(app: FastAPI, *, refresh_context: bool = True) -> dict[str, Any]:
    project = getattr(app.state, "project", None)
    if project is not None:
        _adopt_fresh_session(app, project)
    if refresh_context and project is not None:
        try:
            publish_context(app, project)
        except (OSError, ValueError):
            pass

    expected_path = str(getattr(app.state, "external_blender_blend_path", "") or "")
    heartbeat, age = _validated_heartbeat(app)
    heartbeat_fresh = bool(heartbeat) and age is not None and age <= HEARTBEAT_MAX_AGE_SECONDS
    heartbeat_path = str(heartbeat.get("blend_path") or "").strip()
    same_file = False
    if heartbeat_path and expected_path:
        try:
            same_file = _resolve(heartbeat_path) == _resolve(expected_path)
        except OSError:
            same_file = False
    connected = heartbeat_fresh and same_file
    process_running = _process_running(app)
    # Before the first valid heartbeat, the launched process owns the file. Once a
    # fresh heartbeat reports a different file, ownership can safely return.
    owns_scene = connected or (process_running and not heartbeat_fresh)

    observed_mtime = 0
    if expected_path:
        try:
            observed_mtime = _resolve(expected_path).stat().st_mtime_ns
        except OSError:
            observed_mtime = 0
    previous_mtime = int(
        getattr(app.state, "external_blender_observed_mtime_ns", 0) or 0
    )
    if observed_mtime and previous_mtime and observed_mtime != previous_mtime:
        app.state.dirty = True
    if observed_mtime:
        app.state.external_blender_observed_mtime_ns = observed_mtime

    if not owns_scene and not process_running and (
        age is None or age > HEARTBEAT_MAX_AGE_SECONDS
    ):
        app.state.external_blender_process = None

    preview_path: Path | None = None
    scene_id = str(getattr(app.state, "external_blender_scene3d_id", "") or "")
    if project is not None:
        if not scene_id:
            legacy_scene = project.settings.get("scene3d")
            scene_id = str(
                project.settings.get("active_scene3d_id")
                or (
                    legacy_scene.get("id")
                    if isinstance(legacy_scene, dict)
                    else ""
                )
                or ""
            )
        if scene_id:
            try:
                preview_path = scene3d.preview_file_path(project, scene_id)
            except ValueError:
                preview_path = None
    preview_revision = 0
    if preview_path is not None:
        try:
            preview_revision = preview_path.stat().st_mtime_ns
        except OSError:
            preview_revision = 0

    return {
        "owner": "external" if owns_scene else "none",
        "external_blender_owned": owns_scene,
        "external_blender_connected": connected,
        "external_blender_pending": owns_scene and not connected,
        "external_blender_process_running": process_running,
        "external_blender_age_seconds": age,
        "external_blender_blend_path": expected_path,
        "external_blender_scene3d_id": scene_id,
        "external_blender_camera": str(heartbeat.get("active_camera") or ""),
        "external_blender_dirty": bool(heartbeat.get("dirty", False)),
        "preview_path": str(preview_path or ""),
        "preview_revision": preview_revision,
        "preview_exporting": bool(heartbeat.get("preview_exporting", False)),
        "preview_error": str(heartbeat.get("preview_error") or ""),
    }


def owns_scene(app: FastAPI) -> bool:
    return bool(status(app, refresh_context=False)["external_blender_owned"])


def require_released(app: FastAPI, action: str) -> None:
    if owns_scene(app):
        raise ValueError(
            f"Save and close the externally opened Blender scene before {action}. "
            "Storyboarder has paused its built-in Blender to prevent double editing."
        )
