from __future__ import annotations

from pathlib import Path

from .image_utils import create_thumbnail, export_psd_composite_to_png, is_psd_path
from .models import Project, Shot


def linked_mtime(project: Project, shot: Shot) -> float:
    """Return the latest modification time among linked source/preview files."""
    latest = 0.0
    for rel_path in (shot.source_file_path, shot.preview_image_path, shot.image_path):
        if not rel_path:
            continue
        path = project.root_path / rel_path
        if path.is_file():
            latest = max(latest, path.stat().st_mtime)
    shot_dir = project.shots_dir / shot.shot_id
    for file_name in (f"{shot.shot_id}.psd", f"{shot.shot_id}_preview.png"):
        path = shot_dir / file_name
        if path.is_file():
            latest = max(latest, path.stat().st_mtime)
    return latest


def sync_shot_from_linked_files(project: Project, shot: Shot, force: bool = False) -> dict[str, object]:
    """
    Refresh preview/thumbnail when linked PSD or raster source changed on disk.
    Returns a result dict with synced flag and optional message.
    """
    current_mtime = linked_mtime(project, shot)
    if current_mtime <= 0:
        return {"synced": False, "message": "No linked files to sync."}

    stored_mtime = float(getattr(shot, "source_sync_mtime", 0.0) or 0.0)
    if not force and current_mtime <= stored_mtime:
        return {"synced": False, "message": "Already up to date."}

    preview_path = _preview_path(project, shot)
    preview_path.parent.mkdir(parents=True, exist_ok=True)
    psd_path = _linked_psd_path(project, shot)

    preview_exists = preview_path.is_file()
    psd_exists = psd_path is not None
    if not preview_exists and not psd_exists:
        return {"synced": False, "message": "Linked files are missing."}

    preview_mtime = preview_path.stat().st_mtime if preview_exists else 0.0
    psd_mtime = psd_path.stat().st_mtime if psd_exists else 0.0

    # The Photoshop plugin saves PSD + preview together. Prefer the PNG when it
    # is at least as new as the PSD — psd_tools compositing can disagree with
    # Photoshop's own export (hidden reference layers, effects, etc.).
    if preview_exists and (not psd_exists or preview_mtime + 1.0 >= psd_mtime):
        source_name = preview_path.name
    elif psd_exists:
        export_psd_composite_to_png(psd_path, preview_path)
        source_name = psd_path.name
    else:
        return {"synced": False, "message": "Linked files are missing."}

    shot.preview_image_path = preview_path.relative_to(project.root_path).as_posix()
    shot.image_path = shot.preview_image_path
    thumb_path = create_thumbnail(preview_path, preview_path.parent / f"{shot.shot_id}_thumb.png")
    shot.thumbnail_path = thumb_path.relative_to(project.root_path).as_posix()
    shot.source_sync_mtime = linked_mtime(project, shot)

    return {
        "synced": True,
        "message": f"Synced from {source_name}",
        "source": source_name,
    }


def sync_project(project: Project, force: bool = False) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for shot in project.shots:
        if not shot.source_file_path and not shot.preview_image_path and not shot.image_path:
            continue
        result = sync_shot_from_linked_files(project, shot, force=force)
        if result.get("synced"):
            results.append({"shot_id": shot.shot_id, **result})
    return results


def _linked_psd_path(project: Project, shot: Shot) -> Path | None:
    if shot.source_file_path:
        candidate = project.root_path / shot.source_file_path
        if candidate.is_file() and is_psd_path(candidate):
            return candidate
    fallback = project.shots_dir / shot.shot_id / f"{shot.shot_id}.psd"
    if fallback.is_file() and is_psd_path(fallback):
        return fallback
    return None


def _preview_path(project: Project, shot: Shot) -> Path:
    if shot.preview_image_path:
        return project.root_path / shot.preview_image_path
    return project.shots_dir / shot.shot_id / f"{shot.shot_id}_preview.png"
