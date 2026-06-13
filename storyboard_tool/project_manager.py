from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, BinaryIO

from .image_utils import (
    board_background_filename,
    copy_and_convert_image,
    copy_and_convert_image_stream,
    create_blank_canvas,
    create_blank_psd,
    create_solid_preview_png,
    create_thumbnail,
    ensure_psd_board_background_layer,
    export_psd_composite_to_png,
    is_psd_path,
    is_solid_color_image,
    normalize_hex_color,
    save_png_data_url,
)
from .linked_sync import linked_mtime, sync_shot_from_linked_files
from .models import Project, Shot
from .shot_store import load_shots_csv, new_shot_id, save_shots_csv, shots_csv_mtime, shots_csv_path


PROJECT_JSON_VERSION = 3
DEFAULT_SETTINGS = {
    "autosave": True,
    "pdf_layout": "two_per_page",
    "recent_projects": [],
    "backup_on_save": True,
    "photoshop_path": "",
    "blender_path": "",
    "canvas_background_color": "#E8E8E8",
    "reference_video_path": "",
    "reference_model_path": "",
    "reference_image_path": "",
    "reference_segment_mode": "video",
    "reference_links": [],
    "ref_segment": {},
    "ref_segments": [],
    "active_ref_segment_id": "",
    "ref_segment_video": {},
    "ref_segment_apply": {},
}

BLEND_TEMPLATE_PATH = Path(__file__).resolve().parent / "assets" / "scene_template.blend"
REFERENCE_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp"}
REFERENCE_VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v"}
REFERENCE_MODEL_EXTENSIONS = {".glb", ".gltf"}


def new_ref_segment_id() -> str:
    import uuid

    return f"seg_{uuid.uuid4().hex[:10]}"


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
            reference_path = _normalize_rel_path(str(item.get("reference_path", "") or "").strip())
            normalized.append(
                {
                    "id": seg_id,
                    "anchor_shot_id": anchor,
                    "end_shot_id": end,
                    "video_start": round(video_start, 3),
                    "source_type": source_type,
                    "reference_id": reference_id,
                    "reference_path": reference_path,
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
                ref_path = _normalize_rel_path(str(settings.get("reference_video_path", "") or "").strip())
            elif mode == "model":
                ref_path = _normalize_rel_path(str(settings.get("reference_model_path", "") or "").strip())
            elif mode == "image":
                ref_path = _normalize_rel_path(str(settings.get("reference_image_path", "") or "").strip())
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
    ref_path = _normalize_rel_path(str(segment.get("reference_path", "") or "").strip())
    if ref_path:
        target = next((item for item in links if item["path"] == ref_path), None)
        media_type = target["type"] if target else str(segment.get("source_type", "") or "none")
        return ref_path, media_type
    source_type = str(segment.get("source_type", "") or "").strip().lower()
    if source_type == "video":
        ref_path = _normalize_rel_path(str(project.settings.get("reference_video_path", "") or "").strip())
    elif source_type == "model":
        ref_path = _normalize_rel_path(str(project.settings.get("reference_model_path", "") or "").strip())
    elif source_type == "image":
        ref_path = _normalize_rel_path(str(project.settings.get("reference_image_path", "") or "").strip())
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


def create_project(parent_or_project_dir: Path) -> Project:
    root = parent_or_project_dir
    if root.name != "Storyboard_Project":
        root = root / "Storyboard_Project"

    root.mkdir(parents=True, exist_ok=True)
    _ensure_project_dirs(root)

    project = Project(root_path=root, settings=DEFAULT_SETTINGS.copy())
    save_project(project)
    ensure_project_blend_file(project)
    return project


def get_canvas_color(project: Project) -> str:
    return normalize_hex_color(str(project.settings.get("canvas_background_color", "#E8E8E8")))


def persist_canvas_color(project: Project, color: str, shot: Shot | None = None) -> str:
    normalized = normalize_hex_color(color)
    project.settings["canvas_background_color"] = normalized
    save_settings(project)
    write_canvas_color_files(project, normalized, shot)
    sync_canvas_color_to_shots(project, normalized)
    return normalized


def shot_has_artwork_preview(shot: Shot) -> bool:
    return bool(shot.preview_image_path or shot.image_path)


def sync_canvas_color_to_shots(project: Project, color: str) -> bool:
    """Keep blank-canvas shots aligned with the global canvas color."""
    normalized = normalize_hex_color(color)
    changed = False
    for shot in project.shots:
        if _sync_shot_canvas_color_assets(project, shot, normalized):
            changed = True
    if changed:
        save_project(project)
    return changed


def _sync_shot_canvas_color_assets(project: Project, shot: Shot, color: str) -> bool:
    shot_dir = get_shot_dir(project, shot)
    shot_dir.mkdir(parents=True, exist_ok=True)
    preview_path = shot_dir / f"{shot.shot_id}_preview.png"
    thumb_path = shot_dir / f"{shot.shot_id}_thumb.png"

    if not shot_has_artwork_preview(shot):
        create_solid_preview_png(preview_path, 1920, 1080, color)
        created_thumb = create_thumbnail(preview_path, thumb_path)
        shot.thumbnail_path = created_thumb.relative_to(project.root_path).as_posix()
        return True

    linked_preview = project.root_path / (shot.preview_image_path or shot.image_path)
    if linked_preview.is_file() and is_solid_color_image(linked_preview):
        create_solid_preview_png(linked_preview, 1920, 1080, color)
        created_thumb = create_thumbnail(linked_preview, thumb_path)
        shot.thumbnail_path = created_thumb.relative_to(project.root_path).as_posix()
        shot.preview_image_path = ""
        shot.image_path = ""
        return True

    return False


def write_canvas_color_files(project: Project, color: str, shot: Shot | None = None) -> None:
    normalized = normalize_hex_color(color)
    payload = {
        "canvas_background_color": normalized,
        "shot_id": shot.shot_id if shot else "",
        "source_file_path": shot.source_file_path if shot else "",
    }
    payload_text = json.dumps(payload, indent=2)
    color_text = f"{normalized}\n"

    targets = [project.root_path]
    if shot is not None:
        targets.append(get_shot_dir(project, shot))

    for target_dir in targets:
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / "canvas_color.txt").write_text(color_text, encoding="utf-8")
        (target_dir / "storyboard_bridge.json").write_text(payload_text, encoding="utf-8")


def project_disk_mtime(project: Project) -> float:
    json_mtime = project.json_path.stat().st_mtime if project.json_path.is_file() else 0.0
    csv_mtime = shots_csv_mtime(project.root_path)
    return max(json_mtime, csv_mtime)


def reload_project_if_changed(project: Project, loaded_mtime: float) -> tuple[Project, float, bool]:
    """Reload project.json from disk when the plugin or another tool updated it."""
    disk_mtime = project_disk_mtime(project)
    if disk_mtime <= loaded_mtime + 1e-6:
        return project, loaded_mtime, False
    reloaded = open_project(project.json_path)
    return reloaded, disk_mtime, True


def open_project(project_json_path: Path) -> Project:
    if not project_json_path.exists():
        raise FileNotFoundError(f"Project file not found: {project_json_path}")

    try:
        payload = json.loads(project_json_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid project.json: {exc}") from exc

    project = Project(root_path=project_json_path.parent)
    _ensure_project_dirs(project.root_path)
    project.settings = _load_settings(project)
    sync_ref_segment_settings(project)

    csv_path = shots_csv_path(project.root_path)
    if csv_path.is_file():
        project.shots = load_shots_csv(csv_path)
    else:
        shots_data = payload.get("shots")
        if isinstance(shots_data, list):
            project.shots = [Shot.from_dict(item) for item in shots_data if isinstance(item, dict)]
        else:
            project.shots = []

    for shot in project.shots:
        _ensure_shot_files(project, shot)

    migrated = _migrate_project_storage(project, payload)
    save_settings(project)
    color = get_canvas_color(project)
    write_canvas_color_files(project, color)
    sync_canvas_color_to_shots(project, color)
    ensure_project_blend_file(project)
    return project


def save_project(project: Project) -> None:
    _ensure_project_dirs(project.root_path)
    if project.settings.get("backup_on_save", True):
        _write_backup(project)
    payload = {"version": PROJECT_JSON_VERSION}
    project.json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    save_shots_csv(project.root_path, project.shots)
    save_settings(project)


def save_settings(project: Project) -> None:
    settings = DEFAULT_SETTINGS.copy()
    settings.update(project.settings)
    project.settings = settings
    project.settings_path.write_text(json.dumps(settings, indent=2), encoding="utf-8")


def add_shot(project: Project, *, after_index: int | None = None) -> Shot:
    shot = Shot(shot_id=new_shot_id())
    _ensure_shot_files(project, shot)
    create_canvas_for_shot(project, shot)
    if after_index is None:
        project.shots.append(shot)
    else:
        _require_index(project, after_index)
        project.shots.insert(after_index + 1, shot)
    return shot


def duplicate_shot(project: Project, index: int) -> Shot:
    _require_index(project, index)
    source = project.shots[index]
    duplicate = Shot.from_dict(source.to_dict())
    duplicate.shot_id = new_shot_id()
    duplicate.title = f"{source.title} Copy".strip()
    duplicate.image_path = ""
    duplicate.preview_image_path = ""
    duplicate.thumbnail_path = ""
    duplicate.source_file_path = ""
    duplicate.annotation_path = ""
    duplicate.reference_image_paths = []
    duplicate.ref_video_path = ""
    duplicate.ref_video_time = 0.0
    duplicate.ref_segment_time = 0.0
    duplicate.comments = []
    _ensure_shot_files(project, duplicate)
    project.shots.insert(index + 1, duplicate)
    create_canvas_for_shot(project, duplicate)
    return duplicate


def delete_shot(project: Project, index: int) -> Shot:
    _require_index(project, index)
    return project.shots.pop(index)


def restore_shot(project: Project, shot_data: dict[str, Any], index: int) -> Shot:
    index = max(0, min(int(index), len(project.shots)))
    shot = Shot.from_dict(shot_data)
    if any(existing.shot_id == shot.shot_id for existing in project.shots):
        raise ValueError(f"Shot already exists: {shot.shot_id}")
    project.shots.insert(index, shot)
    return shot


def reorder_shots(project: Project, shot_ids: list[str]) -> None:
    by_id = {shot.shot_id: shot for shot in project.shots}
    if len(shot_ids) != len(project.shots) or set(shot_ids) != set(by_id.keys()):
        raise ValueError("Shot order mismatch")
    project.shots = [by_id[shot_id] for shot_id in shot_ids]


def move_shot_up(project: Project, index: int) -> int:
    _require_index(project, index)
    if index <= 0:
        return index
    project.shots[index - 1], project.shots[index] = project.shots[index], project.shots[index - 1]
    return index - 1


def move_shot_down(project: Project, index: int) -> int:
    _require_index(project, index)
    if index >= len(project.shots) - 1:
        return index
    project.shots[index + 1], project.shots[index] = project.shots[index], project.shots[index + 1]
    return index + 1


def import_image_for_shot(project: Project, shot: Shot, source_path: Path) -> Path:
    shot_dir = get_shot_dir(project, shot)
    destination = shot_dir / f"{shot.shot_id}_preview.png"
    copied_path = copy_and_convert_image(source_path, destination)
    _save_board_background_copy(copied_path, shot_dir / board_background_filename(shot.shot_id))
    _set_shot_preview_paths(project, shot, copied_path)
    return copied_path


def import_image_stream_for_shot(
    project: Project,
    shot: Shot,
    source_stream: BinaryIO,
    source_suffix: str,
) -> Path:
    shot_dir = get_shot_dir(project, shot)
    destination = shot_dir / f"{shot.shot_id}_preview.png"
    copied_path = copy_and_convert_image_stream(source_stream, source_suffix, destination)
    _save_board_background_copy(copied_path, shot_dir / board_background_filename(shot.shot_id))
    _set_shot_preview_paths(project, shot, copied_path)
    return copied_path


def remove_image_for_shot(project: Project, shot: Shot) -> None:
    shot_dir = get_shot_dir(project, shot)
    (shot_dir / board_background_filename(shot.shot_id)).unlink(missing_ok=True)
    shot.image_path = ""
    shot.preview_image_path = ""
    shot.thumbnail_path = ""


def get_shot_board_background_path(project: Project, shot: Shot) -> Path | None:
    shot_dir = get_shot_dir(project, shot)
    dedicated = shot_dir / board_background_filename(shot.shot_id)
    if dedicated.is_file():
        return dedicated
    preview_rel = shot.preview_image_path or shot.image_path
    if not preview_rel:
        return None
    preview = project.root_path / preview_rel
    if not preview.is_file() or is_solid_color_image(preview):
        return None
    return preview


def sync_psd_board_background(project: Project, shot: Shot, psd_path: Path) -> bool:
    background_path = get_shot_board_background_path(project, shot)
    if background_path is None:
        return False
    return ensure_psd_board_background_layer(psd_path, background_path)


def _save_board_background_copy(source_path: Path, destination_path: Path) -> Path:
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    if source_path.resolve() == destination_path.resolve():
        return destination_path
    shutil.copy2(source_path, destination_path)
    return destination_path


def add_reference_image_stream(
    project: Project,
    shot: Shot,
    source_stream: BinaryIO,
    source_suffix: str,
) -> Path:
    shot_dir = get_shot_dir(project, shot)
    ref_dir = shot_dir / "references"
    next_number = len(shot.reference_image_paths) + 1
    destination = ref_dir / f"{shot.shot_id}_ref_{next_number:03d}.png"
    copied_path = copy_and_convert_image_stream(source_stream, source_suffix, destination)
    shot.reference_image_paths.append(copied_path.relative_to(project.root_path).as_posix())
    return copied_path


def _normalize_rel_path(path: str) -> str:
    return str(path or "").replace("\\", "/").strip()


def collect_reference_image_paths(project: Project) -> set[str]:
    referenced: set[str] = set()
    for shot in project.shots:
        for rel_path in shot.reference_image_paths:
            normalized = _normalize_rel_path(rel_path)
            if normalized:
                referenced.add(normalized)
    return referenced


def remove_reference_image(project: Project, shot: Shot, rel_path: str) -> None:
    normalized = _normalize_rel_path(rel_path)
    if not normalized:
        raise ValueError("Reference path is required.")
    current = {_normalize_rel_path(path) for path in shot.reference_image_paths}
    if normalized not in current:
        raise ValueError("Reference image not found on this board.")
    shot.reference_image_paths = [
        path for path in shot.reference_image_paths if _normalize_rel_path(path) != normalized
    ]


def set_reference_image_paths(project: Project, shot: Shot, paths: list[str]) -> None:
    shot.reference_image_paths = [
        _normalize_rel_path(path) for path in paths if _normalize_rel_path(path)
    ]


def cleanup_orphan_reference_images(project: Project) -> list[str]:
    root = project.root_path.resolve()
    referenced = collect_reference_image_paths(project)
    deleted: list[str] = []
    shots_dir = project.shots_dir
    if not shots_dir.is_dir():
        return deleted
    for ref_dir in shots_dir.glob("*/references"):
        if not ref_dir.is_dir():
            continue
        for file_path in ref_dir.iterdir():
            if not file_path.is_file():
                continue
            try:
                rel_path = file_path.relative_to(root).as_posix()
            except ValueError:
                continue
            if rel_path in referenced:
                continue
            file_path.unlink(missing_ok=True)
            deleted.append(rel_path)
    return deleted


def shutdown_reference_cleanup(project: Project | None, *, save_if_dirty: bool = True, dirty: bool = False) -> list[str]:
    if project is None:
        return []
    if save_if_dirty and dirty:
        save_project(project)
    return cleanup_orphan_reference_images(project)


def import_source_file_stream(
    project: Project,
    shot: Shot,
    source_stream: BinaryIO,
    filename: str,
) -> Path:
    suffix = Path(filename).suffix or ".psd"
    shot_dir = get_shot_dir(project, shot)
    destination = shot_dir / f"{shot.shot_id}{suffix}"
    with destination.open("wb") as file:
        shutil.copyfileobj(source_stream, file)
    shot.source_file_path = destination.relative_to(project.root_path).as_posix()
    if is_psd_path(destination):
        preview_path = export_psd_composite_to_png(destination, shot_dir / f"{shot.shot_id}_preview.png")
        _set_shot_preview_paths(project, shot, preview_path)
    shot.source_sync_mtime = linked_mtime(project, shot)
    return destination


def relink_preview_image(project: Project, shot: Shot, relative_path: str) -> Path:
    candidate = (project.root_path / relative_path).resolve()
    root = project.root_path.resolve()
    if root not in candidate.parents and candidate != root:
        raise ValueError("Preview path must be inside the project folder.")
    if not candidate.exists() or not candidate.is_file():
        raise FileNotFoundError(f"Preview image not found: {relative_path}")
    shot.preview_image_path = candidate.relative_to(project.root_path).as_posix()
    shot.image_path = shot.preview_image_path
    thumbnail_path = create_thumbnail(candidate, get_shot_dir(project, shot) / f"{shot.shot_id}_thumb.png")
    shot.thumbnail_path = thumbnail_path.relative_to(project.root_path).as_posix()
    return candidate


def create_canvas_for_shot(
    project: Project,
    shot: Shot,
    width: int = 1920,
    height: int = 1080,
    background_color: str | None = None,
) -> Path:
    shot_dir = get_shot_dir(project, shot)
    color = persist_canvas_color(
        project,
        background_color or get_canvas_color(project),
    )
    background_path = get_shot_board_background_path(project, shot)
    psd_path = create_blank_psd(
        shot_dir / f"{shot.shot_id}.psd",
        width,
        height,
        background_color=color,
    )
    sync_psd_board_background(project, shot, psd_path)
    preview_path = shot_dir / f"{shot.shot_id}_preview.png"
    if background_path is not None:
        bg_dest = shot_dir / board_background_filename(shot.shot_id)
        _save_board_background_copy(background_path, bg_dest)
        if not preview_path.is_file() or is_solid_color_image(preview_path):
            source = bg_dest if bg_dest.is_file() else background_path
            if source.resolve() != preview_path.resolve():
                shutil.copy2(source, preview_path)
        _set_shot_preview_paths(project, shot, preview_path)
    else:
        preview_path = create_solid_preview_png(preview_path, width, height, color)
        _set_shot_canvas_thumbnail(project, shot, preview_path)
    shot.source_file_path = psd_path.relative_to(project.root_path).as_posix()
    shot.source_sync_mtime = linked_mtime(project, shot)
    write_canvas_color_files(project, color, shot)
    return psd_path


def write_bridge_file(project: Project, shot: Shot | None = None) -> None:
    write_canvas_color_files(project, get_canvas_color(project), shot)


def save_drawing_for_shot(project: Project, shot: Shot, data_url: str) -> Path:
    shot_dir = get_shot_dir(project, shot)
    preview_path = save_png_data_url(data_url, shot_dir / f"{shot.shot_id}_preview.png")
    _set_shot_preview_paths(project, shot, preview_path)
    return preview_path


def sync_shot(project: Project, shot: Shot, force: bool = False) -> dict[str, object]:
    return sync_shot_from_linked_files(project, shot, force=force)


def normalize_reference_links(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    normalized: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        path = _normalize_rel_path(str(item.get("path") or item.get("url") or "").strip())
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
    video_path = _normalize_rel_path(str(settings.get("reference_video_path") or "").strip())
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
    model_path = _normalize_rel_path(str(settings.get("reference_model_path") or "").strip())
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
    image_path = _normalize_rel_path(str(settings.get("reference_image_path") or "").strip())
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
    scene3d_path = _normalize_rel_path(str((settings.get("scene3d") or {}).get("file_path", "") or "").strip())
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
    save_settings(project)
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
    target_path = _normalize_rel_path(target["path"])
    segments = normalize_ref_segments(project.settings)
    cleared_segments = False
    for segment in segments:
        seg_ref_id = str(segment.get("reference_id", "") or "").strip()
        seg_ref_path = _normalize_rel_path(str(segment.get("reference_path", "") or "").strip())
        if seg_ref_id == ref_id or (seg_ref_path and seg_ref_path == target_path):
            segment["reference_id"] = ""
            segment["reference_path"] = ""
            segment["source_type"] = "none"
            cleared_segments = True
    if cleared_segments:
        project.settings["ref_segments"] = segments
        sync_ref_segment_settings(project)
    active_video = _normalize_rel_path(str(project.settings.get("reference_video_path") or "").strip())
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
    active_model = _normalize_rel_path(str(project.settings.get("reference_model_path") or "").strip())
    if active_model == target["path"]:
        next_model = next((item["path"] for item in project.settings["reference_links"] if item["type"] == "model"), "")
        if next_model:
            _set_active_reference_model(project, next_model, save=False)
        else:
            project.settings["reference_model_path"] = ""
            if str(project.settings.get("reference_segment_mode") or "") == "model":
                project.settings["reference_segment_mode"] = "video"
    save_settings(project)


def _default_scene3d_meta(project: Project, relative_path: str, title: str = "") -> dict[str, Any]:
    existing = dict(project.settings.get("scene3d") or {})
    existing.update(
        {
            "source": "blender",
            "file_path": _normalize_rel_path(relative_path),
            "file_name": title or Path(relative_path).name,
            "follow_camera": existing.get("follow_camera", True) is not False,
            "program_lighting": existing.get("program_lighting", "auto"),
            "object_color_preview": existing.get("object_color_preview", True) is not False,
            "wireframe_mode": existing.get("wireframe_mode", "off"),
        }
    )
    return existing


def set_active_reference_model(project: Project, relative_path: str) -> None:
    relative_path = _normalize_rel_path(relative_path)
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
    relative_path = _normalize_rel_path(relative_path)
    project.settings["reference_model_path"] = relative_path
    project.settings["reference_segment_mode"] = "model"
    project.settings["scene3d"] = _default_scene3d_meta(project, relative_path)
    project.settings.pop("ref_segment_apply", None)
    if save:
        save_settings(project)


def set_active_reference_video(project: Project, relative_path: str) -> None:
    relative_path = _normalize_rel_path(relative_path)
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
    save_settings(project)


def _set_active_reference_video(project: Project, relative_path: str, *, save: bool = True) -> None:
    project.settings["reference_video_path"] = _normalize_rel_path(relative_path)
    project.settings["reference_segment_mode"] = "video"
    project.settings.pop("ref_segment_apply", None)
    project.settings.pop("ref_segment_video", None)
    _clear_shot_ref_video_fields(project)
    if save:
        save_settings(project)


def set_active_reference_image(project: Project, relative_path: str) -> None:
    relative_path = _normalize_rel_path(relative_path)
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
    relative_path = _normalize_rel_path(relative_path)
    project.settings["reference_image_path"] = relative_path
    project.settings["reference_segment_mode"] = "image"
    project.settings.pop("ref_segment_apply", None)
    if save:
        save_settings(project)


def open_project_file(
    project: Project,
    relative_path: str,
    app_path: str = "",
    shot: Shot | None = None,
) -> Path:
    if shot is not None:
        write_bridge_file(project, shot)
    file_path = (project.root_path / relative_path).resolve()
    root = project.root_path.resolve()
    if root not in file_path.parents and file_path != root:
        raise ValueError("File path must be inside the project folder.")
    if not file_path.exists() or not file_path.is_file():
        raise FileNotFoundError(f"File not found: {relative_path}")
    if shot is not None and is_psd_path(file_path):
        sync_psd_board_background(project, shot, file_path)
    if app_path:
        configured_app = Path(app_path).expanduser()
        if not configured_app.exists():
            raise FileNotFoundError(f"Configured editor not found: {configured_app}")
        subprocess.Popen([str(configured_app), str(file_path)])
    elif sys.platform.startswith("win"):
        os.startfile(file_path)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(file_path)])
    else:
        subprocess.Popen(["xdg-open", str(file_path)])
    return file_path


def get_shot_dir(project: Project, shot: Shot) -> Path:
    return project.shots_dir / shot.shot_id


def _require_index(project: Project, index: int) -> None:
    if index < 0 or index >= len(project.shots):
        raise IndexError("Shot index out of range.")


SCENE3D_EXTENSIONS = {".glb", ".gltf"}


def blend_template_path() -> Path:
    return BLEND_TEMPLATE_PATH


def get_project_blend_path(project: Project) -> Path:
    return project.root_path / "scene3d" / "scene.blend"


def ensure_project_blend_file(project: Project) -> Path:
    """Copy bundled scene_template.blend into the project when scene.blend is missing."""
    scene_dir = project.root_path / "scene3d"
    scene_dir.mkdir(parents=True, exist_ok=True)
    blend_path = get_project_blend_path(project)
    if not blend_path.exists():
        template = blend_template_path()
        if template.is_file():
            shutil.copy2(template, blend_path)
    scene_settings = dict(project.settings.get("scene3d") or {})
    if blend_path.exists():
        scene_settings["blend_file_path"] = blend_path.relative_to(project.root_path).as_posix()
    project.settings["scene3d"] = scene_settings
    save_settings(project)
    return blend_path


def open_blender_scene(project: Project) -> Path:
    from .system_utils import detect_blender_paths, resolve_blender_executable

    blend_path = ensure_project_blend_file(project)
    if not blend_path.exists():
        template = blend_template_path()
        if not template.is_file():
            raise FileNotFoundError(
                "scene3d/scene.blend is missing and no template was found. "
                "Place scene_template.blend in storyboard_tool/assets/."
            )
    blender_path = str(project.settings.get("blender_path", "")).strip()
    if not blender_path:
        candidates = detect_blender_paths()
        if candidates:
            blender_path = candidates[0]
    if not blender_path:
        raise FileNotFoundError("Blender path not configured. Open Blender Setup and choose blender.exe.")
    try:
        configured = resolve_blender_executable(blender_path)
    except (FileNotFoundError, ValueError) as exc:
        raise FileNotFoundError(str(exc)) from exc
    args = [str(configured)]
    if blend_path.exists():
        args.append(str(blend_path.resolve()))
    subprocess.Popen(args)
    return blend_path


def import_scene3d_stream(project: Project, source_stream: BinaryIO, filename: str) -> dict:
    suffix = Path(filename).suffix.lower()
    if suffix not in SCENE3D_EXTENSIONS:
        raise ValueError("Only .glb and .gltf Blender exports are supported.")
    scene_dir = project.root_path / "scene3d"
    scene_dir.mkdir(exist_ok=True)
    destination = scene_dir / f"scene{suffix}"
    with destination.open("wb") as file:
        shutil.copyfileobj(source_stream, file)
    relative_path = destination.relative_to(project.root_path).as_posix()
    scene_settings = dict(project.settings.get("scene3d") or {})
    scene_settings.update(
        {
            "source": "blender",
            "file_path": relative_path,
            "file_name": Path(filename).name,
        }
    )
    project.settings["scene3d"] = scene_settings
    save_settings(project)
    return scene_settings


def get_scene3d_file_path(project: Project) -> Path | None:
    relative_path = str((project.settings.get("scene3d") or {}).get("file_path", "")).strip()
    if not relative_path:
        return None
    candidate = (project.root_path / relative_path).resolve()
    root = project.root_path.resolve()
    if root not in candidate.parents and candidate != root:
        raise ValueError("Scene file path must be inside the project folder.")
    if not candidate.exists() or not candidate.is_file():
        raise FileNotFoundError(f"Scene file not found: {relative_path}")
    return candidate


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


def apply_ref_segment_to_boards(
    project: Project,
    anchor_index: int,
    end_index: int,
    segment_id: str | None = None,
) -> dict[str, Any]:
    from datetime import datetime, timezone

    from .video_utils import extract_video_frame_to_png, get_video_duration

    shots = project.shots
    if not shots:
        raise ValueError("Project has no boards.")
    min_index = max(0, min(int(anchor_index), int(end_index)))
    max_index = min(len(shots) - 1, max(int(anchor_index), int(end_index)))
    if min_index > max_index:
        raise ValueError("Invalid board range.")

    video_seg = find_ref_segment(project, segment_id) or {}
    video_rel, ref_type = resolve_segment_reference(project, video_seg)
    if ref_type != "video" or not video_rel:
        raise ValueError("Bind a reference video to this segment first.")
    video_path = (project.root_path / video_rel).resolve()
    root = project.root_path.resolve()
    if root not in video_path.parents and video_path != root:
        raise ValueError("Reference video path is outside the project.")
    if not video_path.is_file():
        raise FileNotFoundError(f"Reference video not found: {video_rel}")

    video_duration = get_video_duration(video_path)
    video_mtime = video_path.stat().st_mtime
    segment_offset = 0.0
    storyboard_duration = 0.0
    for index in range(min_index, max_index + 1):
        storyboard_duration += max(0.1, float(shots[index].duration_seconds or 3))

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
        shot_dir = get_shot_dir(project, shot)
        preview_path = shot_dir / f"{shot.shot_id}_preview.png"
        extract_video_frame_to_png(video_path, video_time, preview_path)
        _save_board_background_copy(preview_path, shot_dir / board_background_filename(shot.shot_id))
        _set_shot_preview_paths(project, shot, preview_path)
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

    project.settings["ref_segment_apply"] = {
        "segment_id": video_seg.get("id", segment_id or ""),
        "anchor_shot_id": shots[min_index].shot_id,
        "end_shot_id": shots[max_index].shot_id,
        "reference_video_path": video_rel,
        "video_mtime": video_mtime,
        "video_start": round(video_start, 3),
        "storyboard_duration": round(storyboard_duration, 3),
        "applied_at": datetime.now(timezone.utc).isoformat(),
    }
    project.settings["ref_segment"] = {
        "anchor_shot_id": shots[min_index].shot_id,
        "end_shot_id": shots[max_index].shot_id,
    }
    segments = normalize_ref_segments(project.settings)
    seg_id = str(video_seg.get("id", segment_id or "") or "").strip()
    for segment in segments:
        if seg_id and segment["id"] == seg_id:
            segment["video_start"] = round(video_start, 3)
            break
    project.settings["ref_segments"] = segments
    if seg_id:
        project.settings["active_ref_segment_id"] = seg_id
    sync_ref_segment_settings(project)
    save_settings(project)
    save_shots_csv(project.root_path, project.shots)
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
    if not shots:
        raise ValueError("Project has no boards.")
    min_index = max(0, min(int(anchor_index), int(end_index)))
    max_index = min(len(shots) - 1, max(int(anchor_index), int(end_index)))
    if min_index > max_index:
        raise ValueError("Invalid board range.")

    model_seg = find_ref_segment(project, segment_id) or {}
    model_rel, ref_type = resolve_segment_reference(project, model_seg)
    if ref_type != "model" or not model_rel:
        raise ValueError("Bind a reference GLB to this segment first.")
    model_path = (project.root_path / model_rel).resolve()
    root = project.root_path.resolve()
    if root not in model_path.parents and model_path != root:
        raise ValueError("Reference model path is outside the project.")
    if not model_path.is_file():
        raise FileNotFoundError(f"Reference model not found: {model_rel}")

    model_mtime = model_path.stat().st_mtime
    segment_offset = 0.0
    storyboard_duration = 0.0
    for index in range(min_index, max_index + 1):
        storyboard_duration += max(0.1, float(shots[index].duration_seconds or 3))

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

    project.settings["ref_segment_apply"] = {
        "segment_id": model_seg.get("id", segment_id or ""),
        "anchor_shot_id": shots[min_index].shot_id,
        "end_shot_id": shots[max_index].shot_id,
        "source_type": "model",
        "reference_model_path": model_rel,
        "model_mtime": model_mtime,
        "video_start": round(anim_start, 3),
        "storyboard_duration": round(storyboard_duration, 3),
        "applied_at": datetime.now(timezone.utc).isoformat(),
    }
    project.settings["ref_segment"] = {
        "anchor_shot_id": shots[min_index].shot_id,
        "end_shot_id": shots[max_index].shot_id,
    }
    segments = normalize_ref_segments(project.settings)
    seg_id = str(model_seg.get("id", segment_id or "") or "").strip()
    for segment in segments:
        if seg_id and segment["id"] == seg_id:
            segment["video_start"] = round(anim_start, 3)
            segment["source_type"] = "model"
            break
    project.settings["ref_segments"] = segments
    if seg_id:
        project.settings["active_ref_segment_id"] = seg_id
    sync_ref_segment_settings(project)
    save_settings(project)
    save_shots_csv(project.root_path, project.shots)
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
    if not shots:
        raise ValueError("Project has no boards.")
    min_index = max(0, min(int(anchor_index), int(end_index)))
    max_index = min(len(shots) - 1, max(int(anchor_index), int(end_index)))
    if min_index > max_index:
        raise ValueError("Invalid board range.")

    image_seg = find_ref_segment(project, segment_id) or {}
    image_rel, ref_type = resolve_segment_reference(project, image_seg)
    if ref_type != "image" or not image_rel:
        raise ValueError("Bind a reference image to this segment first.")
    image_path = (project.root_path / image_rel).resolve()
    root = project.root_path.resolve()
    if root not in image_path.parents and image_path != root:
        raise ValueError("Reference image path is outside the project.")
    if not image_path.is_file():
        raise FileNotFoundError(f"Reference image not found: {image_rel}")

    image_mtime = image_path.stat().st_mtime
    segment_offset = 0.0
    storyboard_duration = 0.0
    for index in range(min_index, max_index + 1):
        storyboard_duration += max(0.1, float(shots[index].duration_seconds or 3))

    applied: list[dict[str, Any]] = []
    for index in range(min_index, max_index + 1):
        shot = shots[index]
        segment_time = segment_offset
        shot_dir = get_shot_dir(project, shot)
        preview_path = shot_dir / f"{shot.shot_id}_preview.png"
        copy_and_convert_image(image_path, preview_path)
        _save_board_background_copy(preview_path, shot_dir / board_background_filename(shot.shot_id))
        _set_shot_preview_paths(project, shot, preview_path)
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

    project.settings["ref_segment_apply"] = {
        "segment_id": image_seg.get("id", segment_id or ""),
        "anchor_shot_id": shots[min_index].shot_id,
        "end_shot_id": shots[max_index].shot_id,
        "source_type": "image",
        "reference_image_path": image_rel,
        "image_mtime": image_mtime,
        "storyboard_duration": round(storyboard_duration, 3),
        "applied_at": datetime.now(timezone.utc).isoformat(),
    }
    project.settings["ref_segment"] = {
        "anchor_shot_id": shots[min_index].shot_id,
        "end_shot_id": shots[max_index].shot_id,
    }
    segments = normalize_ref_segments(project.settings)
    seg_id = str(image_seg.get("id", segment_id or "") or "").strip()
    for segment in segments:
        if seg_id and segment["id"] == seg_id:
            segment["video_start"] = 0.0
            segment["source_type"] = "image"
            break
    project.settings["ref_segments"] = segments
    if seg_id:
        project.settings["active_ref_segment_id"] = seg_id
    sync_ref_segment_settings(project)
    save_settings(project)
    save_shots_csv(project.root_path, project.shots)
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
            remove_image_for_shot(project, shot)
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
    save_settings(project)
    save_shots_csv(project.root_path, project.shots)
    return {"deleted_segment_id": seg_id, "cleared_boards": cleared}


def _ensure_project_dirs(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for dirname in ("shots", "references", "exports", "scripts", "backups", "scene3d"):
        (root / dirname).mkdir(exist_ok=True)


def _ensure_shot_files(project: Project, shot: Shot) -> None:
    shot_dir = get_shot_dir(project, shot)
    shot_dir.mkdir(parents=True, exist_ok=True)
    (shot_dir / "references").mkdir(exist_ok=True)
    if not shot.annotation_path:
        annotation_path = shot_dir / f"{shot.shot_id}_annotations.json"
        if not annotation_path.exists():
            annotation_path.write_text("[]", encoding="utf-8")
        shot.annotation_path = annotation_path.relative_to(project.root_path).as_posix()
    notes_path = shot_dir / f"{shot.shot_id}_notes.json"
    if not notes_path.exists():
        notes_path.write_text(json.dumps(shot.to_dict(), indent=2), encoding="utf-8")


def _set_shot_preview_paths(project: Project, shot: Shot, preview_path: Path) -> None:
    shot.image_path = preview_path.relative_to(project.root_path).as_posix()
    shot.preview_image_path = shot.image_path
    thumbnail_path = create_thumbnail(preview_path, get_shot_dir(project, shot) / f"{shot.shot_id}_thumb.png")
    shot.thumbnail_path = thumbnail_path.relative_to(project.root_path).as_posix()


def _set_shot_canvas_thumbnail(project: Project, shot: Shot, preview_path: Path) -> None:
    """Keep the in-app canvas on the configured color until Photoshop sync adds artwork."""
    thumbnail_path = create_thumbnail(preview_path, get_shot_dir(project, shot) / f"{shot.shot_id}_thumb.png")
    shot.thumbnail_path = thumbnail_path.relative_to(project.root_path).as_posix()
    shot.preview_image_path = ""
    shot.image_path = ""


def _load_settings(project: Project) -> dict:
    if not project.settings_path.exists():
        return DEFAULT_SETTINGS.copy()
    try:
        loaded = json.loads(project.settings_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return DEFAULT_SETTINGS.copy()
    settings = DEFAULT_SETTINGS.copy()
    if isinstance(loaded, dict):
        settings.update(loaded)
    settings["reference_links"] = normalize_reference_links(settings.get("reference_links"))
    ensure_reference_library(settings)
    return settings


def _migrate_project_storage(project: Project, payload: dict) -> bool:
    version = int(payload.get("version", 1) or 1)
    has_inline_shots = isinstance(payload.get("shots"), list)
    csv_path = shots_csv_path(project.root_path)
    needs_csv = not csv_path.is_file() or has_inline_shots or version < PROJECT_JSON_VERSION
    if not needs_csv:
        return False
    save_project(project)
    return True


def _write_backup(project: Project) -> None:
    project.backups_dir.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if project.json_path.is_file():
        shutil.copy2(project.json_path, project.backups_dir / f"project_{stamp}.json")
    csv_path = shots_csv_path(project.root_path)
    if csv_path.is_file():
        shutil.copy2(csv_path, project.backups_dir / f"shots_{stamp}.csv")
