from __future__ import annotations

import sys
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import app_state, project_manager, reference_segments
from .backend_service import StoryboardBackendService
from .image_utils import normalize_reference_fit_mode, save_png_data_url
from .shot_store import save_shots

# Photoshop plugin treats bridge files older than ~8s as stale (see BRIDGE_STALE_MS in panel.js).
_BRIDGE_REFRESH_SECONDS = 1.5


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


class SetActiveReferenceVideoRequest(BaseModel):
    path: str


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


class LiveBridgeUpdateRequest(BaseModel):
    selected_shot_id: str | None = None


class PluginHeartbeatRequest(BaseModel):
    open_shot_ids: list[str] = Field(default_factory=list)


class AddShotRequest(BaseModel):
    after_shot_id: str | None = None


_REACT_BUILD_HINT = "React build not found. Run: cd frontend && npm run build"


def _react_index_response(react_dist: Path) -> FileResponse:
    index_file = react_dist / "index.html"
    if not index_file.is_file():
        raise HTTPException(status_code=404, detail=_REACT_BUILD_HINT)
    return FileResponse(index_file)


def _apply_ref_segment_3d_captures(app: FastAPI, request: ApplyRefSegmentRequest) -> dict[str, Any]:
    """Finalize browser-rendered GLB captures as a normal 3D reference apply.

    The browser renders the GLB frame for each board, but this backend function owns the destructive
    write: it snapshots the original board files first, composites each capture through the existing
    board-background path, stamps provenance, and returns an undo token.
    """
    from datetime import datetime, timezone

    project = app_state._require_project(app)
    anchor = app_state._find_shot_index(project, request.anchor_shot_id)
    end = app_state._find_shot_index(project, request.end_shot_id)
    min_index = max(0, min(anchor, end))
    max_index = min(len(project.shots) - 1, max(anchor, end))
    if min_index > max_index:
        raise HTTPException(status_code=400, detail="Invalid board range.")

    captures = request.captures or []
    if not captures:
        raise HTTPException(status_code=400, detail="3D captures are required.")
    capture_by_shot: dict[str, RefSegment3dCapture] = {}
    for capture in captures:
        shot_id = str(capture.shot_id or "").strip()
        if not shot_id:
            raise HTTPException(status_code=400, detail="Capture shot_id is required.")
        if shot_id in capture_by_shot:
            raise HTTPException(status_code=400, detail=f"Duplicate 3D capture for board: {shot_id}")
        if not str(capture.data_url or "").startswith("data:image/png;base64,"):
            raise HTTPException(status_code=400, detail=f"Invalid PNG data URL for board: {shot_id}")
        capture_by_shot[shot_id] = capture

    range_shots = project.shots[min_index : max_index + 1]
    missing = [shot.shot_id for shot in range_shots if shot.shot_id not in capture_by_shot]
    if missing:
        raise HTTPException(status_code=400, detail=f"Missing 3D captures for board(s): {', '.join(missing)}")

    model_seg = project_manager.find_ref_segment(project, request.segment_id or None) or {}
    model_rel, ref_type = project_manager.resolve_segment_reference(project, model_seg)
    if ref_type != "model" or not model_rel:
        raise HTTPException(status_code=400, detail="Bind a reference GLB to this segment first.")
    model_path = (project.root_path / model_rel).resolve()
    root = project.root_path.resolve()
    if root not in model_path.parents and model_path != root:
        raise HTTPException(status_code=400, detail="Reference model path is outside the project.")
    if not model_path.is_file():
        raise HTTPException(status_code=400, detail=f"Reference model not found: {model_rel}")

    fit_mode = normalize_reference_fit_mode(str(model_seg.get("fit_mode", "") or "fit"))
    seg_id = str(model_seg.get("id", request.segment_id or "") or "").strip()
    undo_token = reference_segments.snapshot_boards_for_undo(project, min_index, max_index)
    model_mtime = model_path.stat().st_mtime
    storyboard_duration = sum(max(0.1, float(shot.duration_seconds or 3)) for shot in range_shots)
    applied_at = datetime.now(timezone.utc).isoformat()
    applied: list[dict[str, Any]] = []
    segment_offset = 0.0

    for index in range(min_index, max_index + 1):
        shot = project.shots[index]
        capture = capture_by_shot[shot.shot_id]
        if capture.animation_time is None:
            anim_time = segment_offset
        else:
            anim_time = max(0.0, float(capture.animation_time))
        shot_dir = project_manager.get_shot_dir(project, shot)
        raw_path = shot_dir / f"{shot.shot_id}_ref_raw.png"
        try:
            save_png_data_url(capture.data_url, raw_path)
            preview_path = project_manager._apply_reference_frame_to_shot(project, shot, raw_path, fit_mode)
        finally:
            raw_path.unlink(missing_ok=True)
        shot.source_sync_mtime = preview_path.stat().st_mtime
        shot.ref_video_path = model_rel
        shot.ref_video_time = round(anim_time, 3)
        shot.ref_segment_time = round(segment_offset, 3)
        camera_data = dict(shot.camera_data or {})
        camera_data["scene3d_time"] = round(anim_time, 3)
        camera_name = str(request.camera_name or "").strip()
        if camera_name:
            camera_data["scene3d_camera"] = camera_name
        camera_data["ref_segment_id"] = seg_id
        camera_data["ref_source_type"] = "model"
        camera_data["ref_applied_at"] = applied_at
        camera_data["ref_frame_time"] = round(anim_time, 3)
        shot.camera_data = camera_data
        applied.append(
            {
                "shot_id": shot.shot_id,
                "board_index": index,
                "segment_time": round(segment_offset, 3),
                "animation_time": round(anim_time, 3),
            }
        )
        segment_offset += max(0.1, float(shot.duration_seconds or 3))

    project.settings["ref_segment_apply"] = {
        "segment_id": seg_id,
        "anchor_shot_id": project.shots[min_index].shot_id,
        "end_shot_id": project.shots[max_index].shot_id,
        "source_type": "model",
        "reference_model_path": model_rel,
        "model_mtime": model_mtime,
        "video_start": round(float(model_seg.get("video_start", 0.0) or 0.0), 3),
        "storyboard_duration": round(storyboard_duration, 3),
        "fit_mode": fit_mode,
        "applied_at": applied_at,
    }
    project.settings["ref_segment"] = {
        "anchor_shot_id": project.shots[min_index].shot_id,
        "end_shot_id": project.shots[max_index].shot_id,
    }
    segments = project_manager.normalize_ref_segments(project.settings)
    if seg_id:
        for segment in segments:
            if segment["id"] == seg_id:
                segment.update({"video_start": round(float(model_seg.get("video_start", 0.0) or 0.0), 3), "source_type": "model"})
                break
        project.settings["active_ref_segment_id"] = seg_id
    project.settings["ref_segments"] = segments
    project_manager.sync_ref_segment_settings(project)
    project_manager.save_settings(project)
    save_shots(project.root_path, project.shots)
    app_state._autosave(app)
    return {
        "board_count": len(applied),
        "segment_duration": round(segment_offset, 3),
        "applied": applied,
        "undo_token": undo_token,
        **app_state._project_payload(project, app.state.dirty),
    }


def create_app(base_dir: Path, bridge_port: int = 8000) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        stop_event = threading.Event()

        def bridge_refresh_loop() -> None:
            from . import app_state

            while not stop_event.wait(_BRIDGE_REFRESH_SECONDS):
                try:
                    app_state._touch_live_bridge(app)
                except Exception:
                    # Keep the loop alive; bridge file writes are best-effort.
                    pass

        refresh_thread = threading.Thread(
            target=bridge_refresh_loop,
            name="storyboard-bridge-refresh",
            daemon=True,
        )
        refresh_thread.start()
        try:
            yield
        finally:
            stop_event.set()
            refresh_thread.join(timeout=2.0)
            _shutdown_reference_cleanup(app)

    app = FastAPI(title="Storyboard Tool", lifespan=lifespan)
    app.state.base_dir = base_dir
    app.state.project = None
    app.state.project_disk_mtime = 0.0
    app.state.dirty = False
    app.state.live_selected_shot_id = ""
    app.state.bridge_port = bridge_port
    app.state.plugin_last_seen = 0.0
    app.state.plugin_open_shot_ids = []
    app.state.live_focus_shot_id = ""
    app.state.live_focus_token = 0

    def _svc() -> StoryboardBackendService:
        return StoryboardBackendService(app)

    def _file_response_from_meta(meta: dict[str, str]) -> FileResponse:
        path = Path(meta["path"])
        kwargs: dict[str, str] = {}
        if meta.get("media_type"):
            kwargs["media_type"] = meta["media_type"]
        if meta.get("filename"):
            kwargs["filename"] = meta["filename"]
        return FileResponse(path, **kwargs)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def _no_store_assets(request, call_next):
        response = await call_next(request)
        path = request.url.path
        if (
            path == "/"
            or path.startswith("/static")
            or path.startswith("/react")
            or path.startswith("/ref-")
            or path.endswith(".html")
        ):
            response.headers["Cache-Control"] = "no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response

    web_dir = Path(__file__).parent / "web"
    react_dist = web_dir / "dist"
    app.mount("/static", StaticFiles(directory=web_dir / "static"), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return _react_index_response(react_dist)

    @app.get("/ref-segment")
    @app.get("/ref-scene3d")
    @app.get("/ref-video")
    def ref_window_redirect() -> RedirectResponse:
        return RedirectResponse(url="/", status_code=302)

    @app.get("/react")
    def react_index() -> FileResponse:
        return _react_index_response(react_dist)

    @app.get("/react/{asset_path:path}")
    def react_asset(asset_path: str) -> FileResponse:
        index_file = react_dist / "index.html"
        resolved = (react_dist / asset_path).resolve()
        dist_root = react_dist.resolve()
        if resolved.is_file() and (resolved == dist_root or dist_root in resolved.parents):
            return FileResponse(resolved)
        if not index_file.is_file():
            raise HTTPException(status_code=404, detail=_REACT_BUILD_HINT)
        return FileResponse(index_file)

    @app.get("/api/project")
    def get_project() -> dict[str, Any]:
        return _svc().method_get_project()

    @app.get("/api/app/session")
    def get_app_session() -> dict[str, Any]:
        return _svc().method_get_session()

    @app.put("/api/app/session")
    def put_app_session(request: AppSessionUpdateRequest) -> dict[str, Any]:
        return _svc().method_update_session(request.model_dump(exclude_unset=True))

    @app.get("/api/bridge/live")
    def get_live_bridge() -> dict[str, Any]:
        return _svc().method_touch_live_bridge()

    @app.put("/api/bridge/live")
    def put_live_bridge(request: LiveBridgeUpdateRequest) -> dict[str, Any]:
        return _svc().method_touch_live_bridge(selected_shot_id=request.selected_shot_id)

    @app.post("/api/bridge/relink")
    def relink_bridge() -> dict[str, Any]:
        return _svc().method_bridge_relink()

    @app.get("/api/bridge/status")
    def bridge_status() -> dict[str, Any]:
        return _svc().method_bridge_status()

    @app.post("/api/bridge/plugin-heartbeat")
    def plugin_heartbeat(payload: PluginHeartbeatRequest | None = None) -> dict[str, str]:
        app.state.plugin_last_seen = time.time()
        if payload is not None:
            app.state.plugin_open_shot_ids = [str(item) for item in payload.open_shot_ids if item]
        return {"ok": "true"}

    @app.get("/api/project/missing-files")
    def missing_project_files() -> dict[str, Any]:
        return _svc().method_get_missing_files()

    @app.post("/api/project/new")
    def new_project(request: ProjectPathRequest) -> dict[str, Any]:
        return _svc().method_new_project(request.path, request.canvas_width, request.canvas_height)

    @app.post("/api/project/open")
    def open_project(request: OpenProjectRequest) -> dict[str, Any]:
        return _svc().method_open_project(request.project_json_path)

    @app.post("/api/project/save")
    def save_project() -> dict[str, Any]:
        return _svc().method_save_project()

    @app.get("/api/system/blender-candidates")
    def blender_candidates() -> dict[str, Any]:
        return _svc().method_blender_candidates()

    @app.post("/api/system/browse-blender")
    def browse_blender() -> dict[str, str]:
        return _svc().method_browse_blender()

    @app.get("/api/system/photoshop-candidates")
    def photoshop_candidates() -> dict[str, Any]:
        return _svc().method_photoshop_candidates()

    @app.post("/api/system/browse-folder")
    def browse_folder_dialog() -> dict[str, Any]:
        return _svc().method_browse_folder()

    @app.post("/api/system/browse-project-json")
    def browse_project_json_dialog() -> dict[str, Any]:
        return _svc().method_browse_project_json()

    @app.post("/api/system/browse-photoshop")
    def browse_photoshop() -> dict[str, str]:
        return _svc().method_browse_photoshop()

    @app.patch("/api/project/settings")
    def update_settings(request: SettingsUpdateRequest) -> dict[str, Any]:
        return _svc().method_update_settings(request.model_dump(exclude_unset=True))

    @app.post("/api/project/references")
    async def upload_project_reference(file: UploadFile = File(...)) -> dict[str, Any]:
        try:
            data = await file.read()
        finally:
            await file.close()
        return _svc().method_upload_project_reference(file.filename or "reference", data)

    @app.delete("/api/project/references/{ref_id}")
    def delete_project_reference(ref_id: str) -> dict[str, Any]:
        return _svc().method_delete_project_reference(ref_id)

    @app.post("/api/project/reference-video")
    async def upload_reference_video(file: UploadFile = File(...)) -> dict[str, Any]:
        try:
            data = await file.read()
        finally:
            await file.close()
        return _svc().method_upload_reference_video(file.filename or "reference.mp4", data)

    @app.post("/api/project/ref-segment/apply-3d")
    def apply_ref_segment_3d(request: ApplyRefSegmentRequest) -> dict[str, Any]:
        if request.captures:
            return _apply_ref_segment_3d_captures(app, request)
        return _svc().method_apply_ref_segment_3d(
            request.anchor_shot_id,
            request.end_shot_id,
            request.segment_id or "",
            str(request.camera_name or ""),
        )

    @app.post("/api/project/ref-segment/apply-image")
    def apply_ref_segment_image(request: ApplyRefSegmentRequest) -> dict[str, Any]:
        return _svc().method_apply_ref_segment_image(request.anchor_shot_id, request.end_shot_id, request.segment_id or "")

    @app.post("/api/project/ref-segment/apply")
    def apply_ref_segment(request: ApplyRefSegmentRequest) -> dict[str, Any]:
        return _svc().method_apply_ref_segment(request.anchor_shot_id, request.end_shot_id, request.segment_id or "")

    @app.delete("/api/project/ref-segments/{segment_id}")
    def delete_ref_segment(segment_id: str) -> dict[str, Any]:
        return _svc().method_delete_ref_segment(segment_id)

    @app.post("/api/project/ref-apply/undo")
    def restore_ref_apply(request: RestoreRefApplyRequest) -> dict[str, Any]:
        return _svc().method_restore_ref_apply(request.token)

    @app.post("/api/project/scene3d/open-blender")
    def open_blender_scene() -> dict[str, Any]:
        return _svc().method_open_blender_scene()

    @app.post("/api/project/scene3d/import")
    async def import_scene3d(file: UploadFile = File(...)) -> dict[str, Any]:
        try:
            data = await file.read()
        finally:
            await file.close()
        return _svc().method_import_scene3d(file.filename or "scene.glb", data)

    @app.get("/api/project/scene3d/file")
    def get_scene3d_file() -> FileResponse:
        return _file_response_from_meta(_svc().method_get_scene3d_file())

    @app.get("/api/project/canvas-color")
    def get_canvas_color() -> dict[str, str]:
        return _svc().method_get_canvas_color()

    @app.post("/api/project/canvas-color")
    def set_canvas_color(request: CanvasColorRequest) -> dict[str, Any]:
        return _svc().method_set_canvas_color(request.color)

    @app.post("/api/shots")
    def add_shot(request: AddShotRequest = AddShotRequest()) -> dict[str, Any]:
        return _svc().method_add_shot(request.after_shot_id)

    @app.post("/api/shots/{shot_id}/duplicate")
    def duplicate_shot(shot_id: str) -> dict[str, Any]:
        return _svc().method_duplicate_shot(shot_id)

    @app.patch("/api/shots/{shot_id}")
    def update_shot(shot_id: str, request: ShotUpdateRequest) -> dict[str, Any]:
        return _svc().method_update_shot(shot_id, request.model_dump())

    @app.delete("/api/shots/{shot_id}")
    def delete_shot(shot_id: str) -> dict[str, Any]:
        return _svc().method_delete_shot(shot_id)

    @app.post("/api/shots/restore")
    def restore_shot(request: RestoreShotRequest) -> dict[str, Any]:
        return _svc().method_restore_shot(request.shot, request.index)

    @app.post("/api/shots/reorder")
    def reorder_shots(request: ReorderShotsRequest) -> dict[str, Any]:
        return _svc().method_reorder_shots(request.shot_ids)

    @app.post("/api/shots/{shot_id}/import-image-path")
    def import_image_path(shot_id: str, request: ImportImagePathRequest) -> dict[str, Any]:
        return _svc().method_import_image_path(shot_id, request.source_path)

    @app.post("/api/shots/{shot_id}/move-up")
    def move_shot_up(shot_id: str) -> dict[str, Any]:
        return _svc().method_move_shot_up(shot_id)

    @app.post("/api/shots/{shot_id}/move-down")
    def move_shot_down(shot_id: str) -> dict[str, Any]:
        return _svc().method_move_shot_down(shot_id)

    @app.post("/api/shots/{shot_id}/image")
    async def import_image(shot_id: str, file: UploadFile = File(...)) -> dict[str, Any]:
        try:
            data = await file.read()
        finally:
            await file.close()
        return _svc().method_import_shot_image(shot_id, file.filename or "", data)

    @app.post("/api/shots/{shot_id}/references")
    async def add_reference_image(shot_id: str, file: UploadFile = File(...)) -> dict[str, Any]:
        try:
            data = await file.read()
        finally:
            await file.close()
        return _svc().method_add_shot_reference_image(shot_id, file.filename or "", data)

    @app.delete("/api/shots/{shot_id}/references")
    def remove_reference_image(shot_id: str, request: RemoveReferenceRequest) -> dict[str, Any]:
        return _svc().method_remove_shot_reference_image(shot_id, request.path)

    @app.put("/api/shots/{shot_id}/references")
    def set_reference_image_paths(shot_id: str, request: SetReferencePathsRequest) -> dict[str, Any]:
        return _svc().method_set_shot_reference_image_paths(shot_id, request.paths)

    @app.post("/api/shots/{shot_id}/source")
    async def import_source_file(shot_id: str, file: UploadFile = File(...)) -> dict[str, Any]:
        try:
            data = await file.read()
        finally:
            await file.close()
        return _svc().method_import_shot_source(shot_id, file.filename or f"{shot_id}.psd", data)

    @app.post("/api/shots/{shot_id}/relink-preview")
    def relink_preview(shot_id: str, request: RelinkRequest) -> dict[str, Any]:
        return _svc().method_relink_preview(shot_id, request.relative_path)

    @app.post("/api/shots/{shot_id}/canvas")
    def create_canvas(shot_id: str, request: CanvasRequest) -> dict[str, Any]:
        return _svc().method_create_shot_canvas(shot_id, request.width, request.height, request.background_color)

    @app.post("/api/shots/{shot_id}/drawing")
    def save_drawing(shot_id: str, request: DrawingSaveRequest) -> dict[str, Any]:
        return _svc().method_save_shot_drawing(shot_id, request.image_data)

    @app.post("/api/shots/{shot_id}/sync")
    def sync_shot(shot_id: str, force: bool = False) -> dict[str, Any]:
        return _svc().method_sync_shot(shot_id, force)

    @app.post("/api/project/sync")
    def sync_all_shots(force: bool = False) -> dict[str, Any]:
        return _svc().method_sync_all_shots(force)

    @app.post("/api/shots/{shot_id}/open-source")
    def open_source(shot_id: str) -> dict[str, str]:
        return _svc().method_open_source(shot_id)

    @app.post("/api/shots/{shot_id}/recover-source")
    def recover_source(shot_id: str, preserve_layers: bool = True) -> dict[str, Any]:
        return _svc().method_recover_shot_source(shot_id, preserve_layers)

    @app.post("/api/shots/{shot_id}/open-preview")
    def open_preview(shot_id: str) -> dict[str, str]:
        return _svc().method_open_preview(shot_id)

    @app.delete("/api/shots/{shot_id}/image")
    def remove_image(shot_id: str) -> dict[str, Any]:
        return _svc().method_remove_shot_image(shot_id)

    @app.get("/api/shots/{shot_id}/image")
    def get_image(shot_id: str) -> FileResponse:
        return _file_response_from_meta(_svc().method_get_shot_image(shot_id))

    @app.get("/api/shots/{shot_id}/thumbnail")
    def get_thumbnail(shot_id: str) -> FileResponse:
        return _file_response_from_meta(_svc().method_get_shot_thumbnail(shot_id))

    @app.get("/api/shots/{shot_id}/board-background")
    def get_board_background(shot_id: str) -> FileResponse:
        return _file_response_from_meta(_svc().method_get_shot_board_background(shot_id))

    @app.get("/api/files")
    def get_project_file(path: str) -> FileResponse:
        return _file_response_from_meta(_svc().method_get_project_file(path))

    @app.post("/api/shots/{shot_id}/comments")
    def add_comment(shot_id: str, request: CommentRequest) -> dict[str, Any]:
        return _svc().method_add_comment(shot_id, request.text)

    @app.patch("/api/shots/{shot_id}/comments/{comment_id}")
    def resolve_comment(shot_id: str, comment_id: int, request: CommentResolveRequest) -> dict[str, Any]:
        return _svc().method_resolve_comment(shot_id, comment_id, request.resolved)

    @app.get("/api/shots/{shot_id}/annotations")
    def get_annotations(shot_id: str) -> dict[str, Any]:
        return _svc().method_get_annotations(shot_id)

    @app.put("/api/shots/{shot_id}/annotations")
    def save_annotations(shot_id: str, request: AnnotationSaveRequest) -> dict[str, Any]:
        return _svc().method_save_annotations(shot_id, request.annotations)

    @app.post("/api/export/pdf")
    def export_pdf(request: PdfExportRequest) -> dict[str, str]:
        return _svc().method_export_pdf(request.layout)

    @app.post("/api/export/shot-list")
    def export_shot_list() -> dict[str, str]:
        return _svc().method_export_shot_list()

    @app.get("/api/export/shot-list")
    def download_shot_list() -> FileResponse:
        return _file_response_from_meta(_svc().method_download_shot_list())

    @app.post("/api/export/timing")
    def export_timing() -> dict[str, str]:
        return _svc().method_export_timing()

    @app.get("/api/export/timing")
    def download_timing() -> FileResponse:
        return _file_response_from_meta(_svc().method_download_timing())

    @app.post("/api/export/contact-sheet")
    def export_contact() -> dict[str, str]:
        return _svc().method_export_contact_sheet()

    @app.get("/api/export/contact-sheet")
    def download_contact() -> FileResponse:
        return _file_response_from_meta(_svc().method_download_contact_sheet())

    @app.post("/api/export/image-sequence")
    def export_sequence() -> dict[str, str]:
        return _svc().method_export_image_sequence()

    @app.get("/api/export/pdf")
    def download_pdf() -> FileResponse:
        return _file_response_from_meta(_svc().method_download_pdf())

    return app


def _shutdown_reference_cleanup(app: FastAPI) -> None:
    try:
        project_manager.shutdown_reference_cleanup(
            app.state.project,
            save_if_dirty=bool(getattr(app.state, "dirty", False)),
            dirty=bool(getattr(app.state, "dirty", False)),
        )
    except Exception as exc:
        print(f"Reference cleanup failed: {exc}", file=sys.stderr)
