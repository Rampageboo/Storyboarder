from __future__ import annotations

import time
from typing import Any

from fastapi import FastAPI


def init_bridge_state(app: FastAPI, bridge_port: int) -> None:
    app.state.live_selected_shot_id = ""
    app.state.bridge_port = bridge_port
    app.state.plugin_last_seen = 0.0
    app.state.plugin_open_shot_ids = []
    app.state.plugin_selected_shot_id = ""
    app.state.plugin_last_exported_preview = {}
    app.state.plugin_project_revision = 0
    app.state.live_focus_shot_id = ""
    app.state.live_focus_token = 0


def live_selected_shot_id(app: FastAPI) -> str:
    return str(getattr(app.state, "live_selected_shot_id", "") or "")


def set_live_selected_shot_id(app: FastAPI, shot_id: str) -> None:
    app.state.live_selected_shot_id = str(shot_id or "")


def live_focus_shot_id(app: FastAPI) -> str:
    return str(getattr(app.state, "live_focus_shot_id", "") or "")


def live_focus_token(app: FastAPI) -> int:
    return int(getattr(app.state, "live_focus_token", 0) or 0)


def request_live_focus(app: FastAPI, shot_id: str) -> None:
    app.state.live_focus_shot_id = str(shot_id or "")
    app.state.live_focus_token = live_focus_token(app) + 1


def plugin_last_seen(app: FastAPI) -> float:
    return float(getattr(app.state, "plugin_last_seen", 0.0) or 0.0)


def plugin_selected_shot_id(app: FastAPI) -> str:
    return str(getattr(app.state, "plugin_selected_shot_id", "") or "")


def plugin_open_shot_ids(app: FastAPI) -> list[str]:
    raw = getattr(app.state, "plugin_open_shot_ids", None)
    if not isinstance(raw, list):
        return []
    return [str(item) for item in raw if item]


def set_plugin_and_live_selected_shot_id(app: FastAPI, shot_id: str) -> None:
    selected = str(shot_id or "")
    app.state.plugin_selected_shot_id = selected
    app.state.live_selected_shot_id = selected


def record_plugin_heartbeat(app: FastAPI, payload: dict[str, Any] | None = None) -> None:
    data = payload if isinstance(payload, dict) else {}
    app.state.plugin_last_seen = time.time()
    selected = str(data.get("selected_shot_id") or "").strip()
    if selected:
        set_plugin_and_live_selected_shot_id(app, selected)
    open_ids = data.get("open_shot_ids")
    if isinstance(open_ids, list):
        app.state.plugin_open_shot_ids = [str(item) for item in open_ids if item]


def plugin_last_exported_preview(app: FastAPI) -> dict[str, float]:
    exported = getattr(app.state, "plugin_last_exported_preview", None)
    if not isinstance(exported, dict):
        exported = {}
        app.state.plugin_last_exported_preview = exported
    return exported


def mark_plugin_preview_exported(app: FastAPI, shot_id: str) -> None:
    plugin_last_exported_preview(app)[str(shot_id)] = time.time()


def plugin_project_revision(app: FastAPI) -> int:
    return int(getattr(app.state, "plugin_project_revision", 0) or 0)


def mark_plugin_project_changed(app: FastAPI) -> None:
    app.state.plugin_project_revision = plugin_project_revision(app) + 1
