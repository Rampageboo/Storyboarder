"""Project integrity validation.

validate_project_integrity reports structural and ownership violations
without mutating any data or raising exceptions.  Designed for non-fatal
health checks: callers receive a list of typed issue dicts and decide what
to do with them.

Checks performed:
- Duplicate shot IDs.
- Missing shot directories.
- image_path / preview_image_path pointing to a background or Codex layer.
- Path-traversal in metadata paths (escaping project root).
- source_file_path pointing to a non-existent file.
"""
from __future__ import annotations

from pathlib import Path

from .image_utils import board_background_filename, codex_layer_filename
from .models import Project
from .project_layout import ProjectPathError, resolve_project_path
from .shot_files import get_shot_dir


def validate_project_integrity(project: Project) -> list[dict]:
    """Check project data for structural and ownership violations.

    Returns a list of issue dicts (empty list = clean).  Missing generated
    files such as thumbnails and notes are not flagged -- they are
    recoverable on demand.
    """
    issues: list[dict] = []
    seen_ids: set[str] = set()
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

        # Artwork metadata must never point at a managed background/Codex layer.
        bg_filename = board_background_filename(shot.shot_id)
        codex_filename = codex_layer_filename(shot.shot_id)
        managed_filenames = {bg_filename, codex_filename}
        for field in ("image_path", "preview_image_path"):
            value = getattr(shot, field, "") or ""
            if value and Path(value).name in managed_filenames:
                issues.append({
                    "kind": (
                        "metadata_points_to_background"
                        if Path(value).name == bg_filename
                        else "metadata_points_to_codex_layer"
                    ),
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
                resolve_project_path(project, value, field_name=field)
            except ProjectPathError:
                issues.append({
                    "kind": "path_traversal",
                    "shot_id": shot.shot_id,
                    "field": field,
                    "value": value,
                })
            except OSError:
                issues.append({
                    "kind": "invalid_path",
                    "shot_id": shot.shot_id,
                    "field": field,
                    "value": value,
                })

        # source_file_path: warn if linked but file is missing on disk.
        if shot.source_file_path:
            try:
                source_exists = resolve_project_path(
                    project,
                    shot.source_file_path,
                    field_name="source_file_path",
                ).is_file()
            except ProjectPathError:
                source_exists = False
            if not source_exists:
                issues.append({
                    "kind": "missing_source_file",
                    "shot_id": shot.shot_id,
                    "path": shot.source_file_path,
                })

    return issues
