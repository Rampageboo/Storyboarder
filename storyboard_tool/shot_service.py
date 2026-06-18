"""Canonical shot domain module.

All shot business logic lives here.  No FastAPI or HTTP concerns — errors
are raised as ``ValueError`` so callers at the HTTP layer can convert them
to the appropriate status codes.
"""

from __future__ import annotations

from typing import Any

from . import project_manager
from .models import SHOT_STATUSES, Project, Shot


def find_shot_index(project: Project, shot_id: str) -> int:
    for index, shot in enumerate(project.shots):
        if shot.shot_id == shot_id:
            return index
    raise ValueError(f"Shot not found: {shot_id}")


def find_shot(project: Project, shot_id: str) -> Shot:
    return project.shots[find_shot_index(project, shot_id)]


def create_shot(project: Project, after_shot_id: str | None = None) -> Shot:
    after_index: int | None = None
    if after_shot_id:
        after_index = find_shot_index(project, after_shot_id)
    return project_manager.add_shot(project, after_index=after_index)


def duplicate_shot(project: Project, shot_id: str) -> Shot:
    return project_manager.duplicate_shot(project, find_shot_index(project, shot_id))


def delete_shot(project: Project, shot_id: str) -> Shot:
    return project_manager.delete_shot(project, find_shot_index(project, shot_id))


def reorder_shots(project: Project, shot_ids: list[str]) -> None:
    project_manager.reorder_shots(project, [str(item) for item in shot_ids])


def update_shot(shot: Shot, data: dict[str, Any]) -> None:
    if not isinstance(data, dict):
        return
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
    shot.camera_data = (
        data.get("camera_data")
        if isinstance(data.get("camera_data"), dict)
        else shot.camera_data
    )
    tags = data.get("tags")
    shot.tags = (
        [str(tag).strip() for tag in tags if str(tag).strip()]
        if isinstance(tags, list)
        else shot.tags
    )
    status = str(data.get("status", shot.status))
    shot.status = status if status in SHOT_STATUSES else "Draft"


def update_shot_duration(shot: Shot, seconds: float) -> None:
    shot.duration_seconds = max(0.1, float(seconds))


def normalize_shot_payload(shot: Shot, data: dict[str, Any]) -> None:
    update_shot(shot, data)
