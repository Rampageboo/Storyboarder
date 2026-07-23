"""Project manifest and settings I/O helpers.

Handles the storage-level concerns of a project's non-shot files:
- Project directory structure creation.
- Atomic JSON writes (crash-safe temp-file swap).
- settings.json read/write with defaults and normalization.
- Project file modification-time tracking for change detection.

Shot metadata storage lives in storyboard_tool.shot_store (shots.json, shots.csv).
Settings normalization that needs reference_segments is imported lazily inside
load_settings to avoid a circular import: reference_segments imports project_manager
at module level, so project_storage must not trigger that chain at import time.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .models import Project
from .shot_store import shots_csv_mtime, shots_json_mtime

PROJECT_JSON_VERSION = 3

DEFAULT_SETTINGS: dict = {
    "autosave": True,
    "autosave_interval_minutes": 5,
    "pdf_layout": "two_per_page",
    "recent_projects": [],
    "backup_on_save": True,
    "photoshop_path": "",
    "blender_path": "",
    "canvas_background_color": "#E8E8E8",
    "canvas_width": 1920,
    "canvas_height": 1080,
    "preheat_photoshop_on_open": False,
    "character_bible_prompt": "",
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


def ensure_project_dirs(root: Path) -> None:
    """Create the standard project directory structure under *root*."""
    root.mkdir(parents=True, exist_ok=True)
    for dirname in ("shots", "references", "exports", "scripts", "backups", "scene3d", "scenes2d", "scenes3d"):
        (root / dirname).mkdir(exist_ok=True)


def atomic_write_text(path: Path, text: str) -> None:
    """Write *text* to *path* atomically via a sibling temp file.

    A crash mid-write leaves at most a stale .tmp file — the destination
    is never left in a partially-written state.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f"{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as file:
            file.write(text)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def atomic_write_json(path: Path, data: Any) -> None:
    """Write *data* as JSON to *path* atomically via a sibling temp file."""
    atomic_write_text(path, json.dumps(data, indent=2, ensure_ascii=False))


def load_settings(project: Project) -> dict:
    """Read and normalize settings.json; returns DEFAULT_SETTINGS copy on failure.

    reference_segments is imported lazily here to avoid a circular import
    (reference_segments imports project_manager at module level).
    """
    # Lazy import: reference_segments imports project_manager at module level, so
    # importing it here at call time (not at project_storage import time) avoids
    # triggering that circular chain before project_manager is fully initialized.
    from .reference_segments import ensure_reference_library, normalize_reference_links  # noqa: PLC0415

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


def save_settings(project: Project) -> None:
    """Persist project settings to settings.json, filling in any missing defaults."""
    settings = DEFAULT_SETTINGS.copy()
    settings.update(project.settings)
    project.settings = settings
    atomic_write_json(project.settings_path, settings)


def project_disk_mtime(project: Project) -> float:
    """Return the most recent mtime across canonical project files.

    shots.json is checked first (canonical store).  shots.csv is the
    fallback for legacy projects that have not yet migrated to shots.json.
    """
    manifest_mtime = project.json_path.stat().st_mtime if project.json_path.is_file() else 0.0
    settings_mtime = project.settings_path.stat().st_mtime if project.settings_path.is_file() else 0.0
    shots_mtime = shots_json_mtime(project.root_path)
    # shots.csv only matters for legacy projects that have not migrated to shots.json yet.
    if shots_mtime <= 0.0:
        shots_mtime = shots_csv_mtime(project.root_path)
    scenes2d_dir = project.root_path / "scenes2d"
    scenes2d_index = scenes2d_dir / "scenes2d.json"
    scenes2d_mtime = scenes2d_index.stat().st_mtime if scenes2d_index.is_file() else 0.0
    if scenes2d_dir.is_dir():
        for meta_path in scenes2d_dir.glob("*/*_meta.json"):
            if meta_path.is_file():
                scenes2d_mtime = max(scenes2d_mtime, meta_path.stat().st_mtime)
    scenes3d_dir = project.root_path / "scenes3d"
    scenes3d_index = scenes3d_dir / "scenes3d.json"
    scenes3d_mtime = scenes3d_index.stat().st_mtime if scenes3d_index.is_file() else 0.0
    if scenes3d_dir.is_dir():
        for meta_path in scenes3d_dir.glob("scene3d_*/scene3d_*_meta.json"):
            if meta_path.is_file():
                scenes3d_mtime = max(scenes3d_mtime, meta_path.stat().st_mtime)
    return max(manifest_mtime, settings_mtime, shots_mtime, scenes2d_mtime, scenes3d_mtime)
