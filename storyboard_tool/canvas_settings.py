from __future__ import annotations

import json
from pathlib import Path

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


def _pm():
    # Lazy import: project_manager re-exports this module at the end of its load.
    from . import project_manager

    return project_manager


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
        linked = _pm().resolve_project_path(project, shot.preview_image_path or shot.image_path)
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
    _pm().save_settings(project)
    write_canvas_color_files(project, get_canvas_color(project))
    rebuilt = 0
    if apply_to_blank_shots:
        for shot in project.shots:
            if not shot_is_blank_canvas(project, shot):
                continue
            create_canvas_for_shot(project, shot, canvas_width, canvas_height)
            rebuilt += 1
        if rebuilt:
            _pm().save_project(project)
    return canvas_width, canvas_height, rebuilt


def get_canvas_color(project: Project) -> str:
    return normalize_hex_color(str(project.settings.get("canvas_background_color", "#E8E8E8")))


def persist_canvas_color(project: Project, color: str, shot: Shot | None = None) -> str:
    normalized = normalize_hex_color(color)
    project.settings["canvas_background_color"] = normalized
    _pm().save_settings(project)
    write_canvas_color_files(project, normalized, shot)
    return normalized


def shot_has_artwork_preview(shot: Shot) -> bool:
    return bool(shot.preview_image_path or shot.image_path)


def sync_canvas_color_to_shots(project: Project, color: str) -> bool:
    """Legacy helper: previously generated per-shot solid previews.

    The React UI now treats the canvas background as a global, non-destructive UI
    backdrop. We avoid generating per-shot "default background" PNGs so deleting
    a preview never removes the canvas background.
    """
    normalized = normalize_hex_color(color)
    changed = False
    for shot in project.shots:
        if _sync_shot_canvas_color_assets(project, shot, normalized):
            changed = True
    if changed:
        _pm().save_project(project)
    return changed


def _sync_shot_canvas_color_assets(project: Project, shot: Shot, color: str) -> bool:
    # Photoshop-backed boards own their preview export — never rewrite or unlink it
    # when canvas color sync runs (e.g. on project reload after switching boards).
    if _pm().shot_has_psd_canvas(project, shot):
        return False

    shot_dir = _pm().get_shot_dir(project, shot)
    shot_dir.mkdir(parents=True, exist_ok=True)
    preview_path = _pm().resolve_project_child(
        project,
        "shots",
        shot.shot_id,
        f"{shot.shot_id}_preview.png",
    )
    thumb_path = _pm().resolve_project_child(
        project,
        "shots",
        shot.shot_id,
        f"{shot.shot_id}_thumb.png",
    )

    if not shot_has_artwork_preview(shot):
        # Do not generate per-shot default preview/thumbnail files. If old solid
        # placeholders exist on disk from a previous version, clean them up.
        changed = False
        if preview_path.is_file() and is_solid_color_image(preview_path):
            preview_path.unlink(missing_ok=True)
            changed = True
        if thumb_path.is_file() and is_solid_color_image(thumb_path):
            thumb_path.unlink(missing_ok=True)
            changed = True
        if shot.thumbnail_path:
            shot.thumbnail_path = ""
            changed = True
        return changed

    linked_preview = _pm().resolve_project_path(
        project,
        shot.preview_image_path or shot.image_path,
    )
    if linked_preview.is_file() and is_solid_color_image(linked_preview):
        # Avoid rewriting the shot's preview fields; the UI will render the global
        # canvas background when no artwork exists.
        return False

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

    targets = [
        (
            _pm().resolve_project_child(project, "canvas_color.txt"),
            _pm().resolve_project_child(project, "storyboard_bridge.json"),
        )
    ]
    if shot is not None:
        targets.append(
            (
                _pm().resolve_project_child(
                    project,
                    "shots",
                    shot.shot_id,
                    "canvas_color.txt",
                ),
                _pm().resolve_project_child(
                    project,
                    "shots",
                    shot.shot_id,
                    "storyboard_bridge.json",
                ),
            )
        )

    for color_path, bridge_path in targets:
        color_path.parent.mkdir(parents=True, exist_ok=True)
        color_path.write_text(color_text, encoding="utf-8")
        bridge_path.write_text(payload_text, encoding="utf-8")


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
    color = persist_canvas_color(
        project,
        background_color or get_canvas_color(project),
    )
    background_path = _pm().get_shot_board_background_path(project, shot)
    psd_path = create_blank_psd(
        _pm().resolve_project_child(
            project,
            "shots",
            shot.shot_id,
            f"{shot.shot_id}.psd",
        ),
        canvas_width,
        canvas_height,
        background_color=color,
    )
    _pm().sync_psd_board_background(project, shot, psd_path)
    if background_path is not None:
        bg_dest = _pm().resolve_project_child(
            project,
            "shots",
            shot.shot_id,
            board_background_filename(shot.shot_id),
        )
        _pm()._save_board_background_copy(background_path, bg_dest)
    else:
        # No per-shot default background PNG; the canvas background is a UI backdrop.
        # The PSD already contains the background color layer.
        shot.thumbnail_path = ""
        shot.preview_image_path = ""
        shot.image_path = ""
    shot.source_file_path = _pm().project_relative_posix(project, psd_path)
    shot.source_sync_mtime = linked_mtime(project, shot)
    write_canvas_color_files(project, color, shot)
    return psd_path


def write_bridge_file(project: Project, shot: Shot | None = None) -> None:
    write_canvas_color_files(project, get_canvas_color(project), shot)


def _set_shot_canvas_thumbnail(project: Project, shot: Shot, preview_path: Path) -> None:
    """Keep the in-app canvas on the configured color until Photoshop sync adds artwork."""
    thumbnail_path = create_thumbnail(
        preview_path,
        _pm().resolve_project_child(
            project,
            "shots",
            shot.shot_id,
            f"{shot.shot_id}_thumb.png",
        ),
    )
    shot.thumbnail_path = _pm().project_relative_posix(project, thumbnail_path)
    shot.preview_image_path = ""
    shot.image_path = ""
