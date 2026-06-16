from __future__ import annotations

import shutil
from datetime import datetime

from .models import Project
from .shot_store import shots_csv_path

# Keep the most recent N timestamped backup sets.
MAX_BACKUP_SETS = 50


def _backup_stamps(backups_dir) -> list[str]:
    stamps: list[str] = []
    for path in backups_dir.glob("project_*.json"):
        name = path.stem
        if name.startswith("project_"):
            stamps.append(name[len("project_") :])
    stamps.sort(reverse=True)
    return stamps


def _backup_filenames(stamp: str) -> tuple[str, ...]:
    return (
        f"project_{stamp}.json",
        f"shots_{stamp}.csv",
        f"settings_{stamp}.json",
    )


def _prune_old_backups(project: Project, *, keep: int = MAX_BACKUP_SETS) -> None:
    backups_dir = project.backups_dir
    if not backups_dir.is_dir() or keep < 1:
        return
    for stamp in _backup_stamps(backups_dir)[keep:]:
        for filename in _backup_filenames(stamp):
            path = backups_dir / filename
            if path.is_file():
                path.unlink()


def _write_backup(project: Project) -> None:
    project.backups_dir.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    if project.json_path.is_file():
        shutil.copy2(project.json_path, project.backups_dir / f"project_{stamp}.json")
    csv_path = shots_csv_path(project.root_path)
    if csv_path.is_file():
        shutil.copy2(csv_path, project.backups_dir / f"shots_{stamp}.csv")
    if project.settings_path.is_file():
        shutil.copy2(project.settings_path, project.backups_dir / f"settings_{stamp}.json")
    _prune_old_backups(project)
