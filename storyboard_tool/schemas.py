"""Pydantic models for API response shapes and focused API contracts.

Most request models live in ``api.py`` alongside the route definitions that
consume them.  The Photoshop bridge request/response models live here because
the bridge is shared by the backend service, frontend polling code, and UXP
plugin.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ErrorBody(BaseModel):
    """Structured error response body returned by all app-level errors.

    ``detail`` is the human-readable message (preserved for backward
    compatibility — existing frontend and bridge code reads this field).
    ``code`` is a machine-readable constant from ``errors.AppErrorCode`` that
    callers can use for branching without string-matching the message.
    """

    detail: str
    code: str | None = None


class LiveBridgeUpdateRequest(BaseModel):
    """Frontend heartbeat request for ``PUT /api/bridge/live``."""

    selected_shot_id: str | None = None


class PluginHeartbeatRequest(BaseModel):
    """UXP plugin heartbeat, accepted by both plugin heartbeat endpoints."""

    open_shot_ids: list[str] = Field(default_factory=list)
    selected_shot_id: str | None = None


class PluginShotEventRequest(BaseModel):
    """Plugin event payload for preview export and PSD-saved notifications."""

    source_file_path: str | None = None
    preview_image_path: str | None = None


class PluginNextShotRequest(BaseModel):
    """Plugin request to advance from the current shot, optionally creating one."""

    current_shot_id: str | None = None
    auto_add: bool = False


class BridgeStatusResponse(BaseModel):
    """Contract fields returned by ``GET /api/bridge/status``.

    The live bridge payload is intentionally loose because it mirrors the JSON
    bridge file used by older plugin builds.
    """

    app_running: bool
    project_open: bool
    plugin_linked: bool
    plugin_last_seen_seconds_ago: float | None = None
    plugin_selected_shot_id: str = ""
    plugin_open_shot_ids: list[str] = Field(default_factory=list)
    plugin_last_exported_preview: dict[str, float] = Field(default_factory=dict)
    plugin_project_revision: int = 0
    bridge_url: str
    global_bridge_path: str
    shared_bridge_path: str
    plugin_heartbeat_path: str
    server_port: int
    live: dict[str, Any] = Field(default_factory=dict)


class PluginContextResponse(BaseModel):
    """Core contract fields returned by ``GET /api/plugin/context``."""

    project_name: str
    project_root: str
    project_json_path: str
    selected_shot_id: str = ""
    focused_shot_id: str = ""
    canvas: dict[str, Any]
    shots: list[dict[str, Any]]
    previous_shots: list[dict[str, Any]]
    next_shot_id: str = ""
    paths: dict[str, str] = Field(default_factory=dict)
    bridge: dict[str, Any]
