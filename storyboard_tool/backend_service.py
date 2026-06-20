from __future__ import annotations

import io
import json
import logging
from pathlib import Path
from typing import Any, BinaryIO

from fastapi import FastAPI, HTTPException

from . import app_state, project_manager, project_transaction, reference_segments, runtime_state, session_store, shot_service
from .errors import AppErrorCode, app_error
from .export_utils import missing_files
from .image_utils import normalize_hex_color
from .linked_sync import sync_project
from .plugin_service import PluginBridgeService
from .service_exports import ExportServiceMixin
from .system_utils import (
    browse_blender_executable,
    browse_folder,
    browse_photoshop_executable,
    browse_project_json,
    detect_blender_paths,
    detect_photoshop_paths,
    validate_blender_path,
    validate_folder_path,
    validate_photoshop_path,
    validate_project_json_path,
)

logger = logging.getLogger(__name__)


def _normalize_upload_bytes(data: list[int] | bytes | bytearray) -> bytes:
    if isinstance(data, (bytes, bytearray)):
        return bytes(data)
    if isinstance(data, list):
        return bytes(int(value) & 0xFF for value in data)
    raise HTTPException(status_code=400, detail="Upload payload must be bytes.")


def _upload_stream(data: list[int] | bytes | bytearray) -> BinaryIO:
    return io.BytesIO(_normalize_upload_bytes(data))


class StoryboardBackendService(ExportServiceMixin):
    """Business logic shared by every REST route and the desktop bridge."""

    def __init__(self, app: FastAPI) -> None:
        self.app = app

    def call(self, method: str, args: list[Any] | None = None) -> Any:
        handler = getattr(self, f"method_{method}", None)
        if handler is None:
            raise ValueError(f"Unknown API method: {method}")
        raw_args = args if isinstance(args, list) else []
        return handler(*raw_args)

    def method_ping(self) -> str:
        return "python-backend-ready"

    def method_get_project(self) -> dict[str, Any]:
        project = app_state._refresh_project_from_disk(self.app)
        return app_state._project_payload(project, self.app.state.dirty)

    def method_get_session(self) -> dict[str, Any]:
        return session_store.read_session(self.app.state.base_dir)

    def method_update_session(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        data = payload if isinstance(payload, dict) else {}
        return session_store.update_session(
            self.app.state.base_dir,
            last_project_json_path=data.get("last_project_json_path"),
            selected_shot_id=data.get("selected_shot_id"),
            recent_projects=data.get("recent_projects"),
            timeline_scroll_left=data.get("timeline_scroll_left"),
            status_filter=data.get("status_filter"),
            revision_only=data.get("revision_only"),
            advanced_panel_open=data.get("advanced_panel_open"),
            ui_theme=data.get("ui_theme"),
        )

    def method_new_project(
        self,
        path: str | None = None,
        canvas_width: int | None = None,
        canvas_height: int | None = None,
    ) -> dict[str, Any]:
        root = Path(path).expanduser() if path else self.app.state.base_dir / "Storyboard_Project"
        try:
            app_state._track_project(
                self.app,
                project_manager.create_project(
                    root,
                    canvas_width=canvas_width if canvas_width is not None else 1920,
                    canvas_height=canvas_height if canvas_height is not None else 1080,
                ),
            )
        except (FileNotFoundError, ValueError) as exc:
            logger.exception("Failed to create project: %s", root)
            raise app_error(AppErrorCode.PROJECT_OPEN_FAILED, str(exc)) from exc
        app_state._remember_recent(self.app.state.project)
        app_state._persist_app_session(self.app)
        app_state._touch_live_bridge(self.app)
        self.app.state.dirty = False
        return app_state._project_payload(self.app.state.project, self.app.state.dirty)

    def method_open_project(self, project_json_path: str) -> dict[str, Any]:
        try:
            app_state._track_project(
                self.app,
                project_manager.open_project(Path(project_json_path).expanduser()),
            )
        except (FileNotFoundError, ValueError) as exc:
            logger.exception("Failed to open project: %s", project_json_path)
            raise app_error(AppErrorCode.PROJECT_OPEN_FAILED, str(exc)) from exc
        app_state._remember_recent(self.app.state.project)
        app_state._persist_app_session(self.app)
        app_state._touch_live_bridge(self.app)
        self.app.state.dirty = False
        return app_state._project_payload(self.app.state.project, self.app.state.dirty)

    def method_save_project(self) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        try:
            project_manager.save_project(project)
        except Exception as exc:
            logger.exception("Failed to save project")
            raise app_error(AppErrorCode.PROJECT_SAVE_FAILED, str(exc), status=500) from exc
        self.app.state.dirty = False
        return app_state._project_payload(project, self.app.state.dirty)

    def method_get_missing_files(self) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        return {"missing_files": missing_files(project)}

    def method_bridge_status(self) -> dict[str, Any]:
        return app_state._bridge_status_payload(self.app)

    def method_bridge_relink(self) -> dict[str, Any]:
        app_state._require_project(self.app)
        app_state._touch_live_bridge(self.app, selected_shot_id=runtime_state.live_selected_shot_id(self.app))
        return app_state._bridge_status_payload(self.app)

    def method_touch_live_bridge(self, selected_shot_id: str | None = None) -> dict[str, Any]:
        return app_state._touch_live_bridge(self.app, selected_shot_id=selected_shot_id)

    def _plugin_service(self) -> PluginBridgeService:
        return PluginBridgeService(self.app)

    def _mark_plugin_project_changed(self) -> None:
        self._plugin_service().mark_project_changed()

    def method_plugin_heartbeat(self, payload: dict[str, Any] | None = None) -> dict[str, str]:
        return self._plugin_service().heartbeat(payload)

    def method_plugin_context(self) -> dict[str, Any]:
        return self._plugin_service().context()

    def _plugin_context_payload(self, project) -> dict[str, Any]:
        return self._plugin_service().context_payload(project)

    def method_plugin_export_preview(self, shot_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._plugin_service().export_preview(shot_id, payload)

    def method_plugin_psd_saved(self, shot_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._plugin_service().psd_saved(shot_id, payload)

    def method_plugin_focus_shot(self, shot_id: str) -> dict[str, Any]:
        return self._plugin_service().focus_shot(shot_id)

    def method_plugin_next_shot(self, current_shot_id: str | None = None, auto_add: bool = False) -> dict[str, Any]:
        return self._plugin_service().next_shot(current_shot_id, auto_add)

    def _plugin_shot_payload(self, project, shot) -> dict[str, Any]:
        return self._plugin_service().shot_payload(project, shot)

    def _plugin_shot_paths(self, project, shot) -> dict[str, str]:
        return self._plugin_service().shot_paths(project, shot)

    def _plugin_shot_psd_path(self, project, shot) -> Path | None:
        return self._plugin_service().shot_psd_path(project, shot)

    def _plugin_shot_health(self, project, shot) -> dict[str, Any]:
        return self._plugin_service().shot_health(project, shot)

    def method_add_shot(self, after_shot_id: str | None = None) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        try:
            shot = shot_service.create_shot(project, after_shot_id or None)
        except ValueError as exc:
            raise app_error(AppErrorCode.SHOT_NOT_FOUND, str(exc), status=404) from exc
        app_state._autosave(self.app)
        return {"shot": shot.to_dict(), **app_state._project_payload(project, self.app.state.dirty)}

    def method_duplicate_shot(self, shot_id: str) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        try:
            duplicate = shot_service.duplicate_shot(project, shot_id)
        except ValueError as exc:
            raise app_error(AppErrorCode.SHOT_NOT_FOUND, str(exc), status=404) from exc
        app_state._autosave(self.app)
        return {"shot": duplicate.to_dict(), **app_state._project_payload(project, self.app.state.dirty)}

    def method_update_shot(self, shot_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        shot = app_state._find_shot(project, shot_id)
        shot_service.update_shot(shot, payload if isinstance(payload, dict) else {})
        app_state._autosave(self.app)
        return app_state._project_payload(project, self.app.state.dirty)

    def method_delete_shot(self, shot_id: str) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        try:
            with project_transaction.mutate_project(project):
                shot_service.delete_shot(project, shot_id)
        except ValueError as exc:
            raise app_error(AppErrorCode.SHOT_NOT_FOUND, str(exc), status=404) from exc
        app_state._autosave(self.app)
        return app_state._project_payload(project, self.app.state.dirty)

    def method_restore_shot(self, shot: dict[str, Any], index: int = 0) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        if not isinstance(shot, dict):
            raise app_error(AppErrorCode.INVALID_REQUEST, "Shot payload required.")
        try:
            with project_transaction.mutate_project(project):
                project_manager.restore_shot(project, shot, int(index))
        except (KeyError, ValueError) as exc:
            raise app_error(AppErrorCode.INVALID_REQUEST, str(exc)) from exc
        app_state._autosave(self.app)
        return app_state._project_payload(project, self.app.state.dirty)

    def method_reorder_shots(self, shot_ids: list[str]) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        if not isinstance(shot_ids, list):
            raise app_error(AppErrorCode.INVALID_REQUEST, "Shot order required.")
        try:
            with project_transaction.mutate_project(project):
                shot_service.reorder_shots(project, shot_ids)
        except ValueError as exc:
            raise app_error(AppErrorCode.INVALID_REQUEST, str(exc)) from exc
        app_state._autosave(self.app)
        return app_state._project_payload(project, self.app.state.dirty)

    def method_import_image_path(self, shot_id: str, source_path: str) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        shot = app_state._find_shot(project, shot_id)
        try:
            project_manager.import_image_for_shot(project, shot, Path(str(source_path)).expanduser())
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        app_state._autosave(self.app)
        return app_state._project_payload(project, self.app.state.dirty)

    def method_apply_ref_segment(self, anchor_shot_id: str, end_shot_id: str, segment_id: str = "") -> dict[str, Any]:
        project = app_state._require_project(self.app)
        anchor = app_state._find_shot_index(project, anchor_shot_id)
        end = app_state._find_shot_index(project, end_shot_id)
        try:
            with project_transaction.mutate_project(project):
                result = project_manager.apply_ref_segment_to_boards(
                    project,
                    anchor,
                    end,
                    segment_id or None,
                )
        except (FileNotFoundError, ValueError) as exc:
            raise app_error(AppErrorCode.REF_APPLY_FAILED, str(exc)) from exc
        app_state._autosave(self.app)
        return {**result, **app_state._project_payload(project, self.app.state.dirty)}

    def method_apply_ref_segment_image(
        self,
        anchor_shot_id: str,
        end_shot_id: str,
        segment_id: str = "",
    ) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        anchor = app_state._find_shot_index(project, anchor_shot_id)
        end = app_state._find_shot_index(project, end_shot_id)
        try:
            with project_transaction.mutate_project(project):
                result = project_manager.apply_ref_segment_image_to_boards(
                    project,
                    anchor,
                    end,
                    segment_id or None,
                )
        except (FileNotFoundError, ValueError) as exc:
            raise app_error(AppErrorCode.REF_APPLY_FAILED, str(exc)) from exc
        app_state._autosave(self.app)
        return {**result, **app_state._project_payload(project, self.app.state.dirty)}

    def method_apply_ref_segment_3d(
        self,
        anchor_shot_id: str,
        end_shot_id: str,
        segment_id: str = "",
        camera_name: str = "",
    ) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        anchor = app_state._find_shot_index(project, anchor_shot_id)
        end = app_state._find_shot_index(project, end_shot_id)
        try:
            with project_transaction.mutate_project(project):
                result = project_manager.apply_ref_segment_3d_to_boards(
                    project,
                    anchor,
                    end,
                    segment_id or None,
                    camera_name=str(camera_name or ""),
                )
        except (FileNotFoundError, ValueError) as exc:
            raise app_error(AppErrorCode.REF_APPLY_FAILED, str(exc)) from exc
        app_state._autosave(self.app)
        return {**result, **app_state._project_payload(project, self.app.state.dirty)}

    def method_apply_ref_segment_model_captures(
        self,
        anchor_shot_id: str,
        end_shot_id: str,
        segment_id: str,
        camera_name: str,
        captures: list[dict[str, Any]],
    ) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        try:
            with project_transaction.mutate_project(project):
                result = reference_segments.apply_model_captures_to_boards(
                    project,
                    anchor_shot_id,
                    end_shot_id,
                    segment_id,
                    camera_name,
                    captures,
                )
        except (KeyError, FileNotFoundError, ValueError) as exc:
            raise app_error(AppErrorCode.REF_APPLY_FAILED, str(exc)) from exc
        app_state._autosave(self.app)
        return {**result, **app_state._project_payload(project, self.app.state.dirty)}

    def method_snapshot_ref_boards(self, anchor_shot_id: str, end_shot_id: str) -> dict[str, Any]:
        # Manual snapshot of a board range before a destructive bake. Returns an undo token usable
        # with method_restore_ref_apply / restore_boards_from_undo. Browser 3D apply snapshots
        # inside apply_model_captures_to_boards before writing board images.
        project = app_state._require_project(self.app)
        anchor = app_state._find_shot_index(project, anchor_shot_id)
        end = app_state._find_shot_index(project, end_shot_id)
        lo, hi = (anchor, end) if anchor <= end else (end, anchor)
        try:
            token = project_manager.snapshot_boards_for_undo(project, lo, hi)
        except (FileNotFoundError, ValueError) as exc:
            raise app_error(AppErrorCode.REF_APPLY_FAILED, str(exc)) from exc
        return {"undo_token": token}

    def method_restore_ref_apply(self, token: str) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        try:
            with project_transaction.mutate_project(project):
                result = project_manager.restore_boards_from_undo(project, token)
        except (FileNotFoundError, ValueError) as exc:
            raise app_error(AppErrorCode.REF_APPLY_FAILED, str(exc)) from exc
        app_state._autosave(self.app)
        return {**result, **app_state._project_payload(project, self.app.state.dirty)}

    def method_delete_ref_segment(self, segment_id: str) -> dict[str, Any]:
        project = app_state._refresh_project_from_disk(self.app)
        try:
            with project_transaction.mutate_project(project):
                result = project_manager.delete_ref_segment(project, segment_id)
        except (KeyError, FileNotFoundError, ValueError) as exc:
            raise app_error(AppErrorCode.REF_APPLY_FAILED, str(exc)) from exc
        app_state._autosave(self.app)
        return {**result, **app_state._project_payload(project, self.app.state.dirty)}

    def method_move_shot_up(self, shot_id: str) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        project_manager.move_shot_up(project, app_state._find_shot_index(project, shot_id))
        app_state._autosave(self.app)
        return app_state._project_payload(project, self.app.state.dirty)

    def method_move_shot_down(self, shot_id: str) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        project_manager.move_shot_down(project, app_state._find_shot_index(project, shot_id))
        app_state._autosave(self.app)
        return app_state._project_payload(project, self.app.state.dirty)

    def method_sync_shot(self, shot_id: str, force: bool = False) -> dict[str, Any]:
        project = app_state._refresh_project_from_disk(self.app)
        shot = app_state._find_shot(project, shot_id)
        if project_manager.relink_shot_preview_from_disk(project, shot):
            app_state._autosave(self.app)
        try:
            result = project_manager.sync_shot(project, shot, force=bool(force))
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if result.get("synced"):
            app_state._autosave(self.app)
        return {"result": result, **app_state._project_payload(project, self.app.state.dirty)}

    def method_get_annotations(self, shot_id: str) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        shot = app_state._find_shot(project, shot_id)
        path = app_state._annotation_path(project, shot)
        try:
            annotations = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid annotation JSON: {exc}") from exc
        if not isinstance(annotations, list):
            raise HTTPException(status_code=400, detail="Annotation file must contain a list.")
        return {"annotations": annotations}

    def method_save_annotations(self, shot_id: str, annotations: list[Any]) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        shot = app_state._find_shot(project, shot_id)
        path = app_state._annotation_path(project, shot)
        payload = annotations if isinstance(annotations, list) else []
        project_manager._atomic_write_text(path, json.dumps(payload, indent=2))
        return {"annotations": payload}

    def method_add_comment(self, shot_id: str, text: str) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        shot = app_state._find_shot(project, shot_id)
        cleaned = str(text or "").strip()
        if not cleaned:
            raise HTTPException(status_code=400, detail="Comment cannot be empty.")
        next_id = max([int(comment.get("id", 0)) for comment in shot.comments] or [0]) + 1
        shot.comments.append({"id": next_id, "text": cleaned, "resolved": False})
        app_state._autosave(self.app)
        return app_state._project_payload(project, self.app.state.dirty)

    def method_resolve_comment(self, shot_id: str, comment_id: int, resolved: bool = True) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        shot = app_state._find_shot(project, shot_id)
        for comment in shot.comments:
            if int(comment.get("id", 0)) == int(comment_id):
                comment["resolved"] = bool(resolved)
                app_state._autosave(self.app)
                return app_state._project_payload(project, self.app.state.dirty)
        raise HTTPException(status_code=404, detail="Comment not found.")

    def method_update_settings(self, payload: dict[str, Any]) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        data = payload if isinstance(payload, dict) else {}
        if "photoshop_path" in data:
            value = str(data.get("photoshop_path") or "").strip()
            if value:
                try:
                    value = validate_photoshop_path(value)
                except (FileNotFoundError, ValueError) as exc:
                    raise HTTPException(status_code=400, detail=str(exc)) from exc
            project.settings["photoshop_path"] = value
        if "blender_path" in data:
            value = str(data.get("blender_path") or "").strip()
            if value:
                try:
                    value = validate_blender_path(value)
                except (FileNotFoundError, ValueError) as exc:
                    raise HTTPException(status_code=400, detail=str(exc)) from exc
            project.settings["blender_path"] = value
        if "reference_video_path" in data:
            value = str(data.get("reference_video_path") or "").strip()
            if value:
                project_manager.set_active_reference_video(project, value)
            else:
                project_manager.clear_active_reference_video(project)
        if "reference_model_path" in data:
            value = str(data.get("reference_model_path") or "").strip()
            if value:
                project_manager.set_active_reference_model(project, value)
            else:
                project_manager.clear_active_reference_model(project)
        if "reference_image_path" in data:
            value = str(data.get("reference_image_path") or "").strip()
            if value:
                project_manager.set_active_reference_image(project, value)
            else:
                project_manager.clear_active_reference_image(project)
        if "reference_segment_mode" in data:
            mode = str(data.get("reference_segment_mode") or "").strip().lower()
            if mode in {"video", "model", "image"}:
                project.settings["reference_segment_mode"] = mode
        if "reference_links" in data:
            project.settings["reference_links"] = project_manager.normalize_reference_links(data.get("reference_links"))
        if "ref_segment" in data:
            segment = data.get("ref_segment")
            project.settings["ref_segment"] = segment if isinstance(segment, dict) else {}
        if "ref_segments" in data:
            segments = data.get("ref_segments")
            project.settings["ref_segments"] = segments if isinstance(segments, list) else []
            project_manager.sync_ref_segment_settings(project)
        if "active_ref_segment_id" in data:
            project.settings["active_ref_segment_id"] = str(data.get("active_ref_segment_id") or "").strip()
            project_manager.sync_ref_segment_settings(project)
        if "ref_segment_video" in data:
            segment = data.get("ref_segment_video")
            project.settings["ref_segment_video"] = segment if isinstance(segment, dict) else {}
            seg_id = str(segment.get("segment_id", "") or project.settings.get("active_ref_segment_id", "") or "").strip()
            if seg_id and isinstance(segment, dict) and "start" in segment:
                project_manager.update_ref_segment_video_start(
                    project,
                    seg_id,
                    float(segment.get("start", 0.0) or 0.0),
                )
        if "canvas_width" in data and "canvas_height" in data:
            project_manager.persist_canvas_size(
                project,
                data.get("canvas_width"),
                data.get("canvas_height"),
                apply_to_blank_shots=bool(data.get("apply_canvas_size_to_blank_shots")),
            )
            self.app.state.dirty = True
        if "canvas_background_color" in data:
            color = normalize_hex_color(str(data["canvas_background_color"]))
            project.settings["canvas_background_color"] = color
            project_manager.write_canvas_color_files(project, color)
        if "scene3d" in data:
            project.settings["scene3d"] = data["scene3d"]
        project_manager.save_settings(project)
        project_manager.write_bridge_file(project)
        app_state._touch_live_bridge(self.app)
        return app_state._project_payload(project, self.app.state.dirty)

    def method_browse_folder(self) -> dict[str, Any]:
        return self._browse("folder", browse_folder, validate_folder_path)

    def method_browse_project_json(self) -> dict[str, Any]:
        return self._browse("project-json", browse_project_json, validate_project_json_path)

    def method_browse_photoshop(self) -> dict[str, str]:
        return self._browse("photoshop", browse_photoshop_executable, validate_photoshop_path)

    def method_browse_blender(self) -> dict[str, str]:
        return self._browse("blender", browse_blender_executable, validate_blender_path)

    def method_photoshop_candidates(self) -> dict[str, Any]:
        project = self.app.state.project
        current = str(project.settings.get("photoshop_path", "") or "") if project else ""
        return {"candidates": detect_photoshop_paths(), "current": current}

    def method_blender_candidates(self) -> dict[str, Any]:
        project = self.app.state.project
        current = str(project.settings.get("blender_path", "") or "") if project else ""
        return {
            "candidates": detect_blender_paths(),
            "current": current,
            "template_exists": project_manager.blend_template_path().is_file(),
            "template_path": str(project_manager.blend_template_path()),
        }

    def method_remove_shot_image(self, shot_id: str) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        shot = app_state._find_shot(project, shot_id)
        project_manager.remove_image_for_shot(project, shot)
        app_state._autosave(self.app)
        return app_state._project_payload(project, self.app.state.dirty)

    def method_relink_preview(self, shot_id: str, relative_path: str) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        shot = app_state._find_shot(project, shot_id)
        try:
            project_manager.relink_preview_image(project, shot, relative_path)
        except (FileNotFoundError, ValueError) as exc:
            logger.exception("Failed to relink preview for shot %s", shot_id)
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        app_state._autosave(self.app)
        return app_state._project_payload(project, self.app.state.dirty)

    def method_open_preview(self, shot_id: str) -> dict[str, str]:
        project = app_state._require_project(self.app)
        shot = app_state._find_shot(project, shot_id)
        rel_path = shot.preview_image_path or shot.image_path
        if not rel_path:
            raise app_error(AppErrorCode.MEDIA_NOT_FOUND, "No preview image linked.")
        try:
            opened = project_manager.open_project_file(project, rel_path, project.settings.get("photoshop_path", ""))
        except (FileNotFoundError, ValueError) as exc:
            logger.exception("Failed to open preview for shot %s", shot_id)
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"path": str(opened)}

    def _request_plugin_focus(self, shot_id: str) -> None:
        """Ask the connected plugin to switch to an already-open shot tab."""
        runtime_state.request_live_focus(self.app, shot_id)
        app_state._touch_live_bridge(self.app, selected_shot_id=shot_id)

    def method_open_source(self, shot_id: str) -> dict[str, str]:
        project = app_state._require_project(self.app)
        shot = app_state._find_shot(project, shot_id)
        if not shot.source_file_path:
            raise app_error(AppErrorCode.MEDIA_NOT_FOUND, "No source file linked. Create a PS canvas first.")
        # If the plugin already has this shot open as a tab, switch to it instead
        # of launching Photoshop again (which creates a confusing duplicate).
        plugin_linked, _age, open_shot_ids = app_state._plugin_link_state(self.app)
        if plugin_linked and shot_id in open_shot_ids:
            self._request_plugin_focus(shot_id)
            return {"path": shot.source_file_path, "switched": "true"}
        try:
            opened = project_manager.open_project_file(
                project,
                shot.source_file_path,
                project.settings.get("photoshop_path", ""),
                shot=shot,
            )
        except (FileNotFoundError, ValueError) as exc:
            logger.exception("Failed to open source file for shot %s", shot_id)
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"path": str(opened)}

    def method_recover_shot_source(self, shot_id: str, preserve_layers: bool = True) -> dict[str, Any]:
        """Rebuild a broken (Photoshop-unopenable) source PSD from its layers."""
        project = app_state._require_project(self.app)
        shot = app_state._find_shot(project, shot_id)
        try:
            result = project_manager.recover_shot_source_psd(
                project, shot, preserve_layers=bool(preserve_layers)
            )
        except (ValueError, FileNotFoundError) as exc:
            logger.exception("Failed to recover source file for shot %s", shot_id)
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 - surface rebuild failures to the caller
            logger.exception("Failed to recover source file for shot %s", shot_id)
            raise HTTPException(status_code=400, detail=f"PSD recovery failed: {exc}") from exc
        app_state._autosave(self.app)
        return {"result": result, **app_state._project_payload(project, self.app.state.dirty)}

    def method_delete_project_reference(self, ref_id: str) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        try:
            with project_transaction.mutate_project(project):
                project_manager.remove_project_reference(project, ref_id)
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        app_state._autosave(self.app)
        return app_state._project_payload(project, self.app.state.dirty)

    def method_open_blender_scene(self) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        try:
            opened = project_manager.open_blender_scene(project)
        except (FileNotFoundError, ValueError) as exc:
            logger.exception("Failed to open Blender scene")
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        app_state._touch_live_bridge(self.app)
        return {
            "path": str(opened),
            "relative_path": opened.relative_to(project.root_path).as_posix() if opened.exists() else "",
            **app_state._project_payload(project, self.app.state.dirty),
        }

    def method_get_canvas_color(self) -> dict[str, str]:
        project = app_state._require_project(self.app)
        return {"color": project_manager.get_canvas_color(project)}

    def method_set_canvas_color(self, color: str) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        try:
            normalized = project_manager.persist_canvas_color(project, color)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        app_state._touch_live_bridge(self.app)
        return {"color": normalized, **app_state._project_payload(project, self.app.state.dirty)}

    def method_remove_shot_reference_image(self, shot_id: str, path: str) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        shot = app_state._find_shot(project, shot_id)
        try:
            project_manager.remove_reference_image(project, shot, path)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        app_state._autosave(self.app)
        return app_state._project_payload(project, self.app.state.dirty)

    def method_set_shot_reference_image_paths(self, shot_id: str, paths: list[str]) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        shot = app_state._find_shot(project, shot_id)
        project_manager.set_reference_image_paths(
            project,
            shot,
            paths if isinstance(paths, list) else [],
        )
        app_state._autosave(self.app)
        return app_state._project_payload(project, self.app.state.dirty)

    def method_create_shot_canvas(
        self,
        shot_id: str,
        width: int | None = None,
        height: int | None = None,
        background_color: str | None = None,
    ) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        shot = app_state._find_shot(project, shot_id)
        default_w, default_h = project_manager.get_canvas_size(project)
        canvas_width, canvas_height = project_manager.normalize_canvas_size(
            width if width is not None else default_w,
            height if height is not None else default_h,
        )
        try:
            with project_transaction.mutate_project(project):
                project_manager.create_canvas_for_shot(
                    project,
                    shot,
                    canvas_width,
                    canvas_height,
                    background_color=background_color,
                )
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        app_state._autosave(self.app)
        return app_state._project_payload(project, self.app.state.dirty)

    def method_save_shot_drawing(self, shot_id: str, image_data: str) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        shot = app_state._find_shot(project, shot_id)
        try:
            with project_transaction.mutate_project(project):
                project_manager.save_drawing_for_shot(project, shot, str(image_data or ""))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        app_state._autosave(self.app)
        return app_state._project_payload(project, self.app.state.dirty)

    def method_sync_all_shots(self, force: bool = False) -> dict[str, Any]:
        project = app_state._refresh_project_from_disk(self.app)
        try:
            results = sync_project(project, force=bool(force))
        except (FileNotFoundError, ValueError) as exc:
            logger.exception("Failed to sync all shots")
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if results:
            app_state._autosave(self.app)
        return {"results": results, **app_state._project_payload(project, self.app.state.dirty)}

    def method_upload_project_reference(self, filename: str, data: list[int] | bytes | bytearray) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        try:
            with project_transaction.mutate_project(project):
                entry = project_manager.import_project_reference_stream(
                    project,
                    _upload_stream(data),
                    str(filename or "reference"),
                )
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        app_state._autosave(self.app)
        return {"reference": entry, **app_state._project_payload(project, self.app.state.dirty)}

    def method_upload_reference_video(self, filename: str, data: list[int] | bytes | bytearray) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        try:
            with project_transaction.mutate_project(project):
                project_manager.import_reference_video_stream(
                    project,
                    _upload_stream(data),
                    str(filename or "reference.mp4"),
                )
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        app_state._autosave(self.app)
        return app_state._project_payload(project, self.app.state.dirty)

    def method_import_scene3d(self, filename: str, data: list[int] | bytes | bytearray) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        try:
            with project_transaction.mutate_project(project):
                scene_settings = project_manager.import_scene3d_stream(
                    project,
                    _upload_stream(data),
                    str(filename or "scene.glb"),
                )
        except (FileNotFoundError, ValueError) as exc:
            logger.exception("Failed to import Scene3D file: %s", filename)
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        app_state._touch_live_bridge(self.app)
        payload = app_state._project_payload(project, self.app.state.dirty)
        return {"scene3d": scene_settings, **payload}

    def method_import_shot_image(
        self,
        shot_id: str,
        filename: str,
        data: list[int] | bytes | bytearray,
    ) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        shot = app_state._find_shot(project, shot_id)
        suffix = Path(str(filename or "")).suffix
        try:
            project_manager.import_image_stream_for_shot(project, shot, _upload_stream(data), suffix)
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        app_state._autosave(self.app)
        return app_state._project_payload(project, self.app.state.dirty)

    def method_add_shot_reference_image(
        self,
        shot_id: str,
        filename: str,
        data: list[int] | bytes | bytearray,
    ) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        shot = app_state._find_shot(project, shot_id)
        suffix = Path(str(filename or "")).suffix
        try:
            project_manager.add_reference_image_stream(project, shot, _upload_stream(data), suffix)
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        app_state._autosave(self.app)
        return app_state._project_payload(project, self.app.state.dirty)

    def method_import_shot_source(
        self,
        shot_id: str,
        filename: str,
        data: list[int] | bytes | bytearray,
    ) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        shot = app_state._find_shot(project, shot_id)
        try:
            project_manager.import_source_file_stream(
                project,
                shot,
                _upload_stream(data),
                str(filename or f"{shot_id}.psd"),
            )
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        app_state._autosave(self.app)
        return app_state._project_payload(project, self.app.state.dirty)

    def _browse(self, kind: str, picker, validator) -> dict[str, Any]:
        initial_dir = app_state._dialog_initial_dir(self.app, kind)
        try:
            selected = picker(initial_dir)
        except Exception as exc:
            logger.exception("Could not open %s picker", kind)
            raise HTTPException(status_code=500, detail=f"Could not open picker: {exc}") from exc
        if not selected:
            return {"path": "", "cancelled": True}
        try:
            validated = validator(selected)
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"path": validated, "cancelled": False}
