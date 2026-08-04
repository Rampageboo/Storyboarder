from __future__ import annotations

import hmac
import json
import logging
import os
import re
import sys
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import (
    app_state,
    blender_bridge,
    bpy_viewport,
    bpy_viewport_api,
    generation_service,
    logging_config,
    project_manager,
    runtime_state,
)
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
    GenerationCandidateAcceptRequest,
    GenerationBatchQueueRequest,
    GenerationBatchDispatchRequest,
    GenerationRequestCreateRequest,
    ImportImagePathRequest,
    LiveBridgeUpdateRequest,
    OpenProjectRequest,
    AnimaticExportRequest,
    ExportOpenRequest,
    ExportScopeRequest,
    PdfExportRequest,
    PluginHeartbeatRequest,
    PluginNextShotRequest,
    PluginShotEventRequest,
    PluginWriteIntentRequest,
    ProjectPathRequest,
    RecentForgetRequest,
    RefSegment3dCapture,
    RelinkRequest,
    RemoveReferenceRequest,
    ReorderShotsRequest,
    RestoreRefApplyRequest,
    RestoreShotRequest,
    SaveProjectAsRequest,
    Scene2DCreateRequest,
    Scene2DPerspectiveCreateRequest,
    Scene2DPerspectiveMoveRequest,
    Scene2DPerspectiveReorderRequest,
    Scene2DPerspectiveUpdateRequest,
    Scene2DUpdateRequest,
    Scene3DCreateRequest,
    Scene3DUpdateRequest,
    SetReferencePathsRequest,
    SettingsUpdateRequest,
    ShotUpdateRequest,
    ShotBatchDeleteRequest,
    ShotBatchRestoreRequest,
    ShotBatchUpdateRequest,
)

# Photoshop plugin treats bridge files older than ~8s as stale (see BRIDGE_STALE_MS in panel.js).
_BRIDGE_REFRESH_SECONDS = 1.5
_GENERATION_SIGNAL_SECONDS = 0.5

# Uploads are buffered in memory by _read_upload; cap the size so a single large or
# hostile upload cannot exhaust process memory. Generous enough for reference-video
# clips while still bounding worst-case allocation.
_MAX_UPLOAD_BYTES = 1024 * 1024 * 1024  # 1 GiB

# The local server is same-origin for the React app (it serves the bundle) and is
# reached cross-origin only by localhost clients (the Photoshop UXP plugin, which
# probes 127.0.0.1/localhost ports). Reflecting arbitrary web origins would let any
# page the user visits read API responses (project data, board images). Restrict the
# allowed cross-origin set to localhost only. `null` is deliberately excluded: a
# sandboxed iframe on a hostile page carries `Origin: null`, so allowing it would
# re-open cross-origin reads. Non-browser clients (the UXP plugin) send no Origin and
# are not subject to CORS, so they are unaffected by this restriction.
_ALLOWED_ORIGIN_REGEX = r"^https?://(127\.0\.0\.1|localhost)(:\d+)?$"

# Per-launch API token. The launcher exports STORYBOARDER_LAUNCH_TOKEN; when present,
# state-changing /api requests must echo it in this header. This blocks cross-origin
# CSRF writes (which CORS alone cannot: multipart/simple POSTs are preflight-exempt so
# the browser still sends them) and stray local processes. Read/GET routes stay open so
# <img>/<a> media loads, which cannot carry custom headers, keep working; cross-origin
# reads are already blocked by the CORS restriction above.
_API_TOKEN_HEADER = "x-storyboarder-token"
_LAUNCH_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
# Health/identity probe hit by the launcher before the UI (and thus the token) loads.
_TOKEN_EXEMPT_API_PATHS = frozenset({"/api/bridge/status"})


_REACT_BUILD_HINT = "React build not found. Run: cd frontend && npm run build"
logger = logging.getLogger(__name__)


def _read_launch_token() -> str:
    token = os.environ.get("STORYBOARDER_LAUNCH_TOKEN", "").strip()
    if token and _LAUNCH_TOKEN_RE.match(token):
        return token
    return ""


def _react_index_response(react_dist: Path, token: str = "") -> FileResponse | HTMLResponse:
    index_file = react_dist / "index.html"
    if not index_file.is_file():
        raise HTTPException(status_code=404, detail=_REACT_BUILD_HINT)
    if not token:
        return FileResponse(index_file)
    # Inject the per-launch token into the same-origin document so the SPA can read it
    # and echo it on API calls. The token is charset-validated (see _read_launch_token)
    # so it is safe to embed; json.dumps also quotes/escapes it defensively.
    markup = index_file.read_text(encoding="utf-8")
    injection = (
        f'<meta name="storyboarder-token" content="{token}">'
        f"<script>window.__STORYBOARDER_TOKEN__={json.dumps(token)};</script>"
    )
    if "</head>" in markup:
        markup = markup.replace("</head>", injection + "</head>", 1)
    else:
        markup = injection + markup
    return HTMLResponse(markup)


def _model_captures_payload(captures: list[RefSegment3dCapture]) -> list[dict[str, Any]]:
    return [capture.model_dump() for capture in captures]


def _plugin_protocol_headers(request: Request) -> dict[str, Any]:
    raw_version = request.headers.get("x-storyboarder-protocol", "").strip()
    raw_revision = request.headers.get("x-storyboarder-context-revision", "").strip()
    try:
        version = int(raw_version)
    except ValueError:
        version = None
    try:
        context_revision = int(raw_revision)
    except ValueError:
        context_revision = None
    capabilities = [
        item.strip()
        for item in request.headers.get("x-storyboarder-capabilities", "").split(",")
        if item.strip()
    ]
    return {
        "version": version,
        "capabilities": capabilities,
        "project_session_id": request.headers.get(
            "x-storyboarder-project-session",
            "",
        ).strip(),
        "context_revision": context_revision,
        "work_key": request.headers.get("x-storyboarder-work-key", "").strip(),
        "asset_role": request.headers.get("x-storyboarder-asset-role", "").strip(),
        "write_intent": request.headers.get(
            "x-storyboarder-write-intent",
            "",
        ).strip(),
    }


async def _read_upload(file: UploadFile, fallback_name: str) -> tuple[str, bytes]:
    chunks: list[bytes] = []
    total = 0
    try:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > _MAX_UPLOAD_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail=f"Upload exceeds the {_MAX_UPLOAD_BYTES // (1024 * 1024)} MiB limit.",
                )
            chunks.append(chunk)
    finally:
        await file.close()
    return file.filename or fallback_name, b"".join(chunks)


def create_app(base_dir: Path, bridge_port: int = 8000) -> FastAPI:
    setup_logging()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        stop_event = threading.Event()

        def bridge_refresh_loop() -> None:
            from . import app_state

            while not stop_event.wait(_BRIDGE_REFRESH_SECONDS):
                try:
                    with app_state.project_background_writer(
                        app,
                        "live_bridge",
                    ) as allowed:
                        if allowed:
                            app_state._touch_live_bridge(app)
                except Exception:
                    # Keep the loop alive; bridge file writes are best-effort, but a
                    # persistent failure should be visible in the log, not silent.
                    logger.debug("Live bridge refresh failed", exc_info=True)

        def generation_result_loop() -> None:
            # Codex deposits an immutable result manifest through the MCP server.
            # Watching that durable marker makes the handoff effectively push-based
            # while still recovering results submitted during an app crash/restart.
            observed_revisions: dict[str, int] = {}
            while not stop_event.wait(_GENERATION_SIGNAL_SECONDS):
                project = app.state.project
                if project is None:
                    continue
                project_key = str(project.project_root.resolve())
                revision = generation_service.result_inbox_revision(project)
                previous = observed_revisions.get(project_key)
                if previous is not None and revision <= previous:
                    continue
                if revision <= 0:
                    observed_revisions[project_key] = revision
                    continue
                try:
                    with app_state.project_background_writer(
                        app,
                        "generation_results",
                    ) as allowed:
                        if not allowed:
                            continue
                        with project_manager.PROJECT_LOCK:
                            # Do not let a result from a project just closed or replaced
                            # get applied to whichever project became active meanwhile.
                            if app.state.project is not project:
                                continue
                            result = _svc().method_pull_generation_results()
                    if result["updated_shot_ids"] or result["accepted_request_ids"]:
                        runtime_state.mark_generation_results_changed(app)
                        app_state._touch_live_bridge(app)
                    observed_revisions[project_key] = revision
                except Exception:
                    # Keep watching: an interrupted import remains deposited and
                    # will be retried without asking Codex to generate it again.
                    logger.debug("Generation result signal processing failed", exc_info=True)

        refresh_thread = threading.Thread(
            target=bridge_refresh_loop,
            name="storyboard-bridge-refresh",
            daemon=True,
        )
        generation_thread = threading.Thread(
            target=generation_result_loop,
            name="storyboard-generation-results",
            daemon=True,
        )
        refresh_thread.start()
        generation_thread.start()
        # Exposed so shutdown can halt these loops *before* the work tree is
        # removed. The bridge loop writes into the project root, so deleting the
        # tree while it runs leaves a directory Windows can never reclaim.
        app.state.background_stop = stop_event
        app.state.background_threads = (refresh_thread, generation_thread)
        try:
            yield
        finally:
            app_state.stop_background_loops(app)
            bpy_viewport.stop_worker(app)
            _shutdown_reference_cleanup(app)
            if not blender_bridge.owns_scene(app):
                project_manager.cleanup_document_working_root(app.state.project)

    app = FastAPI(title="Storyboard Tool", lifespan=lifespan)
    app.state.base_dir = base_dir
    app.state.project = None
    app.state.project_disk_mtime = 0.0
    app.state.dirty = False
    app.state.main_window = None
    app.state.api_token = _read_launch_token()
    runtime_state.init_bridge_state(app, bridge_port)
    bpy_viewport_api.register_bpy_viewport_routes(app)

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
        # Keep the absolute log-file path server-side only; the client (which may be a
        # cross-origin browser page) should not learn local filesystem layout.
        return JSONResponse(
            status_code=500,
            content={
                "detail": "Internal error. See the application log for details.",
                "code": AppErrorCode.INTERNAL_ERROR,
            },
        )

    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=_ALLOWED_ORIGIN_REGEX,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def _guard_requests(request, call_next):
        # 1. Reject oversized bodies up front, before multipart parsing spools them.
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                declared = int(content_length)
            except ValueError:
                declared = -1
            if declared > _MAX_UPLOAD_BYTES:
                return JSONResponse(
                    status_code=413,
                    content={
                        "detail": f"Request body exceeds the {_MAX_UPLOAD_BYTES // (1024 * 1024)} MiB limit.",
                        "code": AppErrorCode.PAYLOAD_TOO_LARGE,
                    },
                )
        # 2. Per-launch token gate for state-changing /api calls (no-op when unset).
        token = getattr(app.state, "api_token", "")
        if (
            token
            and request.method in _UNSAFE_METHODS
            and request.url.path.startswith("/api/")
            and request.url.path not in _TOKEN_EXEMPT_API_PATHS
        ):
            provided = request.headers.get(_API_TOKEN_HEADER, "")
            if not hmac.compare_digest(provided, token):
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Missing or invalid API token.", "code": AppErrorCode.UNAUTHORIZED},
                )
        return await call_next(request)

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
    def index() -> Response:
        return _react_index_response(react_dist, app.state.api_token)

    @app.get("/ref-video")
    def ref_video_redirect() -> RedirectResponse:
        # bridge.py opens a second pywebview window at /ref-video; redirect to the React SPA.
        return RedirectResponse(url="/", status_code=302)

    @app.get("/react")
    def react_index() -> Response:
        return _react_index_response(react_dist, app.state.api_token)

    @app.get("/react/{asset_path:path}")
    def react_asset(asset_path: str) -> Response:
        index_file = react_dist / "index.html"
        resolved = (react_dist / asset_path).resolve()
        dist_root = react_dist.resolve()
        if resolved.is_file() and (resolved == dist_root or dist_root in resolved.parents):
            return FileResponse(resolved)
        if not index_file.is_file():
            raise HTTPException(status_code=404, detail=_REACT_BUILD_HINT)
        return _react_index_response(react_dist, app.state.api_token)

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

    @app.get("/api/app/recents")
    def list_recents() -> dict[str, Any]:
        return _svc().method_list_recents()

    @app.post("/api/app/recents/forget")
    def forget_recent(request: RecentForgetRequest) -> dict[str, Any]:
        return _svc().method_forget_recent(request.path)

    @app.post("/api/app/close-project")
    def close_project() -> dict[str, Any]:
        return _svc().method_close_project()

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

    @app.get("/api/generation/events")
    def generation_events() -> StreamingResponse:
        def event_stream():
            revision = runtime_state.generation_result_revision(app)
            while True:
                next_revision = runtime_state.wait_for_generation_result_change(app, revision, timeout=15.0)
                if next_revision != revision:
                    revision = next_revision
                    yield f"event: generation-result\ndata: {revision}\n\n"
                else:
                    yield ": keep-alive\n\n"

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/api/bridge/plugin-heartbeat")
    def plugin_heartbeat(payload: PluginHeartbeatRequest | None = None) -> dict[str, str]:
        return _svc().method_plugin_heartbeat(payload.model_dump() if payload is not None else {})

    @app.get("/api/plugin/context")
    def plugin_context(request: Request) -> dict[str, Any]:
        return _svc().method_plugin_context(_plugin_protocol_headers(request))

    @app.post("/api/plugin/write-intents")
    def plugin_write_intent(
        request: PluginWriteIntentRequest,
        http_request: Request,
    ) -> dict[str, Any]:
        return _svc().method_plugin_write_intent(
            request.work_key,
            request.asset_role,
            _plugin_protocol_headers(http_request),
        )

    @app.post("/api/plugin/heartbeat")
    def plugin_api_heartbeat(payload: PluginHeartbeatRequest | None = None) -> dict[str, str]:
        return _svc().method_plugin_heartbeat(payload.model_dump() if payload is not None else {})

    @app.post("/api/plugin/shots/{shot_id}/export-preview")
    def plugin_export_preview(
        shot_id: str,
        http_request: Request,
        request: PluginShotEventRequest | None = None,
    ) -> dict[str, Any]:
        return _svc().method_plugin_export_preview(
            shot_id,
            request.model_dump() if request is not None else {},
            _plugin_protocol_headers(http_request),
        )

    @app.post("/api/plugin/shots/{shot_id}/psd-saved")
    def plugin_psd_saved(
        shot_id: str,
        http_request: Request,
        request: PluginShotEventRequest | None = None,
    ) -> dict[str, Any]:
        return _svc().method_plugin_psd_saved(
            shot_id,
            request.model_dump() if request is not None else {},
            _plugin_protocol_headers(http_request),
        )

    @app.post("/api/plugin/shots/{shot_id}/focus")
    def plugin_focus_shot(shot_id: str, request: Request) -> dict[str, Any]:
        return _svc().method_plugin_focus_shot(
            shot_id,
            _plugin_protocol_headers(request),
        )

    @app.post("/api/plugin/shots/next")
    def plugin_next_shot(
        request: PluginNextShotRequest,
        http_request: Request,
    ) -> dict[str, Any]:
        return _svc().method_plugin_next_shot(
            request.current_shot_id,
            request.auto_add,
            _plugin_protocol_headers(http_request),
        )

    @app.post("/api/plugin/scenes2d/{scene_id}/perspectives/{perspective_id}/export-preview")
    def plugin_scene2d_export_preview(
        scene_id: str,
        perspective_id: str,
        request: Request,
    ) -> dict[str, Any]:
        return _svc().method_plugin_scene2d_export_preview(
            scene_id,
            perspective_id,
            _plugin_protocol_headers(request),
        )

    @app.post("/api/plugin/scenes2d/{scene_id}/perspectives/{perspective_id}/psd-saved")
    def plugin_scene2d_psd_saved(
        scene_id: str,
        perspective_id: str,
        request: Request,
    ) -> dict[str, Any]:
        return _svc().method_plugin_scene2d_psd_saved(
            scene_id,
            perspective_id,
            _plugin_protocol_headers(request),
        )

    @app.post("/api/plugin/scenes2d/{scene_id}/perspectives/{perspective_id}/next-perspective")
    def plugin_scene2d_next_perspective(
        scene_id: str,
        perspective_id: str,
        request: Request,
    ) -> dict[str, Any]:
        return _svc().method_plugin_scene2d_next_perspective(
            scene_id,
            perspective_id,
            _plugin_protocol_headers(request),
        )

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

    @app.post("/api/project/save-as")
    def save_project_as(request: SaveProjectAsRequest) -> dict[str, Any]:
        return _svc().method_save_project_as(request.path)

    @app.post("/api/project/convert")
    def convert_project(request: SaveProjectAsRequest) -> dict[str, Any]:
        return _svc().method_convert_project(request.path)

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

    @app.post("/api/system/browse-project-save")
    def browse_project_save_dialog() -> dict[str, Any]:
        return _svc().method_browse_project_save()

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

    @app.post("/api/project/scenes2d/{scene_id}/perspectives/reorder")
    def reorder_scene2d_perspectives(scene_id: str, request: Scene2DPerspectiveReorderRequest) -> dict[str, Any]:
        return _svc().method_reorder_scene2d_perspectives(scene_id, request.perspective_ids)

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

    @app.post("/api/project/scenes2d/{scene_id}/perspectives/{perspective_id}/duplicate")
    def duplicate_scene2d_perspective(scene_id: str, perspective_id: str) -> dict[str, Any]:
        return _svc().method_duplicate_scene2d_perspective(scene_id, perspective_id)

    @app.post("/api/project/scenes2d/{scene_id}/perspectives/{perspective_id}/move-to-scene")
    def move_scene2d_perspective(scene_id: str, perspective_id: str, request: Scene2DPerspectiveMoveRequest) -> dict[str, Any]:
        return _svc().method_move_scene2d_perspective(
            scene_id,
            perspective_id,
            request.target_scene_id,
        )

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

    @app.patch("/api/shots/batch")
    def update_shots_batch(request: ShotBatchUpdateRequest) -> dict[str, Any]:
        return _svc().method_update_shots_batch(
            [item.model_dump() for item in request.updates]
        )

    @app.delete("/api/shots/batch")
    def delete_shots_batch(request: ShotBatchDeleteRequest) -> dict[str, Any]:
        return _svc().method_delete_shots_batch(request.shot_ids)

    @app.post("/api/shots/batch/restore")
    def restore_shots_batch(request: ShotBatchRestoreRequest) -> dict[str, Any]:
        return _svc().method_restore_shots_batch(
            [item.model_dump() for item in request.items]
        )

    @app.post("/api/shots/batch/generation-requests")
    def create_queue_batch_requests(request: GenerationBatchQueueRequest) -> dict[str, Any]:
        return _svc().method_create_queue_batch_requests(request.shot_ids)

    @app.post("/api/shots/{shot_id}/duplicate")
    def duplicate_shot(shot_id: str) -> dict[str, Any]:
        return _svc().method_duplicate_shot(shot_id)

    @app.patch("/api/shots/{shot_id}")
    def update_shot(shot_id: str, request: ShotUpdateRequest) -> dict[str, Any]:
        return _svc().method_update_shot(shot_id, request.model_dump())

    @app.post("/api/shots/{shot_id}/generation-requests")
    def create_generation_request(shot_id: str, request: GenerationRequestCreateRequest) -> dict[str, Any]:
        return _svc().method_create_generation_request(
            shot_id,
            request.destination,
            request.provider,
            request.mode,
            request.clear_queue_on_result,
        )

    @app.post("/api/generation/requests/codex-batch")
    def create_codex_batch_requests(
        request: GenerationBatchDispatchRequest = GenerationBatchDispatchRequest(),
    ) -> dict[str, Any]:
        return _svc().method_create_codex_batch_requests(
            request.provider,
            request.clear_queue_on_result,
            request.scope,
        )

    @app.get("/api/generation/requests")
    def list_generation_requests(
        shot_id: str = "",
        destination: str = "",
        status: str = "",
    ) -> dict[str, Any]:
        return _svc().method_list_generation_requests(
            shot_id=shot_id,
            destination=destination,
            status=status,
        )

    @app.delete("/api/generation/requests/{request_id}")
    def delete_generation_request(request_id: str) -> dict[str, Any]:
        return _svc().method_delete_generation_request(request_id)

    @app.post("/api/generation/pull")
    def pull_generation_results() -> dict[str, Any]:
        return _svc().method_pull_generation_results()

    @app.post("/api/generation/reconcile")
    def reconcile_generation_results() -> dict[str, Any]:
        return _svc().method_reconcile_generation_results()

    @app.post("/api/shots/{shot_id}/codex-layer/accept")
    def accept_generation_candidate(shot_id: str, request: GenerationCandidateAcceptRequest) -> dict[str, Any]:
        return _svc().method_accept_generation_candidate(
            shot_id,
            request.request_id,
            request.result_id,
            request.artifact_path,
        )

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

    @app.delete("/api/shots/{shot_id}/layers/{layer_id}")
    def remove_fixed_layer(shot_id: str, layer_id: str) -> dict[str, Any]:
        return _svc().method_remove_fixed_layer(shot_id, layer_id)

    @app.get("/api/shots/{shot_id}/image")
    def get_image(shot_id: str) -> FileResponse:
        return _file_response_from_meta(_svc().method_get_shot_image(shot_id))

    @app.get("/api/shots/{shot_id}/thumbnail")
    def get_thumbnail(shot_id: str) -> FileResponse:
        return _file_response_from_meta(_svc().method_get_shot_thumbnail(shot_id))

    @app.get("/api/shots/{shot_id}/board-background")
    def get_board_background(shot_id: str) -> FileResponse:
        return _file_response_from_meta(_svc().method_get_shot_board_background(shot_id))

    @app.get("/api/shots/{shot_id}/codex-layer")
    def get_codex_layer(shot_id: str) -> FileResponse:
        return _file_response_from_meta(_svc().method_get_shot_codex_layer(shot_id))

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
        return _svc().method_export_pdf(request.layout, boards=request.boards)

    @app.post("/api/export/shot-list")
    def export_shot_list(request: ExportScopeRequest = ExportScopeRequest()) -> dict[str, str]:
        return _svc().method_export_shot_list(boards=request.boards)

    @app.get("/api/export/shot-list")
    def download_shot_list() -> FileResponse:
        return _file_response_from_meta(_svc().method_download_shot_list())

    @app.post("/api/export/timing")
    def export_timing(request: ExportScopeRequest = ExportScopeRequest()) -> dict[str, str]:
        return _svc().method_export_timing(boards=request.boards)

    @app.get("/api/export/timing")
    def download_timing() -> FileResponse:
        return _file_response_from_meta(_svc().method_download_timing())

    @app.post("/api/export/contact-sheet")
    def export_contact(request: ExportScopeRequest = ExportScopeRequest()) -> dict[str, str]:
        return _svc().method_export_contact_sheet(boards=request.boards)

    @app.get("/api/export/contact-sheet")
    def download_contact() -> FileResponse:
        return _file_response_from_meta(_svc().method_download_contact_sheet())

    @app.post("/api/export/image-sequence")
    def export_sequence(request: ExportScopeRequest = ExportScopeRequest()) -> dict[str, str]:
        return _svc().method_export_image_sequence(boards=request.boards)

    @app.get("/api/export/pdf")
    def download_pdf() -> FileResponse:
        return _file_response_from_meta(_svc().method_download_pdf())

    @app.post("/api/export/animatic")
    def export_animatic(request: AnimaticExportRequest = AnimaticExportRequest()) -> dict[str, str]:
        return _svc().method_export_animatic(
            fps=request.fps,
            seconds_per_board=request.seconds_per_board,
            captions=request.captions,
        )

    @app.get("/api/export/animatic")
    def download_animatic() -> FileResponse:
        return _file_response_from_meta(_svc().method_download_animatic())

    @app.post("/api/export/resolve-range")
    def resolve_board_range(request: ExportScopeRequest = ExportScopeRequest()) -> dict[str, Any]:
        return _svc().method_resolve_board_range(request.boards)

    @app.post("/api/export/open")
    def open_export(request: ExportOpenRequest) -> dict[str, str]:
        return _svc().method_open_export(request.type, boards=request.boards)

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
