"""Shared pytest setup."""
from __future__ import annotations

from pathlib import Path

from storyboard_tool import project_manager
from storyboard_tool.models import Project


def make_project(parent: Path, name: str = "Demo", **kwargs) -> Project:
    """Create a project folder ``parent/name`` through the real creation path."""
    return project_manager.create_project(Path(parent) / f"{name}.sbd", **kwargs)
