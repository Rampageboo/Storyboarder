"""Shared pytest setup.

Opening or creating a `.sbd` expands it into a private TEMP work tree. Tests
create documents constantly and almost never reach the app's cleanup path, so
without this the suite leaves a `storyboarder-*` directory in TEMP per document
— hundreds of megabytes after a few runs of the larger fixtures.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from storyboard_tool.project_document import WORKING_ROOT_PREFIX, remove_working_root


def _working_roots() -> set[Path]:
    base = Path(tempfile.gettempdir())
    try:
        return {path for path in base.glob(f"{WORKING_ROOT_PREFIX}*") if path.is_dir()}
    except OSError:
        return set()


@pytest.fixture(scope="session", autouse=True)
def _remove_test_working_roots():
    """Delete work trees the run created, keeping ones that predate it.

    Session-scoped on purpose: TEMP holds thousands of unrelated entries, so
    scanning it around every test cost the suite ~40s for no extra safety.
    """
    before = _working_roots()
    yield
    for root in _working_roots() - before:
        remove_working_root(root)
