from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import make_project
from storyboard_tool import project_manager
from storyboard_tool.models import Project
from storyboard_tool.project_layout import (
    MAX_STORAGE_REVISION,
    PROJECT_JSON_VERSION,
    ProjectIntegrityError,
    ProjectManifest,
    ProjectPathError,
    ProjectSchemaError,
    ensure_no_casefold_collisions,
    parse_project_manifest,
    project_relative_posix,
    resolve_project_path,
)


def test_model_distinguishes_project_and_metadata_roots(tmp_path: Path) -> None:
    project = Project(
        root_path=tmp_path,
        project_id="stable-project-id",
        storage_revision=7,
    )

    assert project.project_root == tmp_path
    assert project.metadata_root == tmp_path / ".storyboarder" / "data"
    assert project.json_path == tmp_path / ".storyboarder" / "data" / "project.json"
    assert not hasattr(project, "layout")
    assert not hasattr(project, "shots_dir")


def test_current_manifest_parses_to_id_and_revision() -> None:
    manifest = parse_project_manifest(
        {"version": PROJECT_JSON_VERSION, "project_id": "stable-id", "storage_revision": 3}
    )

    assert manifest == ProjectManifest(project_id="stable-id", storage_revision=3)


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {},
        {"version": None},
        {"version": True},
        {"version": 0},
        {"version": 4, "layout": 2, "project_id": "id", "storage_revision": 0},
        {"version": PROJECT_JSON_VERSION + 1, "project_id": "id", "storage_revision": 0},
        {"version": str(PROJECT_JSON_VERSION), "project_id": "id", "storage_revision": 0},
    ],
)
def test_unknown_or_malformed_schema_values_fail_closed(payload) -> None:
    with pytest.raises(ProjectSchemaError):
        parse_project_manifest(payload)


@pytest.mark.parametrize(
    "fields",
    [
        {},
        {"project_id": ""},
        {"project_id": " id "},
        {"project_id": "id"},
        {"project_id": "id", "storage_revision": None},
        {"project_id": "id", "storage_revision": True},
        {"project_id": "id", "storage_revision": -1},
        {"project_id": "id", "storage_revision": MAX_STORAGE_REVISION + 1},
    ],
)
def test_manifest_requires_stable_id_and_bounded_revision(fields: dict) -> None:
    with pytest.raises(ProjectSchemaError):
        parse_project_manifest({"version": PROJECT_JSON_VERSION, **fields})


def test_open_rejects_an_unsupported_manifest_without_rewriting_it(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    old_manifest = {"version": 4, "layout": 2, "project_id": project.project_id, "storage_revision": 1}
    project.json_path.write_text(json.dumps(old_manifest), encoding="utf-8")
    before = project.json_path.read_bytes()

    with pytest.raises(ProjectSchemaError):
        project_manager.open_project(project.document_path)
    assert project.json_path.read_bytes() == before


def test_new_manifest_is_exactly_version_id_and_revision(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    manifest = json.loads(project.json_path.read_text(encoding="utf-8"))

    assert manifest == {
        "version": PROJECT_JSON_VERSION,
        "project_id": project.project_id,
        "storage_revision": project.storage_revision,
    }
    assert PROJECT_JSON_VERSION == 5


@pytest.mark.xfail(
    reason=(
        "SOURCE BUG: the Photoshop plugin's offline manifest writers still write "
        "project.json version 4 (photoshop_uxp_plugin/panel_storage_adapter.js:9, "
        "backend_client.js:240, panel.js:877/901) while the backend only accepts "
        "version 5 under .storyboarder/data; the plan leaves offline mode undecided."
    ),
    strict=True,
)
def test_uxp_offline_manifest_writers_mirror_current_schema() -> None:
    plugin_root = Path(__file__).resolve().parents[1] / "photoshop_uxp_plugin"

    assert f"version: {PROJECT_JSON_VERSION}" in (plugin_root / "backend_client.js").read_text(encoding="utf-8")
    panel = (plugin_root / "panel.js").read_text(encoding="utf-8")
    assert panel.count(f"version || {PROJECT_JSON_VERSION}") == 2
    adapter = (plugin_root / "panel_storage_adapter.js").read_text(encoding="utf-8")
    assert f"const PROJECT_JSON_VERSION = {PROJECT_JSON_VERSION};" in adapter


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
    project = Project(root_path=tmp_path)
    resolve_project_path(project, "Images/board.png")
    try:
        second.mkdir()
    except FileExistsError:
        pytest.skip("Host filesystem is case-insensitive.")

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
