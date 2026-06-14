from __future__ import annotations

import json
import shutil
from pathlib import Path

from . import project_manager as pm
from .image_utils import (
    board_background_filename,
    create_blank_psd,
    create_solid_preview_png,
    create_thumbnail,
    is_solid_color_image,
    normalize_hex_color,
)
from .linked_sync import linked_mtime
from .models import Project, Shot


def normalize_canvas_size(width: int, height: int) -> tuple[int, int]:
    w = min(max(int(width), 320), 8192)
    h = min(max(int(height), 180), 8192)
    return w, h


def get_canvas_size(project: Project) -> tuple[int, int]:
    try:
        width = int(project.settings.get("canvas_width", 1920) or 1920)
    except (TypeError, ValueError):
        width = 1920
    try:
        height = int(project.settings.get("canvas_height", 1080) or 1080)
    except (TypeError, ValueError):
        height = 1080
    return normalize_canvas_size(width, height)


def shot_is_blank_canvas(project: Project, shot: Shot) -> bool:
    if shot.preview_image_path or shot.image_path:
        linked = project.root_path / (shot.preview_image_path or shot.image_path)
        if linked.is_file() and not is_solid_color_image(linked):
            return False
    return not shot_has_artwork_preview(shot)


def persist_canvas_size(
    project: Project,
    width: int,
    height: int,
    *,
    apply_to_blank_shots: bool = False,
) -> tuple[int, int, int]:
    canvas_width, canvas_height = normalize_canvas_size(width, height)
    project.settings["canvas_width"] = canvas_width
    project.settings["canvas_height"] = canvas_height
    pm.save_settings(project)
    write_canvas_color_files(project, get_canvas_color(project))
    rebuilt = 0
    if apply_to_blank_shots:
        for shot in project.shots:
            if not shot_is_blank_canvas(project, shot):
                continue
            create_canvas_for_shot(project, shot, canvas_width, canvas_height)
            rebuilt += 1
        if rebuilt:
            pm.save_project(project)
    return canvas_width, canvas_height, rebuilt


def get_canvas_color(project: Project) -> str:
    return normalize_hex_color(str(project.settings.get("canvas_background_color", "#E8E8E8")))


def persist_canvas_color(project: Project, color: str, shot: Shot | None = None) -> str:
    normalized = normalize_hex_color(color)
    project.settings["canvas_background_color"] = normalized
    pm.save_settings(project)
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
        pm.save_project(project)
    return changed


def _sync_shot_canvas_color_assets(project: Project, shot: Shot, color: str) -> bool:
    shot_dir = pm.get_shot_dir(project, shot)
    shot_dir.mkdir(parents=True, exist_ok=True)
    preview_path = shot_dir / f"{shot.shot_id}_preview.png"
    thumb_path = shot_dir / f"{shot.shot_id}_thumb.png"
    width, height = get_canvas_size(project)

    if not shot_has_artwork_preview(shot):
        create_solid_preview_png(preview_path, width, height, color)
        created_thumb = create_thumbnail(preview_path, thumb_path)
        shot.thumbnail_path = created_thumb.relative_to(project.root_path).as_posix()
        return True

    linked_preview = project.root_path / (shot.preview_image_path or shot.image_path)
    if linked_preview.is_file() and is_solid_color_image(linked_preview):
        create_solid_preview_png(linked_preview, width, height, color)
        created_thumb = create_thumbnail(linked_preview, thumb_path)
        shot.thumbnail_path = created_thumb.relative_to(project.root_path).as_posix()
        shot.preview_image_path = ""
        shot.image_path = ""
        return True

    return False


def write_canvas_color_files(project: Project, color: str, shot: Shot | None = None) -> None:
    normalized = normalize_hex_color(color)
    canvas_width, canvas_height = get_canvas_size(project)
    payload = {
        "canvas_background_color": normalized,
        "canvas_width": canvas_width,
        "canvas_height": canvas_height,
        "shot_id": shot.shot_id if shot else "",
        "source_file_path": shot.source_file_path if shot else "",
    }
    payload_text = json.dumps(payload, indent=2)
    color_text = f"{normalized}\n"

    targets = [project.root_path]
    if shot is not None:
        targets.append(pm.get_shot_dir(project, shot))

    for target_dir in targets:
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / "canvas_color.txt").write_text(color_text, encoding="utf-8")
        (target_dir / "storyboard_bridge.json").write_text(payload_text, encoding="utf-8")


def create_canvas_for_shot(
    project: Project,
    shot: Shot,
    width: int | None = None,
    height: int | None = None,
    background_color: str | None = None,
) -> Path:
    default_width, default_height = get_canvas_size(project)
    canvas_width, canvas_height = normalize_canvas_size(
        default_width if width is None else width,
        default_height if height is None else height,
    )
    shot_dir = pm.get_shot_dir(project, shot)
    color = persist_canvas_color(
        project,
        background_color or get_canvas_color(project),
    )
    background_path = pm.get_shot_board_background_path(project, shot)
    psd_path = create_blank_psd(
        shot_dir / f"{shot.shot_id}.psd",
        canvas_width,
        canvas_height,
        background_color=color,
    )
    pm.sync_psd_board_background(project, shot, psd_path)
    preview_path = shot_dir / f"{shot.shot_id}_preview.png"
    if background_path is not None:
        bg_dest = shot_dir / board_background_filename(shot.shot_id)
        pm._save_board_background_copy(background_path, bg_dest)
        if not preview_path.is_file() or is_solid_color_image(preview_path):
            source = bg_dest if bg_dest.is_file() else background_path
            if source.resolve() != preview_path.resolve():
                shutil.copy2(source, preview_path)
        pm._set_shot_preview_paths(project, shot, preview_path)
    else:
        preview_path = create_solid_preview_png(preview_path, canvas_width, canvas_height, color)
        _set_shot_canvas_thumbnail(project, shot, preview_path)
    shot.source_file_path = psd_path.relative_to(project.root_path).as_posix()
    shot.source_sync_mtime = linked_mtime(project, shot)
    write_canvas_color_files(project, color, shot)
    return psd_path


def write_bridge_file(project: Project, shot: Shot | None = None) -> None:
    write_canvas_color_files(project, get_canvas_color(project), shot)


def _set_shot_canvas_thumbnail(project: Project, shot: Shot, preview_path: Path) -> None:
    """Keep the in-app canvas on the configured color until Photoshop sync adds artwork."""
    thumbnail_path = create_thumbnail(preview_path, pm.get_shot_dir(project, shot) / f"{shot.shot_id}_thumb.png")
    shot.thumbnail_path = thumbnail_path.relative_to(project.root_path).as_posix()
    shot.preview_image_path = ""
    shot.image_path = ""
