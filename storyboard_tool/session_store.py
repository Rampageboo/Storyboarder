from __future__ import annotations

import json
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
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def update_session(
    base_dir: Path,
    *,
    last_project_json_path: str | None = None,
    selected_shot_id: str | None = None,
    recent_projects: list[str] | None = None,
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
    write_session(base_dir, session)
    return session
