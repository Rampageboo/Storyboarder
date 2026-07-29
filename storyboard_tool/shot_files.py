"""Shot directory and file path utilities.

Low-level, side-effect-free helpers for:
- resolving a shot's canonical directory path
- detecting whether a shot has a linked Photoshop canvas
- validating and resolving project-relative paths

No functions here mutate shot metadata or write files; they compute
and validate paths only.  Functions that create directories or write
files belong in project_manager (they orchestrate multiple concerns).
"""
from __future__ import annotations

from pathlib import Path

from .image_utils import is_psd_path
from .models import Project, Shot
from .project_layout import resolve_project_path, resolve_shot_asset


def get_shot_dir(project: Project, shot: Shot) -> Path:
    """Return the canonical shot-assets parent (shared in Layout 2)."""
    return resolve_shot_asset(project, shot.shot_id, "preview").parent


def shot_has_psd_canvas(project: Project, shot: Shot) -> bool:
    """True when the shot folder contains a linked Photoshop canvas."""
    if shot.source_file_path:
        path = resolve_project_path(project, shot.source_file_path)
        if path.is_file() and is_psd_path(path):
            return True
    fallback = resolve_shot_asset(project, shot.shot_id, "source_psd")
    return fallback.is_file() and is_psd_path(fallback)


def resolve_project_relative_path(
    project: Project,
    rel_path: str,
    *,
    required_suffixes: tuple[str, ...] | None = None,
) -> Path:
    """Resolve and validate a project-relative path.

    Raises ValueError for missing paths, path-traversal, or wrong extension.
    Does NOT check whether the path exists on disk.
    """
    return resolve_project_path(
        project,
        rel_path,
        required_suffixes=required_suffixes,
    )
