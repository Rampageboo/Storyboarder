from __future__ import annotations

import re
import shutil
import uuid
from pathlib import Path
from typing import Any, BinaryIO

from . import project_manager as pm
from .image_utils import (
    copy_and_convert_image_stream,
    normalize_reference_fit_mode,
)
from .models import Project, Shot
from .shot_store import save_shots_csv

REFERENCE_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp"}
REFERENCE_VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v"}
REFERENCE_MODEL_EXTENSIONS = {".glb", ".gltf"}


def new_ref_segment_id() -> str:
    return f"seg_{uuid.uuid4().hex[:10]}"


def _segment_board_range(shots: list[Shot], anchor_index: int, end_index: int) -> tuple[int, int]:
    """Shared board-range validation used by every ref-segment apply function."""
    if not shots:
        raise ValueError("Project has no boards.")
    min_index = max(0, min(int(anchor_index), int(end_index)))
    max_index = min(len(shots) - 1, max(int(anchor_index), int(end_index)))
    if min_index > max_index:
        raise ValueError("Invalid board range.")
    return min_index, max_index


def _segment_storyboard_duration(shots: list[Shot], min_index: int, max_index: int) -> float:
    """Shared storyboard-duration accumulation used by every ref-segment apply function."""
    storyboard_duration = 0.0
    for index in range(min_index, max_index + 1):
        storyboard_duration += max(0.1, float(shots[index].duration_seconds or 3))
    return storyboard_duration


def normalize_ref_segments(settings: dict[str, Any]) -> list[dict[str, Any]]:
    raw = settings.get("ref_segments")
    if isinstance(raw, list) and raw:
        normalized: list[dict[str, Any]] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            anchor = str(item.get("anchor_shot_id", "") or "").strip()
            end = str(item.get("end_shot_id", "") or "").strip()
            if not anchor or not end:
                continue
            seg_id = str(item.get("id", "") or "").strip() or new_ref_segment_id()
            try:
                video_start = max(0.0, float(item.get("video_start", 0.0) or 0.0))
            except (TypeError, ValueError):
                video_start = 0.0
            source_type = str(item.get("source_type", "") or "").strip().lower()
            if source_type not in {"video", "model", "image", "none"}:
                source_type = "none"
            reference_id = str(item.get("reference_id", "") or "").strip()
            reference_path = pm._normalize_rel_path(str(item.get("reference_path", "") or "").strip())
            fit_mode = normalize_reference_fit_mode(str(item.get("fit_mode", "") or "fit"))
            normalized.append(
                {
                    "id": seg_id,
                    "anchor_shot_id": anchor,
                    "end_shot_id": end,
                    "video_start": round(video_start, 3),
                    "source_type": source_type,
                    "reference_id": reference_id,
                    "reference_path": reference_path,
                    "fit_mode": fit_mode,
                }
            )
        return normalized
    legacy = settings.get("ref_segment") or {}
    if isinstance(legacy, dict):
        anchor = str(legacy.get("anchor_shot_id", "") or "").strip()
        end = str(legacy.get("end_shot_id", "") or "").strip()
        if anchor and end:
            video = settings.get("ref_segment_video") or {}
            try:
                video_start = max(0.0, float(video.get("start", 0.0) or 0.0))
            except (TypeError, ValueError):
                video_start = 0.0
            mode = str(settings.get("reference_segment_mode", "video") or "video").lower()
            if mode not in {"video", "model", "image"}:
                mode = "video"
            ref_path = ""
            ref_id = ""
            if mode == "video":
                ref_path = pm._normalize_rel_path(str(settings.get("reference_video_path", "") or "").strip())
            elif mode == "model":
                ref_path = pm._normalize_rel_path(str(settings.get("reference_model_path", "") or "").strip())
            elif mode == "image":
                ref_path = pm._normalize_rel_path(str(settings.get("reference_image_path", "") or "").strip())
            if ref_path:
                links = normalize_reference_links(settings.get("reference_links"))
                target = next((item for item in links if item["path"] == ref_path), None)
                if target:
                    ref_id = target["id"]
            return [
                {
                    "id": "seg_default",
                    "anchor_shot_id": anchor,
                    "end_shot_id": end,
                    "video_start": round(video_start, 3),
                    "source_type": mode,
                    "reference_id": ref_id,
                    "reference_path": ref_path,
                    "fit_mode": "fit",
                }
            ]
    return []


def resolve_segment_reference(
    project: Project,
    segment: dict[str, Any] | None,
) -> tuple[str, str]:
    """Return (relative_path, source_type) bound to a segment, with legacy fallbacks."""
    if not segment:
        return "", "none"
    links = normalize_reference_links(project.settings.get("reference_links"))
    ref_id = str(segment.get("reference_id", "") or "").strip()
    if ref_id:
        target = next((item for item in links if item["id"] == ref_id), None)
        if target:
            return target["path"], target["type"]
    ref_path = pm._normalize_rel_path(str(segment.get("reference_path", "") or "").strip())
    if ref_path:
        target = next((item for item in links if item["path"] == ref_path), None)
        media_type = target["type"] if target else str(segment.get("source_type", "") or "none")
        return ref_path, media_type
    source_type = str(segment.get("source_type", "") or "").strip().lower()
    if source_type == "video":
        ref_path = pm._normalize_rel_path(str(project.settings.get("reference_video_path", "") or "").strip())
    elif source_type == "model":
        ref_path = pm._normalize_rel_path(str(project.settings.get("reference_model_path", "") or "").strip())
    elif source_type == "image":
        ref_path = pm._normalize_rel_path(str(project.settings.get("reference_image_path", "") or "").strip())
    else:
        ref_path = ""
    return ref_path, source_type if source_type in {"video", "model", "image"} else "none"


def sync_ref_segment_settings(project: Project) -> None:
    segments = normalize_ref_segments(project.settings)
    project.settings["ref_segments"] = segments
    active_id = str(project.settings.get("active_ref_segment_id", "") or "").strip()
    if not active_id or not any(segment["id"] == active_id for segment in segments):
        active_id = segments[0]["id"] if segments else ""
    project.settings["active_ref_segment_id"] = active_id
    if not segments or not active_id:
        project.settings["ref_segment"] = {}
        return
    active = next(segment for segment in segments if segment["id"] == active_id)
    project.settings["ref_segment"] = {
        "anchor_shot_id": active["anchor_shot_id"],
        "end_shot_id": active["end_shot_id"],
    }
    project.settings["ref_segment_video"] = {
        "start": active.get("video_start", 0.0),
        "segment_id": active_id,
    }
    ref_path, ref_type = resolve_segment_reference(project, active)
    if ref_path and ref_type in {"video", "model", "image"}:
        project.settings["reference_segment_mode"] = ref_type
        if ref_type == "video":
            project.settings["reference_video_path"] = ref_path
        elif ref_type == "model":
            project.settings["reference_model_path"] = ref_path
            project.settings["scene3d"] = _default_scene3d_meta(project, ref_path)
        elif ref_type == "image":
            project.settings["reference_image_path"] = ref_path


def find_ref_segment(project: Project, segment_id: str | None = None) -> dict[str, Any] | None:
    segments = normalize_ref_segments(project.settings)
    if not segments:
        return None
    if segment_id:
        for segment in segments:
            if segment["id"] == segment_id:
                return segment
    active_id = str(project.settings.get("active_ref_segment_id", "") or "").strip()
    if active_id:
        for segment in segments:
            if segment["id"] == active_id:
                return segment
    return segments[0]


def update_ref_segment_video_start(project: Project, segment_id: str, video_start: float) -> None:
    segments = normalize_ref_segments(project.settings)
    updated = False
    for segment in segments:
        if segment["id"] == segment_id:
            segment["video_start"] = round(max(0.0, float(video_start)), 3)
            updated = True
            break
    if not updated:
        return
    project.settings["ref_segments"] = segments
    sync_ref_segment_settings(project)


def normalize_reference_links(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    normalized: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        path = pm._normalize_rel_path(str(item.get("path") or item.get("url") or "").strip())
        if not path or re.match(r"^https?://", path, re.IGNORECASE):
            continue
        media_type = str(item.get("type") or "").strip().lower()
        if media_type not in {"image", "video", "model"}:
            media_type = reference_media_type(path)
        title = str(item.get("title", "") or "").strip() or Path(path).name or path
        ref_id = str(item.get("id", "") or "").strip() or uuid.uuid4().hex
        while ref_id in seen_ids:
            ref_id = uuid.uuid4().hex
        seen_ids.add(ref_id)
        normalized.append({"id": ref_id, "title": title, "type": media_type, "path": path})
    return normalized


def reference_media_type(path: str) -> str:
    suffix = Path(path).suffix.lower()
    if suffix in REFERENCE_MODEL_EXTENSIONS:
        return "model"
    if suffix in REFERENCE_VIDEO_EXTENSIONS:
        return "video"
    return "image"


def ensure_reference_library(settings: dict[str, Any]) -> None:
    links = normalize_reference_links(settings.get("reference_links"))
    video_path = pm._normalize_rel_path(str(settings.get("reference_video_path") or "").strip())
    if video_path and not any(link["path"] == video_path for link in links):
        links.insert(
            0,
            {
                "id": uuid.uuid4().hex,
                "title": Path(video_path).name or "Reference video",
                "type": "video",
                "path": video_path,
            },
        )
    model_path = pm._normalize_rel_path(str(settings.get("reference_model_path") or "").strip())
    if model_path and not any(link["path"] == model_path for link in links):
        links.insert(
            0,
            {
                "id": uuid.uuid4().hex,
                "title": Path(model_path).name or "Reference model",
                "type": "model",
                "path": model_path,
            },
        )
    image_path = pm._normalize_rel_path(str(settings.get("reference_image_path") or "").strip())
    if image_path and not any(link["path"] == image_path for link in links):
        links.insert(
            0,
            {
                "id": uuid.uuid4().hex,
                "title": Path(image_path).name or "Reference image",
                "type": "image",
                "path": image_path,
            },
        )
    scene3d_path = pm._normalize_rel_path(str((settings.get("scene3d") or {}).get("file_path", "") or "").strip())
    if scene3d_path and scene3d_path not in {link["path"] for link in links}:
        media_type = reference_media_type(scene3d_path)
        if media_type == "model":
            links.append(
                {
                    "id": uuid.uuid4().hex,
                    "title": Path(scene3d_path).name or "Scene model",
                    "type": "model",
                    "path": scene3d_path,
                }
            )
    for link in links:
        inferred = reference_media_type(link["path"])
        if inferred != link["type"]:
            link["type"] = inferred
    settings["reference_links"] = links


def import_project_reference_stream(
    project: Project,
    source_stream: BinaryIO,
    source_name: str,
    *,
    set_active_video: bool = False,
) -> dict[str, str]:
    ref_dir = project.references_dir
    ref_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(source_name or "").suffix.lower()
    ref_id = uuid.uuid4().hex
    if suffix in REFERENCE_VIDEO_EXTENSIONS:
        destination = ref_dir / f"ref_{ref_id}{suffix}"
        with destination.open("wb") as file:
            shutil.copyfileobj(source_stream, file)
        media_type = "video"
    elif suffix in REFERENCE_IMAGE_EXTENSIONS:
        destination = ref_dir / f"ref_{ref_id}.png"
        copy_and_convert_image_stream(source_stream, suffix, destination)
        media_type = "image"
    elif suffix in REFERENCE_MODEL_EXTENSIONS:
        destination = ref_dir / f"ref_{ref_id}{suffix}"
        with destination.open("wb") as file:
            shutil.copyfileobj(source_stream, file)
        media_type = "model"
    else:
        raise ValueError("Only image, video, or GLB/GLTF model references are supported.")

    relative = destination.relative_to(project.root_path).as_posix()
    title = Path(source_name or destination.name).name or relative
    entry = {"id": ref_id, "title": title, "type": media_type, "path": relative}
    links = normalize_reference_links(project.settings.get("reference_links"))
    links.append(entry)
    project.settings["reference_links"] = links
    if media_type == "video" and (set_active_video or not str(project.settings.get("reference_video_path") or "").strip()):
        _set_active_reference_video(project, relative, save=False)
    if media_type == "model" and not str(project.settings.get("reference_model_path") or "").strip():
        _set_active_reference_model(project, relative, save=False)
    pm.save_settings(project)
    return entry


def remove_project_reference(project: Project, ref_id: str) -> None:
    ref_id = str(ref_id or "").strip()
    if not ref_id:
        raise ValueError("Reference id is required.")
    links = normalize_reference_links(project.settings.get("reference_links"))
    target = next((item for item in links if item["id"] == ref_id), None)
    if not target:
        raise ValueError("Reference not found.")
    file_path = (project.root_path / target["path"]).resolve()
    root = project.root_path.resolve()
    if root in file_path.parents and file_path.is_file():
        file_path.unlink()
    project.settings["reference_links"] = [item for item in links if item["id"] != ref_id]
    target_path = pm._normalize_rel_path(target["path"])
    segments = normalize_ref_segments(project.settings)
    cleared_segments = False
    for segment in segments:
        seg_ref_id = str(segment.get("reference_id", "") or "").strip()
        seg_ref_path = pm._normalize_rel_path(str(segment.get("reference_path", "") or "").strip())
        if seg_ref_id == ref_id or (seg_ref_path and seg_ref_path == target_path):
            segment["reference_id"] = ""
            segment["reference_path"] = ""
            segment["source_type"] = "none"
            cleared_segments = True
    if cleared_segments:
        project.settings["ref_segments"] = segments
        sync_ref_segment_settings(project)
    active_video = pm._normalize_rel_path(str(project.settings.get("reference_video_path") or "").strip())
    if active_video == target["path"]:
        next_video = next((item["path"] for item in project.settings["reference_links"] if item["type"] == "video"), "")
        if next_video:
            _set_active_reference_video(project, next_video, save=False)
        else:
            project.settings["reference_video_path"] = ""
            if str(project.settings.get("reference_segment_mode") or "") == "video":
                project.settings["reference_segment_mode"] = "video"
            project.settings.pop("ref_segment_apply", None)
            project.settings.pop("ref_segment_video", None)
            _clear_shot_ref_video_fields(project)
    active_model = pm._normalize_rel_path(str(project.settings.get("reference_model_path") or "").strip())
    if active_model == target["path"]:
        next_model = next((item["path"] for item in project.settings["reference_links"] if item["type"] == "model"), "")
        if next_model:
            _set_active_reference_model(project, next_model, save=False)
        else:
            project.settings["reference_model_path"] = ""
            if str(project.settings.get("reference_segment_mode") or "") == "model":
                project.settings["reference_segment_mode"] = "video"
    pm.save_settings(project)


def _default_scene3d_meta(project: Project, relative_path: str, title: str = "") -> dict[str, Any]:
    existing = dict(project.settings.get("scene3d") or {})
    existing.update(
        {
            "source": "blender",
            "file_path": pm._normalize_rel_path(relative_path),
            "file_name": title or Path(relative_path).name,
            "follow_camera": existing.get("follow_camera", True) is not False,
            "program_lighting": existing.get("program_lighting", "auto"),
            "object_color_preview": existing.get("object_color_preview", True) is not False,
            "wireframe_mode": existing.get("wireframe_mode", "off"),
        }
    )
    return existing


def set_active_reference_model(project: Project, relative_path: str) -> None:
    relative_path = pm._normalize_rel_path(relative_path)
    if not relative_path:
        raise ValueError("Reference model path is required.")
    links = normalize_reference_links(project.settings.get("reference_links"))
    target = next((item for item in links if item["path"] == relative_path), None)
    if not target:
        raise ValueError("Reference not found in library.")
    if target["type"] != "model":
        raise ValueError("Only GLB/GLTF model references can be used for 3D segments.")
    _set_active_reference_model(project, relative_path)


def _set_active_reference_model(project: Project, relative_path: str, *, save: bool = True) -> None:
    relative_path = pm._normalize_rel_path(relative_path)
    project.settings["reference_model_path"] = relative_path
    project.settings["reference_segment_mode"] = "model"
    project.settings["scene3d"] = _default_scene3d_meta(project, relative_path)
    project.settings.pop("ref_segment_apply", None)
    if save:
        pm.save_settings(project)


def set_active_reference_video(project: Project, relative_path: str) -> None:
    relative_path = pm._normalize_rel_path(relative_path)
    if not relative_path:
        raise ValueError("Reference video path is required.")
    links = normalize_reference_links(project.settings.get("reference_links"))
    target = next((item for item in links if item["path"] == relative_path), None)
    if not target:
        raise ValueError("Reference not found in library.")
    if target["type"] != "video":
        raise ValueError("Only video references can be used for segments.")
    _set_active_reference_video(project, relative_path)


def clear_active_reference_video(project: Project) -> None:
    project.settings["reference_video_path"] = ""
    project.settings.pop("ref_segment_apply", None)
    project.settings.pop("ref_segment_video", None)
    _clear_shot_ref_video_fields(project)
    pm.save_settings(project)


def _set_active_reference_video(project: Project, relative_path: str, *, save: bool = True) -> None:
    project.settings["reference_video_path"] = pm._normalize_rel_path(relative_path)
    project.settings["reference_segment_mode"] = "video"
    project.settings.pop("ref_segment_apply", None)
    project.settings.pop("ref_segment_video", None)
    _clear_shot_ref_video_fields(project)
    if save:
        pm.save_settings(project)


def set_active_reference_image(project: Project, relative_path: str) -> None:
    relative_path = pm._normalize_rel_path(relative_path)
    if not relative_path:
        raise ValueError("Reference image path is required.")
    links = normalize_reference_links(project.settings.get("reference_links"))
    target = next((item for item in links if item["path"] == relative_path), None)
    if not target:
        raise ValueError("Reference not found in library.")
    if target["type"] != "image":
        raise ValueError("Only image references can be used for image segments.")
    _set_active_reference_image(project, relative_path)


def _set_active_reference_image(project: Project, relative_path: str, *, save: bool = True) -> None:
    relative_path = pm._normalize_rel_path(relative_path)
    project.settings["reference_image_path"] = relative_path
    project.settings["reference_segment_mode"] = "image"
    project.settings.pop("ref_segment_apply", None)
    if save:
        pm.save_settings(project)


def _clear_shot_ref_video_fields(project: Project) -> None:
    for shot in project.shots:
        if not shot.ref_video_path and not shot.ref_video_time and not shot.ref_segment_time:
            continue
        shot.ref_video_path = ""
        shot.ref_video_time = 0.0
        shot.ref_segment_time = 0.0


def import_reference_video_stream(
    project: Project,
    source_stream: BinaryIO,
    source_name: str,
) -> Path:
    entry = import_project_reference_stream(project, source_stream, source_name, set_active_video=True)
    return project.root_path / entry["path"]


def _validate_segment_reference(
    project: Project,
    seg: dict[str, Any],
    expected_type: str,
) -> tuple[str, Path]:
    bind_messages = {
        "video": "Bind a reference video to this segment first.",
        "model": "Bind a reference GLB to this segment first.",
        "image": "Bind a reference image to this segment first.",
    }
    outside_messages = {
        "video": "Reference video path is outside the project.",
        "model": "Reference model path is outside the project.",
        "image": "Reference image path is outside the project.",
    }
    missing_messages = {
        "video": "Reference video not found",
        "model": "Reference model not found",
        "image": "Reference image not found",
    }
    rel_path, ref_type = resolve_segment_reference(project, seg)
    if ref_type != expected_type or not rel_path:
        raise ValueError(bind_messages[expected_type])
    file_path = (project.root_path / rel_path).resolve()
    root = project.root_path.resolve()
    if root not in file_path.parents and file_path != root:
        raise ValueError(outside_messages[expected_type])
    if not file_path.is_file():
        raise FileNotFoundError(f"{missing_messages[expected_type]}: {rel_path}")
    return rel_path, file_path


def _persist_ref_segment_apply(
    project: Project,
    *,
    seg: dict[str, Any],
    segment_id: str | None,
    min_index: int,
    max_index: int,
    apply_meta: dict[str, Any],
    segment_patch: dict[str, Any] | None = None,
) -> None:
    shots = project.shots
    project.settings["ref_segment_apply"] = apply_meta
    project.settings["ref_segment"] = {
        "anchor_shot_id": shots[min_index].shot_id,
        "end_shot_id": shots[max_index].shot_id,
    }
    segments = normalize_ref_segments(project.settings)
    seg_id = str(seg.get("id", segment_id or "") or "").strip()
    if seg_id and segment_patch:
        for segment in segments:
            if segment["id"] == seg_id:
                segment.update(segment_patch)
                break
    project.settings["ref_segments"] = segments
    if seg_id:
        project.settings["active_ref_segment_id"] = seg_id
    sync_ref_segment_settings(project)
    pm.save_settings(project)
    save_shots_csv(project.root_path, project.shots)


def apply_ref_segment_to_boards(
    project: Project,
    anchor_index: int,
    end_index: int,
    segment_id: str | None = None,
) -> dict[str, Any]:
    from datetime import datetime, timezone

    from .video_utils import extract_video_frame_to_png, get_video_duration

    shots = project.shots
    min_index, max_index = _segment_board_range(shots, anchor_index, end_index)

    video_seg = find_ref_segment(project, segment_id) or {}
    video_rel, video_path = _validate_segment_reference(project, video_seg, "video")

    video_duration = get_video_duration(video_path)
    video_mtime = video_path.stat().st_mtime
    segment_offset = 0.0
    storyboard_duration = _segment_storyboard_duration(shots, min_index, max_index)

    try:
        video_start = max(0.0, float(video_seg.get("video_start", 0.0) or 0.0))
    except (TypeError, ValueError):
        video_start = 0.0
    if not video_seg:
        legacy = project.settings.get("ref_segment_video") or {}
        try:
            video_start = max(0.0, float(legacy.get("start", 0.0) or 0.0))
        except (TypeError, ValueError):
            video_start = 0.0
    if video_duration > 0:
        if storyboard_duration >= video_duration:
            video_start = 0.0
        else:
            video_start = min(video_start, max(0.0, video_duration - storyboard_duration))
        video_span = max(0.001, min(storyboard_duration, video_duration - video_start))
    else:
        video_span = max(0.001, storyboard_duration)
    fit_mode = normalize_reference_fit_mode(str(video_seg.get("fit_mode", "") or "fit"))
    applied: list[dict[str, Any]] = []

    for index in range(min_index, max_index + 1):
        shot = shots[index]
        segment_time = segment_offset
        if storyboard_duration > 0:
            ratio = segment_time / storyboard_duration
            video_time = video_start + ratio * video_span
        else:
            video_time = video_start
        if video_duration > 0:
            video_time = min(video_time, max(0.0, video_duration - 0.001))
        else:
            video_time = 0.0
        shot_dir = pm.get_shot_dir(project, shot)
        raw_path = shot_dir / f"{shot.shot_id}_ref_raw.png"
        extract_video_frame_to_png(video_path, video_time, raw_path)
        try:
            preview_path = pm._apply_reference_frame_to_shot(project, shot, raw_path, fit_mode)
        finally:
            raw_path.unlink(missing_ok=True)
        shot.source_sync_mtime = preview_path.stat().st_mtime
        shot.ref_video_path = video_rel
        shot.ref_video_time = round(video_time, 3)
        shot.ref_segment_time = round(segment_time, 3)
        applied.append(
            {
                "shot_id": shot.shot_id,
                "board_index": index,
                "segment_time": round(segment_time, 3),
                "video_time": round(video_time, 3),
            }
        )
        segment_offset += max(0.1, float(shot.duration_seconds or 3))

    _persist_ref_segment_apply(
        project,
        seg=video_seg,
        segment_id=segment_id,
        min_index=min_index,
        max_index=max_index,
        apply_meta={
            "segment_id": video_seg.get("id", segment_id or ""),
            "anchor_shot_id": shots[min_index].shot_id,
            "end_shot_id": shots[max_index].shot_id,
            "reference_video_path": video_rel,
            "video_mtime": video_mtime,
            "video_start": round(video_start, 3),
            "storyboard_duration": round(storyboard_duration, 3),
            "fit_mode": fit_mode,
            "applied_at": datetime.now(timezone.utc).isoformat(),
        },
        segment_patch={"video_start": round(video_start, 3)},
    )
    return {
        "board_count": len(applied),
        "segment_duration": round(segment_offset, 3),
        "video_duration": round(video_duration, 3),
        "applied": applied,
    }


def apply_ref_segment_3d_to_boards(
    project: Project,
    anchor_index: int,
    end_index: int,
    segment_id: str | None = None,
    *,
    camera_name: str = "",
) -> dict[str, Any]:
    from datetime import datetime, timezone

    shots = project.shots
    min_index, max_index = _segment_board_range(shots, anchor_index, end_index)

    model_seg = find_ref_segment(project, segment_id) or {}
    model_rel, model_path = _validate_segment_reference(project, model_seg, "model")

    model_mtime = model_path.stat().st_mtime
    segment_offset = 0.0
    storyboard_duration = _segment_storyboard_duration(shots, min_index, max_index)

    try:
        anim_start = max(0.0, float(model_seg.get("video_start", 0.0) or 0.0))
    except (TypeError, ValueError):
        anim_start = 0.0
    if not model_seg:
        legacy = project.settings.get("ref_segment_video") or {}
        try:
            anim_start = max(0.0, float(legacy.get("start", 0.0) or 0.0))
        except (TypeError, ValueError):
            anim_start = 0.0

    anim_span = max(0.001, storyboard_duration)
    fit_mode = normalize_reference_fit_mode(str(model_seg.get("fit_mode", "") or "fit"))
    applied: list[dict[str, Any]] = []

    for index in range(min_index, max_index + 1):
        shot = shots[index]
        segment_time = segment_offset
        if storyboard_duration > 0:
            ratio = segment_time / storyboard_duration
            anim_time = anim_start + ratio * anim_span
        else:
            anim_time = anim_start
        anim_time = max(0.0, anim_time)
        camera_data = dict(shot.camera_data or {})
        camera_data["scene3d_time"] = round(anim_time, 3)
        if camera_name:
            camera_data["scene3d_camera"] = camera_name
        shot.camera_data = camera_data
        shot.ref_video_path = model_rel
        shot.ref_video_time = round(anim_time, 3)
        shot.ref_segment_time = round(segment_time, 3)
        applied.append(
            {
                "shot_id": shot.shot_id,
                "board_index": index,
                "segment_time": round(segment_time, 3),
                "animation_time": round(anim_time, 3),
            }
        )
        segment_offset += max(0.1, float(shot.duration_seconds or 3))

    for index in range(min_index, max_index + 1):
        shot = shots[index]
        preview_rel = str(shot.preview_image_path or shot.image_path or "").strip()
        if not preview_rel:
            continue
        preview_path = (project.root_path / preview_rel).resolve()
        if preview_path.is_file():
            composed = pm._apply_reference_frame_to_shot(project, shot, preview_path, fit_mode)
            shot.source_sync_mtime = composed.stat().st_mtime

    _persist_ref_segment_apply(
        project,
        seg=model_seg,
        segment_id=segment_id,
        min_index=min_index,
        max_index=max_index,
        apply_meta={
            "segment_id": model_seg.get("id", segment_id or ""),
            "anchor_shot_id": shots[min_index].shot_id,
            "end_shot_id": shots[max_index].shot_id,
            "source_type": "model",
            "reference_model_path": model_rel,
            "model_mtime": model_mtime,
            "video_start": round(anim_start, 3),
            "storyboard_duration": round(storyboard_duration, 3),
            "fit_mode": fit_mode,
            "applied_at": datetime.now(timezone.utc).isoformat(),
        },
        segment_patch={"video_start": round(anim_start, 3), "source_type": "model"},
    )
    return {
        "board_count": len(applied),
        "segment_duration": round(segment_offset, 3),
        "applied": applied,
    }


def apply_ref_segment_image_to_boards(
    project: Project,
    anchor_index: int,
    end_index: int,
    segment_id: str | None = None,
) -> dict[str, Any]:
    from datetime import datetime, timezone

    shots = project.shots
    min_index, max_index = _segment_board_range(shots, anchor_index, end_index)

    image_seg = find_ref_segment(project, segment_id) or {}
    image_rel, image_path = _validate_segment_reference(project, image_seg, "image")

    image_mtime = image_path.stat().st_mtime
    segment_offset = 0.0
    storyboard_duration = _segment_storyboard_duration(shots, min_index, max_index)

    fit_mode = normalize_reference_fit_mode(str(image_seg.get("fit_mode", "") or "fit"))
    applied: list[dict[str, Any]] = []
    for index in range(min_index, max_index + 1):
        shot = shots[index]
        segment_time = segment_offset
        preview_path = pm._apply_reference_frame_to_shot(project, shot, image_path, fit_mode)
        shot.source_sync_mtime = preview_path.stat().st_mtime
        shot.ref_video_path = image_rel
        shot.ref_video_time = 0.0
        shot.ref_segment_time = round(segment_time, 3)
        applied.append(
            {
                "shot_id": shot.shot_id,
                "board_index": index,
                "segment_time": round(segment_time, 3),
            }
        )
        segment_offset += max(0.1, float(shot.duration_seconds or 3))

    _persist_ref_segment_apply(
        project,
        seg=image_seg,
        segment_id=segment_id,
        min_index=min_index,
        max_index=max_index,
        apply_meta={
            "segment_id": image_seg.get("id", segment_id or ""),
            "anchor_shot_id": shots[min_index].shot_id,
            "end_shot_id": shots[max_index].shot_id,
            "source_type": "image",
            "reference_image_path": image_rel,
            "image_mtime": image_mtime,
            "storyboard_duration": round(storyboard_duration, 3),
            "fit_mode": fit_mode,
            "applied_at": datetime.now(timezone.utc).isoformat(),
        },
        segment_patch={"video_start": 0.0, "source_type": "image"},
    )
    return {
        "board_count": len(applied),
        "segment_duration": round(segment_offset, 3),
        "applied": applied,
    }


def delete_ref_segment(project: Project, segment_id: str) -> dict[str, Any]:
    seg_id = str(segment_id or "").strip()
    if not seg_id:
        raise ValueError("Segment id is required.")

    segments = normalize_ref_segments(project.settings)
    segment = next((item for item in segments if item.get("id") == seg_id), None)
    if segment is None:
        raise ValueError(f"Segment not found: {seg_id}")

    anchor_idx = next(
        (index for index, shot in enumerate(project.shots) if shot.shot_id == segment.get("anchor_shot_id")),
        -1,
    )
    end_idx = next(
        (index for index, shot in enumerate(project.shots) if shot.shot_id == segment.get("end_shot_id")),
        -1,
    )
    cleared = 0
    if anchor_idx >= 0 and end_idx >= 0:
        min_index = min(anchor_idx, end_idx)
        max_index = max(anchor_idx, end_idx)
        for index in range(min_index, max_index + 1):
            shot = project.shots[index]
            shot.ref_video_path = ""
            shot.ref_video_time = 0.0
            shot.ref_segment_time = 0.0
            pm.remove_image_for_shot(project, shot)
            cleared += 1

    project.settings["ref_segments"] = [item for item in segments if item.get("id") != seg_id]

    apply_meta = project.settings.get("ref_segment_apply") or {}
    if str(apply_meta.get("segment_id", "") or "").strip() == seg_id:
        project.settings.pop("ref_segment_apply", None)

    active_id = str(project.settings.get("active_ref_segment_id", "") or "").strip()
    if active_id == seg_id:
        remaining = normalize_ref_segments(project.settings)
        project.settings["active_ref_segment_id"] = remaining[0]["id"] if remaining else ""

    sync_ref_segment_settings(project)
    pm.save_settings(project)
    save_shots_csv(project.root_path, project.shots)
    return {"deleted_segment_id": seg_id, "cleared_boards": cleared}
