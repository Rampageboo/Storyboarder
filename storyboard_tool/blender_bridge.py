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
from .project_layout import LAYOUT_2


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
    scene_id = str(scene.get("id") or "")
    if project.layout == LAYOUT_2:
        stored = str(scene.get("blend_file_path") or "")
        if not stored:
            raise ValueError("Layout 2 Scene 3D metadata has no Blender path.")
        stored_path = scene3d._safe_rel_path(project, stored).resolve()
        if stored_path.suffix.lower() != ".blend":
            raise ValueError("Layout 2 Scene 3D Blender path must be a .blend file.")
        if not stored_path.is_file():
            raise FileNotFoundError(f"Layout 2 Blender scene not found: {stored}.")
        if resolved_blend != stored_path:
            raise ValueError("External Blender must use the persisted Scene 3D path.")
    project_session_id = str(
        getattr(app.state, "project_session_id", "") or ""
    )
    if project.layout == LAYOUT_2 and not project_session_id:
        raise ValueError("Layout 2 Blender project session is missing.")
    app.state.external_blender_session_id = session_id
    app.state.external_blender_blend_path = str(resolved_blend)
    app.state.external_blender_scene3d_id = scene_id
    app.state.external_blender_project_session_id = project_session_id
    app.state.external_blender_context_revision = int(project.storage_revision)
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
    session_id = str(getattr(app.state, "external_blender_session_id", "") or "")
    if session_id:
        try:
            context = _read_json(bridge_file_path())
            if str(context.get("session_id") or "") == session_id:
                context.update(
                    {
                        "session_id": "",
                        "write_enabled": False,
                        "lease_expires_at": 0.0,
                        "updated_at": time.time(),
                    }
                )
                _write_json(bridge_file_path(), context)
        except OSError:
            pass
    app.state.external_blender_session_id = ""
    app.state.external_blender_blend_path = ""
    app.state.external_blender_scene3d_id = ""
    app.state.external_blender_project_session_id = ""
    app.state.external_blender_context_revision = -1
    app.state.external_blender_launched_at = 0.0
    app.state.external_blender_process = None
    app.state.external_blender_initial_mtime_ns = 0
    app.state.external_blender_observed_mtime_ns = 0


def publish_context(app: FastAPI, project: Project) -> dict[str, Any]:
    session_id = str(getattr(app.state, "external_blender_session_id", "") or "")
    blend_path = str(getattr(app.state, "external_blender_blend_path", "") or "")
    scene_id = str(getattr(app.state, "external_blender_scene3d_id", "") or "")
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
    portable_references: list[dict[str, str]] = []
    from .external_tools import blender_portable_reference

    blend = Path(blend_path)
    published_at = time.time()
    for link in project.settings.get("reference_links") or []:
        if not isinstance(link, dict):
            continue
        relative = str(link.get("path") or "")
        if Path(relative).suffix.lower() not in {".blend", ".glb", ".gltf"}:
            continue
        try:
            asset = scene3d._safe_rel_path(project, relative)
            portable = blender_portable_reference(project, blend, asset)
        except (OSError, ValueError):
            continue
        portable_references.append(
            {"id": str(link.get("id") or ""), "path": portable}
        )
    payload = {
        "write_enabled": project.layout != LAYOUT_2 or (
            str(getattr(app.state, "external_blender_project_session_id", "") or "")
            == str(getattr(app.state, "project_session_id", "") or "")
            and int(getattr(app.state, "external_blender_context_revision", -1))
            == int(project.storage_revision)
        ),
        "version": 2 if project.layout == LAYOUT_2 else 1,
        "project_session_id": str(
            getattr(app.state, "external_blender_project_session_id", "") or ""
        ),
        "context_revision": int(
            getattr(app.state, "external_blender_context_revision", -1)
        ),
        "path_mode": "explicit-assets" if project.layout == LAYOUT_2 else "legacy",
        "offline_write_allowed": project.layout != LAYOUT_2,
        "lease_expires_at": published_at + HEARTBEAT_MAX_AGE_SECONDS,
        "lease_duration_seconds": HEARTBEAT_MAX_AGE_SECONDS,
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
        "portable_references": portable_references,
        "updated_at": published_at,
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


def _validated_heartbeat(
    app: FastAPI,
    project: Project | None,
) -> tuple[dict[str, Any], float | None]:
    heartbeat_path = heartbeat_file_path()
    heartbeat = _read_json(heartbeat_path)
    try:
        age = max(0.0, time.time() - heartbeat_path.stat().st_mtime)
    except OSError:
        return {}, None
    expected_session = str(getattr(app.state, "external_blender_session_id", "") or "")
    if not expected_session or str(heartbeat.get("session_id") or "") != expected_session:
        return {}, age
    if project is not None and project.layout == LAYOUT_2:
        expected_project_session = str(
            getattr(app.state, "external_blender_project_session_id", "") or ""
        )
        expected_revision = int(
            getattr(app.state, "external_blender_context_revision", -1)
        )
        if (
            expected_project_session
            != str(getattr(app.state, "project_session_id", "") or "")
            or expected_revision != int(project.storage_revision)
            or heartbeat.get("project_session_id") != expected_project_session
            or heartbeat.get("context_revision") != expected_revision
        ):
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
    lease_expires_at = context.get("lease_expires_at")
    if (
        context.get("write_enabled") is not True
        or isinstance(lease_expires_at, bool)
        or not isinstance(lease_expires_at, (int, float))
        or time.time() > float(lease_expires_at)
    ):
        return
    try:
        age = max(0.0, time.time() - heartbeat_file_path().stat().st_mtime)
        context_root = _resolve(str(context.get("project_root") or ""))
        blend_path = _resolve(str(context.get("blend_path") or ""))
        heartbeat_blend = _resolve(str(heartbeat.get("blend_path") or ""))
    except (OSError, ValueError):
        return
    project_root = project.project_root.resolve()
    if project.layout == LAYOUT_2 and (
        context.get("project_session_id")
        != str(getattr(app.state, "project_session_id", "") or "")
        or context.get("context_revision") != int(project.storage_revision)
        or heartbeat.get("project_session_id") != context.get("project_session_id")
        or heartbeat.get("context_revision") != context.get("context_revision")
    ):
        return
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
    app.state.external_blender_project_session_id = str(
        context.get("project_session_id") or ""
    )
    app.state.external_blender_context_revision = int(
        context.get("context_revision") or 0
    )
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
    heartbeat, age = _validated_heartbeat(app, project)
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
