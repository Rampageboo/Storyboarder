"""Project integrity validation.

validate_project_integrity reports structural and ownership violations
without mutating any data or raising exceptions.  Designed for non-fatal
health checks: callers receive a list of typed issue dicts and decide what
to do with them.

Checks performed:
- Duplicate shot IDs.
- Missing shot directories.
- image_path / preview_image_path pointing to the background plate.
- Path-traversal in metadata paths (escaping project root).
- source_file_path pointing to a non-existent file.
"""
from __future__ import annotations

from pathlib import Path

from .image_utils import board_background_filename
from .models import Project
from .shot_files import get_shot_dir


def validate_project_integrity(project: Project) -> list[dict]:
    """Check project data for structural and ownership violations.

    Returns a list of issue dicts (empty list = clean).  Missing generated
    files such as thumbnails and notes are not flagged -- they are
    recoverable on demand.
    """
    issues: list[dict] = []
    seen_ids: set[str] = set()
    root = project.root_path.resolve()

    for shot in project.shots:
        if shot.shot_id in seen_ids:
            issues.append({"kind": "duplicate_shot_id", "shot_id": shot.shot_id})
        seen_ids.add(shot.shot_id)

        if not get_shot_dir(project, shot).is_dir():
            issues.append({
                "kind": "missing_shot_dir",
                "shot_id": shot.shot_id,
                "path": str(get_shot_dir(project, shot)),
            })

        # image_path / preview_image_path must never be the background plate.
        bg_filename = board_background_filename(shot.shot_id)
        for field in ("image_path", "preview_image_path"):
            value = getattr(shot, field, "") or ""
            if value and Path(value).name == bg_filename:
                issues.append({
                    "kind": "metadata_points_to_background",
                    "shot_id": shot.shot_id,
                    "field": field,
                    "value": value,
                })

        # All metadata paths must stay inside the project root (no traversal).
        for field in ("image_path", "preview_image_path", "thumbnail_path", "source_file_path"):
            value = getattr(shot, field, "") or ""
            if not value:
                continue
            try:
                resolved = (project.root_path / value).resolve()
                if resolved != root and root not in resolved.parents:
                    issues.append({
                        "kind": "path_traversal",
                        "shot_id": shot.shot_id,
                        "field": field,
                        "value": value,
                    })
            except (ValueError, OSError):
                issues.append({
                    "kind": "invalid_path",
                    "shot_id": shot.shot_id,
                    "field": field,
                    "value": value,
                })

        # source_file_path: warn if linked but file is missing on disk.
        if shot.source_file_path:
            if not (project.root_path / shot.source_file_path).is_file():
                issues.append({
                    "kind": "missing_source_file",
                    "shot_id": shot.shot_id,
                    "path": shot.source_file_path,
                })

    return issues
