"""Scene 3D endpoint orchestration and external Blender session adapters."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from . import app_state, blender_bridge, bpy_viewport, generation_service, project_manager, scene3d
from .errors import AppErrorCode, app_error
from .mutation_executor import MutationPolicy, project_mutation
from .upload_payload import normalize_upload_bytes as _normalize_upload_bytes

logger = logging.getLogger(__name__)


class Scene3DServiceMixin:
    @project_mutation(MutationPolicy.LAYOUT2)
    def method_open_blender_scene(self) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        existing = blender_bridge.status(self.app)
        if existing["external_blender_owned"]:
            opened = Path(str(existing["external_blender_blend_path"]))
            try:
                relative_path = project_manager.project_relative_posix(project, opened)
            except ValueError:
                relative_path = ""
            return {
                "path": str(opened),
                "relative_path": relative_path,
                "blender_bridge": existing,
                **app_state._project_payload(project, self.app.state.dirty),
            }
        manager = bpy_viewport.manager_for_app(self.app)
        try:
            bpy_viewport.require_current_context(self.app)
            manager.save_if_running()
            bpy_viewport.stop_worker(self.app)
            active_scene = scene3d.ensure_active_scene(project)
            attached = str(active_scene.get("blend_file_path") or "").strip()
            blend_path = (
                project_manager.resolve_project_path(project, attached)
                if attached
                else project_manager.ensure_project_blend_file(
                    project,
                    scene_id=str(active_scene["id"]),
                ).resolve()
            )
            active_scene = scene3d.configure_blend_preview(
                project,
                str(active_scene["id"]),
                blend_path,
            )
            app_state.persist_project_mutation(self.app)
            session = blender_bridge.begin_session(
                self.app,
                project,
                active_scene,
                blend_path,
            )
            bootstrap = (
                Path(__file__).resolve().parent
                / "blender_addon"
                / "register_storyboarder_addon.py"
            )
            launch_path = Path(session["launch_path"])
            launch_relative = project_manager.project_relative_posix(
                project, launch_path
            )
            opened = project_manager.open_blender_scene(
                project,
                launch_relative,
                python_script=bootstrap,
                script_args=[
                    "--storyboarder-bridge",
                    session["bridge_path"],
                    "--storyboarder-heartbeat",
                    session["heartbeat_path"],
                    "--storyboarder-session",
                    session["session_id"],
                ],
                on_launch=lambda process: blender_bridge.attach_process(self.app, process),
            )
        except (FileNotFoundError, ValueError) as exc:
            blender_bridge.cancel_session(self.app)
            logger.exception("Failed to open Blender scene")
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception:
            blender_bridge.cancel_session(self.app)
            raise
        app_state._touch_live_bridge(self.app)
        return {
            "path": str(opened),
            "relative_path": (
                project_manager.project_relative_posix(project, opened) if opened.exists() else ""
            ),
            "blender_bridge": blender_bridge.status(self.app),
            **app_state._project_payload(project, self.app.state.dirty),
        }

    def method_list_scene3d(self) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        return scene3d.list_scenes(project)

    @project_mutation(MutationPolicy.LAYOUT2)
    def method_create_scene3d(self, data: dict[str, Any]) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        try:
            payload = scene3d.create_scene(
                project,
                title=str(data.get("title") or ""),
                description=str(data.get("description") or ""),
                keywords=data.get("keywords") if isinstance(data.get("keywords"), list) else None,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        app_state.persist_project_mutation(self.app)
        return payload

    @project_mutation(MutationPolicy.LAYOUT2)
    def method_update_scene3d(self, scene3d_id: str, data: dict[str, Any]) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        try:
            before_scene = next(
                (item for item in scene3d.list_scenes(project).get("scenes", []) if item.get("id") == scene3d_id),
                None,
            )
            payload = scene3d.update_scene(project, scene3d_id, data)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        semantic_keys = {"title", "description", "keywords"}
        scene_changed = before_scene is None or any(
            key in data and before_scene.get(key) != payload["scene"].get(key)
            for key in semantic_keys
        )
        generation_service.mark_generated_shots_for_asset_keywords_stale(
            project,
            [
                *generation_service.semantic_asset_keywords(before_scene),
                *generation_service.semantic_asset_keywords(payload["scene"]),
            ],
        ) if scene_changed else []
        app_state.persist_project_mutation(self.app)
        return payload

    @project_mutation(MutationPolicy.LAYOUT2)
    def method_delete_scene3d(self, scene3d_id: str) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        try:
            blender_bridge.require_released(self.app, "deleting a Scene 3D")
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        try:
            payload = scene3d.delete_scene(project, scene3d_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        app_state.persist_project_mutation(self.app)
        return payload

    @project_mutation(MutationPolicy.LAYOUT2)
    def method_set_active_scene3d(self, scene3d_id: str) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        try:
            blender_bridge.require_released(self.app, "switching the active Scene 3D")
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        try:
            payload = scene3d.set_active(project, scene3d_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        app_state.persist_project_mutation(self.app)
        return payload

    @project_mutation(MutationPolicy.LAYOUT2)
    def method_import_scene3d_to_scene(self, scene3d_id: str, filename: str, data: list[int] | bytes | bytearray) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        try:
            blender_bridge.require_released(self.app, "replacing a Scene 3D asset")
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        try:
            before_scene = next(
                (item for item in scene3d.list_scenes(project).get("scenes", []) if item.get("id") == scene3d_id),
                None,
            )
            payload = scene3d.import_scene_file(project, scene3d_id, str(filename or "scene.glb"), _normalize_upload_bytes(data))
        except (FileNotFoundError, ValueError) as exc:
            logger.exception("Failed to import Scene3D file: %s", filename)
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        generation_service.mark_generated_shots_for_asset_keywords_stale(
            project,
            [
                *generation_service.semantic_asset_keywords(before_scene),
                *generation_service.semantic_asset_keywords(payload["scene"]),
            ],
        )
        app_state.persist_project_mutation(self.app)
        return payload

    def method_get_scene3d_file(self, scene3d_id: str | None = None) -> dict[str, str]:
        project = app_state._require_project(self.app)
        try:
            path = scene3d.file_path(project, scene3d_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if path is None:
            raise app_error(AppErrorCode.MEDIA_NOT_FOUND, "No Scene 3D file linked.", status=404)
        return {"path": str(path), "media_type": "model/gltf-binary", "filename": path.name}

    @project_mutation(MutationPolicy.LAYOUT2)
    def method_import_scene3d(self, filename: str, data: list[int] | bytes | bytearray) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        try:
            blender_bridge.require_released(self.app, "replacing the active Scene 3D asset")
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        try:
            scene_payload = scene3d.import_active_scene_file(project, str(filename or "scene.glb"), _normalize_upload_bytes(data))
        except (FileNotFoundError, ValueError) as exc:
            logger.exception("Failed to import Scene3D file: %s", filename)
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        app_state.persist_project_mutation(self.app)
        app_state._touch_live_bridge(self.app)
        payload = app_state._project_payload(project, self.app.state.dirty)
        return {"scene3d": project.settings.get("scene3d") or {}, "scenes3d": scene_payload, **payload}
