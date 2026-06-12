from __future__ import annotations

from pathlib import Path

from PIL import Image

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

    source_path = _best_source_path(project, shot)
    if source_path is None:
        return {"synced": False, "message": "Linked files are missing."}

    preview_path = _preview_path(project, shot)
    preview_path.parent.mkdir(parents=True, exist_ok=True)

    if is_psd_path(source_path):
        export_psd_composite_to_png(source_path, preview_path)
    elif source_path.suffix.lower() in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp"}:
        if source_path.resolve() != preview_path.resolve():
            with Image.open(source_path) as image:
                if image.mode not in ("RGB", "RGBA"):
                    image = image.convert("RGBA")
                image.save(preview_path, "PNG")
        # Preview was already updated on disk; just refresh thumbnail below.
    else:
        return {"synced": False, "message": f"Unsupported source format: {source_path.suffix}"}

    shot.preview_image_path = preview_path.relative_to(project.root_path).as_posix()
    shot.image_path = shot.preview_image_path
    thumb_path = create_thumbnail(preview_path, preview_path.parent / f"{shot.shot_id}_thumb.png")
    shot.thumbnail_path = thumb_path.relative_to(project.root_path).as_posix()
    shot.source_sync_mtime = linked_mtime(project, shot)

    return {
        "synced": True,
        "message": f"Synced from {source_path.name}",
        "source": source_path.name,
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


def _best_source_path(project: Project, shot: Shot) -> Path | None:
    """Pick the linked file with the newest modification time."""
    candidates: list[Path] = []
    if shot.source_file_path:
        candidates.append(project.root_path / shot.source_file_path)
    if shot.preview_image_path:
        candidates.append(project.root_path / shot.preview_image_path)
    if shot.image_path and shot.image_path != shot.preview_image_path:
        candidates.append(project.root_path / shot.image_path)

    existing = [path.resolve() for path in candidates if path.is_file()]
    if not existing:
        return None

    return max(existing, key=lambda path: path.stat().st_mtime)


def _preview_path(project: Project, shot: Shot) -> Path:
    if shot.preview_image_path:
        return project.root_path / shot.preview_image_path
    return project.shots_dir / shot.shot_id / f"{shot.shot_id}_preview.png"
