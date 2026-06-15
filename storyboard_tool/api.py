from __future__ import annotations

import json
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import live_bridge, project_manager, session_store
from .models import Project, SHOT_STATUSES, Shot
from .backend_service import ApiCallRequest, StoryboardBackendService, dispatch_api_call


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


class ApplyRefSegmentRequest(BaseModel):
    anchor_shot_id: str
    end_shot_id: str
    segment_id: str | None = None
    camera_name: str | None = None


class LiveBridgeUpdateRequest(BaseModel):
    selected_shot_id: str | None = None


class AddShotRequest(BaseModel):
    after_shot_id: str | None = None


def create_app(base_dir: Path, bridge_port: int = 8000) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        _shutdown_reference_cleanup(app)

    app = FastAPI(title="Storyboard Tool", lifespan=lifespan)
    app.state.base_dir = base_dir
    app.state.project = None
    app.state.project_disk_mtime = 0.0
    app.state.dirty = False
    app.state.live_selected_shot_id = ""
    app.state.bridge_port = bridge_port
    app.state.plugin_last_seen = 0.0

    def _svc() -> StoryboardBackendService:
        return StoryboardBackendService(app)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    web_dir = Path(__file__).parent / "web"
    app.mount("/static", StaticFiles(directory=web_dir / "static"), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(web_dir / "index.html")

    @app.get("/ref-segment")
    def ref_segment_window() -> FileResponse:
        return FileResponse(web_dir / "ref_segment.html")

    @app.get("/ref-scene3d")
    def ref_scene3d_window() -> FileResponse:
        return FileResponse(web_dir / "ref_segment.html")

    @app.get("/ref-video")
    def ref_video_window() -> FileResponse:
        return FileResponse(web_dir / "ref_segment.html")

    @app.get("/api/project")
    def get_project() -> dict[str, Any]:
        return _svc().method_get_project()

    @app.post("/api")
    def api_dispatch(request: ApiCallRequest) -> dict[str, Any]:
        return dispatch_api_call(app, request.method, request.args)

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
    def plugin_heartbeat() -> dict[str, str]:
        app.state.plugin_last_seen = time.time()
        return {"ok": "true"}

    @app.get("/api/project/missing-files")
    def missing_project_files() -> dict[str, Any]:
        return _svc().method_get_missing_files()

    @app.post("/api/project/new")
    def new_project(request: ProjectPathRequest) -> dict[str, Any]:
        return _svc().method_new_project(
            request.path,
            request.canvas_width,
            request.canvas_height,
        )

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
        return _svc().method_apply_ref_segment_3d(
            request.anchor_shot_id,
            request.end_shot_id,
            request.segment_id or "",
            str(request.camera_name or ""),
        )

    @app.post("/api/project/ref-segment/apply-image")
    def apply_ref_segment_image(request: ApplyRefSegmentRequest) -> dict[str, Any]:
        return _svc().method_apply_ref_segment_image(
            request.anchor_shot_id,
            request.end_shot_id,
            request.segment_id or "",
        )

    @app.post("/api/project/ref-segment/apply")
    def apply_ref_segment(request: ApplyRefSegmentRequest) -> dict[str, Any]:
        return _svc().method_apply_ref_segment(
            request.anchor_shot_id,
            request.end_shot_id,
            request.segment_id or "",
        )

    @app.delete("/api/project/ref-segments/{segment_id}")
    def delete_ref_segment(segment_id: str) -> dict[str, Any]:
        return _svc().method_delete_ref_segment(segment_id)

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
        project = _require_project(app)
        try:
            path = project_manager.get_scene3d_file_path(project)
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if path is None:
            raise HTTPException(status_code=404, detail="No Blender scene imported.")
        media_type = "model/gltf-binary" if path.suffix.lower() == ".glb" else "model/gltf+json"
        return FileResponse(path, media_type=media_type, filename=path.name)

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
        return _svc().method_create_shot_canvas(
            shot_id,
            request.width,
            request.height,
            request.background_color,
        )

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

    @app.post("/api/shots/{shot_id}/open-preview")
    def open_preview(shot_id: str) -> dict[str, str]:
        return _svc().method_open_preview(shot_id)

    @app.delete("/api/shots/{shot_id}/image")
    def remove_image(shot_id: str) -> dict[str, Any]:
        return _svc().method_remove_shot_image(shot_id)

    @app.get("/api/shots/{shot_id}/image")
    def get_image(shot_id: str) -> FileResponse:
        project = _require_project(app)
        shot = _find_shot(project, shot_id)
        image_rel_path = shot.preview_image_path or shot.image_path
        if not image_rel_path:
            raise HTTPException(status_code=404, detail="No image for this shot.")
        image_path = project.root_path / image_rel_path
        if not image_path.exists():
            raise HTTPException(status_code=404, detail="Image file is missing.")
        return FileResponse(image_path)

    @app.get("/api/shots/{shot_id}/thumbnail")
    def get_thumbnail(shot_id: str) -> FileResponse:
        project = _require_project(app)
        shot = _find_shot(project, shot_id)
        image_rel_path = shot.thumbnail_path or shot.preview_image_path or shot.image_path
        if not image_rel_path:
            raise HTTPException(status_code=404, detail="No thumbnail for this shot.")
        image_path = project.root_path / image_rel_path
        if not image_path.exists():
            raise HTTPException(status_code=404, detail="Thumbnail file is missing.")
        return FileResponse(image_path)

    @app.get("/api/shots/{shot_id}/board-background")
    def get_board_background(shot_id: str) -> FileResponse:
        project = _require_project(app)
        shot = _find_shot(project, shot_id)
        background_path = project_manager.get_shot_board_background_path(project, shot)
        if background_path is None or not background_path.is_file():
            raise HTTPException(status_code=404, detail="No board background for this shot.")
        return FileResponse(background_path)

    @app.get("/api/files")
    def get_project_file(path: str) -> FileResponse:
        project = _require_project(app)
        file_path = (project.root_path / path).resolve()
        root = project.root_path.resolve()
        if root not in file_path.parents and file_path != root:
            raise HTTPException(status_code=400, detail="File path is outside the project.")
        if not file_path.exists() or not file_path.is_file():
            raise HTTPException(status_code=404, detail="File is missing.")
        return FileResponse(file_path)

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
        project = _require_project(app)
        output_path = project.exports_dir / "shot_list.csv"
        if not output_path.exists():
            raise HTTPException(status_code=404, detail="Export the shot list first.")
        return FileResponse(output_path, filename="shot_list.csv", media_type="text/csv")

    @app.post("/api/export/timing")
    def export_timing() -> dict[str, str]:
        return _svc().method_export_timing()

    @app.get("/api/export/timing")
    def download_timing() -> FileResponse:
        project = _require_project(app)
        output_path = project.exports_dir / "timing.json"
        if not output_path.exists():
            raise HTTPException(status_code=404, detail="Export timing data first.")
        return FileResponse(output_path, filename="timing.json", media_type="application/json")

    @app.post("/api/export/contact-sheet")
    def export_contact() -> dict[str, str]:
        return _svc().method_export_contact_sheet()

    @app.get("/api/export/contact-sheet")
    def download_contact() -> FileResponse:
        project = _require_project(app)
        output_path = project.exports_dir / "contact_sheet.png"
        if not output_path.exists():
            raise HTTPException(status_code=404, detail="Export the contact sheet first.")
        return FileResponse(output_path, filename="contact_sheet.png", media_type="image/png")

    @app.post("/api/export/image-sequence")
    def export_sequence() -> dict[str, str]:
        return _svc().method_export_image_sequence()

    @app.get("/api/export/pdf")
    def download_pdf() -> FileResponse:
        project = _require_project(app)
        output_path = project.exports_dir / "storyboard.pdf"
        if not output_path.exists():
            raise HTTPException(status_code=404, detail="Export the PDF first.")
        return FileResponse(output_path, filename="storyboard.pdf", media_type="application/pdf")

    return app


def _project_payload(project: Project, dirty: bool) -> dict[str, Any]:
    return {
        "project_path": str(project.root_path),
        "project_json_path": str(project.json_path),
        "name": project.name,
        "dirty": dirty,
        "settings": project.settings,
        "statuses": list(SHOT_STATUSES),
        "shots": [shot.to_dict() for shot in project.shots],
    }


def _export_storyboard_pdf(project: Project, output_path: Path, *, layout: str) -> None:
    from .pdf_exporter import export_storyboard_pdf

    export_storyboard_pdf(project, output_path, layout=layout)


def _require_project(app: FastAPI) -> Project:
    project = app.state.project
    if project is None:
        raise HTTPException(status_code=400, detail="No project opened.")
    return project


def _find_shot(project: Project, shot_id: str) -> Shot:
    return project.shots[_find_shot_index(project, shot_id)]


def _find_shot_index(project: Project, shot_id: str) -> int:
    for index, shot in enumerate(project.shots):
        if shot.shot_id == shot_id:
            return index
    raise HTTPException(status_code=404, detail=f"Shot not found: {shot_id}")


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


def _shutdown_reference_cleanup(app: FastAPI) -> None:
    try:
        project_manager.shutdown_reference_cleanup(
            app.state.project,
            save_if_dirty=bool(getattr(app.state, "dirty", False)),
            dirty=bool(getattr(app.state, "dirty", False)),
        )
    except Exception as exc:
        print(f"Reference cleanup failed: {exc}", file=sys.stderr)


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
    )


def _bridge_status_payload(app: FastAPI) -> dict[str, Any]:
    live = _touch_live_bridge(app)
    project = app.state.project
    http_seen = float(getattr(app.state, "plugin_last_seen", 0.0) or 0.0)
    file_seen = live_bridge.read_plugin_heartbeat_mtime()
    last_seen = max(http_seen, file_seen)
    age = round(time.time() - last_seen, 1) if last_seen else None
    plugin_linked = age is not None and age <= 12.0
    return {
        "app_running": True,
        "project_open": project is not None,
        "plugin_linked": plugin_linked,
        "plugin_last_seen_seconds_ago": age,
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
