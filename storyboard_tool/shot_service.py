"""Canonical shot domain module.

All shot business logic lives here.  No FastAPI or HTTP concerns — errors
are raised as ``ValueError`` so callers at the HTTP layer can convert them
to the appropriate status codes.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from . import project_manager
from .models import (
    SHOT_STATUSES,
    Project,
    Shot,
    default_generation_state,
    normalize_continuity,
    normalize_prompt_config,
    normalize_shot_design,
)


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
    duplicate = project_manager.duplicate_shot(project, find_shot_index(project, shot_id))
    # Authored intent is useful on a duplicate, but observed/canonical continuity
    # and generation identities belong to the source output and must not leak.
    duplicate.continuity["observed_out"] = ""
    duplicate.continuity["resolved_out"] = ""
    duplicate.generation_state = default_generation_state()
    return duplicate


def delete_shot(project: Project, shot_id: str) -> Shot:
    return project_manager.delete_shot(project, find_shot_index(project, shot_id))


def reorder_shots(project: Project, shot_ids: list[str]) -> None:
    project_manager.reorder_shots(project, [str(item) for item in shot_ids])


def update_shot(shot: Shot, data: dict[str, Any]) -> None:
    if not isinstance(data, dict):
        return
    prior_generation_inputs = _generation_input_snapshot(shot)
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
    if "shot_design" in data and isinstance(data.get("shot_design"), dict):
        shot.shot_design = normalize_shot_design(data["shot_design"])
    if "prompt_config" in data and isinstance(data.get("prompt_config"), dict):
        shot.prompt_config = normalize_prompt_config(data["prompt_config"])
    if "continuity" in data and isinstance(data.get("continuity"), dict):
        shot.continuity = normalize_continuity(data["continuity"])
    if (
        prior_generation_inputs != _generation_input_snapshot(shot)
        and _has_generation_activity(shot)
    ):
        shot.generation_state["freshness_status"] = "stale"


def update_shot_duration(shot: Shot, seconds: float) -> None:
    shot.duration_seconds = max(0.1, float(seconds))


def normalize_shot_payload(shot: Shot, data: dict[str, Any]) -> None:
    update_shot(shot, data)


def _has_generation_activity(shot: Shot) -> bool:
    state = shot.generation_state
    return bool(
        state.get("latest_attempt_id")
        or state.get("active_output_id")
        or state.get("approved_output_id")
        or state.get("execution_status") in {"queued", "running", "succeeded", "failed"}
    )


def _generation_input_snapshot(shot: Shot) -> dict[str, Any]:
    continuity = shot.continuity
    return deepcopy({
        "description": shot.description,
        "action_note": shot.action_note,
        "camera_note": shot.camera_note,
        "character_note": shot.character_note,
        "dialogue": shot.dialogue,
        "lighting_note": shot.lighting_note,
        "transition_note": shot.transition_note,
        "camera_data": shot.camera_data,
        "shot_design": shot.shot_design,
        "prompt_config": shot.prompt_config,
        "continuity": {
            "mode": continuity.get("mode"),
            "depends_on_shot_ids": continuity.get("depends_on_shot_ids"),
            "primary_continuity_source_shot_id": continuity.get("primary_continuity_source_shot_id"),
            "expected_in": continuity.get("expected_in"),
            "expected_out": continuity.get("expected_out"),
            "preserve": continuity.get("preserve"),
            "intentional_changes": continuity.get("intentional_changes"),
        },
    })
