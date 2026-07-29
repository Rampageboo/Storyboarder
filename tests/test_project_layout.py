from __future__ import annotations

import json
from pathlib import Path

import pytest

from storyboard_tool import project_manager
from storyboard_tool.models import Project
from storyboard_tool.project_layout import (
    LAYOUT_1,
    LAYOUT_2,
    MAX_STORAGE_REVISION,
    PROJECT_JSON_VERSION,
    LayoutDisabledError,
    ProjectIntegrityError,
    ProjectPathError,
    ProjectSchemaError,
    ensure_no_casefold_collisions,
    parse_project_manifest,
    project_relative_posix,
    resolve_project_path,
)


def test_layout1_roots_preserve_root_path_behavior(tmp_path: Path) -> None:
    project = Project(root_path=tmp_path)

    assert project.layout == LAYOUT_1
    assert project.project_root == tmp_path
    assert project.metadata_root == tmp_path
    assert project.json_path == tmp_path / "project.json"
    assert project.shots_dir == tmp_path / "shots"


def test_layout2_model_distinguishes_project_and_metadata_roots(tmp_path: Path) -> None:
    project_root = tmp_path / "Portable"
    metadata_root = project_root / ".storyboarder" / "work"
    project = Project(
        root_path=metadata_root,
        project_root_path=project_root,
        layout=LAYOUT_2,
        project_id="stable-project-id",
        storage_revision=7,
    )

    assert project.project_root == project_root
    assert project.metadata_root == metadata_root
    assert project.json_path == metadata_root / "project.json"


@pytest.mark.parametrize("version", [1, 2, 3, PROJECT_JSON_VERSION])
def test_supported_layout1_versions_default_missing_layout(version: int) -> None:
    spec = parse_project_manifest({"version": version})

    assert spec.schema_version == version
    assert spec.layout == LAYOUT_1
    assert spec.project_id == ""
    assert spec.storage_revision == 0


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"version": None},
        {"version": True},
        {"version": 0},
        {"version": 5},
        {"version": "4"},
        {"version": 4, "layout": 0},
        {"version": 4, "layout": 3},
        {"version": 4, "layout": "2"},
    ],
)
def test_unknown_or_malformed_schema_values_fail_closed(payload: dict) -> None:
    with pytest.raises(ProjectSchemaError):
        parse_project_manifest(payload)


@pytest.mark.parametrize(
    "fields",
    [
        {},
        {"project_id": ""},
        {"project_id": " id "},
        {"project_id": "id", "storage_revision": None},
        {"project_id": "id", "storage_revision": True},
        {"project_id": "id", "storage_revision": -1},
        {"project_id": "id", "storage_revision": MAX_STORAGE_REVISION + 1},
    ],
)
def test_layout2_requires_stable_id_and_bounded_revision(fields: dict) -> None:
    with pytest.raises(ProjectSchemaError):
        parse_project_manifest({"version": 4, "layout": 2, **fields})


def test_layout2_schema_can_be_validated_but_open_is_disabled(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    manifest = {
        "version": 4,
        "layout": 2,
        "project_id": "stable-project-id",
        "storage_revision": 0,
    }
    (root / "project.json").write_text(json.dumps(manifest), encoding="utf-8")

    assert parse_project_manifest(manifest).layout == LAYOUT_2
    with pytest.raises(LayoutDisabledError, match="not enabled"):
        project_manager.open_project(root / "project.json")
    assert sorted(path.name for path in root.iterdir()) == ["project.json"]


def test_layout2_save_is_disabled_before_writing(tmp_path: Path) -> None:
    metadata_root = tmp_path / ".storyboarder" / "work"
    project = Project(
        root_path=metadata_root,
        project_root_path=tmp_path,
        layout=LAYOUT_2,
        project_id="stable-project-id",
        storage_revision=0,
    )

    with pytest.raises(LayoutDisabledError, match="not enabled"):
        project_manager.save_project(project)
    assert not metadata_root.exists()


def test_new_layout1_manifest_uses_schema_v4_without_layout_fields(tmp_path: Path) -> None:
    project = project_manager.create_project(tmp_path)
    manifest = json.loads(project.json_path.read_text(encoding="utf-8"))

    assert manifest == {"version": PROJECT_JSON_VERSION}
    assert project.layout == LAYOUT_1


def test_uxp_offline_manifest_writers_mirror_schema_v4() -> None:
    plugin_root = Path(__file__).resolve().parents[1] / "photoshop_uxp_plugin"

    assert "version: 4" in (plugin_root / "backend_client.js").read_text(encoding="utf-8")
    panel = (plugin_root / "panel.js").read_text(encoding="utf-8")
    assert panel.count("version || 4") == 2
    adapter = (plugin_root / "panel_storage_adapter.js").read_text(encoding="utf-8")
    assert "const PROJECT_JSON_VERSION = 4;" in adapter


@pytest.mark.parametrize(
    "value",
    [
        "/absolute/file.png",
        "//server/share/file.png",
        r"\\server\share\file.png",
        r"C:\project\file.png",
        "C:/project/file.png",
        "C:project/file.png",
        r"shots\board.png",
        "../outside.png",
        "shots/../outside.png",
        "./shots/board.png",
        "shots/./board.png",
        "shots//board.png",
        "shots/board.png/",
        " shots/board.png",
        "shots/board.png ",
        "shots/file:name.png",
    ],
)
def test_resolver_rejects_nonportable_or_escaping_paths(tmp_path: Path, value: str) -> None:
    project = Project(root_path=tmp_path)

    with pytest.raises(ProjectPathError):
        resolve_project_path(project, value)


def test_persisted_path_wins_and_default_is_used_only_when_empty(tmp_path: Path) -> None:
    project = Project(root_path=tmp_path)

    assert resolve_project_path(project, "custom/board.png", default="shots/default.png") == (
        tmp_path / "custom" / "board.png"
    ).resolve()
    assert resolve_project_path(project, "", default="shots/default.png") == (
        tmp_path / "shots" / "default.png"
    ).resolve()


def test_missing_stored_target_is_integrity_error_not_default_rebind(tmp_path: Path) -> None:
    project = Project(root_path=tmp_path)
    (tmp_path / "shots").mkdir()
    (tmp_path / "shots" / "default.png").write_bytes(b"default")

    with pytest.raises(ProjectIntegrityError, match="Stored project path target is missing"):
        resolve_project_path(
            project,
            "custom/missing.png",
            default="shots/default.png",
            must_exist=True,
        )


def test_required_suffix_is_checked_after_safe_resolution(tmp_path: Path) -> None:
    project = Project(root_path=tmp_path)

    with pytest.raises(ProjectPathError, match="extensions"):
        resolve_project_path(project, "shots/board.png", required_suffixes=(".psd",))


def test_casefold_collision_in_persisted_paths_is_rejected() -> None:
    with pytest.raises(ProjectPathError, match="case-fold collision"):
        ensure_no_casefold_collisions(["Images/Shots/A.png", "images/shots/a.PNG"])


def test_casefold_collision_on_disk_is_rejected_when_host_allows_it(tmp_path: Path) -> None:
    first = tmp_path / "Images"
    second = tmp_path / "images"
    first.mkdir()
    try:
        second.mkdir()
    except FileExistsError:
        pytest.skip("Host filesystem is case-insensitive.")
    project = Project(root_path=tmp_path)

    with pytest.raises(ProjectPathError, match="Case-fold collision"):
        resolve_project_path(project, "Images/board.png")


def test_reparse_escape_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    link = tmp_path / "linked"
    link.mkdir()
    project = Project(root_path=tmp_path)
    original_resolve = Path.resolve

    def resolve_with_reparse_escape(
        path: Path,
        strict: bool = False,
    ) -> Path:
        if path == link:
            return outside.resolve()
        return original_resolve(path, strict=strict)

    monkeypatch.setattr(Path, "resolve", resolve_with_reparse_escape)

    with pytest.raises(ProjectPathError, match="reparse point"):
        resolve_project_path(project, "linked/asset.png")


def test_absolute_path_converts_to_project_relative_posix(tmp_path: Path) -> None:
    project = Project(root_path=tmp_path)

    assert project_relative_posix(project, tmp_path / "Images" / "Shots" / "A.png") == (
        "Images/Shots/A.png"
    )


def test_project_relative_conversion_rejects_project_root_and_outside(tmp_path: Path) -> None:
    project = Project(root_path=tmp_path)

    with pytest.raises(ProjectPathError):
        project_relative_posix(project, tmp_path)
    with pytest.raises(ProjectPathError):
        project_relative_posix(project, tmp_path.parent / "outside.png")
