"""In-memory project-state snapshot and rollback.

The ``mutate_project`` context manager takes a snapshot
of ``project.shots`` and ``project.settings`` before the guarded block runs
and restores that snapshot if the block raises.  It does not protect
filesystem side-effects (PNG writes, PSD creation) — those are the caller's
responsibility.

Atomic file I/O for the on-disk project files lives in project_manager via
``_atomic_write_json``. ``metadata_transaction`` additionally coordinates the
Layout 1 metadata files and app-state flags; its storage imports stay local.
"""

from __future__ import annotations

import contextlib
import copy
from collections.abc import Generator

from .models import Project, Shot


@contextlib.contextmanager
def mutate_project(project: Project) -> Generator[None, None, None]:
    """Snapshot and conditionally restore in-memory project state.

    On enter: deep-copies ``project.shots`` and ``project.settings``.
    On success: yields normally; the caller's changes are kept.
    On exception: restores both collections to the snapshot, then re-raises.

    Usage::

        with project_transaction.mutate_project(project):
            apply_ref_segment_to_boards(project, anchor, end, ...)
        # if the call above raises, project.shots and project.settings are
        # restored to their state before this block was entered.
    """
    shots_backup = [Shot.from_dict(s.to_dict()) for s in project.shots]
    settings_backup = copy.deepcopy(project.settings)
    try:
        yield
    except Exception:
        project.shots = shots_backup
        project.settings = settings_backup
        raise


@contextlib.contextmanager
def metadata_transaction(app):
    """Rollback Layout 1 canonical metadata plus memory for graph-aware writes.

    Layout 2 uses its recoverable work-tree transaction in mutation_executor.
    Artwork is never snapshotted or rewritten by a graph update.
    """
    from . import project_manager
    from .file_transactions import rollback_paths

    project = app.state.project
    before = {name: getattr(app.state, name, None) for name in ("dirty", "project_disk_mtime")}
    paths = [project.json_path, project.settings_path,
             project_manager.shots_json_path(project.metadata_root),
             project_manager.shots_csv_path(project.metadata_root)]
    try:
        with mutate_project(project), rollback_paths(paths):
            yield
    except BaseException:
        for name, value in before.items():
            setattr(app.state, name, value)
        raise
