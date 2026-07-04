"""Shot preview, thumbnail, and board background asset management.

Manages the three distinct asset roles for a shot:

  _preview.png     -- artist artwork (the drawing); tracked in image_path /
                      preview_image_path metadata.
  _background.png  -- reference plate (source for the SB bg linked smart object
                      in Photoshop); owned by the plugin; NEVER becomes the
                      artwork preview.
  _thumb.png       -- display cache regenerated on demand; derived from artwork
                      or background (in that priority order).

Key invariant enforced by this module:
  _background.png must NEVER appear in image_path or preview_image_path.
  relink_preview_image raises ValueError if the candidate is the background file.
"""
from __future__ import annotations

from pathlib import Path

from .file_transactions import atomic_copy_file
from .image_utils import board_background_filename, create_thumbnail, is_solid_color_image
from .models import Project, Shot
from .shot_files import get_shot_dir, resolve_project_relative_path


def _contained_project_path(project: Project, rel_path: str) -> Path | None:
    """Resolve a stored metadata path and return it only if it stays inside the project.

    Shot metadata (image_path / preview_image_path / thumbnail_path) can arrive from
    untrusted callers (e.g. POST /api/shots/restore builds a Shot straight from a
    client dict).  Because these paths are later handed to FileResponse, a value like
    an absolute path or ``..\\..\\`` escape would let a caller read arbitrary files.
    Resolve the path and confirm it is the project root or a descendant; otherwise
    return None so the caller falls through to the canonical on-disk location.
    """
    text = str(rel_path or "").strip()
    if not text:
        return None
    try:
        resolved = (project.root_path / text).resolve()
    except (OSError, ValueError):
        return None
    root = project.root_path.resolve()
    if resolved == root or root in resolved.parents:
        return resolved
    return None


def resolve_shot_preview_path(project: Project, shot: Shot) -> Path | None:
    """Find the best on-disk preview image for a shot.

    Checks: preview_image_path, image_path (if different), then the
    canonical on-disk path <shot_id>_preview.png.  Returns the first
    path that exists, or None.  Metadata-supplied paths are containment-checked
    so a hostile value cannot escape the project folder.
    """
    candidates: list[Path] = []
    preview_candidate = _contained_project_path(project, shot.preview_image_path)
    if preview_candidate is not None:
        candidates.append(preview_candidate)
    if shot.image_path and shot.image_path != shot.preview_image_path:
        image_candidate = _contained_project_path(project, shot.image_path)
        if image_candidate is not None:
            candidates.append(image_candidate)
    shot_dir = get_shot_dir(project, shot)
    candidates.append(shot_dir / f"{shot.shot_id}_preview.png")
    for path in candidates:
        if path.is_file():
            return path
    return None


def resolve_shot_thumbnail_path(project: Project, shot: Shot) -> Path | None:
    """Find the best on-disk thumbnail for timeline / filmstrip display.

    Falls back through: thumbnail_path metadata, canonical _thumb.png,
    preview path, and finally the background plate.
    """
    candidates: list[Path] = []
    thumbnail_candidate = _contained_project_path(project, shot.thumbnail_path)
    if thumbnail_candidate is not None:
        candidates.append(thumbnail_candidate)
    shot_dir = get_shot_dir(project, shot)
    candidates.append(shot_dir / f"{shot.shot_id}_thumb.png")
    preview_path = resolve_shot_preview_path(project, shot)
    if preview_path is not None:
        candidates.append(preview_path)
    background_path = get_shot_board_background_path(project, shot)
    if background_path is not None:
        candidates.append(background_path)
    for path in candidates:
        if path.is_file():
            return path
    return None


def get_shot_board_background_path(project: Project, shot: Shot) -> Path | None:
    """Return the dedicated background-plate path, or None if absent.

    The board background reference is ONLY the dedicated background file --
    never the shot preview.  The preview is the artist's drawing; treating
    it as the background would bake the drawing into the PSD as an SB bg
    layer, which the preview composite then hides, producing a blank board.
    This mirrors the Photoshop plugin's resolveBoardBackgroundEntry logic.
    """
    shot_dir = get_shot_dir(project, shot)
    dedicated = shot_dir / board_background_filename(shot.shot_id)
    if dedicated.is_file():
        return dedicated
    return None


def remove_board_background_for_shot(project: Project, shot: Shot) -> None:
    """Drop only the reference background, preserving the artist's drawing.

    Unlike remove_image_for_shot, this leaves image_path / preview_image_path /
    thumbnail_path intact so a board the artist has drawn on keeps its
    illustration when its reference is removed.
    """
    shot_dir = get_shot_dir(project, shot)
    (shot_dir / board_background_filename(shot.shot_id)).unlink(missing_ok=True)


def _save_board_background_copy(source_path: Path, destination_path: Path) -> Path:
    """Copy the board background file to its canonical location atomically."""
    return atomic_copy_file(source_path, destination_path)


def _set_shot_preview_paths(project: Project, shot: Shot, preview_path: Path) -> None:
    """Set image_path, preview_image_path, and thumbnail_path from the given preview file.

    This is the single write point for artwork metadata paths.  Callers must
    ensure preview_path is never the _background.png file; use relink_preview_image
    for the validated external entry point.

    Thumbnail generation is treated as a recoverable cache step: if it fails
    (e.g. disk full, PIL error), image_path and preview_image_path are still
    committed (the preview file exists at this point) and thumbnail_path is
    left at its previous value so the frontend can regenerate it on demand.
    """
    # Set critical artwork metadata first — the preview file is safely on disk.
    shot.image_path = preview_path.relative_to(project.root_path).as_posix()
    shot.preview_image_path = shot.image_path
    # Thumbnail is a display cache; failure must not roll back the artwork paths above.
    try:
        thumbnail_path = create_thumbnail(
            preview_path,
            get_shot_dir(project, shot) / f"{shot.shot_id}_thumb.png",
        )
        shot.thumbnail_path = thumbnail_path.relative_to(project.root_path).as_posix()
    except Exception:  # noqa: BLE001
        pass  # thumbnail_path stays at prior value; frontend regenerates on next load


def _refresh_thumbnail_for_shot(project: Project, shot: Shot) -> Path | None:
    """Refresh the _thumb.png cache for a shot.  Never touches metadata paths.

    image_path / preview_image_path are artist-artwork fields and are
    never written here.  The frontend uses the has_board_background flag
    (computed in app_state) to decide when to render the background plate
    as a display fallback.

    Priority:
    1. Non-solid artist artwork (_preview.png or current image_path).
    2. Reference background plate (_background.png).
    3. Nothing available -- returns None.
    """
    shot_dir = get_shot_dir(project, shot)
    thumb_path = shot_dir / f"{shot.shot_id}_thumb.png"

    preview_path = resolve_shot_preview_path(project, shot)
    has_artwork = (
        preview_path is not None
        and preview_path.is_file()
        and not is_solid_color_image(preview_path)
    )

    if has_artwork:
        thumbnail = create_thumbnail(preview_path, thumb_path)
        shot.thumbnail_path = thumbnail.relative_to(project.root_path).as_posix()
        return thumbnail

    bg_path = get_shot_board_background_path(project, shot)
    if bg_path is None:
        return None

    thumbnail = create_thumbnail(bg_path, thumb_path)
    shot.thumbnail_path = thumbnail.relative_to(project.root_path).as_posix()
    return thumbnail


def relink_preview_image(project: Project, shot: Shot, preview_rel: str) -> Path:
    """Set image_path / preview_image_path from a validated project-relative path.

    Raises ValueError if the path is the background plate.  The background
    plate must NEVER become the artwork preview -- accepting it would let any
    caller set image_path / preview_image_path to the background file, which
    is exactly the corruption the asset ownership model is designed to prevent.
    """
    candidate = resolve_project_relative_path(project, preview_rel)
    if candidate.name == board_background_filename(shot.shot_id):
        raise ValueError(
            f"Background plate cannot be used as preview metadata: {preview_rel}"
        )
    if not candidate.is_file():
        raise FileNotFoundError(f"Preview not found: {preview_rel}")
    _set_shot_preview_paths(project, shot, candidate)
    return candidate


def relink_shot_preview_from_disk(project: Project, shot: Shot) -> bool:
    """Restore preview metadata when the PNG exists on disk but paths were cleared.

    Returns True if paths were restored, False if nothing changed.
    """
    if shot.preview_image_path or shot.image_path:
        return False
    preview_path = resolve_shot_preview_path(project, shot)
    if preview_path is None or is_solid_color_image(preview_path):
        return False
    _set_shot_preview_paths(project, shot, preview_path)
    return True
