from __future__ import annotations

import logging
import sys
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import app_state, logging_config, project_manager, runtime_state
from .backend_service import StoryboardBackendService
from .errors import AppErrorCode
from .logging_config import setup_logging
from .schemas import (
    AddShotRequest,
    AnnotationSaveRequest,
    AppSessionUpdateRequest,
    ApplyRefSegmentRequest,
    CanvasColorRequest,
    CanvasRequest,
    CommentRequest,
    CommentResolveRequest,
    DrawingSaveRequest,
    ImportImagePathRequest,
    LiveBridgeUpdateRequest,
    OpenProjectRequest,
    PdfExportRequest,
    PluginHeartbeatRequest,
    PluginNextShotRequest,
    PluginShotEventRequest,
    ProjectPathRequest,
    RefSegment3dCapture,
    RelinkRequest,
    RemoveReferenceRequest,
    ReorderShotsRequest,
    RestoreRefApplyRequest,
    RestoreShotRequest,
    Scene2DCreateRequest,
    Scene2DPerspectiveCreateRequest,
    Scene2DPerspectiveUpdateRequest,
    Scene2DUpdateRequest,
    Scene3DCreateRequest,
    Scene3DUpdateRequest,
    SetReferencePathsRequest,
    SettingsUpdateRequest,
    ShotUpdateRequest,
)

# Photoshop plugin treats bridge files older than ~8s as stale (see BRIDGE_STALE_MS in panel.js).
_BRIDGE_REFRESH_SECONDS = 1.5


_REACT_BUILD_HINT = "React build not found. Run: cd frontend && npm run build"
logger = logging.getLogger(__name__)


def _react_index_response(react_dist: Path) -> FileResponse:
    index_file = react_dist / "index.html"
    if not index_file.is_file():
        raise HTTPException(status_code=404, detail=_REACT_BUILD_HINT)
    return FileResponse(index_file)


def _model_captures_payload(captures: list[RefSegment3dCapture]) -> list[dict[str, Any]]:
    return [capture.model_dump() for capture in captures]


async def _read_upload(file: UploadFile, fallback_name: str) -> tuple[str, bytes]:
    try:
        data = await file.read()
    finally:
        await file.close()
    return file.filename or fallback_name, data


def create_app(base_dir: Path, bridge_port: int = 8000) -> FastAPI:
    setup_logging()

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
    app.state.main_window = None
    runtime_state.init_bridge_state(app, bridge_port)

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

    @app.exception_handler(HTTPException)
    async def _structured_error_handler(request: Request, exc: HTTPException) -> JSONResponse:
        # When detail is already a flat dict (from app_error()), return it directly so
        # the response is {"detail": "...", "code": "..."}.  For plain-string detail
        # (legacy HTTPException raises) produce the same {"detail": "..."} as FastAPI's
        # default handler, so all existing callers continue to work.
        body = exc.detail if isinstance(exc.detail, dict) else {"detail": exc.detail}
        return JSONResponse(content=body, status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def _unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled API exception for %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={
                "detail": f"Internal error. See {logging_config.LOG_FILE}.",
                "code": AppErrorCode.INTERNAL_ERROR,
            },
        )

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

    @app.get("/ref-video")
    def ref_video_redirect() -> RedirectResponse:
        # bridge.py opens a second pywebview window at /ref-video; redirect to the React SPA.
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

    @app.get("/api/app/bootstrap")
    def bootstrap() -> dict[str, Any]:
        return _svc().method_bootstrap()

    @app.post("/api/app/ui-ready")
    def ui_ready() -> dict[str, Any]:
        return _svc().method_ui_ready()

    @app.post("/api/app/focus")
    def focus_app() -> dict[str, Any]:
        return _svc().method_app_focus()

    @app.post("/api/app/preheat-photoshop")
    def preheat_photoshop() -> dict[str, Any]:
        return _svc().method_preheat_photoshop()

    @app.post("/api/project/preview-analysis/refresh")
    def refresh_preview_analysis() -> dict[str, Any]:
        return _svc().method_refresh_preview_analysis()

    @app.get("/api/project/preview-analysis/status")
    def preview_analysis_status() -> dict[str, Any]:
        return _svc().method_preview_analysis_status()

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
        return _svc().method_plugin_heartbeat(payload.model_dump() if payload is not None else {})

    @app.get("/api/plugin/context")
    def plugin_context() -> dict[str, Any]:
        return _svc().method_plugin_context()

    @app.post("/api/plugin/heartbeat")
    def plugin_api_heartbeat(payload: PluginHeartbeatRequest | None = None) -> dict[str, str]:
        return _svc().method_plugin_heartbeat(payload.model_dump() if payload is not None else {})

    @app.post("/api/plugin/shots/{shot_id}/export-preview")
    def plugin_export_preview(shot_id: str, request: PluginShotEventRequest | None = None) -> dict[str, Any]:
        return _svc().method_plugin_export_preview(shot_id, request.model_dump() if request is not None else {})

    @app.post("/api/plugin/shots/{shot_id}/psd-saved")
    def plugin_psd_saved(shot_id: str, request: PluginShotEventRequest | None = None) -> dict[str, Any]:
        return _svc().method_plugin_psd_saved(shot_id, request.model_dump() if request is not None else {})

    @app.post("/api/plugin/shots/{shot_id}/focus")
    def plugin_focus_shot(shot_id: str) -> dict[str, Any]:
        return _svc().method_plugin_focus_shot(shot_id)

    @app.post("/api/plugin/shots/next")
    def plugin_next_shot(request: PluginNextShotRequest) -> dict[str, Any]:
        return _svc().method_plugin_next_shot(request.current_shot_id, request.auto_add)

    @app.post("/api/plugin/scenes2d/{scene_id}/perspectives/{perspective_id}/export-preview")
    def plugin_scene2d_export_preview(scene_id: str, perspective_id: str) -> dict[str, Any]:
        return _svc().method_plugin_scene2d_export_preview(scene_id, perspective_id)

    @app.post("/api/plugin/scenes2d/{scene_id}/perspectives/{perspective_id}/psd-saved")
    def plugin_scene2d_psd_saved(scene_id: str, perspective_id: str) -> dict[str, Any]:
        return _svc().method_plugin_scene2d_psd_saved(scene_id, perspective_id)

    @app.post("/api/plugin/scenes2d/{scene_id}/perspectives/{perspective_id}/next-perspective")
    def plugin_scene2d_next_perspective(scene_id: str, perspective_id: str) -> dict[str, Any]:
        return _svc().method_plugin_scene2d_next_perspective(scene_id, perspective_id)

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
        filename, data = await _read_upload(file, "reference")
        return _svc().method_upload_project_reference(filename, data)

    @app.delete("/api/project/references/{ref_id}")
    def delete_project_reference(ref_id: str) -> dict[str, Any]:
        return _svc().method_delete_project_reference(ref_id)

    @app.post("/api/project/reference-video")
    async def upload_reference_video(file: UploadFile = File(...)) -> dict[str, Any]:
        filename, data = await _read_upload(file, "reference.mp4")
        return _svc().method_upload_reference_video(filename, data)

    @app.post("/api/project/ref-segment/apply-3d")
    def apply_ref_segment_3d(request: ApplyRefSegmentRequest) -> dict[str, Any]:
        if request.captures:
            return _svc().method_apply_ref_segment_model_captures(
                request.anchor_shot_id,
                request.end_shot_id,
                request.segment_id or "",
                str(request.camera_name or ""),
                _model_captures_payload(request.captures),
            )
        return _svc().method_apply_ref_segment_3d(
            request.anchor_shot_id,
            request.end_shot_id,
            request.segment_id or "",
            str(request.camera_name or ""),
        )

    @app.post("/api/project/ref-segment/apply-model-captures")
    def apply_ref_segment_model_captures(request: ApplyRefSegmentRequest) -> dict[str, Any]:
        """Finalize desktop-rendered GLB captures — validate, snapshot, save boards, stamp metadata."""
        return _svc().method_apply_ref_segment_model_captures(
            request.anchor_shot_id,
            request.end_shot_id,
            request.segment_id or "",
            str(request.camera_name or ""),
            _model_captures_payload(request.captures),
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

    @app.post("/api/project/ref-segments/snapshot")
    def snapshot_ref_boards(request: ApplyRefSegmentRequest) -> dict[str, Any]:
        return _svc().method_snapshot_ref_boards(request.anchor_shot_id, request.end_shot_id)

    @app.post("/api/project/ref-apply/undo")
    def restore_ref_apply(request: RestoreRefApplyRequest) -> dict[str, Any]:
        return _svc().method_restore_ref_apply(request.token)

    @app.post("/api/project/scene3d/open-blender")
    def open_blender_scene() -> dict[str, Any]:
        return _svc().method_open_blender_scene()

    @app.post("/api/project/scene3d/import")
    async def import_scene3d(file: UploadFile = File(...)) -> dict[str, Any]:
        filename, data = await _read_upload(file, "scene.glb")
        return _svc().method_import_scene3d(filename, data)

    @app.get("/api/project/scene3d/file")
    def get_scene3d_file() -> FileResponse:
        return _file_response_from_meta(_svc().method_get_scene3d_file())

    @app.get("/api/project/scenes3d")
    def list_scenes3d() -> dict[str, Any]:
        return _svc().method_list_scene3d()

    @app.post("/api/project/scenes3d")
    def create_scene3d(request: Scene3DCreateRequest = Scene3DCreateRequest()) -> dict[str, Any]:
        return _svc().method_create_scene3d(request.model_dump(exclude_unset=True))

    @app.patch("/api/project/scenes3d/{scene3d_id}")
    def update_scene3d(scene3d_id: str, request: Scene3DUpdateRequest) -> dict[str, Any]:
        return _svc().method_update_scene3d(scene3d_id, request.model_dump(exclude_unset=True))

    @app.delete("/api/project/scenes3d/{scene3d_id}")
    def delete_scene3d(scene3d_id: str) -> dict[str, Any]:
        return _svc().method_delete_scene3d(scene3d_id)

    @app.post("/api/project/scenes3d/{scene3d_id}/set-active")
    def set_active_scene3d(scene3d_id: str) -> dict[str, Any]:
        return _svc().method_set_active_scene3d(scene3d_id)

    @app.post("/api/project/scenes3d/{scene3d_id}/import")
    async def import_scene3d_to_scene(scene3d_id: str, file: UploadFile = File(...)) -> dict[str, Any]:
        filename, data = await _read_upload(file, "scene.glb")
        return _svc().method_import_scene3d_to_scene(scene3d_id, filename, data)

    @app.get("/api/project/scenes3d/{scene3d_id}/file")
    def get_scene3d_scene_file(scene3d_id: str) -> FileResponse:
        return _file_response_from_meta(_svc().method_get_scene3d_file(scene3d_id))

    @app.get("/api/project/scenes2d")
    def list_scenes2d() -> dict[str, Any]:
        return _svc().method_list_scene2d()

    @app.post("/api/project/scenes2d")
    def create_scene2d(request: Scene2DCreateRequest = Scene2DCreateRequest()) -> dict[str, Any]:
        return _svc().method_create_scene2d(request.model_dump(exclude_unset=True))

    @app.patch("/api/project/scenes2d/{scene_id}")
    def update_scene2d(scene_id: str, request: Scene2DUpdateRequest) -> dict[str, Any]:
        return _svc().method_update_scene2d(scene_id, request.model_dump(exclude_unset=True))

    @app.delete("/api/project/scenes2d/{scene_id}")
    def delete_scene2d(scene_id: str) -> dict[str, Any]:
        return _svc().method_delete_scene2d(scene_id)

    @app.post("/api/project/scenes2d/{scene_id}/open")
    def open_scene2d(scene_id: str) -> dict[str, Any]:
        return _svc().method_open_scene2d(scene_id)

    @app.post("/api/project/scenes2d/{scene_id}/refresh-preview")
    def refresh_scene2d_preview(scene_id: str) -> dict[str, Any]:
        return _svc().method_refresh_scene2d_preview(scene_id)

    @app.post("/api/project/scenes2d/{scene_id}/add-to-references")
    def add_scene2d_to_references(scene_id: str) -> dict[str, Any]:
        return _svc().method_add_scene2d_to_references(scene_id)

    @app.get("/api/project/scenes2d/{scene_id}/preview")
    def get_scene2d_preview(scene_id: str) -> FileResponse:
        return _file_response_from_meta(_svc().method_get_scene2d_preview(scene_id))

    @app.get("/api/project/scenes2d/{scene_id}/perspectives")
    def list_scene2d_perspectives(scene_id: str) -> dict[str, Any]:
        return _svc().method_list_scene2d_perspectives(scene_id)

    @app.post("/api/project/scenes2d/{scene_id}/perspectives")
    def create_scene2d_perspective(scene_id: str, request: Scene2DPerspectiveCreateRequest = Scene2DPerspectiveCreateRequest()) -> dict[str, Any]:
        return _svc().method_create_scene2d_perspective(scene_id, request.model_dump(exclude_unset=True))

    @app.post("/api/project/scenes2d/{scene_id}/perspectives/import")
    async def import_scene2d_perspective(
        scene_id: str,
        file: UploadFile = File(...),
        title: str = Form(""),
        linked_scene3d_id: str = Form(""),
    ) -> dict[str, Any]:
        filename, data = await _read_upload(file, "perspective")
        return _svc().method_import_scene2d_perspective(scene_id, filename, data, title, linked_scene3d_id)

    @app.patch("/api/project/scenes2d/{scene_id}/perspectives/{perspective_id}")
    def update_scene2d_perspective(scene_id: str, perspective_id: str, request: Scene2DPerspectiveUpdateRequest) -> dict[str, Any]:
        return _svc().method_update_scene2d_perspective(scene_id, perspective_id, request.model_dump(exclude_unset=True))

    @app.delete("/api/project/scenes2d/{scene_id}/perspectives/{perspective_id}")
    def delete_scene2d_perspective(scene_id: str, perspective_id: str) -> dict[str, Any]:
        return _svc().method_delete_scene2d_perspective(scene_id, perspective_id)

    @app.post("/api/project/scenes2d/{scene_id}/perspectives/{perspective_id}/open")
    def open_scene2d_perspective(scene_id: str, perspective_id: str) -> dict[str, Any]:
        return _svc().method_open_scene2d_perspective(scene_id, perspective_id)

    @app.post("/api/project/scenes2d/{scene_id}/perspectives/{perspective_id}/refresh-preview")
    def refresh_scene2d_perspective_preview(scene_id: str, perspective_id: str) -> dict[str, Any]:
        return _svc().method_refresh_scene2d_perspective_preview(scene_id, perspective_id)

    @app.post("/api/project/scenes2d/{scene_id}/perspectives/{perspective_id}/set-primary")
    def set_primary_scene2d_perspective(scene_id: str, perspective_id: str) -> dict[str, Any]:
        return _svc().method_set_primary_scene2d_perspective(scene_id, perspective_id)

    @app.post("/api/project/scenes2d/{scene_id}/perspectives/{perspective_id}/add-to-references")
    def add_scene2d_perspective_to_references(scene_id: str, perspective_id: str) -> dict[str, Any]:
        return _svc().method_add_scene2d_perspective_to_references(scene_id, perspective_id)

    @app.get("/api/project/scenes2d/{scene_id}/perspectives/{perspective_id}/preview")
    def get_scene2d_perspective_preview(scene_id: str, perspective_id: str) -> FileResponse:
        return _file_response_from_meta(_svc().method_get_scene2d_perspective_preview(scene_id, perspective_id))

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
        filename, data = await _read_upload(file, "")
        return _svc().method_import_shot_image(shot_id, filename, data)

    @app.post("/api/shots/{shot_id}/references")
    async def add_reference_image(shot_id: str, file: UploadFile = File(...)) -> dict[str, Any]:
        filename, data = await _read_upload(file, "")
        return _svc().method_add_shot_reference_image(shot_id, filename, data)

    @app.delete("/api/shots/{shot_id}/references")
    def remove_reference_image(shot_id: str, request: RemoveReferenceRequest) -> dict[str, Any]:
        return _svc().method_remove_shot_reference_image(shot_id, request.path)

    @app.put("/api/shots/{shot_id}/references")
    def set_reference_image_paths(shot_id: str, request: SetReferencePathsRequest) -> dict[str, Any]:
        return _svc().method_set_shot_reference_image_paths(shot_id, request.paths)

    @app.post("/api/shots/{shot_id}/source")
    async def import_source_file(shot_id: str, file: UploadFile = File(...)) -> dict[str, Any]:
        filename, data = await _read_upload(file, f"{shot_id}.psd")
        return _svc().method_import_shot_source(shot_id, filename, data)

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
