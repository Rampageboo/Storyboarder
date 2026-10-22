"""Comfy Cloud connection settings and per-board video takes."""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from . import app_state, comfy_cloud
from .mutation_executor import MutationPolicy, project_mutation


def _user_error(exc: comfy_cloud.ComfyCloudError, status: int = 400) -> HTTPException:
    return HTTPException(status_code=status, detail=str(exc))


class VideoServiceMixin:
    def method_comfy_cloud_status(self) -> dict[str, Any]:
        return comfy_cloud.status()

    def method_set_comfy_cloud_key(self, api_key: str) -> dict[str, Any]:
        try:
            comfy_cloud.set_api_key(api_key)
        except comfy_cloud.ComfyCloudError as exc:
            raise _user_error(exc) from exc
        return comfy_cloud.status()

    def method_clear_comfy_cloud_key(self) -> dict[str, Any]:
        comfy_cloud.clear_api_key()
        return comfy_cloud.status()

    def method_check_comfy_cloud(self) -> dict[str, Any]:
        try:
            return comfy_cloud.check_connection()
        except comfy_cloud.ComfyCloudError as exc:
            raise _user_error(exc, 502) from exc

    def method_video_prompt_draft(self, shot_id: str) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        shot = app_state._find_shot(project, shot_id)
        return {
            "prompt": comfy_cloud.compile_video_prompt(shot),
            "negative_prompt": comfy_cloud.DEFAULT_NEGATIVE,
            "seconds": round(comfy_cloud.frame_count(shot.duration_seconds) / comfy_cloud.FPS, 3),
        }

    def method_list_video_takes(self, shot_id: str) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        app_state._find_shot(project, shot_id)
        return {"takes": comfy_cloud.list_takes(self.app, project, shot_id), **comfy_cloud.status()}

    @project_mutation(MutationPolicy.SERIALIZED)
    def method_create_video_take(self, shot_id: str, data: dict[str, Any]) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        shot = app_state._find_shot(project, shot_id)
        try:
            take = comfy_cloud.create_take(
                self.app,
                project,
                shot,
                prompt=str(data.get("prompt") or ""),
                negative=str(data.get("negative_prompt") or ""),
                seconds=float(data.get("seconds") or shot.duration_seconds or 3.0),
            )
        except comfy_cloud.ComfyCloudError as exc:
            raise _user_error(exc) from exc
        return {"take": take}

    @project_mutation(MutationPolicy.SERIALIZED)
    def method_delete_video_take(self, take_id: str) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        try:
            comfy_cloud.delete_take(project, take_id)
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=404, detail="Video take not found.") from exc
        except comfy_cloud.ComfyCloudError as exc:
            raise _user_error(exc, 409) from exc
        return {"deleted": take_id}

    def method_video_take_file(self, take_id: str) -> dict[str, str]:
        project = app_state._require_project(self.app)
        try:
            path = comfy_cloud.video_file(project, take_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Video take not found.") from exc
        except (comfy_cloud.ComfyCloudError, ValueError) as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if not path.is_file():
            raise HTTPException(status_code=404, detail="The video file is missing on disk.")
        return {"path": str(path), "media_type": "video/mp4"}
