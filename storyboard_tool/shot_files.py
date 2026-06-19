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


def get_shot_dir(project: Project, shot: Shot) -> Path:
    """Return the canonical directory for a shot's files."""
    return project.shots_dir / shot.shot_id


def shot_has_psd_canvas(project: Project, shot: Shot) -> bool:
    """True when the shot folder contains a linked Photoshop canvas."""
    if shot.source_file_path:
        path = project.root_path / shot.source_file_path
        if path.is_file() and is_psd_path(path):
            return True
    fallback = get_shot_dir(project, shot) / f"{shot.shot_id}.psd"
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
    path_text = str(rel_path or "").strip()
    if not path_text:
        raise ValueError("Project-relative path is required.")
    resolved = (project.root_path / path_text).resolve()
    root = project.root_path.resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError("Path must be inside the project.")
    if required_suffixes is not None:
        suffixes = tuple(str(suffix).lower() for suffix in required_suffixes)
        if resolved.suffix.lower() not in suffixes:
            raise ValueError(f"Path must use one of these extensions: {', '.join(required_suffixes)}")
    return resolved
