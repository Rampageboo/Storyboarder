"""In-memory project-state snapshot and rollback.

Provides a single context manager, ``mutate_project``, that takes a snapshot
of ``project.shots`` and ``project.settings`` before the guarded block runs
and restores that snapshot if the block raises.  It does not protect
filesystem side-effects (PNG writes, PSD creation) — those are the caller's
responsibility.

Atomic file I/O for the on-disk project files lives in project_manager via
``_atomic_write_json``; this module deliberately has no dependency on it.
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
