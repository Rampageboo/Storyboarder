"""Comfy Cloud image jobs: generate candidate board images and apply one."""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from . import app_state, comfy_cloud, comfy_images, project_manager
from .mutation_executor import MutationPolicy, project_mutation


def _job_not_found(exc: Exception) -> HTTPException:
    return HTTPException(status_code=404, detail="Image job not found.")


class ImageJobServiceMixin:
    def method_list_image_jobs(self, shot_id: str | None = None) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        if shot_id is not None:
            app_state._find_shot(project, shot_id)
        return {"jobs": comfy_images.list_jobs(self.app, project, shot_id), **comfy_cloud.status()}

    @project_mutation(MutationPolicy.SERIALIZED)
    def method_create_image_job(self, shot_id: str, data: dict[str, Any]) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        shot = app_state._find_shot(project, shot_id)
        seed = data.get("seed")
        try:
            job = comfy_images.create_job(
                self.app,
                project,
                shot,
                prompt=str(data.get("prompt") or ""),
                negative=str(data.get("negative_prompt") or ""),
                references=list(data.get("references") or []),
                seed=int(seed) if seed is not None else None,
                apply=bool(data.get("apply")),
            )
        except comfy_cloud.ComfyCloudError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"job": job}

    @project_mutation(MutationPolicy.SERIALIZED)
    def method_apply_image_job(self, job_id: str, index: int = 0) -> dict[str, Any]:
        """Put one output on its board through the user image-import path."""
        project = app_state._require_project(self.app)
        try:
            record = comfy_images.read_job(project, job_id)
            source = comfy_images.output_file(project, job_id, int(index))
        except (FileNotFoundError, ValueError) as exc:
            raise _job_not_found(exc) from exc
        except comfy_cloud.ComfyCloudError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if not source.is_file():
            raise HTTPException(status_code=404, detail="The generated image is missing on disk.")
        shot = app_state._find_shot(project, str(record.get("shot_id") or ""))
        try:
            project_manager.import_image_for_shot(project, shot, source)
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        app_state.persist_project_mutation(self.app)
        job = comfy_images.mark_applied(project, job_id, int(index))
        return {"job": job, **app_state._project_payload(project)}

    @project_mutation(MutationPolicy.SERIALIZED)
    def method_delete_image_job(self, job_id: str) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        try:
            comfy_images.delete_job(project, job_id)
        except (FileNotFoundError, ValueError) as exc:
            raise _job_not_found(exc) from exc
        except comfy_cloud.ComfyCloudError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"deleted": job_id}

    def method_image_job_output_file(self, job_id: str, index: int) -> dict[str, str]:
        project = app_state._require_project(self.app)
        try:
            path = comfy_images.output_file(project, job_id, int(index))
        except (FileNotFoundError, ValueError) as exc:
            raise _job_not_found(exc) from exc
        except comfy_cloud.ComfyCloudError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if not path.is_file():
            raise HTTPException(status_code=404, detail="The generated image is missing on disk.")
        return {"path": str(path), "media_type": "image/png"}
