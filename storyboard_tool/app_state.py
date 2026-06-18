"""Transport-agnostic project/app-state helpers.

These were previously private functions on the HTTP route module (`api.py`),
which forced the service layer to reach "up" into the route layer via a lazy
import shim. They live here so both `api.py` and `backend_service.py` import
them downward, with no circular dependency.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException

from . import live_bridge, project_manager, session_store, shot_service
from .errors import AppErrorCode, app_error
from .models import Project, SHOT_STATUSES, Shot


def _project_payload(project: Project, dirty: bool) -> dict[str, Any]:
    return {
        "project_path": str(project.root_path),
        "project_json_path": str(project.json_path),
        "name": project.name,
        "dirty": dirty,
        "settings": project.settings,
        "statuses": list(SHOT_STATUSES),
        "shots": [_shot_payload(project, shot) for shot in project.shots],
    }


def _shot_payload(project: Project, shot: Shot) -> dict[str, Any]:
    from .image_utils import is_solid_color_image

    data = shot.to_dict()
    preview_path = project_manager.resolve_shot_preview_path(project, shot)
    if preview_path is not None:
        data["preview_disk_mtime"] = preview_path.stat().st_mtime
    thumb_path = project_manager.resolve_shot_thumbnail_path(project, shot)
    if thumb_path is not None:
        data["thumbnail_disk_mtime"] = thumb_path.stat().st_mtime
    data["has_board_background"] = project_manager.get_shot_board_background_path(project, shot) is not None
    if preview_path is not None and preview_path.is_file():
        data["has_artwork_preview"] = not is_solid_color_image(preview_path)
    else:
        data["has_artwork_preview"] = False
    return data


def _require_project(app: FastAPI) -> Project:
    project = app.state.project
    if project is None:
        raise app_error(AppErrorCode.PROJECT_NOT_OPEN, "No project opened.")
    return project


def _find_shot_index(project: Project, shot_id: str) -> int:
    try:
        return shot_service.find_shot_index(project, shot_id)
    except ValueError as exc:
        raise app_error(AppErrorCode.SHOT_NOT_FOUND, str(exc), status=404) from exc


def _find_shot(project: Project, shot_id: str) -> Shot:
    try:
        return shot_service.find_shot(project, shot_id)
    except ValueError as exc:
        raise app_error(AppErrorCode.SHOT_NOT_FOUND, str(exc), status=404) from exc


def _track_project(app: FastAPI, project: Project) -> None:
    app.state.project = project
    app.state.project_disk_mtime = project_manager.project_disk_mtime(project)


def _refresh_project_from_disk(app: FastAPI) -> Project:
    project = _require_project(app)
    if app.state.dirty:
        return project
    refreshed, disk_mtime, changed = project_manager.reload_project_if_changed(
        project,
        app.state.project_disk_mtime,
    )
    if changed:
        app.state.project = refreshed
        app.state.project_disk_mtime = disk_mtime
        return refreshed
    return project


def _autosave(app: FastAPI) -> None:
    project = _require_project(app)
    project_manager.save_project(project)
    app.state.project_disk_mtime = project_manager.project_disk_mtime(project)
    app.state.dirty = False


def _dialog_initial_dir(app: FastAPI, kind: str) -> str:
    project = app.state.project
    if project is None:
        return str(Path.home())

    if kind == "folder":
        candidate = project.root_path.parent
    elif kind == "project-json":
        candidate = project.root_path
    elif kind == "blender":
        current = str(project.settings.get("blender_path", "") or "")
        candidate = Path(current).parent if current else Path(r"C:\Program Files\Blender Foundation")
    else:
        current = str(project.settings.get("photoshop_path", "") or "")
        candidate = Path(current).parent if current else Path(r"C:\Program Files\Adobe")

    if candidate.is_dir():
        return str(candidate.resolve())
    return str(Path.home())


def _remember_recent(project: Project) -> None:
    recent = [str(project.root_path)]
    for item in project.settings.get("recent_projects", []):
        if item not in recent:
            recent.append(item)
    project.settings["recent_projects"] = recent[:10]
    project_manager.save_settings(project)


def _touch_live_bridge(app: FastAPI, *, selected_shot_id: str | None = None) -> dict[str, Any]:
    if selected_shot_id is not None:
        app.state.live_selected_shot_id = selected_shot_id
    return live_bridge.publish(
        app.state.base_dir,
        app.state.project,
        selected_shot_id=str(app.state.live_selected_shot_id or ""),
        port=int(app.state.bridge_port),
        focus_shot_id=str(getattr(app.state, "live_focus_shot_id", "") or ""),
        focus_token=int(getattr(app.state, "live_focus_token", 0) or 0),
    )


def _plugin_open_shot_ids(app: FastAPI, plugin_linked: bool, file_seen: float, http_seen: float) -> list[str]:
    """Shot ids the plugin reports as open Photoshop tabs (heartbeat file or HTTP)."""
    if not plugin_linked:
        return []

    def normalize_ids(value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(item) for item in value if item]
        return []

    heartbeat = live_bridge.read_plugin_heartbeat()
    file_ids = heartbeat.get("open_shot_ids") if isinstance(heartbeat, dict) else None
    http_ids = getattr(app.state, "plugin_open_shot_ids", None)

    file_open_ids = normalize_ids(file_ids)
    http_open_ids = normalize_ids(http_ids)
    primary, fallback = (file_open_ids, http_open_ids) if file_seen >= http_seen else (http_open_ids, file_open_ids)
    return primary or fallback


def _plugin_link_state(app: FastAPI) -> tuple[bool, float | None, list[str]]:
    """(linked, seconds_since_seen, open_shot_ids) — shared by status + open-source."""
    http_seen = float(getattr(app.state, "plugin_last_seen", 0.0) or 0.0)
    file_seen = live_bridge.read_plugin_heartbeat_mtime()
    last_seen = max(http_seen, file_seen)
    age = round(time.time() - last_seen, 1) if last_seen else None
    plugin_linked = age is not None and age <= 12.0
    open_shot_ids = _plugin_open_shot_ids(app, plugin_linked, file_seen, http_seen)
    return plugin_linked, age, open_shot_ids


def _plugin_selected_shot_id(app: FastAPI) -> str:
    selected = str(getattr(app.state, "plugin_selected_shot_id", "") or "")
    if selected:
        return selected
    heartbeat = live_bridge.read_plugin_heartbeat()
    if isinstance(heartbeat, dict):
        return str(heartbeat.get("selected_shot_id") or "")
    return ""


def _bridge_status_payload(app: FastAPI) -> dict[str, Any]:
    live = _touch_live_bridge(app)
    project = app.state.project
    plugin_linked, age, open_shot_ids = _plugin_link_state(app)
    last_exported = getattr(app.state, "plugin_last_exported_preview", {})
    if not isinstance(last_exported, dict):
        last_exported = {}
    return {
        "app_running": True,
        "project_open": project is not None,
        "plugin_linked": plugin_linked,
        "plugin_last_seen_seconds_ago": age,
        "plugin_selected_shot_id": _plugin_selected_shot_id(app),
        "plugin_open_shot_ids": open_shot_ids,
        "plugin_last_exported_preview": last_exported,
        "plugin_project_revision": int(getattr(app.state, "plugin_project_revision", 0) or 0),
        "bridge_url": live.get("bridge_url", f"http://127.0.0.1:{app.state.bridge_port}/api/bridge/live"),
        "global_bridge_path": live.get("global_bridge_path", str(live_bridge.global_bridge_file_path())),
        "shared_bridge_path": live.get("shared_bridge_path", str(live_bridge.shared_bridge_file_path())),
        "plugin_heartbeat_path": live.get("plugin_heartbeat_path", str(live_bridge.plugin_heartbeat_file_path())),
        "server_port": int(app.state.bridge_port),
        "live": live,
    }


def _persist_app_session(app: FastAPI, *, selected_shot_id: str | None = None) -> None:
    project = app.state.project
    if project is None:
        return
    session_store.update_session(
        app.state.base_dir,
        last_project_json_path=str(project.json_path),
        selected_shot_id=selected_shot_id,
        recent_projects=[str(item) for item in project.settings.get("recent_projects", [])],
    )


def _annotation_path(project: Project, shot: Shot) -> Path:
    if not shot.annotation_path:
        project_manager.get_shot_dir(project, shot).mkdir(parents=True, exist_ok=True)
        path = project_manager.get_shot_dir(project, shot) / f"{shot.shot_id}_annotations.json"
        path.write_text("[]", encoding="utf-8")
        shot.annotation_path = path.relative_to(project.root_path).as_posix()
        project_manager.save_project(project)
        return path
    path = project.root_path / shot.annotation_path
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("[]", encoding="utf-8")
    return path
