from __future__ import annotations

import json
import re
import shutil
import uuid
from pathlib import Path
from typing import Any, BinaryIO, Callable

from . import project_manager as pm
from .image_utils import (
    board_background_filename,
    copy_and_convert_image_stream,
    normalize_reference_fit_mode,
    save_png_data_url,
)
from .models import Project, Shot
from .shot_store import save_shots

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


def _segment_board_range_by_shot_id(shots: list[Shot], anchor_id: str, end_id: str) -> tuple[int, int]:
    id_to_index = {shot.shot_id: index for index, shot in enumerate(shots)}
    if anchor_id not in id_to_index or end_id not in id_to_index:
        raise ValueError("Invalid board range.")
    return _segment_board_range(shots, id_to_index[anchor_id], id_to_index[end_id])


MAX_REF_UNDO_SNAPSHOTS = 20


def _undo_root(project: Project) -> Path:
    return project.root_path / "backups" / "ref_undo"


def _prune_ref_undo_snapshots(project: Project, protect_token: str | None = None) -> None:
    """Keep only the most recent ``MAX_REF_UNDO_SNAPSHOTS`` undo-snapshot token dirs.

    Reference applies create one snapshot per apply and only delete it on undo, so
    apply-without-undo would otherwise grow ``backups/ref_undo/`` without bound. The
    snapshot for the current apply (``protect_token``) is never pruned. Undoing a very
    old apply whose token was already pruned degrades gracefully (the frontend resyncs).
    Best-effort: cleanup must never break a reference apply.
    """
    try:
        root = _undo_root(project)
        if not root.is_dir():
            return
        tokens = [child for child in root.iterdir() if child.is_dir()]
        if len(tokens) <= MAX_REF_UNDO_SNAPSHOTS:
            return
        tokens.sort(key=lambda child: child.stat().st_mtime, reverse=True)
        keep = {child.name for child in tokens[:MAX_REF_UNDO_SNAPSHOTS]}
        if protect_token:
            keep.add(protect_token)
        for child in tokens:
            if child.name not in keep:
                shutil.rmtree(child, ignore_errors=True)
    except Exception:
        pass


def _board_bake_filenames(shot: Shot) -> list[str]:
    """Files captured by the undo snapshot for a reference bake.

    Includes ``_preview.png`` so that undo can restore a shot that was baked
    under the old model (where reference apply wrote the preview directly).
    New bakes no longer write the preview, but the snapshot is kept inclusive
    so legacy undo tokens still work correctly.
    """
    return [
        f"{shot.shot_id}_preview.png",
        board_background_filename(shot.shot_id),
        f"{shot.shot_id}_thumb.png",
    ]


def snapshot_boards_for_undo(project: Project, min_index: int, max_index: int) -> str:
    """Back up the boards a bake is about to overwrite; returns an undo token."""
    token = uuid.uuid4().hex
    backup_root = _undo_root(project) / token
    manifest: list[dict[str, Any]] = []
    for index in range(min_index, max_index + 1):
        shot = project.shots[index]
        shot_dir = pm.get_shot_dir(project, shot)
        shot_backup = backup_root / shot.shot_id
        saved_files: list[str] = []
        for name in _board_bake_filenames(shot):
            source = shot_dir / name
            if source.is_file():
                shot_backup.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, shot_backup / name)
                saved_files.append(name)
        manifest.append({"shot_id": shot.shot_id, "shot": shot.to_dict(), "files": saved_files})
    backup_root.mkdir(parents=True, exist_ok=True)
    (backup_root / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    _prune_ref_undo_snapshots(project, protect_token=token)
    return token


def restore_boards_from_undo(project: Project, token: str) -> dict[str, Any]:
    """Restore boards (image files + shot fields) from a bake snapshot, then drop it."""
    token = re.sub(r"[^a-f0-9]", "", str(token or ""))
    if not token:
        raise ValueError("Invalid undo token.")
    backup_root = _undo_root(project) / token
    manifest_path = backup_root / "manifest.json"
    if not manifest_path.is_file():
        raise ValueError("Undo snapshot not found.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    shots_by_id = {shot.shot_id: shot for shot in project.shots}
    restored = 0
    for entry in manifest:
        shot_id = entry.get("shot_id")
        current = shots_by_id.get(shot_id)
        if current is None:
            continue  # board was deleted since the bake; nothing to restore
        shot_dir = pm.get_shot_dir(project, current)
        saved_files = set(entry.get("files", []))
        for name in _board_bake_filenames(current):
            target = shot_dir / name
            backup_file = backup_root / shot_id / name
            if name in saved_files and backup_file.is_file():
                shutil.copy2(backup_file, target)
            else:
                target.unlink(missing_ok=True)  # file did not exist before the bake
        project.shots[project.shots.index(current)] = Shot.from_dict(entry.get("shot", {}))
        restored += 1
    shutil.rmtree(backup_root, ignore_errors=True)
    return {"restored": restored}


def _segment_storyboard_duration(shots: list[Shot], min_index: int, max_index: int) -> float:
    """Shared storyboard-duration accumulation used by every ref-segment apply function."""
    storyboard_duration = 0.0
    for index in range(min_index, max_index + 1):
        storyboard_duration += max(0.1, float(shots[index].duration_seconds or 3))
    return storyboard_duration


_REF_SEGMENT_CAMERA_KEYS = ("ref_segment_id", "ref_source_type", "ref_applied_at", "ref_frame_time")


def _stamp_ref_segment_provenance(
    shot: Shot,
    segment_id: str,
    source_type: str,
    *,
    frame_time: float | None = None,
    applied_at: str | None = None,
) -> None:
    """Record which reference segment actually generated this board's bake."""
    from datetime import datetime, timezone

    camera_data = dict(shot.camera_data or {})
    camera_data["ref_segment_id"] = str(segment_id or "").strip()
    camera_data["ref_source_type"] = str(source_type or "").strip().lower()
    camera_data["ref_applied_at"] = applied_at or datetime.now(timezone.utc).isoformat()
    if frame_time is not None:
        camera_data["ref_frame_time"] = round(float(frame_time), 3)
    shot.camera_data = camera_data


def _clear_ref_segment_provenance(shot: Shot, segment_id: str | None = None) -> None:
    camera_data = dict(shot.camera_data or {})
    if segment_id and str(camera_data.get("ref_segment_id", "") or "").strip() != str(segment_id).strip():
        return
    for key in _REF_SEGMENT_CAMERA_KEYS:
        camera_data.pop(key, None)
    shot.camera_data = camera_data


def _strip_ref_segment_provenance(shot: Shot) -> None:
    """Remove all reference-segment provenance keys from a board being cleared."""
    camera_data = dict(shot.camera_data or {})
    for key in _REF_SEGMENT_CAMERA_KEYS:
        camera_data.pop(key, None)
    shot.camera_data = camera_data


def _shot_needs_legacy_range_bake_cleanup(
    project: Project,
    shot: Shot,
    seg_id: str,
    segment_ref_path: str,
) -> bool:
    """Catch legacy boards in a segment range that still carry bake artefacts."""
    camera_data = shot.camera_data or {}
    provenance_id = str(camera_data.get("ref_segment_id", "") or "").strip()
    if provenance_id and provenance_id != seg_id:
        return False
    if provenance_id == seg_id:
        return True
    if segment_ref_path and pm._normalize_rel_path(shot.ref_video_path or "") == pm._normalize_rel_path(
        segment_ref_path
    ):
        return True
    if pm.get_shot_board_background_path(project, shot) is not None:
        return True
    return bool(
        shot.ref_video_path
        and (
            shot.preview_image_path
            or shot.image_path
            or (shot.ref_segment_time or 0) > 0
            or (shot.ref_video_time or 0) > 0
        )
    )


def _shot_should_clear_segment_bake(
    project: Project,
    shot: Shot,
    seg_id: str,
    segment_ref_path: str,
    *,
    in_segment_range: bool,
) -> bool:
    if _shot_matches_segment_bake(shot, segment_ref_path, seg_id):
        return True
    if not in_segment_range:
        return False
    return _shot_needs_legacy_range_bake_cleanup(project, shot, seg_id, segment_ref_path)


def _shot_matches_segment_bake(shot: Shot, segment_ref_path: str, seg_id: str) -> bool:
    camera_data = shot.camera_data or {}
    if str(camera_data.get("ref_segment_id", "") or "").strip() == seg_id:
        return True
    if not segment_ref_path:
        return False
    shot_ref = pm._normalize_rel_path(shot.ref_video_path or "")
    if shot_ref != pm._normalize_rel_path(segment_ref_path):
        return False
    return bool(
        shot.preview_image_path
        or shot.image_path
        or (shot.ref_segment_time or 0) > 0
        or (shot.ref_video_time or 0) > 0
    )


def _refresh_shot_preview_from_psd(project: Project, shot: Shot) -> None:
    from .image_utils import export_psd_composite_to_png

    shot_dir = pm.get_shot_dir(project, shot)
    source_path: Path | None = None
    if shot.source_file_path:
        candidate = project.root_path / shot.source_file_path
        if candidate.is_file():
            source_path = candidate
    if source_path is None:
        fallback = shot_dir / f"{shot.shot_id}.psd"
        if fallback.is_file():
            source_path = fallback
    if source_path is None:
        shot.preview_image_path = ""
        shot.image_path = ""
        shot.thumbnail_path = ""
        return
    preview_path = export_psd_composite_to_png(source_path, shot_dir / f"{shot.shot_id}_preview.png")
    pm._set_shot_preview_paths(project, shot, preview_path)


def _segment_index_range_from_record(project: Project, segment: dict[str, Any]) -> tuple[int, int] | None:
    anchor = str(segment.get("anchor_shot_id", "") or "").strip()
    end = str(segment.get("end_shot_id", "") or "").strip()
    if not anchor or not end:
        return None
    try:
        return _segment_board_range_by_shot_id(project.shots, anchor, end)
    except ValueError:
        return None


def _segments_overlap_records(project: Project, left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_range = _segment_index_range_from_record(project, left)
    right_range = _segment_index_range_from_record(project, right)
    if left_range is None or right_range is None:
        return False
    return left_range[0] <= right_range[1] and right_range[0] <= left_range[1]


def _restore_blank_canvas_preview(project: Project, shot: Shot) -> None:
    from .canvas_settings import get_canvas_color, get_canvas_size
    from .image_utils import create_solid_preview_png

    width, height = get_canvas_size(project)
    color = get_canvas_color(project)
    shot_dir = pm.get_shot_dir(project, shot)
    preview_path = shot_dir / f"{shot.shot_id}_preview.png"
    create_solid_preview_png(preview_path, width, height, color)
    pm._set_shot_preview_paths(project, shot, preview_path)


def _clear_shot_preview_paths(shot: Shot) -> None:
    shot.preview_image_path = ""
    shot.image_path = ""
    shot.thumbnail_path = ""
    shot.source_sync_mtime = 0.0


def _shot_preview_is_legacy_baked(project: Project, shot: Shot) -> bool:
    """True when the preview file is a legacy reference bake with no separate artist source.

    Used to decide whether it is safe to delete ``_preview.png`` when clearing a
    segment bake.  A shot is considered legacy-baked when it carries reference
    provenance (ref_segment_id stamped by an old bake) but has no linked PSD /
    source file that would be the true owner of the preview.
    """
    if pm.shot_has_psd_canvas(project, shot) or shot.source_file_path:
        return False
    cam = shot.camera_data or {}
    return bool(str(cam.get("ref_segment_id", "") or "").strip())


def _clear_ref_segment_bake_for_shot(
    project: Project,
    shot: Shot,
    seg_id: str,
    segment_ref_path: str,
) -> None:
    del seg_id, segment_ref_path  # matching is done by callers before this runs

    # Cache the legacy-bake check BEFORE stripping provenance — the check reads
    # camera_data["ref_segment_id"] which _strip_ref_segment_provenance clears.
    has_psd = pm.shot_has_psd_canvas(project, shot)
    is_legacy_baked = (not has_psd) and _shot_preview_is_legacy_baked(project, shot)

    _strip_ref_segment_provenance(shot)
    shot.ref_video_path = ""
    shot.ref_video_time = 0.0
    shot.ref_segment_time = 0.0

    shot_dir = pm.get_shot_dir(project, shot)
    # Always remove reference-owned assets.
    (shot_dir / board_background_filename(shot.shot_id)).unlink(missing_ok=True)
    (shot_dir / f"{shot.shot_id}_thumb.png").unlink(missing_ok=True)
    (shot_dir / f"{shot.shot_id}_ref_raw.png").unlink(missing_ok=True)

    if has_psd:
        # PSD-backed board: regenerate preview from the Photoshop document.
        _refresh_shot_preview_from_psd(project, shot)
        return

    if is_legacy_baked:
        # Legacy baked board (old model wrote the reference into preview directly):
        # safe to delete the preview so the board shows as blank after clearing.
        (shot_dir / f"{shot.shot_id}_preview.png").unlink(missing_ok=True)

    # For non-PSD boards (new model or cleared legacy), do not recreate a
    # per-shot solid preview; the canvas background is a global UI backdrop.
    _clear_shot_preview_paths(shot)


def normalize_ref_segments(settings: dict[str, Any]) -> list[dict[str, Any]]:
    raw = settings.get("ref_segments")
    # An explicitly-present list is authoritative even when empty: an empty array
    # means segments were deliberately cleared and must not be resurrected from
    # the legacy singular ref_segment (otherwise the last segment is undeletable).
    if isinstance(raw, list):
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


def clear_active_reference_model(project: Project) -> None:
    project.settings["reference_model_path"] = ""
    if str(project.settings.get("reference_segment_mode") or "") == "model":
        project.settings["reference_segment_mode"] = "video"
    pm.save_settings(project)


def clear_active_reference_image(project: Project) -> None:
    project.settings["reference_image_path"] = ""
    if str(project.settings.get("reference_segment_mode") or "") == "image":
        project.settings["reference_segment_mode"] = "video"
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
    save_shots(project.root_path, project.shots)


def _apply_ref_segment_template(
    project: Project,
    *,
    min_index: int,
    max_index: int,
    seg: dict[str, Any],
    segment_id: str | None,
    source_type: str,
    prepare_apply: Callable[[str | None], dict[str, Any]],
    apply_board: Callable[[int, Shot, float], tuple[float | None, dict[str, Any]]],
    after_loop: Callable[[], None] | None = None,
    include_undo_token: bool = True,
) -> dict[str, Any]:
    shots = project.shots
    undo_token = snapshot_boards_for_undo(project, min_index, max_index) if include_undo_token else None
    prepared = prepare_apply(undo_token)
    applied: list[dict[str, Any]] = []
    segment_offset = 0.0
    stamp_segment_id = str(prepared.get("stamp_segment_id", seg.get("id", segment_id or "")) or "")
    stamp_applied_at = prepared.get("stamp_applied_at")

    for index in range(min_index, max_index + 1):
        shot = shots[index]
        segment_time = segment_offset
        frame_time, row_extra = apply_board(index, shot, segment_time)
        _stamp_ref_segment_provenance(
            shot,
            stamp_segment_id,
            source_type,
            frame_time=frame_time,
            applied_at=stamp_applied_at if isinstance(stamp_applied_at, str) else None,
        )
        applied_row = {
            "shot_id": shot.shot_id,
            "board_index": index,
            "segment_time": round(segment_time, 3),
        }
        applied_row.update(row_extra)
        applied.append(applied_row)
        segment_offset += max(0.1, float(shot.duration_seconds or 3))

    if after_loop is not None:
        after_loop()

    _persist_ref_segment_apply(
        project,
        seg=seg,
        segment_id=segment_id,
        min_index=min_index,
        max_index=max_index,
        apply_meta=prepared["apply_meta"],
        segment_patch=prepared.get("segment_patch"),
    )
    result = {
        "board_count": len(applied),
        "segment_duration": round(segment_offset, 3),
    }
    result.update(prepared.get("result_extra", {}))
    result["applied"] = applied
    if include_undo_token:
        result["undo_token"] = undo_token
    return result


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
    state: dict[str, Any] = {}

    def prepare_apply(_undo_token: str | None) -> dict[str, Any]:
        video_duration = get_video_duration(video_path)
        video_mtime = video_path.stat().st_mtime
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
        state.update(
            video_duration=video_duration,
            storyboard_duration=storyboard_duration,
            video_start=video_start,
            video_span=video_span,
            fit_mode=fit_mode,
        )
        return {
            "apply_meta": {
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
            "segment_patch": {"video_start": round(video_start, 3)},
            "result_extra": {"video_duration": round(video_duration, 3)},
        }

    def apply_board(index: int, shot: Shot, segment_time: float) -> tuple[float, dict[str, Any]]:
        if state["storyboard_duration"] > 0:
            ratio = segment_time / state["storyboard_duration"]
            video_time = state["video_start"] + ratio * state["video_span"]
        else:
            video_time = state["video_start"]
        if state["video_duration"] > 0:
            video_time = min(video_time, max(0.0, state["video_duration"] - 0.001))
        else:
            video_time = 0.0
        shot_dir = pm.get_shot_dir(project, shot)
        raw_path = shot_dir / f"{shot.shot_id}_ref_raw.png"
        extract_video_frame_to_png(video_path, video_time, raw_path)
        try:
            pm._apply_reference_frame_to_shot(project, shot, raw_path, state["fit_mode"])
        finally:
            raw_path.unlink(missing_ok=True)
        shot.ref_video_path = video_rel
        shot.ref_video_time = round(video_time, 3)
        shot.ref_segment_time = round(segment_time, 3)
        return video_time, {"video_time": round(video_time, 3)}

    return _apply_ref_segment_template(
        project,
        min_index=min_index,
        max_index=max_index,
        seg=video_seg,
        segment_id=segment_id,
        source_type="video",
        prepare_apply=prepare_apply,
        apply_board=apply_board,
    )


def apply_ref_segment_3d_to_boards(
    project: Project,
    anchor_index: int,
    end_index: int,
    segment_id: str | None = None,
    *,
    camera_name: str = "",
) -> dict[str, Any]:
    """Finalize a 3D reference segment: composite each board's existing preview into a board
    background and stamp per-shot metadata/provenance + persist the segment (with an undo token).

    This is NOT a GLB renderer. It requires each board to already have a non-empty, non-solid
    The React UI renders one GLB frame per board in TypeScript (``frontend/src/scene3d/``) and
    uploads captures to ``/api/project/ref-segment/apply-model-captures`` so the composited
    background is the rendered GLB view.
    Legacy/fallback callers may instead rely on a prior Scene3D capture-to-board.
    """
    from datetime import datetime, timezone
    from .image_utils import is_solid_color_image

    shots = project.shots
    min_index, max_index = _segment_board_range(shots, anchor_index, end_index)
    model_seg = find_ref_segment(project, segment_id) or {}
    model_rel, model_path = _validate_segment_reference(project, model_seg, "model")
    state: dict[str, Any] = {}

    def prepare_apply(_undo_token: str | None) -> dict[str, Any]:
        model_mtime = model_path.stat().st_mtime
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
        eligible_preview_indices: set[int] = set()
        for index in range(min_index, max_index + 1):
            shot = shots[index]
            preview_rel = str(shot.preview_image_path or shot.image_path or "").strip()
            if not preview_rel:
                continue
            preview_path = (project.root_path / preview_rel).resolve()
            if not preview_path.is_file() or is_solid_color_image(preview_path):
                continue
            eligible_preview_indices.add(index)
        if not eligible_preview_indices:
            raise ValueError(
                "3D reference apply needs existing non-empty board previews in range. "
                "Capture a board preview first (Scene3D/Photoshop), or use image/video reference apply."
            )
        state.update(
            storyboard_duration=storyboard_duration,
            anim_start=anim_start,
            anim_span=anim_span,
            fit_mode=fit_mode,
            eligible_preview_indices=eligible_preview_indices,
        )
        return {
            "apply_meta": {
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
            "segment_patch": {"video_start": round(anim_start, 3), "source_type": "model"},
        }

    def apply_board(index: int, shot: Shot, segment_time: float) -> tuple[float, dict[str, Any]]:
        if state["storyboard_duration"] > 0:
            ratio = segment_time / state["storyboard_duration"]
            anim_time = state["anim_start"] + ratio * state["anim_span"]
        else:
            anim_time = state["anim_start"]
        anim_time = max(0.0, anim_time)
        camera_data = dict(shot.camera_data or {})
        camera_data["scene3d_time"] = round(anim_time, 3)
        if camera_name:
            camera_data["scene3d_camera"] = camera_name
        shot.camera_data = camera_data
        shot.ref_video_path = model_rel
        shot.ref_video_time = round(anim_time, 3)
        shot.ref_segment_time = round(segment_time, 3)
        return anim_time, {"animation_time": round(anim_time, 3)}

    def after_loop() -> None:
        for index in range(min_index, max_index + 1):
            shot = shots[index]
            preview_rel = str(shot.preview_image_path or shot.image_path or "").strip()
            if not preview_rel:
                continue
            preview_path = (project.root_path / preview_rel).resolve()
            if not preview_path.is_file():
                continue
            if index not in state["eligible_preview_indices"]:
                continue
            pm._apply_reference_frame_to_shot(project, shot, preview_path, state["fit_mode"])

    return _apply_ref_segment_template(
        project,
        min_index=min_index,
        max_index=max_index,
        seg=model_seg,
        segment_id=segment_id,
        source_type="model",
        prepare_apply=prepare_apply,
        apply_board=apply_board,
        after_loop=after_loop,
        include_undo_token=False,
    )


def apply_model_captures_to_boards(
    project: Project,
    anchor_shot_id: str,
    end_shot_id: str,
    segment_id: str,
    camera_name: str,
    captures: list[dict[str, Any]],
) -> dict[str, Any]:
    """Finalize desktop-rendered GLB captures: snapshot, save board images, stamp provenance."""
    from datetime import datetime, timezone

    shots = project.shots
    min_index, max_index = _segment_board_range_by_shot_id(shots, anchor_shot_id, end_shot_id)

    if not captures:
        raise ValueError("3D captures are required.")
    capture_by_shot: dict[str, dict[str, Any]] = {}
    for capture in captures:
        shot_id = str(capture.get("shot_id") or "").strip()
        if not shot_id:
            raise ValueError("Capture shot_id is required.")
        if shot_id in capture_by_shot:
            raise ValueError(f"Duplicate 3D capture for board: {shot_id}")
        data_url = str(capture.get("data_url") or "")
        if not data_url.startswith("data:image/png;base64,"):
            raise ValueError(f"Invalid PNG data URL for board: {shot_id}")
        capture_by_shot[shot_id] = capture

    range_shots = shots[min_index : max_index + 1]
    missing = [shot.shot_id for shot in range_shots if shot.shot_id not in capture_by_shot]
    if missing:
        raise ValueError(f"Missing 3D captures for board(s): {', '.join(missing)}")

    model_seg = find_ref_segment(project, segment_id or None) or {}
    model_rel, model_path = _validate_segment_reference(project, model_seg, "model")
    fit_mode = normalize_reference_fit_mode(str(model_seg.get("fit_mode", "") or "fit"))
    seg_id = str(model_seg.get("id", segment_id or "") or "").strip()
    camera_name = str(camera_name or "").strip()

    def prepare_apply(_undo_token: str | None) -> dict[str, Any]:
        model_mtime = model_path.stat().st_mtime
        storyboard_duration = _segment_storyboard_duration(shots, min_index, max_index)
        applied_at = datetime.now(timezone.utc).isoformat()
        try:
            video_start = max(0.0, float(model_seg.get("video_start", 0.0) or 0.0))
        except (TypeError, ValueError):
            video_start = 0.0
        return {
            "apply_meta": {
                "segment_id": seg_id,
                "anchor_shot_id": shots[min_index].shot_id,
                "end_shot_id": shots[max_index].shot_id,
                "source_type": "model",
                "reference_model_path": model_rel,
                "model_mtime": model_mtime,
                "video_start": round(video_start, 3),
                "storyboard_duration": round(storyboard_duration, 3),
                "fit_mode": fit_mode,
                "applied_at": applied_at,
            },
            "segment_patch": {"video_start": round(video_start, 3), "source_type": "model"},
            "stamp_segment_id": seg_id,
            "stamp_applied_at": applied_at,
        }

    def apply_board(index: int, shot: Shot, segment_time: float) -> tuple[float, dict[str, Any]]:
        capture = capture_by_shot[shot.shot_id]
        animation_time = capture.get("animation_time")
        if animation_time is None:
            anim_time = segment_time
        else:
            anim_time = max(0.0, float(animation_time))
        shot_dir = pm.get_shot_dir(project, shot)
        raw_path = shot_dir / f"{shot.shot_id}_ref_raw.png"
        try:
            save_png_data_url(str(capture.get("data_url") or ""), raw_path)
            pm._apply_model_capture_to_shot(project, shot, raw_path, fit_mode)
        finally:
            raw_path.unlink(missing_ok=True)
        shot.ref_video_path = model_rel
        shot.ref_video_time = round(anim_time, 3)
        shot.ref_segment_time = round(segment_time, 3)
        camera_data = dict(shot.camera_data or {})
        camera_data["scene3d_time"] = round(anim_time, 3)
        if camera_name:
            camera_data["scene3d_camera"] = camera_name
        shot.camera_data = camera_data
        return anim_time, {"animation_time": round(anim_time, 3)}

    return _apply_ref_segment_template(
        project,
        min_index=min_index,
        max_index=max_index,
        seg=model_seg,
        segment_id=segment_id or None,
        source_type="model",
        prepare_apply=prepare_apply,
        apply_board=apply_board,
    )


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
    state: dict[str, Any] = {}

    def prepare_apply(_undo_token: str | None) -> dict[str, Any]:
        image_mtime = image_path.stat().st_mtime
        storyboard_duration = _segment_storyboard_duration(shots, min_index, max_index)
        fit_mode = normalize_reference_fit_mode(str(image_seg.get("fit_mode", "") or "fit"))
        state.update(fit_mode=fit_mode)
        return {
            "apply_meta": {
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
            "segment_patch": {"video_start": 0.0, "source_type": "image"},
        }

    def apply_board(_index: int, shot: Shot, segment_time: float) -> tuple[float, dict[str, Any]]:
        pm._apply_reference_frame_to_shot(project, shot, image_path, state["fit_mode"])
        shot.ref_video_path = image_rel
        shot.ref_video_time = 0.0
        shot.ref_segment_time = round(segment_time, 3)
        return segment_time, {}

    return _apply_ref_segment_template(
        project,
        min_index=min_index,
        max_index=max_index,
        seg=image_seg,
        segment_id=segment_id,
        source_type="image",
        prepare_apply=prepare_apply,
        apply_board=apply_board,
    )




def delete_ref_segment(project: Project, segment_id: str) -> dict[str, Any]:
    seg_id = str(segment_id or "").strip()
    if not seg_id:
        raise ValueError("Segment id is required.")

    segments = normalize_ref_segments(project.settings)
    segment = next((item for item in segments if item.get("id") == seg_id), None)
    if segment is None:
        raise ValueError(f"Segment not found: {seg_id}")

    segment_ref_path, _ = resolve_segment_reference(project, segment)

    anchor = str(segment.get("anchor_shot_id", "") or "").strip()
    end = str(segment.get("end_shot_id", "") or "").strip()
    try:
        min_index, max_index = _segment_board_range_by_shot_id(project.shots, anchor, end)
    except ValueError:
        min_index = max_index = -1

    range_shot_ids: set[str] = set()
    if min_index >= 0:
        for index in range(min_index, max_index + 1):
            range_shot_ids.add(project.shots[index].shot_id)

    cleared_ids: set[str] = set()
    for shot in project.shots:
        in_range = shot.shot_id in range_shot_ids
        if not _shot_should_clear_segment_bake(
            project,
            shot,
            seg_id,
            segment_ref_path,
            in_segment_range=in_range,
        ):
            continue
        _clear_ref_segment_bake_for_shot(project, shot, seg_id, segment_ref_path)
        cleared_ids.add(shot.shot_id)

    cleared = len(cleared_ids)

    ids_to_remove = {seg_id}
    for item in segments:
        item_id = str(item.get("id", "") or "").strip()
        if not item_id or item_id == seg_id:
            continue
        if _segments_overlap_records(project, segment, item):
            ids_to_remove.add(item_id)

    project.settings["ref_segments"] = [
        item for item in segments if str(item.get("id", "") or "").strip() not in ids_to_remove
    ]

    apply_meta = project.settings.get("ref_segment_apply") or {}
    if str(apply_meta.get("segment_id", "") or "").strip() == seg_id:
        project.settings.pop("ref_segment_apply", None)

    active_id = str(project.settings.get("active_ref_segment_id", "") or "").strip()
    if active_id == seg_id:
        remaining = normalize_ref_segments(project.settings)
        project.settings["active_ref_segment_id"] = remaining[0]["id"] if remaining else ""

    sync_ref_segment_settings(project)
    pm.save_settings(project)
    save_shots(project.root_path, project.shots)
    return {"deleted_segment_id": seg_id, "cleared_boards": cleared}
