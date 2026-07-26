from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException

from . import app_state, project_manager, runtime_state, scene2d, shot_service
from .models import Shot


class PluginBridgeService:
    """Photoshop plugin and live bridge workflow logic."""

    def __init__(self, app: FastAPI) -> None:
        self.app = app

    def mark_project_changed(self) -> None:
        runtime_state.mark_plugin_project_changed(self.app)

    def heartbeat(self, payload: dict[str, Any] | None = None) -> dict[str, str]:
        project = getattr(self.app.state, "project", None)
        valid_work_keys = {item["key"] for item in self.work_items(project) if item.get("key")} if project else set()
        runtime_state.record_plugin_heartbeat(
            self.app,
            payload,
            valid_work_keys=valid_work_keys,
        )
        return {"ok": "true"}

    def context(self) -> dict[str, Any]:
        project = app_state._refresh_project_from_disk(self.app)
        return self.context_payload(project)

    def context_payload(self, project) -> dict[str, Any]:
        canvas_width, canvas_height = project_manager.get_canvas_size(project)
        selected_shot_id = str(
            app_state._plugin_selected_shot_id(self.app)
            or runtime_state.live_selected_shot_id(self.app)
            or ""
        )
        if selected_shot_id and all(shot.shot_id != selected_shot_id for shot in project.shots):
            selected_shot_id = ""
        focused_shot_id = runtime_state.live_focus_shot_id(self.app)
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
            "work_context": runtime_state.active_work_context(self.app),
            "work_items": self.work_items(project),
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

    def work_items(self, project) -> list[dict[str, Any]]:
        """Return all editable PSD work items: shots + Scene 2D PSD Perspectives."""
        items: list[dict[str, Any]] = []
        shots = list(project.shots)
        total_shots = len(shots)
        for index, shot in enumerate(shots):
            source_rel = shot.source_file_path or f"shots/{shot.shot_id}/{shot.shot_id}.psd"
            preview_rel = shot.preview_image_path or f"shots/{shot.shot_id}/{shot.shot_id}_preview.png"
            previous_key = f"shot:{shots[index - 1].shot_id}" if index > 0 else ""
            next_key = f"shot:{shots[index + 1].shot_id}" if index + 1 < total_shots else ""
            items.append({
                "kind": "shot",
                "key": f"shot:{shot.shot_id}",
                "shot_id": shot.shot_id,
                "shot_title": str(shot.title or "").strip(),
                "label": shot.title or shot.shot_id,
                "index": index + 1,
                "count": total_shots,
                "previous_key": previous_key,
                "next_key": next_key,
                "source_file_path": source_rel,
                "source_native_path": self._native_project_path(project, source_rel),
                "preview_image_path": preview_rel,
            })
        try:
            scenes = scene2d.list_scenes(project)
        except Exception:
            scenes = []
        for sc in scenes:
            scene_id = sc.get("id", "")
            scene_title = str(sc.get("title") or "")
            psd_perspectives = [p for p in (sc.get("perspectives") or []) if p.get("type") == "psd"]
            count = len(psd_perspectives)
            for index, persp in enumerate(psd_perspectives):
                if persp.get("type") != "psd":
                    continue
                persp_id = persp.get("id", "")
                source_rel = str(persp.get("source_file_path") or "")
                preview_rel = str(persp.get("preview_image_path") or "")
                items.append({
                    "kind": "scene2d",
                    "key": f"scene2d:{scene_id}:{persp_id}",
                    "scene_id": scene_id,
                    "perspective_id": persp_id,
                    "scene_title": scene_title,
                    "perspective_title": str(persp.get("title") or "Untitled Perspective"),
                    "perspective_type": "psd",
                    "label": f"{scene_title} / {persp.get('title') or 'Untitled Perspective'}",
                    "source_file_path": source_rel,
                    "source_native_path": self._native_project_path(project, source_rel),
                    "preview_image_path": preview_rel,
                    "index": index + 1,
                    "count": count,
                    "previous_key": f"scene2d:{scene_id}:{psd_perspectives[index - 1]['id']}" if index > 0 else "",
                    "next_key": f"scene2d:{scene_id}:{psd_perspectives[index + 1]['id']}" if index + 1 < count else "",
                })
        return items

    def _native_project_path(self, project, relative_path: str) -> str:
        rel = str(relative_path or "").strip()
        if not rel:
            return ""
        try:
            return str((project.root_path / rel).resolve()).replace("\\", "/")
        except OSError:
            return str(project.root_path / rel).replace("\\", "/")

    def work_item_by_key(self, project, key: str) -> dict[str, Any] | None:
        key = str(key or "").strip()
        if not key:
            return None
        return next((item for item in self.work_items(project) if item.get("key") == key), None)

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
        runtime_state.mark_plugin_preview_exported(self.app, shot.shot_id)
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
        runtime_state.set_plugin_and_live_selected_shot_id(self.app, shot_id)
        app_state._persist_app_session(self.app, selected_shot_id=shot_id)
        app_state._touch_live_bridge(self.app, selected_shot_id=shot_id)
        return self.context()

    def next_shot(self, current_shot_id: str | None = None, auto_add: bool = False) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        current = str(current_shot_id or runtime_state.plugin_selected_shot_id(self.app) or "").strip()
        index = app_state._find_shot_index(project, current) if current else -1
        created = None
        if index >= 0 and index + 1 < len(project.shots):
            next_shot = project.shots[index + 1]
        elif auto_add:
            next_shot = shot_service.create_shot(
                project,
                after_shot_id=project.shots[index].shot_id if index >= 0 else None,
            )
            created = next_shot
            app_state._autosave(self.app)
            self.mark_project_changed()
        else:
            return {"shot": None, "created": False, "context": self.context()}
        runtime_state.set_plugin_and_live_selected_shot_id(self.app, next_shot.shot_id)
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

    # ── Scene 2D plugin methods ───────────────────────────────────────────

    def scene2d_export_preview(self, scene_id: str, perspective_id: str) -> dict[str, Any]:
        """Called after the plugin exports a Scene 2D preview PNG."""
        project = app_state._refresh_project_from_disk(self.app)
        try:
            sc, scenes = scene2d._find_scene(project, scene_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        try:
            perspective = scene2d._find_perspective(sc, perspective_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        if perspective.get("type") != "psd":
            raise HTTPException(status_code=400, detail="Perspective is not a PSD — export not allowed.")

        source_rel = str(perspective.get("source_file_path") or "")
        canonical_source_rel = scene2d._source_rel(scene_id, perspective_id)
        if source_rel != canonical_source_rel:
            raise HTTPException(status_code=400, detail="Perspective source path is not canonical.")
        source_path = project.root_path / source_rel
        if not source_path.is_file():
            raise HTTPException(status_code=400, detail=f"Source PSD not found: {source_rel}")

        preview_rel = perspective.get("preview_image_path", "")
        if not preview_rel:
            raise HTTPException(status_code=400, detail="Perspective has no preview_image_path.")
        canonical_preview_rel = scene2d._preview_rel(scene_id, perspective_id)
        if preview_rel != canonical_preview_rel:
            raise HTTPException(status_code=400, detail="Perspective preview path is not canonical.")

        preview_path = project.root_path / preview_rel
        # Safety: preview must stay inside project root
        try:
            preview_path.resolve().relative_to(project.root_path.resolve())
        except ValueError:
            raise HTTPException(status_code=400, detail="Preview path escapes project root.") from None

        if not preview_path.is_file():
            raise HTTPException(status_code=400, detail="Exported preview PNG not found — did the plugin save it?")

        # Update timestamps atomically
        timestamp = scene2d._now_iso()
        perspective["updated_at"] = timestamp
        sc["updated_at"] = timestamp
        updated_scenes = scene2d._replace_scene(scenes, scene2d._with_legacy_aliases(sc))
        scene2d._save_scenes(project, updated_scenes)
        project_manager.sync_document(project)

        runtime_state.mark_scene2d_changed(self.app, scene_id, perspective_id)
        app_state._touch_live_bridge(self.app)

        work_ctx = runtime_state.active_work_context(self.app)
        return {
            "work_context": work_ctx,
            "scene": scene2d._with_legacy_aliases(sc),
            "perspective": perspective,
            "preview_image_path": preview_rel,
        }

    def scene2d_psd_saved(self, scene_id: str, perspective_id: str) -> dict[str, Any]:
        """Called when the artist saves the Scene 2D PSD (Ctrl+S in Photoshop)."""
        project = app_state._refresh_project_from_disk(self.app)
        try:
            sc, scenes = scene2d._find_scene(project, scene_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        try:
            perspective = scene2d._find_perspective(sc, perspective_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        source_path = project.root_path / perspective["source_file_path"]
        if not source_path.is_file():
            raise HTTPException(status_code=400, detail=f"Source PSD not found: {perspective['source_file_path']}")

        timestamp = scene2d._now_iso()
        perspective["updated_at"] = timestamp
        sc["updated_at"] = timestamp
        updated_scenes = scene2d._replace_scene(scenes, scene2d._with_legacy_aliases(sc))
        scene2d._save_scenes(project, updated_scenes)
        project_manager.sync_document(project)

        work_ctx = runtime_state.active_work_context(self.app)
        return {"work_context": work_ctx, "scene": scene2d._with_legacy_aliases(sc), "perspective": perspective}

    def scene2d_next_perspective(self, scene_id: str, perspective_id: str) -> dict[str, Any]:
        """Return the next PSD Perspective in the same Scene group."""
        project = app_state._refresh_project_from_disk(self.app)
        try:
            sc, _scenes = scene2d._find_scene(project, scene_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        psd_perspectives = [p for p in (sc.get("perspectives") or []) if p.get("type") == "psd"]
        index = next((i for i, p in enumerate(psd_perspectives) if p.get("id") == perspective_id), -1)
        if index < 0:
            raise HTTPException(status_code=404, detail="Perspective not found in scene.")

        if index >= len(psd_perspectives) - 1:
            return {"next_perspective": None, "at_end": True}

        next_persp = psd_perspectives[index + 1]
        return {"next_perspective": next_persp, "scene": scene2d._with_legacy_aliases(sc), "at_end": False}

    def shot_health(self, project, shot: Shot) -> dict[str, Any]:
        psd = self.shot_psd_path(project, shot)
        preview = project_manager.resolve_shot_preview_path(project, shot)
        thumb = project_manager.resolve_shot_thumbnail_path(project, shot)
        background = project_manager.get_shot_board_background_path(project, shot)
        source_missing = bool(shot.source_file_path) and not (project.root_path / shot.source_file_path).is_file()
        psd_size = psd.stat().st_size if psd and psd.is_file() else 0
        psd_mtime = psd.stat().st_mtime if psd and psd.is_file() else 0.0
        preview_mtime = preview.stat().st_mtime if preview and preview.is_file() else 0.0
        last_exported = runtime_state.plugin_last_exported_preview(self.app)
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
