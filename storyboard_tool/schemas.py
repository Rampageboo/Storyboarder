"""Pydantic models for API requests, response shapes, and focused API contracts.

Route request models live here so the API layer can stay focused on route
registration and transport concerns.  The Photoshop bridge request/response
models also live here because the bridge is shared by the backend service,
frontend polling code, and UXP plugin.
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


class ProjectPathRequest(BaseModel):
    path: str | None = None
    canvas_width: int | None = None
    canvas_height: int | None = None


class OpenProjectRequest(BaseModel):
    project_json_path: str


class ShotUpdateRequest(BaseModel):
    title: str = ""
    scene: str = ""
    sequence: str = ""
    description: str = ""
    action_note: str = ""
    camera_note: str = ""
    character_note: str = ""
    dialogue: str = ""
    lighting_note: str = ""
    transition_note: str = ""
    duration_seconds: float = 3.0
    camera_data: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    status: str = "Draft"


class CommentRequest(BaseModel):
    text: str


class CommentResolveRequest(BaseModel):
    resolved: bool = True


class AnnotationSaveRequest(BaseModel):
    annotations: list[dict[str, Any]] = Field(default_factory=list)


class RelinkRequest(BaseModel):
    relative_path: str


class RemoveReferenceRequest(BaseModel):
    path: str


class SetReferencePathsRequest(BaseModel):
    paths: list[str] = Field(default_factory=list)


class CanvasRequest(BaseModel):
    width: int = 1920
    height: int = 1080
    background_color: str | None = None


class DrawingSaveRequest(BaseModel):
    image_data: str


class PdfExportRequest(BaseModel):
    layout: str = "two_per_page"


class SettingsUpdateRequest(BaseModel):
    photoshop_path: str | None = None
    blender_path: str | None = None
    canvas_background_color: str | None = None
    canvas_width: int | None = None
    canvas_height: int | None = None
    apply_canvas_size_to_blank_shots: bool | None = None
    preheat_photoshop_on_open: bool | None = None
    scene3d: dict[str, Any] | None = None
    reference_video_path: str | None = None
    reference_model_path: str | None = None
    reference_image_path: str | None = None
    reference_segment_mode: str | None = None
    reference_links: list[dict[str, Any]] | None = None
    ref_segment: dict[str, Any] | None = None
    ref_segments: list[dict[str, Any]] | None = None
    active_ref_segment_id: str | None = None
    ref_segment_video: dict[str, Any] | None = None


class Scene2DCreateRequest(BaseModel):
    title: str | None = None
    description: str | None = None


class Scene2DUpdateRequest(BaseModel):
    title: str | None = None
    description: str | None = None
    linked_scene3d_id: str | None = None
    can_be_reference: bool | None = None


class Scene2DPerspectiveCreateRequest(BaseModel):
    title: str | None = None
    type: str = "psd"
    linked_scene3d_id: str | None = None
    linked_scene3d_view: dict[str, Any] | None = None


class Scene2DPerspectiveUpdateRequest(BaseModel):
    title: str | None = None
    linked_scene3d_id: str | None = None
    linked_scene3d_view: dict[str, Any] | None = None


class Scene3DCreateRequest(BaseModel):
    title: str | None = None
    description: str | None = None


class Scene3DUpdateRequest(BaseModel):
    title: str | None = None
    description: str | None = None
    reference_view: dict[str, Any] | None = None
    display_settings: dict[str, Any] | None = None


class CanvasColorRequest(BaseModel):
    color: str


class RestoreRefApplyRequest(BaseModel):
    token: str


class AppSessionUpdateRequest(BaseModel):
    last_project_json_path: str | None = None
    selected_shot_id: str | None = None
    recent_projects: list[str] | None = None
    timeline_scroll_left: int | None = None
    status_filter: str | None = None
    revision_only: bool | None = None
    advanced_panel_open: bool | None = None
    ui_theme: str | None = None


class RestoreShotRequest(BaseModel):
    shot: dict[str, Any]
    index: int = 0


class ReorderShotsRequest(BaseModel):
    shot_ids: list[str]


class ImportImagePathRequest(BaseModel):
    source_path: str


class RefSegment3dCapture(BaseModel):
    shot_id: str
    data_url: str
    animation_time: float | None = None


class ApplyRefSegmentRequest(BaseModel):
    anchor_shot_id: str
    end_shot_id: str
    segment_id: str | None = None
    camera_name: str | None = None
    captures: list[RefSegment3dCapture] = Field(default_factory=list)


class AddShotRequest(BaseModel):
    after_shot_id: str | None = None
