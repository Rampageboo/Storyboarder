from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

SESSION_VERSION = 1
SESSION_FILENAME = "storyboard_session.json"


def session_dir(base_dir: Path) -> Path:
    return base_dir / "Sessions"


def session_file(base_dir: Path) -> Path:
    return session_dir(base_dir) / SESSION_FILENAME


def default_session() -> dict[str, Any]:
    return {
        "version": SESSION_VERSION,
        "last_project_json_path": "",
        "selected_shot_id": "",
        "recent_projects": [],
        "timeline_scroll_left": 0,
        "status_filter": "",
        "revision_only": False,
        "advanced_panel_open": False,
        "ui_theme": "",
    }


def read_session(base_dir: Path) -> dict[str, Any]:
    path = session_file(base_dir)
    if not path.is_file():
        return default_session()
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default_session()
    if not isinstance(loaded, dict):
        return default_session()
    session = default_session()
    session.update(loaded)
    session["version"] = SESSION_VERSION
    if not isinstance(session.get("recent_projects"), list):
        session["recent_projects"] = []
    scroll = session.get("timeline_scroll_left")
    session["timeline_scroll_left"] = max(0, int(scroll)) if isinstance(scroll, (int, float)) else 0
    session["status_filter"] = str(session.get("status_filter") or "")
    session["revision_only"] = bool(session.get("revision_only"))
    session["advanced_panel_open"] = bool(session.get("advanced_panel_open"))
    session["ui_theme"] = str(session.get("ui_theme") or "")
    return session


def write_session(base_dir: Path, session: dict[str, Any]) -> Path:
    directory = session_dir(base_dir)
    directory.mkdir(parents=True, exist_ok=True)
    payload = default_session()
    payload.update(session)
    payload["version"] = SESSION_VERSION
    recent = payload.get("recent_projects")
    if not isinstance(recent, list):
        payload["recent_projects"] = []
    path = session_file(base_dir)
    fd, tmp_name = tempfile.mkstemp(dir=str(directory), prefix="session.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            json.dump(payload, f, indent=2)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return path


def update_session(
    base_dir: Path,
    *,
    last_project_json_path: str | None = None,
    selected_shot_id: str | None = None,
    recent_projects: list[str] | None = None,
    timeline_scroll_left: int | None = None,
    status_filter: str | None = None,
    revision_only: bool | None = None,
    advanced_panel_open: bool | None = None,
    ui_theme: str | None = None,
) -> dict[str, Any]:
    session = read_session(base_dir)
    if last_project_json_path is not None:
        session["last_project_json_path"] = last_project_json_path
        if last_project_json_path:
            recent = [last_project_json_path]
            for item in session.get("recent_projects", []):
                if item not in recent:
                    recent.append(item)
            session["recent_projects"] = recent[:10]
    if selected_shot_id is not None:
        session["selected_shot_id"] = selected_shot_id
    if recent_projects is not None:
        session["recent_projects"] = recent_projects[:10]
    if timeline_scroll_left is not None:
        session["timeline_scroll_left"] = max(0, int(timeline_scroll_left))
    if status_filter is not None:
        session["status_filter"] = status_filter
    if revision_only is not None:
        session["revision_only"] = bool(revision_only)
    if advanced_panel_open is not None:
        session["advanced_panel_open"] = bool(advanced_panel_open)
    if ui_theme is not None:
        session["ui_theme"] = ui_theme
    write_session(base_dir, session)
    return session
