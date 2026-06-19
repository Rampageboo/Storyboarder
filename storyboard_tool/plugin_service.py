from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException

from . import app_state, project_manager
from .models import Shot


class PluginBridgeService:
    """Photoshop plugin and live bridge workflow logic."""

    def __init__(self, app: FastAPI) -> None:
        self.app = app

    def mark_project_changed(self) -> None:
        self.app.state.plugin_project_revision = int(getattr(self.app.state, "plugin_project_revision", 0) or 0) + 1

    def heartbeat(self, payload: dict[str, Any] | None = None) -> dict[str, str]:
        data = payload if isinstance(payload, dict) else {}
        self.app.state.plugin_last_seen = time.time()
        selected = str(data.get("selected_shot_id") or "").strip()
        if selected:
            self.app.state.plugin_selected_shot_id = selected
            self.app.state.live_selected_shot_id = selected
        open_ids = data.get("open_shot_ids")
        if isinstance(open_ids, list):
            self.app.state.plugin_open_shot_ids = [str(item) for item in open_ids if item]
        return {"ok": "true"}

    def context(self) -> dict[str, Any]:
        project = app_state._refresh_project_from_disk(self.app)
        return self.context_payload(project)

    def context_payload(self, project) -> dict[str, Any]:
        canvas_width, canvas_height = project_manager.get_canvas_size(project)
        selected_shot_id = str(
            app_state._plugin_selected_shot_id(self.app)
            or getattr(self.app.state, "live_selected_shot_id", "")
            or ""
        )
        if selected_shot_id and all(shot.shot_id != selected_shot_id for shot in project.shots):
            selected_shot_id = ""
        focused_shot_id = str(getattr(self.app.state, "live_focus_shot_id", "") or "")
        shots = [self.shot_payload(project, shot) for shot in project.shots]
        selected_index = next(
            (index for index, shot in enumerate(project.shots) if shot.shot_id == selected_shot_id),
            -1,
        )
        next_shot_id = ""
        if selected_index >= 0 and selected_index + 1 < len(project.shots):
            next_shot_id = project.shots[selected_index + 1].shot_id
        selected_shot = project.shots[selected_index] if selected_index >= 0 else None
        return {
            "project_name": project.name,
            "project_root": str(project.root_path),
            "project_json_path": str(project.json_path),
            "selected_shot_id": selected_shot_id,
            "focused_shot_id": focused_shot_id,
            "canvas": {
                "width": canvas_width,
                "height": canvas_height,
                "background_color": project_manager.get_canvas_color(project),
            },
            "shots": shots,
            "previous_shots": shots[:selected_index] if selected_index > 0 else [],
            "next_shot_id": next_shot_id,
            "paths": self.shot_paths(project, selected_shot) if selected_shot else {},
            "bridge": app_state._bridge_status_payload(self.app),
        }

    def export_preview(self, shot_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        project = app_state._refresh_project_from_disk(self.app)
        shot = app_state._find_shot(project, shot_id)
        data = payload if isinstance(payload, dict) else {}
        preview_rel = str(data.get("preview_image_path") or f"shots/{shot.shot_id}/{shot.shot_id}_preview.png")
        source_rel = str(data.get("source_file_path") or "").strip()
        if source_rel:
            try:
                source_path = project_manager.resolve_project_relative_path(project, source_rel, required_suffixes=(".psd",))
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            if not source_path.is_file():
                raise HTTPException(status_code=400, detail=f"PSD not found: {source_rel}")
            shot.source_file_path = source_path.relative_to(project.root_path).as_posix()
            shot.source_sync_mtime = source_path.stat().st_mtime
        else:
            fallback_source = project.root_path / f"shots/{shot.shot_id}/{shot.shot_id}.psd"
            if fallback_source.is_file():
                shot.source_file_path = fallback_source.relative_to(project.root_path).as_posix()
                shot.source_sync_mtime = fallback_source.stat().st_mtime
        try:
            project_manager.relink_preview_image(project, shot, preview_rel)
        except (ValueError, FileNotFoundError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        exported = getattr(self.app.state, "plugin_last_exported_preview", None)
        if not isinstance(exported, dict):
            exported = {}
            self.app.state.plugin_last_exported_preview = exported
        exported[shot.shot_id] = time.time()
        app_state._autosave(self.app)
        self.mark_project_changed()
        return {
            "shot": self.shot_payload(project, shot),
            "context": self.context(),
        }

    def psd_saved(self, shot_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        project = app_state._refresh_project_from_disk(self.app)
        shot = app_state._find_shot(project, shot_id)
        data = payload if isinstance(payload, dict) else {}
        source_rel = str(data.get("source_file_path") or shot.source_file_path or f"shots/{shot.shot_id}/{shot.shot_id}.psd")
        try:
            source_path = project_manager.resolve_project_relative_path(project, source_rel, required_suffixes=(".psd",))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not source_path.is_file():
            raise HTTPException(status_code=400, detail=f"PSD not found: {source_rel}")
        shot.source_file_path = source_path.relative_to(project.root_path).as_posix()
        shot.source_sync_mtime = source_path.stat().st_mtime
        app_state._autosave(self.app)
        self.mark_project_changed()
        return {"shot": self.shot_payload(project, shot), "context": self.context()}

    def focus_shot(self, shot_id: str) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        app_state._find_shot(project, shot_id)
        self.app.state.plugin_selected_shot_id = shot_id
        self.app.state.live_selected_shot_id = shot_id
        app_state._persist_app_session(self.app, selected_shot_id=shot_id)
        app_state._touch_live_bridge(self.app, selected_shot_id=shot_id)
        return self.context()

    def next_shot(self, current_shot_id: str | None = None, auto_add: bool = False) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        current = str(current_shot_id or getattr(self.app.state, "plugin_selected_shot_id", "") or "").strip()
        index = app_state._find_shot_index(project, current) if current else -1
        created = None
        if index >= 0 and index + 1 < len(project.shots):
            next_shot = project.shots[index + 1]
        elif auto_add:
            next_shot = project_manager.add_shot(project, after_index=index if index >= 0 else None)
            created = next_shot
            app_state._autosave(self.app)
            self.mark_project_changed()
        else:
            return {"shot": None, "created": False, "context": self.context()}
        self.app.state.plugin_selected_shot_id = next_shot.shot_id
        self.app.state.live_selected_shot_id = next_shot.shot_id
        app_state._touch_live_bridge(self.app, selected_shot_id=next_shot.shot_id)
        return {
            "shot": self.shot_payload(project, next_shot),
            "created": created is not None,
            "context": self.context(),
        }

    def shot_payload(self, project, shot: Shot) -> dict[str, Any]:
        data = app_state._shot_payload(project, shot)
        data.update(self.shot_health(project, shot))
        return data

    def shot_paths(self, project, shot: Shot | None) -> dict[str, str]:
        if shot is None:
            return {}
        shot_dir = project_manager.get_shot_dir(project, shot)
        preview = project_manager.resolve_shot_preview_path(project, shot)
        thumb = project_manager.resolve_shot_thumbnail_path(project, shot)
        background = project_manager.get_shot_board_background_path(project, shot)
        psd = self.shot_psd_path(project, shot)
        return {
            "psd": str(psd) if psd else str(shot_dir / f"{shot.shot_id}.psd"),
            "preview": str(preview) if preview else str(shot_dir / f"{shot.shot_id}_preview.png"),
            "thumbnail": str(thumb) if thumb else str(shot_dir / f"{shot.shot_id}_thumb.png"),
            "board_background": str(background) if background else str(shot_dir / f"{shot.shot_id}_background.png"),
        }

    def shot_psd_path(self, project, shot: Shot) -> Path | None:
        candidates: list[Path] = []
        if shot.source_file_path:
            candidates.append(project.root_path / shot.source_file_path)
        candidates.append(project_manager.get_shot_dir(project, shot) / f"{shot.shot_id}.psd")
        for candidate in candidates:
            if candidate.is_file():
                return candidate
        return None

    def shot_health(self, project, shot: Shot) -> dict[str, Any]:
        psd = self.shot_psd_path(project, shot)
        preview = project_manager.resolve_shot_preview_path(project, shot)
        thumb = project_manager.resolve_shot_thumbnail_path(project, shot)
        background = project_manager.get_shot_board_background_path(project, shot)
        source_missing = bool(shot.source_file_path) and not (project.root_path / shot.source_file_path).is_file()
        psd_size = psd.stat().st_size if psd and psd.is_file() else 0
        psd_mtime = psd.stat().st_mtime if psd and psd.is_file() else 0.0
        preview_mtime = preview.stat().st_mtime if preview and preview.is_file() else 0.0
        last_exported = getattr(self.app.state, "plugin_last_exported_preview", {})
        if not isinstance(last_exported, dict):
            last_exported = {}
        return {
            "psd_exists": bool(psd and psd.is_file()),
            "preview_exists": bool(preview and preview.is_file()),
            "thumbnail_exists": bool(thumb and thumb.is_file()),
            "source_path_missing": source_missing,
            "preview_out_of_date": bool(psd_mtime and (not preview_mtime or preview_mtime + 1.0 < psd_mtime)),
            "broken_or_zero_byte_psd": bool(psd and psd.is_file() and psd_size < 26),
            "last_exported_preview_time": last_exported.get(shot.shot_id),
            "paths": self.shot_paths(project, shot),
            "ref_video_path": shot.ref_video_path,
            "ref_video_time": shot.ref_video_time,
            "ref_segment_time": shot.ref_segment_time,
        }
