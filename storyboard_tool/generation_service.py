"""Generation request snapshots and Codex handoff storage.

Storyboarder owns request state.  External generators receive immutable request
snapshots and may only deposit result manifests/artifacts in the generation
inbox.  The desktop backend explicitly reconciles those results into shot
generation state, keeping external processes away from ``shots.json``.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from PIL import Image

from . import shot_assets
from .models import Project, Shot
from .project_layout import (
    ProjectPathError,
    project_relative_posix,
    resolve_project_child,
)
from .project_storage import atomic_write_json
from .shot_files import resolve_project_relative_path

SCHEMA_VERSION = 1
DESTINATIONS = frozenset({"queue", "codex"})
PROVIDERS = frozenset({"codex", "stable_diffusion"})
MODES = frozenset({"draft", "clean", "final"})
REQUEST_STATUSES = frozenset({"queued", "needs-review", "completed", "failed", "cancelled"})
IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp"})
MAX_ARTIFACTS = 8
MAX_ARTIFACT_BYTES = 64 * 1024 * 1024
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,96}$")

# Generation precision strategy per mode. `backend`/`provider` decides WHO executes;
# `mode` decides the quality/speed strategy. The numeric values below are starting
# defaults chosen within Owner-specified ranges; they are advisory guidance emitted
# in the request payload for whoever operates Stable Diffusion, not engine constraints.
_MODE_PROFILES: dict[str, dict[str, Any]] = {
    "draft": {
        "max_edge": 768,
        "steps": 12,
        "cfg_scale": 5.0,
        "upscale_to_panel": True,
        "overwrite_final": False,
        "use_prior_frame_as_reference": False,
        "style_hint": "rough storyboard, grayscale, loose sketch; prioritize composition, camera, and staging",
    },
    "clean": {
        "max_edge": 1024,
        "steps": 22,
        "cfg_scale": 6.5,
        "upscale_to_panel": True,
        "overwrite_final": False,
        "use_prior_frame_as_reference": True,
        "style_hint": "clean storyboard line art, readable silhouettes, clear staging",
    },
    "final": {
        # max_edge 0 = generate at full panel size (or higher via upscale).
        "max_edge": 0,
        "steps": 32,
        "cfg_scale": 7.0,
        "upscale_to_panel": True,
        "overwrite_final": True,
        "use_prior_frame_as_reference": True,
        "style_hint": "finished frame with lighting, materials, and character detail",
    },
}

# Default mode when a request does not pass one explicitly: driven by shot status.
_STATUS_MODE_DEFAULTS = {
    "draft": "draft",
    "in progress": "clean",
    "review": "clean",
    "approved": "final",
    "final": "final",
}


def _default_mode_for_status(status: str) -> str:
    return _STATUS_MODE_DEFAULTS.get(str(status or "").strip().lower(), "draft")


def _scaled_target(canvas_width: int, canvas_height: int, max_edge: int) -> tuple[int, int]:
    """Scale a panel down so its longest edge is at most ``max_edge`` (never upscales)."""
    longest = max(int(canvas_width), int(canvas_height))
    if max_edge <= 0 or longest <= max_edge:
        return int(canvas_width), int(canvas_height)
    scale = max_edge / longest
    return max(1, round(canvas_width * scale)), max(1, round(canvas_height * scale))


def _build_generation_plan(mode: str, canvas_width: int, canvas_height: int) -> dict[str, Any]:
    profile = _MODE_PROFILES[mode]
    target_width, target_height = _scaled_target(canvas_width, canvas_height, profile["max_edge"])
    return {
        "mode": mode,
        "target_width": target_width,
        "target_height": target_height,
        "panel_width": int(canvas_width),
        "panel_height": int(canvas_height),
        "steps": profile["steps"],
        "cfg_scale": profile["cfg_scale"],
        "style_hint": profile["style_hint"],
        "use_prior_frame_as_reference": profile["use_prior_frame_as_reference"],
        "output_policy": {
            "preserve_aspect_ratio": True,
            "upscale_to_panel": profile["upscale_to_panel"],
            "overwrite_final": profile["overwrite_final"],
        },
    }


def _prior_frame_ref(project: Project, path: Path | None) -> dict[str, Any] | None:
    """Describe an existing accepted Codex layer for use as an img2img base."""
    if path is None:
        return None
    try:
        rel = project_relative_posix(project, path)
    except ProjectPathError:
        rel = ""
    return {
        "source": "codex-layer",
        "project_relative_path": rel,
        "absolute_path": str(path.resolve()),
        "exists": path.is_file(),
    }


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _generation_root(project: Project) -> Path:
    return resolve_project_child(project, "generation")


def _requests_dir(project: Project) -> Path:
    return resolve_project_child(project, "generation", "requests")


def _results_dir(project: Project) -> Path:
    return resolve_project_child(project, "generation", "results")


def _state_dir(project: Project) -> Path:
    return resolve_project_child(project, "generation", "state")


def _candidates_dir(project: Project) -> Path:
    return resolve_project_child(project, "generation", "candidates")


def _validate_id(value: str, label: str) -> str:
    cleaned = str(value or "").strip()
    if not _ID_RE.fullmatch(cleaned):
        raise ValueError(f"Invalid {label}.")
    return cleaned


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid generation data: {path.name}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"Invalid generation data: {path.name}")
    return value


def _request_path(project: Project, request_id: str) -> Path:
    return resolve_project_child(
        project,
        "generation",
        "requests",
        f"{_validate_id(request_id, 'request id')}.json",
    )


def _state_path(project: Project, request_id: str) -> Path:
    return resolve_project_child(
        project,
        "generation",
        "state",
        f"{_validate_id(request_id, 'request id')}.json",
    )


def _apply_request_state(project: Project, request: dict[str, Any]) -> dict[str, Any]:
    request_id = str(request.get("request_id") or "")
    state_path = _state_path(project, request_id)
    if state_path.is_file():
        try:
            state = _read_json_object(state_path)
        except ValueError:
            state = {}
        status = str(state.get("status") or "")
        if status in REQUEST_STATUSES:
            request["status"] = status
        if state.get("updated_at"):
            request["updated_at"] = str(state["updated_at"])
    return request


def _canonical_hash(value: dict[str, Any]) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def has_generation_activity(shot: Shot) -> bool:
    state = shot.generation_state
    return bool(
        state.get("latest_attempt_id")
        or state.get("active_output_id")
        or state.get("approved_output_id")
        or state.get("execution_status") in {"queued", "running", "succeeded", "failed"}
    )


def mark_all_generated_shots_stale(project: Project) -> list[str]:
    """Character Bible changes affect every shot that already has generation activity."""
    updated: list[str] = []
    for shot in project.shots:
        if has_generation_activity(shot):
            shot.generation_state["freshness_status"] = "stale"
            updated.append(shot.shot_id)
    return updated


def _append_prompt_line(lines: list[str], label: str, value: Any) -> None:
    if isinstance(value, list):
        text = "; ".join(str(item).strip() for item in value if str(item).strip())
    else:
        text = str(value or "").strip()
    if text:
        lines.append(f"{label}: {text}")


def _compile_shot_override(shot: Shot) -> str:
    """Compile only the per-shot layer; scene and identity live above it."""
    design = shot.shot_design
    continuity = shot.continuity
    lines: list[str] = []
    _append_prompt_line(lines, "Scene", shot.scene)
    story_and_action = str(design.get("story_beat") or shot.description or "").strip()
    action_note = str(shot.action_note or "").strip()
    _append_prompt_line(lines, "Story beat", story_and_action)
    if action_note and action_note.casefold() not in story_and_action.casefold():
        _append_prompt_line(lines, "Action", action_note)
    _append_prompt_line(lines, "Camera note", shot.camera_note)
    _append_prompt_line(lines, "Shot size", design.get("shot_size"))
    camera = ", ".join(
        str(design.get(key) or "").strip()
        for key in ("camera_position", "camera_height", "camera_angle", "camera_direction")
        if str(design.get(key) or "").strip()
    )
    _append_prompt_line(lines, "Camera", camera)
    _append_prompt_line(lines, "Camera movement", design.get("camera_movement"))
    _append_prompt_line(lines, "Lens / FOV intent", design.get("lens_intent"))
    _append_prompt_line(lines, "Subject movement", design.get("subject_movement"))
    _append_prompt_line(lines, "Composition", design.get("composition"))
    _append_prompt_line(lines, "Focal point", design.get("focal_point"))
    _append_prompt_line(lines, "Foreground", design.get("foreground"))
    _append_prompt_line(lines, "Midground", design.get("midground"))
    _append_prompt_line(lines, "Background", design.get("background"))
    _append_prompt_line(lines, "Characters", shot.character_note)
    _append_prompt_line(lines, "Dialogue", shot.dialogue)
    if shot.status != "Draft":
        _append_prompt_line(lines, "Lighting", shot.lighting_note)
    _append_prompt_line(lines, "Axis of action", design.get("axis_of_action"))
    if design.get("intentional_axis_crossing"):
        lines.append("Axis crossing: intentional")
    _append_prompt_line(lines, "Continuity in", continuity.get("expected_in"))
    _append_prompt_line(lines, "Continuity out", continuity.get("expected_out"))
    _append_prompt_line(lines, "Preserve", continuity.get("preserve"))
    _append_prompt_line(lines, "Intentional changes", continuity.get("intentional_changes"))
    return "\n".join(lines) or "Create a storyboard frame for this shot."


def compile_prompt(
    shot: Shot,
    *,
    scene_bible: dict[str, Any] | None = None,
    character_bible_prompt: str = "",
    keyword_assets: list[dict[str, Any]] | None = None,
) -> str:
    """Compile ordinary storyboard fields into generation instructions."""
    shot_override = _compile_shot_override(shot)
    draft_mode = shot.status == "Draft"
    character_prompt = str(character_bible_prompt or "").strip()
    scene_context = scene_bible or {}
    scene_lines: list[str] = []
    _append_prompt_line(scene_lines, "Scene", scene_context.get("title") or shot.scene)
    _append_prompt_line(scene_lines, "Location", scene_context.get("location"))
    _append_prompt_line(scene_lines, "Time of day", scene_context.get("time_of_day"))
    _append_prompt_line(scene_lines, "Setting", scene_context.get("environment_prompt"))
    _append_prompt_line(scene_lines, "Fixed scene details", scene_context.get("consistency_anchors"))
    _append_prompt_line(scene_lines, "Scene context", scene_context.get("description"))
    relevant_assets = keyword_assets or []
    draft_instruction = (
        "DRAFT STORYBOARD MODE â€” render a simple monochrome line drawing only. Prioritize framing, camera, "
        "action, silhouette, and spatial relationships. Do not create a polished style frame, concept art, color "
        "rendering, materials, textures, or cinematic lighting. Ignore lighting direction and mood."
    )
    if not character_prompt and not scene_context and not relevant_assets:
        return f"{draft_instruction}\n\n{shot_override}" if draft_mode else shot_override

    sections: list[str] = []
    if draft_mode:
        sections.append(draft_instruction)
    if scene_lines:
        sections.append("SCENE — keep these facts consistent across its shots.\n" + "\n".join(scene_lines))
    if character_prompt:
        sections.append(
            "CHARACTER BIBLE — preserve identity and wardrobe exactly; render only characters named in the shot.\n"
            f"Character identities: {character_prompt}"
        )
    if relevant_assets:
        asset_lines = []
        for asset in relevant_assets:
            paths = [
                str(asset.get("blend_file_path") or "").strip(),
                str(asset.get("file_path") or "").strip(),
            ]
            path_text = "; ".join(path for path in paths if path)
            matched = ", ".join(str(item) for item in asset.get("matched_keywords") or [])
            asset_lines.append(
                f"- {asset.get('title') or asset.get('scene3d_id')}: matched {matched}; inspect {path_text}"
            )
        sections.append(
            "RELEVANT 3D ASSETS — inspect these project files before generating; use them for environment, "
            "layout, proportions, and camera context.\n" + "\n".join(asset_lines)
        )
    sections.append(
        "SHOT OVERRIDE — change framing, camera, action, expression, and staging only.\n"
        f"{shot_override}"
    )
    sections.append(
        "CONSISTENCY RULES — do not redesign the location, move locked fixtures, change character identity, "
        "or introduce unrequested people. A shot-level background note may describe what is visible from this angle, "
        "and must stay consistent with the named scene."
    )
    return "\n\n".join(sections)


def _keyword_is_present(text: str, keyword: str) -> bool:
    cleaned = str(keyword or "").strip()
    if not cleaned:
        return False
    if re.fullmatch(r"[A-Za-z0-9_ -]+", cleaned):
        return re.search(rf"(?<![A-Za-z0-9_]){re.escape(cleaned)}(?![A-Za-z0-9_])", text, re.IGNORECASE) is not None
    return cleaned.casefold() in text.casefold()


def semantic_asset_keywords(asset: dict[str, Any] | None) -> list[str]:
    asset = asset or {}
    file_path = str(asset.get("file_path") or "").strip()
    blend_file_path = str(asset.get("blend_file_path") or "").strip()
    candidates = [
        *(asset.get("keywords") or []),
        asset.get("title") or "",
        Path(file_path).stem if file_path else "",
        Path(blend_file_path).stem if blend_file_path else "",
    ]
    result: list[str] = []
    seen: set[str] = set()
    for raw in candidates:
        keyword = str(raw or "").strip()
        folded = keyword.casefold()
        if not keyword or folded in seen:
            continue
        seen.add(folded)
        result.append(keyword)
    return result


def mark_generated_shots_for_asset_keywords_stale(project: Project, keywords: list[str]) -> list[str]:
    cleaned = semantic_asset_keywords({"keywords": keywords})
    updated: list[str] = []
    for shot in project.shots:
        if not has_generation_activity(shot):
            continue
        search_text = "\n".join([shot.title, _compile_shot_override(shot), "; ".join(shot.tags)])
        if any(_keyword_is_present(search_text, keyword) for keyword in cleaned):
            shot.generation_state["freshness_status"] = "stale"
            updated.append(shot.shot_id)
    return updated


def _keyword_asset_snapshot(
    project: Project,
    shot: Shot,
    scene_context: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    from . import scene3d

    search_text = "\n".join([
        shot.title,
        _compile_shot_override(shot),
        "; ".join(shot.tags),
        json.dumps(scene_context or {}, ensure_ascii=False, sort_keys=True),
    ])
    result: list[dict[str, Any]] = []
    for asset in scene3d.list_scenes(project).get("scenes", []):
        file_path = str(asset.get("file_path") or "").strip()
        blend_file_path = str(asset.get("blend_file_path") or "").strip()
        if not file_path and not blend_file_path:
            continue
        keywords = semantic_asset_keywords(asset)
        matched = [keyword for keyword in keywords if _keyword_is_present(search_text, keyword)]
        if not matched:
            continue
        file_resolved = resolve_project_relative_path(project, file_path) if file_path else None
        blend_resolved = resolve_project_relative_path(project, blend_file_path) if blend_file_path else None
        result.append({
            "scene3d_id": str(asset.get("id") or ""),
            "title": str(asset.get("title") or ""),
            "description": str(asset.get("description") or ""),
            "matched_keywords": matched,
            "file_path": file_path,
            "absolute_path": str(file_resolved) if file_resolved else "",
            "file_exists": bool(file_resolved and file_resolved.is_file()),
            "blend_file_path": blend_file_path,
            "blend_absolute_path": str(blend_resolved) if blend_resolved else "",
            "blend_file_exists": bool(blend_resolved and blend_resolved.is_file()),
        })
    return result


def _reference_snapshot(
    project: Project,
    shot: Shot,
    scene_bible: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    raw_paths: list[tuple[str, str]] = [(path, "shot-reference") for path in shot.reference_image_paths]
    if scene_bible:
        scene_reference = str(
            scene_bible.get("primary_reference_path") or scene_bible.get("preview_image_path") or ""
        ).strip()
        if scene_reference:
            raw_paths.insert(0, (scene_reference, "scene-environment"))
    for binding in shot.prompt_config.get("reference_bindings", []):
        if not isinstance(binding, dict):
            continue
        path = binding.get("path") or binding.get("relative_path") or binding.get("reference_path")
        if path:
            raw_paths.append((str(path), str(binding.get("role") or "prompt-binding")))

    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for raw_path, role in raw_paths:
        cleaned = str(raw_path or "").strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        try:
            resolved = resolve_project_relative_path(project, cleaned)
            inside_project = True
        except ValueError:
            resolved = Path(cleaned).expanduser().resolve()
            inside_project = False
        result.append({
            "role": role,
            "project_relative_path": cleaned if inside_project else "",
            "absolute_path": str(resolved),
            "exists": resolved.is_file(),
            "media_type": resolved.suffix.lower().lstrip("."),
        })
    return result


def _continuity_context(project: Project, shot: Shot) -> list[dict[str, Any]]:
    wanted = list(shot.continuity.get("depends_on_shot_ids", []))
    primary = str(shot.continuity.get("primary_continuity_source_shot_id") or "").strip()
    if primary and primary not in wanted:
        wanted.insert(0, primary)
    by_id = {candidate.shot_id: candidate for candidate in project.shots}
    context: list[dict[str, Any]] = []
    for shot_id in wanted:
        candidate = by_id.get(str(shot_id))
        if candidate is None:
            continue
        context.append({
            "shot_id": candidate.shot_id,
            "title": candidate.title,
            "description": candidate.description,
            "resolved_out": candidate.continuity.get("resolved_out", ""),
            "expected_out": candidate.continuity.get("expected_out", ""),
            "approved_output_id": candidate.generation_state.get("approved_output_id", ""),
        })
    return context


def build_request_snapshot(
    project: Project,
    shot: Shot,
    destination: str,
    *,
    provider: str = "codex",
    mode: str = "",
    clear_queue_on_result: bool = True,
) -> dict[str, Any]:
    destination = str(destination or "").strip().lower()
    if destination not in DESTINATIONS:
        raise ValueError("Destination must be 'queue' or 'codex'.")
    provider = str(provider or "").strip().lower()
    if provider not in PROVIDERS:
        raise ValueError("Provider must be 'codex' or 'stable_diffusion'.")
    mode = str(mode or "").strip().lower() or _default_mode_for_status(shot.status)
    if mode not in MODES:
        raise ValueError("Mode must be 'draft', 'clean', or 'final'.")
    shot_number = next(
        (index + 1 for index, candidate in enumerate(project.shots) if candidate.shot_id == shot.shot_id),
        0,
    )
    if shot_number == 0:
        raise ValueError("Shot not found in project.")
    created_at = _utc_now()
    request_id = _new_id("gen")
    canvas_width = int(project.settings.get("canvas_width") or 1920)
    canvas_height = int(project.settings.get("canvas_height") or 1080)
    scene_context = None
    if shot.scene_id:
        from . import scene2d

        scene_context = next(
            (scene for scene in scene2d.list_scenes(project) if scene.get("id") == shot.scene_id),
            None,
        )
    character_bible_prompt = str(project.settings.get("character_bible_prompt") or "").strip()
    character_bible = {"prompt": character_bible_prompt}
    keyword_assets = _keyword_asset_snapshot(project, shot, scene_context)
    authored = {
        "shot_id": shot.shot_id,
        "title": shot.title,
        "scene": shot.scene,
        "scene_id": shot.scene_id,
        "sequence": shot.sequence,
        "description": shot.description,
        "action_note": shot.action_note,
        "camera_note": shot.camera_note,
        "character_note": shot.character_note,
        "dialogue": shot.dialogue,
        "lighting_note": shot.lighting_note,
        "transition_note": shot.transition_note,
        "duration_seconds": shot.duration_seconds,
        "tags": list(shot.tags),
        "shot_design": dict(shot.shot_design),
    }
    input_snapshot = {
        "shot": authored,
        "scene_bible": None,
        "scene_context": scene_context,
        "character_bible": character_bible,
        "prompt_config": dict(shot.prompt_config),
        "continuity": dict(shot.continuity),
        "references": _reference_snapshot(project, shot, scene_context),
        "keyword_assets": keyword_assets,
        "continuity_context": _continuity_context(project, shot),
        "canvas": {"width": canvas_width, "height": canvas_height},
    }
    generation_plan = _build_generation_plan(mode, canvas_width, canvas_height)
    generation_plan["prior_frame"] = (
        _prior_frame_ref(project, shot_assets.get_shot_codex_layer_path(project, shot))
        if generation_plan["use_prior_frame_as_reference"]
        else None
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "request_id": request_id,
        "project_name": project.name,
        "project_root": str(project.project_root.resolve()),
        "shot_id": shot.shot_id,
        "shot_number": shot_number,
        "destination": destination,
        "provider": provider,
        "mode": mode,
        "execution_constraints": {
            "required_backend": provider,
            "backend_is_mandatory": True,
            "forbid_alternative_image_generators": provider == "stable_diffusion",
        },
        "clear_queue_on_result": bool(clear_queue_on_result),
        "generation_plan": generation_plan,
        "status": "queued",
        "created_at": created_at,
        "updated_at": created_at,
        "input_revision": _canonical_hash(input_snapshot),
        "consistency_revision": _canonical_hash({
            "scene": scene_context or {"title": shot.scene},
            "character_bible": character_bible,
        }),
        **input_snapshot,
        "prompt": {
            "mode": "auto",
            "compiled_prompt": compile_prompt(
                shot,
                scene_bible=scene_context,
                character_bible_prompt=character_bible_prompt,
                keyword_assets=keyword_assets,
            ),
            "layers": {
                "scene": str((scene_context or {}).get("title") or shot.scene or ""),
                "scene_context": scene_context or {},
                "characters": character_bible_prompt,
                "shot": _compile_shot_override(shot),
            },
            "negative_prompt": "",
            "style_profile_id": str(shot.prompt_config.get("style_profile_id") or ""),
            "aspect_ratio": str(shot.prompt_config.get("aspect_ratio_override") or f"{canvas_width}:{canvas_height}"),
            "variant_count": int(shot.prompt_config.get("variant_count") or 1),
        },
        "output_contract": {
            "kind": "storyboard-image",
            "width": canvas_width,
            "height": canvas_height,
            "accepted_formats": ["png", "jpg", "jpeg", "webp"],
            "review_required": True,
        },
    }


def create_request(
    project: Project,
    shot: Shot,
    destination: str,
    *,
    provider: str = "codex",
    mode: str = "",
    clear_queue_on_result: bool = True,
) -> dict[str, Any]:
    request = build_request_snapshot(
        project,
        shot,
        destination,
        provider=provider,
        mode=mode,
        clear_queue_on_result=clear_queue_on_result,
    )
    if request["destination"] == "queue":
        queued = [
            row for row in list_requests(project, shot_id=shot.shot_id, destination="queue")
            if row.get("status") == "queued"
        ]
        if queued:
            request["request_id"] = str(queued[0]["request_id"])
    atomic_write_json(_request_path(project, request["request_id"]), request)
    return request


def clear_pending_queue_requests(project: Project, shot_id: str) -> list[str]:
    """Remove a shot's pending (queued) queue-destination requests.

    Dispatching a shot to Codex supersedes its staged queue entry, so the queue
    should no longer list it. Codex-destination requests are left untouched (they
    track the handoff and its results). Returns the removed request ids.
    """
    removed: list[str] = []
    for row in list_requests(project, shot_id=shot_id, destination="queue"):
        if row.get("status") != "queued":
            continue
        request_id = str(row.get("request_id") or "")
        if request_id:
            delete_request(project, request_id)
            removed.append(request_id)
    return removed


def codex_batch_handoff_prompt(request_ids: list[str], *, provider: str = "codex") -> str:
    cleaned_ids = [_validate_id(request_id, "request id") for request_id in request_ids]
    if not cleaned_ids:
        raise ValueError("No Codex generation requests were created.")
    provider = str(provider or "").strip().lower()
    backend_rule = (
        "BACKEND REQUIREMENT: every request in this batch explicitly requires Stable Diffusion. "
        "You MUST operate Stable Diffusion for image generation. Do NOT use OpenAI imagegen, "
        "DALL-E, or any other image generator, even if earlier conversation context suggests one. "
        "The request provider is an execution constraint, not a preference. "
        if provider == "stable_diffusion"
        else ""
    )
    return (
        backend_rule +
        "Use the Storyboarder MCP tools to fetch and generate one storyboard image for every request ID below. "
        "For each request, inspect every matched keyword asset before generating, then submit its image with "
        "storyboard_submit_generation_result. Do not edit shots.json directly.\n\n"
        "Request IDs:\n"
        + "\n".join(f"- {request_id}" for request_id in cleaned_ids)
    )


def delete_request(project: Project, request_id: str) -> None:
    """Remove a request, with a cancellation marker only as a lock fallback.

    The normal path deletes both the immutable request and mutable state files.
    If Windows has the request open momentarily, the cancellation marker still
    hides it and rejects a late Codex result until the file can be removed.
    """
    request_id = _validate_id(request_id, "request id")
    request_path = _request_path(project, request_id)
    state_path = _state_path(project, request_id)
    atomic_write_json(
        state_path,
        {
            "schema_version": SCHEMA_VERSION,
            "request_id": request_id,
            "status": "cancelled",
            "updated_at": _utc_now(),
        },
    )
    try:
        request_path.unlink(missing_ok=True)
    except OSError:
        # Keep the cancellation marker: the request cannot reappear or accept a
        # result while another process has its manifest open.
        return
    try:
        state_path.unlink(missing_ok=True)
    except OSError:
        # An orphaned state file has no effect once the request manifest is gone.
        pass


def get_request(project: Project, request_id: str) -> dict[str, Any]:
    path = _request_path(project, request_id)
    if not path.is_file():
        raise ValueError(f"Generation request not found: {request_id}")
    request = _apply_request_state(project, _read_json_object(path))
    request["results"] = list_results(project, request_id)
    if request["results"]:
        request["latest_result"] = request["results"][0]
    return request


def list_requests(
    project: Project,
    *,
    shot_id: str = "",
    destination: str = "",
    status: str = "",
) -> list[dict[str, Any]]:
    destination = str(destination or "").strip().lower()
    status = str(status or "").strip().lower()
    if destination and destination not in DESTINATIONS:
        raise ValueError("Invalid generation destination filter.")
    if status and status not in REQUEST_STATUSES:
        raise ValueError("Invalid generation status filter.")
    rows: list[dict[str, Any]] = []
    directory = _requests_dir(project)
    if not directory.is_dir():
        return rows
    for path in directory.glob("*.json"):
        try:
            row = _apply_request_state(project, _read_json_object(path))
        except ValueError:
            continue
        # A removed queue item remains on disk as an immutable audit record so
        # Codex cannot submit a late result for it. It is not an active queue
        # item unless a caller explicitly asks for cancelled requests.
        if not status and row.get("status") == "cancelled":
            continue
        if shot_id and row.get("shot_id") != shot_id:
            continue
        if destination and row.get("destination") != destination:
            continue
        if status and row.get("status") != status:
            continue
        results = list_results(project, str(row.get("request_id") or ""))
        row["result_count"] = len(results)
        if results:
            row["latest_result"] = results[0]
        rows.append(row)
    rows.sort(key=lambda row: str(row.get("created_at") or ""))
    return rows


def _result_request_dir(project: Project, request_id: str) -> Path:
    return resolve_project_child(
        project,
        "generation",
        "results",
        _validate_id(request_id, "request id"),
    )


def list_results(project: Project, request_id: str) -> list[dict[str, Any]]:
    directory = _result_request_dir(project, request_id)
    if not directory.is_dir():
        return []
    rows: list[dict[str, Any]] = []
    for path in directory.glob("*.json"):
        try:
            rows.append(_read_json_object(path))
        except ValueError:
            continue
    rows.sort(key=lambda row: str(row.get("created_at") or ""), reverse=True)
    return rows


def result_inbox_revision(project: Project) -> int:
    """Return a durable change marker for deposited generation results.

    A result manifest is written atomically only after every candidate has been
    copied into the project. The desktop process can therefore use its mtime as
    a safe, restart-resilient completion signal without polling from the UI.
    """
    latest = 0
    directory = _results_dir(project)
    if not directory.is_dir():
        return latest
    for path in directory.rglob("*.json"):
        try:
            latest = max(latest, path.stat().st_mtime_ns)
        except OSError:
            continue
    return latest


def _copy_image_artifact(source: Path, target: Path) -> None:
    if not source.is_file():
        raise ValueError(f"Artifact not found: {source}")
    if source.suffix.lower() not in IMAGE_SUFFIXES:
        raise ValueError(f"Unsupported artifact format: {source.suffix}")
    size = source.stat().st_size
    if size <= 0 or size > MAX_ARTIFACT_BYTES:
        raise ValueError("Artifact must be a non-empty image no larger than 64 MB.")
    with Image.open(source) as image:
        image.verify()
    target.parent.mkdir(parents=True, exist_ok=True)
    # Keep the temporary name short so atomic copies also work near Windows' legacy MAX_PATH limit.
    fd, tmp_name = tempfile.mkstemp(dir=str(target.parent), prefix=".tmp-", suffix=target.suffix)
    os.close(fd)
    try:
        shutil.copyfile(source, tmp_name)
        os.replace(tmp_name, target)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def submit_result(
    project: Project,
    request_id: str,
    artifact_paths: list[str],
    *,
    summary: str = "",
) -> dict[str, Any]:
    request = get_request(project, request_id)
    if request.get("status") in {"completed", "cancelled"}:
        raise ValueError("Generation request is no longer accepting results.")
    paths = [Path(str(path)).expanduser().resolve() for path in artifact_paths if str(path).strip()]
    if not paths or len(paths) > MAX_ARTIFACTS:
        raise ValueError(f"Provide between 1 and {MAX_ARTIFACTS} image artifacts.")

    result_id = _new_id("out")
    candidate_dir = resolve_project_child(
        project,
        "generation",
        "candidates",
        request_id,
        result_id,
    )
    artifacts: list[dict[str, Any]] = []
    try:
        for index, source in enumerate(paths, start=1):
            suffix = source.suffix.lower()
            target = resolve_project_child(
                project,
                "generation",
                "candidates",
                request_id,
                result_id,
                f"candidate_{index:03d}{suffix}",
            )
            _copy_image_artifact(source, target)
            artifacts.append({
                "name": target.name,
                "project_relative_path": project_relative_posix(project, target),
                "absolute_path": str(target.resolve()),
                "media_type": suffix.lstrip("."),
            })
        result = {
            "schema_version": SCHEMA_VERSION,
            "result_id": result_id,
            "request_id": request_id,
            "shot_id": request.get("shot_id", ""),
            "created_at": _utc_now(),
            "summary": str(summary or "").strip(),
            "artifacts": artifacts,
        }
        atomic_write_json(
            resolve_project_child(
                project,
                "generation",
                "results",
                request_id,
                f"{result_id}.json",
            ),
            result,
        )
    except BaseException:
        shutil.rmtree(candidate_dir, ignore_errors=True)
        raise
    if bool(request.get("clear_queue_on_result", True)):
        clear_pending_queue_requests(project, str(request.get("shot_id") or ""))
    return result


def reconcile_results(project: Project) -> dict[str, Any]:
    """Import deposited result state into requests and their canonical shots."""
    by_shot = {shot.shot_id: shot for shot in project.shots}
    updated_request_ids: list[str] = []
    updated_shot_ids: list[str] = []
    for request in list_requests(project):
        latest = request.get("latest_result")
        if not isinstance(latest, dict):
            continue
        request_id = str(request.get("request_id") or "")
        result_id = str(latest.get("result_id") or "")
        shot = by_shot.get(str(request.get("shot_id") or ""))
        if not request_id or not result_id or shot is None:
            continue
        changed = request.get("status") != "needs-review"
        if changed:
            atomic_write_json(
                _state_path(project, request_id),
                {
                    "schema_version": SCHEMA_VERSION,
                    "request_id": request_id,
                    "status": "needs-review",
                    "updated_at": _utc_now(),
                },
            )
            updated_request_ids.append(request_id)
        state = shot.generation_state
        desired = {
            "execution_status": "succeeded",
            "review_status": "needs-review",
            "freshness_status": "current",
            "active_output_id": result_id,
            "latest_attempt_id": request_id,
        }
        if any(state.get(key) != value for key, value in desired.items()):
            state.update(desired)
            updated_shot_ids.append(shot.shot_id)
    return {
        "updated_request_ids": updated_request_ids,
        "updated_shot_ids": list(dict.fromkeys(updated_shot_ids)),
    }


def pull_results(project: Project) -> dict[str, Any]:
    """Pull submitted candidates into their matching shot Codex layers."""
    reconciled = reconcile_results(project)
    shots_by_id = {shot.shot_id: shot for shot in project.shots}
    accepted_request_ids: list[str] = []
    for request in list_requests(project, status="needs-review"):
        latest = request.get("latest_result")
        if not isinstance(latest, dict):
            continue
        artifacts = latest.get("artifacts")
        if not isinstance(artifacts, list) or not artifacts:
            continue
        artifact_path = str((artifacts[0] or {}).get("project_relative_path") or "")
        shot = shots_by_id.get(str(request.get("shot_id") or ""))
        request_id = str(request.get("request_id") or "")
        result_id = str(latest.get("result_id") or "")
        if not shot or not request_id or not result_id or not artifact_path:
            continue
        accept_candidate_as_codex_layer(project, shot, request_id, result_id, artifact_path)
        accepted_request_ids.append(request_id)
    return {**reconciled, "accepted_request_ids": accepted_request_ids}


def accept_candidate_as_codex_layer(
    project: Project,
    shot: Shot,
    request_id: str,
    result_id: str,
    artifact_path: str,
) -> Path:
    """Accept one returned candidate into the shot's independent Codex layer."""
    request = get_request(project, request_id)
    if str(request.get("shot_id") or "") != shot.shot_id:
        raise ValueError("Generation request does not belong to this shot.")
    result_id = _validate_id(result_id, "result id")
    result = next(
        (row for row in request.get("results", []) if str(row.get("result_id") or "") == result_id),
        None,
    )
    if not isinstance(result, dict):
        raise ValueError("Generation result not found.")
    cleaned_path = str(artifact_path or "").strip()
    artifact = next(
        (
            row
            for row in result.get("artifacts", [])
            if isinstance(row, dict) and str(row.get("project_relative_path") or "") == cleaned_path
        ),
        None,
    )
    if artifact is None:
        raise ValueError("Generation artifact not found in this result.")
    source = resolve_project_relative_path(project, cleaned_path)
    candidate_root = resolve_project_child(
        project,
        "generation",
        "candidates",
        _validate_id(request_id, "request id"),
        result_id,
    )
    if candidate_root not in source.parents:
        raise ValueError("Generation artifact is outside its candidate folder.")
    destination = shot_assets.save_codex_layer_from_path(project, shot, source)
    now = _utc_now()
    atomic_write_json(
        _state_path(project, request_id),
        {
            "schema_version": SCHEMA_VERSION,
            "request_id": request_id,
            "status": "completed",
            "updated_at": now,
        },
    )
    shot.generation_state.update({
        "execution_status": "succeeded",
        "review_status": "accepted",
        "freshness_status": "current",
        "active_output_id": result_id,
        "approved_output_id": result_id,
        "latest_attempt_id": request_id,
    })
    return destination


def codex_handoff_prompt(request_id: str, *, provider: str = "codex", mode: str = "") -> str:
    request_id = _validate_id(request_id, "request id")
    provider = str(provider or "").strip().lower()
    mode = str(mode or "").strip().lower()
    mode_label = mode if mode in MODES else "the request's"
    if provider == "stable_diffusion":
        return (
            "BACKEND REQUIREMENT: this request explicitly requires Stable Diffusion. "
            "You MUST operate Stable Diffusion for image generation. Do NOT use OpenAI imagegen, DALL-E, or any "
            "other image generator, even if earlier conversation context suggests one. The request provider is an "
            "execution constraint, not a preference. "
            "Use the Storyboarder MCP tools to fetch generation request "
            f"{request_id}. This request targets the Stable Diffusion provider in {mode_label} mode: operate "
            "Stable Diffusion to render the storyboard image rather than generating it directly. Follow the "
            "request's generation_plan for target size, steps, style, and output policy; build the positive prompt "
            "from compiled_prompt, apply its negative_prompt and every reference, preserve the panel aspect ratio, "
            "and upscale back to panel size when the plan requests it. If generation_plan.prior_frame is present, "
            "use it as the img2img base. Produce the requested number of variants, "
            "then submit the image files with storyboard_submit_generation_result. Inspect every matched file in "
            "keyword_assets before generating. Do not edit shots.json directly."
        )
    return (
        "Use the Storyboarder MCP tools to fetch generation request "
        f"{request_id}, generate the requested storyboard image variants, then submit the image files "
        "with storyboard_submit_generation_result. Inspect every matched file in keyword_assets before generating. "
        "Do not edit shots.json directly."
    )
