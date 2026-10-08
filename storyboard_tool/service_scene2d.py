"""Scene 2D endpoint orchestration, perspectives and plugin editing adapters.

The backend facade supplies app and its shared _plugin_service factory. Domain
storage, runtime context and mutation execution stay in their existing owners.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from . import app_state, generation_service, project_manager, runtime_state, scene2d
from .mutation_executor import MutationPolicy, project_mutation
from .upload_payload import normalize_upload_bytes as _normalize_upload_bytes

logger = logging.getLogger(__name__)


class Scene2DServiceMixin:
    def method_list_scene2d(self) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        return {"scenes": scene2d.list_scenes(project)}

    @project_mutation(MutationPolicy.LAYOUT2)
    def method_create_scene2d(self, data: dict[str, Any]) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        try:
            scene, scenes = scene2d.create_scene(
                project,
                title=str(data.get("title") or ""),
                description=str(data.get("description") or ""),
                location=str(data.get("location") or ""),
                time_of_day=str(data.get("time_of_day") or ""),
                environment_prompt=str(data.get("environment_prompt") or ""),
                consistency_anchors=data.get("consistency_anchors") if isinstance(data.get("consistency_anchors"), list) else [],
            )
        except (FileNotFoundError, ValueError) as exc:
            logger.exception("Failed to create Scene 2D")
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        app_state.persist_project_mutation(self.app)
        app_state._touch_live_bridge(self.app)
        return {"scene": scene, "scenes": scenes}

    @project_mutation(MutationPolicy.LAYOUT2)
    def method_update_scene2d(self, scene_id: str, data: dict[str, Any]) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        try:
            before_scene = next(
                (item for item in scene2d.list_scenes(project) if item.get("id") == scene_id),
                None,
            )
            scene, scenes = scene2d.update_scene(project, scene_id, data)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        context_keys = {"title", "description", "location", "time_of_day", "environment_prompt", "consistency_anchors"}
        scene_context_changed = before_scene is None or any(
            key in data and before_scene.get(key) != scene.get(key)
            for key in context_keys
        )
        for shot in project.shots:
            if shot.scene_id != scene["id"]:
                continue
            if "title" in data and shot.scene != scene["title"]:
                shot.scene = scene["title"]
            if scene_context_changed and generation_service.has_generation_activity(shot):
                shot.generation_state["freshness_status"] = "stale"
        app_state.persist_project_mutation(self.app)
        app_state._touch_live_bridge(self.app)
        return {"scene": scene, "scenes": scenes}

    @project_mutation(MutationPolicy.LAYOUT2)
    def method_delete_scene2d(self, scene_id: str) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        try:
            existing_scene = next(
                (item for item in scene2d.list_scenes(project) if item.get("id") == scene_id),
                None,
            )
            scenes = scene2d.delete_scene(project, scene_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        for shot in project.shots:
            if shot.scene_id != scene_id:
                continue
            shot.scene_id = ""
            if not shot.scene and existing_scene:
                shot.scene = str(existing_scene.get("title") or "")
            if generation_service.has_generation_activity(shot):
                shot.generation_state["freshness_status"] = "stale"
        app_state.persist_project_mutation(self.app)
        app_state._touch_live_bridge(self.app)
        return {"scenes": scenes}

    @project_mutation(MutationPolicy.LAYOUT2)
    def method_open_scene2d(self, scene_id: str) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        try:
            scene, opened, relative_path = scene2d.open_scene(project, scene_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            logger.exception("Failed to open Scene 2D %s", scene_id)
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        app_state._touch_live_bridge(self.app)
        return {"path": opened, "relative_path": relative_path, "scene": scene}

    @project_mutation(MutationPolicy.LAYOUT2)
    def method_refresh_scene2d_preview(self, scene_id: str) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        try:
            scene, preview_exists, message = scene2d.refresh_preview(project, scene_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        app_state.persist_project_mutation(self.app)
        return {"scene": scene, "preview_exists": preview_exists, "message": message}

    @project_mutation(MutationPolicy.LAYOUT2)
    def method_add_scene2d_to_references(self, scene_id: str) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        try:
            reference, scene = scene2d.add_to_references(project, scene_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        app_state.persist_project_mutation(self.app)
        app_state._touch_live_bridge(self.app)
        return {"reference": reference, "scene": scene, "project": app_state._project_payload(project, self.app.state.dirty)}

    def method_get_scene2d_preview(self, scene_id: str) -> dict[str, str]:
        project = app_state._require_project(self.app)
        try:
            return scene2d.preview_meta(project, scene_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    def method_list_scene2d_perspectives(self, scene_id: str) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        try:
            scene, perspectives = scene2d.list_perspectives(project, scene_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"scene": scene, "perspectives": perspectives}

    @project_mutation(MutationPolicy.LAYOUT2)
    def method_create_scene2d_perspective(self, scene_id: str, data: dict[str, Any]) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        try:
            scene, perspective, scenes = scene2d.create_perspective(
                project,
                scene_id,
                title=str(data.get("title") or ""),
                perspective_type=str(data.get("type") or "psd"),
                linked_scene3d_id=str(data.get("linked_scene3d_id") or ""),
                linked_scene3d_view=data.get("linked_scene3d_view") if isinstance(data.get("linked_scene3d_view"), dict) else None,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        app_state.persist_project_mutation(self.app)
        return {"scene": scene, "perspective": perspective, "scenes": scenes}

    @project_mutation(MutationPolicy.LAYOUT2)
    def method_duplicate_scene2d_perspective(self, scene_id: str, perspective_id: str) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        try:
            scene, perspective, scenes = scene2d.duplicate_perspective(project, scene_id, perspective_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        app_state.persist_project_mutation(self.app)
        return {"scene": scene, "perspective": perspective, "scenes": scenes}

    @project_mutation(MutationPolicy.LAYOUT2)
    def method_reorder_scene2d_perspectives(self, scene_id: str, perspective_ids: list[str]) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        try:
            scene, scenes = scene2d.reorder_perspectives(project, scene_id, perspective_ids)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        app_state.persist_project_mutation(self.app)
        return {"scene": scene, "scenes": scenes}

    @project_mutation(MutationPolicy.LAYOUT2)
    def method_import_scene2d_perspective(
        self,
        scene_id: str,
        filename: str,
        data: list[int] | bytes | bytearray,
        title: str = "",
        linked_scene3d_id: str = "",
    ) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        try:
            scene, perspective, scenes = scene2d.import_perspective(
                project,
                scene_id,
                str(filename or "perspective"),
                _normalize_upload_bytes(data),
                title=str(title or ""),
                linked_scene3d_id=str(linked_scene3d_id or ""),
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        app_state.persist_project_mutation(self.app)
        return {"scene": scene, "perspective": perspective, "scenes": scenes}

    @project_mutation(MutationPolicy.LAYOUT2)
    def method_update_scene2d_perspective(self, scene_id: str, perspective_id: str, data: dict[str, Any]) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        try:
            scene, perspective, scenes = scene2d.update_perspective(project, scene_id, perspective_id, data)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        app_state.persist_project_mutation(self.app)
        return {"scene": scene, "perspective": perspective, "scenes": scenes}

    @project_mutation(MutationPolicy.LAYOUT2)
    def method_delete_scene2d_perspective(self, scene_id: str, perspective_id: str) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        try:
            scene, scenes = scene2d.delete_perspective(project, scene_id, perspective_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        app_state.persist_project_mutation(self.app)
        return {"scene": scene, "scenes": scenes}

    @project_mutation(MutationPolicy.LAYOUT2)
    def method_open_scene2d_perspective(self, scene_id: str, perspective_id: str) -> dict[str, Any]:
        from . import runtime_state
        project = app_state._require_project(self.app)

        try:
            sc, _scenes = scene2d._find_scene(project, scene_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        try:
            perspective = scene2d._find_perspective(sc, perspective_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        if perspective.get("type") != "psd":
            raise HTTPException(status_code=400, detail="Only PSD Perspectives can be opened for editing.")

        source_rel = str(perspective.get("source_file_path") or "")
        if Path(source_rel).suffix.lower() != ".psd":
            raise HTTPException(status_code=400, detail="Perspective source must be a PSD.")
        try:
            source_path = project_manager.resolve_project_path(project, source_rel)
        except ValueError as exc:
            raise HTTPException(
                status_code=400, detail="Perspective source path is invalid."
            ) from exc

        if not source_path.is_file():
            raise HTTPException(status_code=400, detail=f"Source PSD not found: {source_rel}")
        opened = str(source_path)
        relative_path = source_rel

        # Set active work context before publishing bridge
        runtime_state.set_active_scene2d_context(
            self.app,
            scene_id,
            perspective_id,
            sc,
            perspective,
            source_native_path=str(source_path.resolve()).replace("\\", "/") if source_path else "",
        )

        # If plugin already has this PSD open, request focus; otherwise OS-open.
        # Use the authoritative shared helper so freshness between file and HTTP
        # heartbeats is respected: a newer explicit empty list is not overridden
        # by stale runtime state, and an unknown or cross-project key is ignored.
        work_key = f"scene2d:{scene_id}:{perspective_id}"
        _active_key, open_keys = app_state.plugin_work_key_state(self.app)
        if work_key in open_keys:
            runtime_state.request_work_context_focus(self.app, runtime_state.active_work_context(self.app))
        else:
            try:
                sc, opened, relative_path = scene2d.open_perspective(project, scene_id, perspective_id)
            except (FileNotFoundError, ValueError) as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            perspective = scene2d._find_perspective(sc, perspective_id)
            source_path = project_manager.resolve_project_path(project, relative_path)
            runtime_state.set_active_scene2d_context(
                self.app,
                scene_id,
                perspective_id,
                sc,
                perspective,
                source_native_path=str(source_path.resolve()).replace("\\", "/"),
            )

        app_state._touch_live_bridge(self.app)
        return {
            "path": opened,
            "relative_path": relative_path,
            "scene": scene2d._with_legacy_aliases(sc),
            "work_context": runtime_state.active_work_context(self.app),
        }

    @project_mutation(MutationPolicy.LAYOUT2)
    def method_plugin_scene2d_export_preview(
        self,
        scene_id: str,
        perspective_id: str,
        protocol: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._plugin_service().scene2d_export_preview(
            scene_id,
            perspective_id,
            protocol,
        )

    @project_mutation(MutationPolicy.LAYOUT2)
    def method_plugin_scene2d_psd_saved(
        self,
        scene_id: str,
        perspective_id: str,
        protocol: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._plugin_service().scene2d_psd_saved(
            scene_id,
            perspective_id,
            protocol,
        )

    @project_mutation(MutationPolicy.LAYOUT2)
    def method_plugin_scene2d_next_perspective(
        self,
        scene_id: str,
        perspective_id: str,
        protocol: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._plugin_service().scene2d_next_perspective(
            scene_id,
            perspective_id,
            protocol,
        )

    @project_mutation(MutationPolicy.LAYOUT2)
    def method_refresh_scene2d_perspective_preview(self, scene_id: str, perspective_id: str) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        try:
            scene, perspective, _scenes = scene2d.refresh_perspective_preview(project, scene_id, perspective_id)
            preview_exists = bool(
                project_manager.resolve_project_path(
                    project,
                    perspective["preview_image_path"],
                ).is_file()
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        app_state.persist_project_mutation(self.app)
        return {
            "scene": scene,
            "perspective": perspective,
            "preview_exists": preview_exists,
            "message": "Scene 2D preview refreshed." if preview_exists else "No Scene 2D preview exists yet.",
        }

    @project_mutation(MutationPolicy.LAYOUT2)
    def method_set_primary_scene2d_perspective(self, scene_id: str, perspective_id: str) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        try:
            scene, scenes = scene2d.set_primary_perspective(project, scene_id, perspective_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        app_state.persist_project_mutation(self.app)
        return {"scene": scene, "scenes": scenes}

    @project_mutation(MutationPolicy.LAYOUT2)
    def method_move_scene2d_perspective(self, scene_id: str, perspective_id: str, target_scene_id: str) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        try:
            source_scene, target_scene, perspective, scenes = scene2d.move_perspective(
                project,
                scene_id,
                perspective_id,
                target_scene_id,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        app_state.persist_project_mutation(self.app)
        return {
            "source_scene": source_scene,
            "target_scene": target_scene,
            "scene": target_scene,
            "perspective": perspective,
            "scenes": scenes,
        }

    @project_mutation(MutationPolicy.LAYOUT2)
    def method_add_scene2d_perspective_to_references(self, scene_id: str, perspective_id: str) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        try:
            reference, scene = scene2d.add_perspective_to_references(project, scene_id, perspective_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        app_state.persist_project_mutation(self.app)
        return {"reference": reference, "scene": scene, "project": app_state._project_payload(project, self.app.state.dirty)}

    def method_get_scene2d_perspective_preview(self, scene_id: str, perspective_id: str) -> dict[str, str]:
        project = app_state._require_project(self.app)
        try:
            return scene2d.perspective_preview_meta(project, scene_id, perspective_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
