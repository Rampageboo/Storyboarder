from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any, BinaryIO

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from . import live_bridge, project_manager, session_store
from .export_utils import (
    export_contact_sheet,
    export_image_sequence,
    export_shot_list_csv,
    export_timing_json,
    missing_files,
)
from .linked_sync import sync_project
from .models import SHOT_STATUSES, Shot
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


class ApiCallRequest(BaseModel):
    method: str
    args: list[Any] = Field(default_factory=list)


def _normalize_upload_bytes(data: list[int] | bytes | bytearray) -> bytes:
    if isinstance(data, (bytes, bytearray)):
        return bytes(data)
    if isinstance(data, list):
        return bytes(int(value) & 0xFF for value in data)
    raise HTTPException(status_code=400, detail="Upload payload must be bytes.")


def _upload_stream(data: list[int] | bytes | bytearray) -> BinaryIO:
    return io.BytesIO(_normalize_upload_bytes(data))


class StoryboardBackendService:
    """Unified JSON API dispatch for desktop bridge and POST /api."""

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
        api = _api()
        project = api._refresh_project_from_disk(self.app)
        return api._project_payload(project, self.app.state.dirty)

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
        api = _api()
        root = Path(path).expanduser() if path else self.app.state.base_dir / "Storyboard_Project"
        try:
            api._track_project(
                self.app,
                project_manager.create_project(
                    root,
                    canvas_width=canvas_width if canvas_width is not None else 1920,
                    canvas_height=canvas_height if canvas_height is not None else 1080,
                ),
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        api._remember_recent(self.app.state.project)
        api._persist_app_session(self.app)
        api._touch_live_bridge(self.app)
        self.app.state.dirty = False
        return api._project_payload(self.app.state.project, self.app.state.dirty)

    def method_open_project(self, project_json_path: str) -> dict[str, Any]:
        api = _api()
        try:
            api._track_project(
                self.app,
                project_manager.open_project(Path(project_json_path).expanduser()),
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        api._remember_recent(self.app.state.project)
        api._persist_app_session(self.app)
        api._touch_live_bridge(self.app)
        self.app.state.dirty = False
        return api._project_payload(self.app.state.project, self.app.state.dirty)

    def method_save_project(self) -> dict[str, Any]:
        api = _api()
        project = api._require_project(self.app)
        try:
            project_manager.save_project(project)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        self.app.state.dirty = False
        return api._project_payload(project, self.app.state.dirty)

    def method_get_missing_files(self) -> dict[str, Any]:
        api = _api()
        project = api._require_project(self.app)
        return {"missing_files": missing_files(project)}

    def method_bridge_status(self) -> dict[str, Any]:
        return _api()._bridge_status_payload(self.app)

    def method_bridge_relink(self) -> dict[str, Any]:
        api = _api()
        api._require_project(self.app)
        api._touch_live_bridge(self.app, selected_shot_id=self.app.state.live_selected_shot_id)
        return api._bridge_status_payload(self.app)

    def method_touch_live_bridge(self, selected_shot_id: str | None = None) -> dict[str, Any]:
        return _api()._touch_live_bridge(self.app, selected_shot_id=selected_shot_id)

    def method_add_shot(self, after_shot_id: str | None = None) -> dict[str, Any]:
        api = _api()
        project = api._require_project(self.app)
        after_index = None
        if after_shot_id:
            after_index = api._find_shot_index(project, after_shot_id)
        shot = project_manager.add_shot(project, after_index=after_index)
        api._autosave(self.app)
        return {"shot": shot.to_dict(), **api._project_payload(project, self.app.state.dirty)}

    def method_duplicate_shot(self, shot_id: str) -> dict[str, Any]:
        api = _api()
        project = api._require_project(self.app)
        duplicate = project_manager.duplicate_shot(project, api._find_shot_index(project, shot_id))
        api._autosave(self.app)
        return {"shot": duplicate.to_dict(), **api._project_payload(project, self.app.state.dirty)}

    def method_update_shot(self, shot_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        api = _api()
        project = api._require_project(self.app)
        shot = api._find_shot(project, shot_id)
        data = payload if isinstance(payload, dict) else {}
        shot.title = str(data.get("title", shot.title))
        shot.scene = str(data.get("scene", shot.scene))
        shot.sequence = str(data.get("sequence", shot.sequence))
        shot.description = str(data.get("description", shot.description))
        shot.action_note = str(data.get("action_note", shot.action_note))
        shot.camera_note = str(data.get("camera_note", shot.camera_note))
        shot.character_note = str(data.get("character_note", shot.character_note))
        shot.dialogue = str(data.get("dialogue", shot.dialogue))
        shot.lighting_note = str(data.get("lighting_note", shot.lighting_note))
        shot.transition_note = str(data.get("transition_note", shot.transition_note))
        shot.duration_seconds = max(0.1, float(data.get("duration_seconds", shot.duration_seconds)))
        shot.camera_data = data.get("camera_data") if isinstance(data.get("camera_data"), dict) else shot.camera_data
        tags = data.get("tags")
        shot.tags = [str(tag).strip() for tag in tags if str(tag).strip()] if isinstance(tags, list) else shot.tags
        status = str(data.get("status", shot.status))
        shot.status = status if status in SHOT_STATUSES else "Draft"
        api._autosave(self.app)
        return api._project_payload(project, self.app.state.dirty)

    def method_delete_shot(self, shot_id: str) -> dict[str, Any]:
        api = _api()
        project = api._require_project(self.app)
        index = api._find_shot_index(project, shot_id)
        try:
            project_manager.delete_shot(project, index)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        api._autosave(self.app)
        return api._project_payload(project, self.app.state.dirty)

    def method_restore_shot(self, shot: dict[str, Any], index: int = 0) -> dict[str, Any]:
        api = _api()
        project = api._require_project(self.app)
        if not isinstance(shot, dict):
            raise HTTPException(status_code=400, detail="Shot payload required.")
        try:
            project_manager.restore_shot(project, shot, int(index))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        api._autosave(self.app)
        return api._project_payload(project, self.app.state.dirty)

    def method_reorder_shots(self, shot_ids: list[str]) -> dict[str, Any]:
        api = _api()
        project = api._require_project(self.app)
        if not isinstance(shot_ids, list):
            raise HTTPException(status_code=400, detail="Shot order required.")
        try:
            project_manager.reorder_shots(project, [str(item) for item in shot_ids])
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        api._autosave(self.app)
        return api._project_payload(project, self.app.state.dirty)

    def method_import_image_path(self, shot_id: str, source_path: str) -> dict[str, Any]:
        api = _api()
        project = api._require_project(self.app)
        shot = api._find_shot(project, shot_id)
        try:
            project_manager.import_image_for_shot(project, shot, Path(str(source_path)).expanduser())
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        api._autosave(self.app)
        return api._project_payload(project, self.app.state.dirty)

    def method_apply_ref_segment(self, anchor_shot_id: str, end_shot_id: str, segment_id: str = "") -> dict[str, Any]:
        api = _api()
        project = api._require_project(self.app)
        anchor = api._find_shot_index(project, anchor_shot_id)
        end = api._find_shot_index(project, end_shot_id)
        try:
            result = project_manager.apply_ref_segment_to_boards(
                project,
                anchor,
                end,
                segment_id or None,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        api._autosave(self.app)
        return {**result, **api._project_payload(project, self.app.state.dirty)}

    def method_apply_ref_segment_image(
        self,
        anchor_shot_id: str,
        end_shot_id: str,
        segment_id: str = "",
    ) -> dict[str, Any]:
        api = _api()
        project = api._require_project(self.app)
        anchor = api._find_shot_index(project, anchor_shot_id)
        end = api._find_shot_index(project, end_shot_id)
        try:
            result = project_manager.apply_ref_segment_image_to_boards(
                project,
                anchor,
                end,
                segment_id or None,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        api._autosave(self.app)
        return {**result, **api._project_payload(project, self.app.state.dirty)}

    def method_apply_ref_segment_3d(
        self,
        anchor_shot_id: str,
        end_shot_id: str,
        segment_id: str = "",
        camera_name: str = "",
    ) -> dict[str, Any]:
        api = _api()
        project = api._require_project(self.app)
        anchor = api._find_shot_index(project, anchor_shot_id)
        end = api._find_shot_index(project, end_shot_id)
        try:
            result = project_manager.apply_ref_segment_3d_to_boards(
                project,
                anchor,
                end,
                segment_id or None,
                camera_name=str(camera_name or ""),
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        api._autosave(self.app)
        return {**result, **api._project_payload(project, self.app.state.dirty)}

    def method_delete_ref_segment(self, segment_id: str) -> dict[str, Any]:
        api = _api()
        project = api._require_project(self.app)
        try:
            result = project_manager.delete_ref_segment(project, segment_id)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        api._autosave(self.app)
        return {**result, **api._project_payload(project, self.app.state.dirty)}

    def method_move_shot_up(self, shot_id: str) -> dict[str, Any]:
        api = _api()
        project = api._require_project(self.app)
        project_manager.move_shot_up(project, api._find_shot_index(project, shot_id))
        api._autosave(self.app)
        return api._project_payload(project, self.app.state.dirty)

    def method_move_shot_down(self, shot_id: str) -> dict[str, Any]:
        api = _api()
        project = api._require_project(self.app)
        project_manager.move_shot_down(project, api._find_shot_index(project, shot_id))
        api._autosave(self.app)
        return api._project_payload(project, self.app.state.dirty)

    def method_sync_shot(self, shot_id: str, force: bool = False) -> dict[str, Any]:
        api = _api()
        project = api._refresh_project_from_disk(self.app)
        shot = api._find_shot(project, shot_id)
        try:
            result = project_manager.sync_shot(project, shot, force=bool(force))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if result.get("synced"):
            api._autosave(self.app)
        return {"result": result, **api._project_payload(project, self.app.state.dirty)}

    def method_get_annotations(self, shot_id: str) -> dict[str, Any]:
        api = _api()
        project = api._require_project(self.app)
        shot = api._find_shot(project, shot_id)
        path = api._annotation_path(project, shot)
        try:
            annotations = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid annotation JSON: {exc}") from exc
        if not isinstance(annotations, list):
            raise HTTPException(status_code=400, detail="Annotation file must contain a list.")
        return {"annotations": annotations}

    def method_save_annotations(self, shot_id: str, annotations: list[Any]) -> dict[str, Any]:
        api = _api()
        project = api._require_project(self.app)
        shot = api._find_shot(project, shot_id)
        path = api._annotation_path(project, shot)
        payload = annotations if isinstance(annotations, list) else []
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return {"annotations": payload}

    def method_add_comment(self, shot_id: str, text: str) -> dict[str, Any]:
        api = _api()
        project = api._require_project(self.app)
        shot = api._find_shot(project, shot_id)
        cleaned = str(text or "").strip()
        if not cleaned:
            raise HTTPException(status_code=400, detail="Comment cannot be empty.")
        next_id = max([int(comment.get("id", 0)) for comment in shot.comments] or [0]) + 1
        shot.comments.append({"id": next_id, "text": cleaned, "resolved": False})
        api._autosave(self.app)
        return api._project_payload(project, self.app.state.dirty)

    def method_resolve_comment(self, shot_id: str, comment_id: int, resolved: bool = True) -> dict[str, Any]:
        api = _api()
        project = api._require_project(self.app)
        shot = api._find_shot(project, shot_id)
        for comment in shot.comments:
            if int(comment.get("id", 0)) == int(comment_id):
                comment["resolved"] = bool(resolved)
                api._autosave(self.app)
                return api._project_payload(project, self.app.state.dirty)
        raise HTTPException(status_code=404, detail="Comment not found.")

    def method_export_pdf(self, layout: str = "two_per_page") -> dict[str, str]:
        api = _api()
        project = api._require_project(self.app)
        output_path = project.exports_dir / "storyboard.pdf"
        chosen = layout if layout in {"one_per_page", "two_per_page", "thumbnails"} else "two_per_page"
        try:
            _export_storyboard_pdf(project, output_path, layout=chosen)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        project.settings["pdf_layout"] = chosen
        project_manager.save_settings(project)
        return {"path": str(output_path), "download_url": "/api/export/pdf"}

    def method_export_shot_list(self) -> dict[str, str]:
        api = _api()
        project = api._require_project(self.app)
        output_path = project.exports_dir / "shot_list.csv"
        try:
            export_shot_list_csv(project, output_path)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return {"path": str(output_path), "download_url": "/api/export/shot-list"}

    def method_export_timing(self) -> dict[str, str]:
        api = _api()
        project = api._require_project(self.app)
        output_path = project.exports_dir / "timing.json"
        try:
            export_timing_json(project, output_path)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return {"path": str(output_path), "download_url": "/api/export/timing"}

    def method_export_contact_sheet(self) -> dict[str, str]:
        api = _api()
        project = api._require_project(self.app)
        output_path = project.exports_dir / "contact_sheet.png"
        try:
            export_contact_sheet(project, output_path)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return {"path": str(output_path), "download_url": "/api/export/contact-sheet"}

    def method_export_image_sequence(self) -> dict[str, str]:
        api = _api()
        project = api._require_project(self.app)
        output_dir = project.exports_dir / "image_sequence"
        try:
            export_image_sequence(project, output_dir)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return {"path": str(output_dir)}

    def method_update_settings(self, payload: dict[str, Any]) -> dict[str, Any]:
        api = _api()
        project = api._require_project(self.app)
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
                project.settings["reference_model_path"] = ""
                if str(project.settings.get("reference_segment_mode") or "") == "model":
                    project.settings["reference_segment_mode"] = "video"
                project_manager.save_settings(project)
        if "reference_image_path" in data:
            value = str(data.get("reference_image_path") or "").strip()
            if value:
                project_manager.set_active_reference_image(project, value)
            else:
                project.settings["reference_image_path"] = ""
                if str(project.settings.get("reference_segment_mode") or "") == "image":
                    project.settings["reference_segment_mode"] = "video"
                project_manager.save_settings(project)
        if "reference_segment_mode" in data:
            mode = str(data.get("reference_segment_mode") or "").strip().lower()
            if mode in {"video", "model", "image"}:
                project.settings["reference_segment_mode"] = mode
                project_manager.save_settings(project)
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
            project_manager.persist_canvas_color(project, str(data["canvas_background_color"]))
        elif "scene3d" in data:
            project.settings["scene3d"] = data["scene3d"]
            project_manager.save_settings(project)
            project_manager.write_bridge_file(project)
        else:
            project_manager.save_settings(project)
            project_manager.write_bridge_file(project)
        api._touch_live_bridge(self.app)
        return api._project_payload(project, self.app.state.dirty)

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
        api = _api()
        project = api._require_project(self.app)
        shot = api._find_shot(project, shot_id)
        project_manager.remove_image_for_shot(project, shot)
        api._autosave(self.app)
        return api._project_payload(project, self.app.state.dirty)

    def method_relink_preview(self, shot_id: str, relative_path: str) -> dict[str, Any]:
        api = _api()
        project = api._require_project(self.app)
        shot = api._find_shot(project, shot_id)
        try:
            project_manager.relink_preview_image(project, shot, relative_path)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        api._autosave(self.app)
        return api._project_payload(project, self.app.state.dirty)

    def method_open_preview(self, shot_id: str) -> dict[str, str]:
        api = _api()
        project = api._require_project(self.app)
        shot = api._find_shot(project, shot_id)
        rel_path = shot.preview_image_path or shot.image_path
        if not rel_path:
            raise HTTPException(status_code=400, detail="No preview image linked.")
        try:
            opened = project_manager.open_project_file(project, rel_path, project.settings.get("photoshop_path", ""))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"path": str(opened)}

    def method_open_source(self, shot_id: str) -> dict[str, str]:
        api = _api()
        project = api._require_project(self.app)
        shot = api._find_shot(project, shot_id)
        if not shot.source_file_path:
            raise HTTPException(status_code=400, detail="No source file linked. Create a PS canvas first.")
        try:
            opened = project_manager.open_project_file(
                project,
                shot.source_file_path,
                project.settings.get("photoshop_path", ""),
                shot=shot,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"path": str(opened)}

    def method_delete_project_reference(self, ref_id: str) -> dict[str, Any]:
        api = _api()
        project = api._require_project(self.app)
        try:
            project_manager.remove_project_reference(project, ref_id)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        api._autosave(self.app)
        return api._project_payload(project, self.app.state.dirty)

    def method_open_blender_scene(self) -> dict[str, Any]:
        api = _api()
        project = api._require_project(self.app)
        try:
            opened = project_manager.open_blender_scene(project)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        api._touch_live_bridge(self.app)
        return {
            "path": str(opened),
            "relative_path": opened.relative_to(project.root_path).as_posix() if opened.exists() else "",
            **api._project_payload(project, self.app.state.dirty),
        }

    def method_get_canvas_color(self) -> dict[str, str]:
        api = _api()
        project = api._require_project(self.app)
        return {"color": project_manager.get_canvas_color(project)}

    def method_set_canvas_color(self, color: str) -> dict[str, Any]:
        api = _api()
        project = api._require_project(self.app)
        try:
            normalized = project_manager.persist_canvas_color(project, color)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        api._touch_live_bridge(self.app)
        return {"color": normalized, **api._project_payload(project, self.app.state.dirty)}

    def method_remove_shot_reference_image(self, shot_id: str, path: str) -> dict[str, Any]:
        api = _api()
        project = api._require_project(self.app)
        shot = api._find_shot(project, shot_id)
        try:
            project_manager.remove_reference_image(project, shot, path)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        api._autosave(self.app)
        return api._project_payload(project, self.app.state.dirty)

    def method_set_shot_reference_image_paths(self, shot_id: str, paths: list[str]) -> dict[str, Any]:
        api = _api()
        project = api._require_project(self.app)
        shot = api._find_shot(project, shot_id)
        project_manager.set_reference_image_paths(
            project,
            shot,
            paths if isinstance(paths, list) else [],
        )
        api._autosave(self.app)
        return api._project_payload(project, self.app.state.dirty)

    def method_create_shot_canvas(
        self,
        shot_id: str,
        width: int | None = None,
        height: int | None = None,
        background_color: str | None = None,
    ) -> dict[str, Any]:
        api = _api()
        project = api._require_project(self.app)
        shot = api._find_shot(project, shot_id)
        default_w, default_h = project_manager.get_canvas_size(project)
        canvas_width, canvas_height = project_manager.normalize_canvas_size(
            width if width is not None else default_w,
            height if height is not None else default_h,
        )
        try:
            project_manager.create_canvas_for_shot(
                project,
                shot,
                canvas_width,
                canvas_height,
                background_color=background_color,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        api._autosave(self.app)
        return api._project_payload(project, self.app.state.dirty)

    def method_save_shot_drawing(self, shot_id: str, image_data: str) -> dict[str, Any]:
        api = _api()
        project = api._require_project(self.app)
        shot = api._find_shot(project, shot_id)
        try:
            project_manager.save_drawing_for_shot(project, shot, str(image_data or ""))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        api._autosave(self.app)
        return api._project_payload(project, self.app.state.dirty)

    def method_sync_all_shots(self, force: bool = False) -> dict[str, Any]:
        api = _api()
        project = api._refresh_project_from_disk(self.app)
        try:
            results = sync_project(project, force=bool(force))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if results:
            api._autosave(self.app)
        return {"results": results, **api._project_payload(project, self.app.state.dirty)}

    def method_get_scene3d_file(self) -> dict[str, str]:
        api = _api()
        project = api._require_project(self.app)
        try:
            path = project_manager.get_scene3d_file_path(project)
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if path is None:
            raise HTTPException(status_code=404, detail="No Blender scene imported.")
        media_type = "model/gltf-binary" if path.suffix.lower() == ".glb" else "model/gltf+json"
        return {"path": str(path), "media_type": media_type, "filename": path.name}

    def method_get_shot_image(self, shot_id: str) -> dict[str, str]:
        api = _api()
        project = api._require_project(self.app)
        shot = api._find_shot(project, shot_id)
        image_rel_path = shot.preview_image_path or shot.image_path
        if not image_rel_path:
            raise HTTPException(status_code=404, detail="No image for this shot.")
        image_path = project.root_path / image_rel_path
        if not image_path.exists():
            raise HTTPException(status_code=404, detail="Image file is missing.")
        return {"path": str(image_path), "media_type": "", "filename": image_path.name}

    def method_get_shot_thumbnail(self, shot_id: str) -> dict[str, str]:
        api = _api()
        project = api._require_project(self.app)
        shot = api._find_shot(project, shot_id)
        image_rel_path = shot.thumbnail_path or shot.preview_image_path or shot.image_path
        if not image_rel_path:
            raise HTTPException(status_code=404, detail="No thumbnail for this shot.")
        image_path = project.root_path / image_rel_path
        if not image_path.exists():
            raise HTTPException(status_code=404, detail="Thumbnail file is missing.")
        return {"path": str(image_path), "media_type": "", "filename": image_path.name}

    def method_get_shot_board_background(self, shot_id: str) -> dict[str, str]:
        api = _api()
        project = api._require_project(self.app)
        shot = api._find_shot(project, shot_id)
        background_path = project_manager.get_shot_board_background_path(project, shot)
        if background_path is None or not background_path.is_file():
            raise HTTPException(status_code=404, detail="No board background for this shot.")
        return {"path": str(background_path), "media_type": "", "filename": background_path.name}

    def method_get_project_file(self, path: str) -> dict[str, str]:
        api = _api()
        project = api._require_project(self.app)
        file_path = (project.root_path / path).resolve()
        root = project.root_path.resolve()
        if root not in file_path.parents and file_path != root:
            raise HTTPException(status_code=400, detail="File path is outside the project.")
        if not file_path.exists() or not file_path.is_file():
            raise HTTPException(status_code=404, detail="File is missing.")
        return {"path": str(file_path), "media_type": "", "filename": file_path.name}

    def method_download_shot_list(self) -> dict[str, str]:
        api = _api()
        project = api._require_project(self.app)
        output_path = project.exports_dir / "shot_list.csv"
        if not output_path.exists():
            raise HTTPException(status_code=404, detail="Export the shot list first.")
        return {
            "path": str(output_path),
            "media_type": "text/csv",
            "filename": "shot_list.csv",
        }

    def method_download_timing(self) -> dict[str, str]:
        api = _api()
        project = api._require_project(self.app)
        output_path = project.exports_dir / "timing.json"
        if not output_path.exists():
            raise HTTPException(status_code=404, detail="Export timing data first.")
        return {
            "path": str(output_path),
            "media_type": "application/json",
            "filename": "timing.json",
        }

    def method_download_contact_sheet(self) -> dict[str, str]:
        api = _api()
        project = api._require_project(self.app)
        output_path = project.exports_dir / "contact_sheet.png"
        if not output_path.exists():
            raise HTTPException(status_code=404, detail="Export the contact sheet first.")
        return {
            "path": str(output_path),
            "media_type": "image/png",
            "filename": "contact_sheet.png",
        }

    def method_download_pdf(self) -> dict[str, str]:
        api = _api()
        project = api._require_project(self.app)
        output_path = project.exports_dir / "storyboard.pdf"
        if not output_path.exists():
            raise HTTPException(status_code=404, detail="Export the PDF first.")
        return {
            "path": str(output_path),
            "media_type": "application/pdf",
            "filename": "storyboard.pdf",
        }

    def method_upload_project_reference(self, filename: str, data: list[int] | bytes | bytearray) -> dict[str, Any]:
        api = _api()
        project = api._require_project(self.app)
        try:
            entry = project_manager.import_project_reference_stream(
                project,
                _upload_stream(data),
                str(filename or "reference"),
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        api._autosave(self.app)
        return {"reference": entry, **api._project_payload(project, self.app.state.dirty)}

    def method_upload_reference_video(self, filename: str, data: list[int] | bytes | bytearray) -> dict[str, Any]:
        api = _api()
        project = api._require_project(self.app)
        try:
            project_manager.import_reference_video_stream(
                project,
                _upload_stream(data),
                str(filename or "reference.mp4"),
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        api._autosave(self.app)
        return api._project_payload(project, self.app.state.dirty)

    def method_import_scene3d(self, filename: str, data: list[int] | bytes | bytearray) -> dict[str, Any]:
        api = _api()
        project = api._require_project(self.app)
        try:
            scene_settings = project_manager.import_scene3d_stream(
                project,
                _upload_stream(data),
                str(filename or "scene.glb"),
            )
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        api._touch_live_bridge(self.app)
        payload = api._project_payload(project, self.app.state.dirty)
        return {"scene3d": scene_settings, **payload}

    def method_import_shot_image(
        self,
        shot_id: str,
        filename: str,
        data: list[int] | bytes | bytearray,
    ) -> dict[str, Any]:
        api = _api()
        project = api._require_project(self.app)
        shot = api._find_shot(project, shot_id)
        suffix = Path(str(filename or "")).suffix
        try:
            project_manager.import_image_stream_for_shot(project, shot, _upload_stream(data), suffix)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        api._autosave(self.app)
        return api._project_payload(project, self.app.state.dirty)

    def method_add_shot_reference_image(
        self,
        shot_id: str,
        filename: str,
        data: list[int] | bytes | bytearray,
    ) -> dict[str, Any]:
        api = _api()
        project = api._require_project(self.app)
        shot = api._find_shot(project, shot_id)
        suffix = Path(str(filename or "")).suffix
        try:
            project_manager.add_reference_image_stream(project, shot, _upload_stream(data), suffix)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        api._autosave(self.app)
        return api._project_payload(project, self.app.state.dirty)

    def method_import_shot_source(
        self,
        shot_id: str,
        filename: str,
        data: list[int] | bytes | bytearray,
    ) -> dict[str, Any]:
        api = _api()
        project = api._require_project(self.app)
        shot = api._find_shot(project, shot_id)
        try:
            project_manager.import_source_file_stream(
                project,
                shot,
                _upload_stream(data),
                str(filename or f"{shot_id}.psd"),
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        api._autosave(self.app)
        return api._project_payload(project, self.app.state.dirty)

    def _browse(self, kind: str, picker, validator) -> dict[str, Any]:
        api = _api()
        initial_dir = api._dialog_initial_dir(self.app, kind)
        try:
            selected = picker(initial_dir)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Could not open picker: {exc}") from exc
        if not selected:
            return {"path": "", "cancelled": True}
        try:
            validated = validator(selected)
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"path": validated, "cancelled": False}


def dispatch_api_call(app: FastAPI, method: str, args: list[Any] | None = None) -> dict[str, Any]:
    service = StoryboardBackendService(app)
    try:
        result = service.call(method, args)
        return {"ok": True, "result": result}
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, str) else json.dumps(exc.detail)
        return {"ok": False, "error": detail}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _api():
    from . import api as api_module

    return api_module


def _export_storyboard_pdf(project, output_path: Path, *, layout: str) -> None:
    from .pdf_exporter import export_storyboard_pdf

    export_storyboard_pdf(project, output_path, layout=layout)
