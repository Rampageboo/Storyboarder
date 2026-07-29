from __future__ import annotations

import re
from pathlib import Path

from storyboard_tool.models import Project


ROOT = Path(__file__).resolve().parents[1]
ROUTED_MODULES = (
    "api.py",
    "app_state.py",
    "asset_validation.py",
    "backend_service.py",
    "backups.py",
    "blender_bridge.py",
    "bpy_viewport.py",
    "canvas_settings.py",
    "export_service.py",
    "export_utils.py",
    "external_tools.py",
    "generation_service.py",
    "linked_sync.py",
    "live_bridge.py",
    "plugin_service.py",
    "preview_analysis_cache.py",
    "project_manager.py",
    "project_storage.py",
    "reference_segments.py",
    "scene2d.py",
    "scene3d.py",
    "service_exports.py",
    "shot_assets.py",
    "shot_files.py",
    "shot_store.py",
)


def test_layout1_static_roles_keep_existing_locations(tmp_path: Path) -> None:
    project = Project(root_path=tmp_path)

    assert project.json_path == tmp_path / "project.json"
    assert project.settings_path == tmp_path / "settings.json"
    assert project.images_dir == tmp_path / "images"
    assert project.shots_dir == tmp_path / "shots"
    assert project.references_dir == tmp_path / "references"
    assert project.scenes2d_dir == tmp_path / "scenes2d"
    assert project.scenes3d_dir == tmp_path / "scenes3d"
    assert project.exports_dir == tmp_path / "exports"
    assert project.scripts_dir == tmp_path / "scripts"
    assert project.backups_dir == tmp_path / "backups"


def test_persistent_path_consumers_do_not_bypass_project_layout() -> None:
    direct_alias_join = re.compile(
        r"\b(?:shot_dir|ref_dir|scene_dir|tx_dir|staging_dir|candidate_dir|output_dir)\s*/"
    )
    failures: list[str] = []

    for filename in ROUTED_MODULES:
        source = (ROOT / "storyboard_tool" / filename).read_text(encoding="utf-8")
        if "project.root_path" in source:
            failures.append(f"{filename}: uses legacy project.root_path directly")
        if re.search(r"relative_to\(project\.(?:root_path|project_root|metadata_root)", source):
            failures.append(f"{filename}: persists a path without project_relative_posix")
        if direct_alias_join.search(source):
            failures.append(f"{filename}: joins a project-path alias outside project_layout")

    assert failures == []


def test_raw_storage_roots_delegate_child_resolution() -> None:
    for filename in ("shot_store.py", "preview_analysis_cache.py", "project_storage.py"):
        source = (ROOT / "storyboard_tool" / filename).read_text(encoding="utf-8")
        assert "resolve_root_child" in source
        assert re.search(r"\b(?:project_root|metadata_root|root)\s*/", source) is None
