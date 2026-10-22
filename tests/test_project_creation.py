from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from conftest import make_project
from storyboard_tool import project_document, project_layout, project_manager, scene2d, scene3d
from storyboard_tool.api import create_app
from storyboard_tool.backend_service import StoryboardBackendService


def test_create_project_publishes_portable_folder(tmp_path: Path) -> None:
    project = project_manager.create_project(
        tmp_path / "New Story.sbd",
        canvas_width=2048,
        canvas_height=858,
    )

    root = tmp_path / "New Story"
    document = root / "New Story.sbd"
    assert project.project_root == root.resolve()
    assert project.metadata_root == (root / ".storyboarder" / "data").resolve()
    assert project.document_path == document.resolve()
    assert project.reopen_path == document.resolve()
    assert uuid.UUID(project.project_id)
    assert project.storage_revision == 1
    assert project.settings["canvas_width"] == 2048
    assert project.settings["canvas_height"] == 858
    assert document.is_file()
    assert all((root / name).is_dir() for name in ("Images", "PSD", "Blender", "Exports"))
    assert not list((root / "Blender").glob("*.blend"))
    assert project_document.read_handle(document) == project.project_id
    assert scene2d.list_scenes(project) == []
    assert scene3d.list_scenes(project) == {"active_scene3d_id": "", "scenes": []}
    payload = json.loads(project.json_path.read_text(encoding="utf-8"))
    assert payload == {
        "version": project_layout.PROJECT_JSON_VERSION,
        "project_id": project.project_id,
        "storage_revision": 1,
    }


def test_create_project_accepts_a_name_without_suffix(tmp_path: Path) -> None:
    project = project_manager.create_project(tmp_path / "NoSuffix")

    assert project.document_path == (tmp_path / "NoSuffix" / "NoSuffix.sbd").resolve()


def test_create_project_rejects_existing_destination(tmp_path: Path) -> None:
    make_project(tmp_path, "Twice")

    with pytest.raises(FileExistsError):
        make_project(tmp_path, "Twice")


def test_create_project_rejects_casefold_collision(tmp_path: Path) -> None:
    (tmp_path / "EXISTING.SBD").write_text("occupied", encoding="utf-8")

    with pytest.raises(FileExistsError, match="collides by case"):
        project_manager.create_project(tmp_path / "existing.sbd")

    assert not (tmp_path / "existing").exists()


def test_create_project_cleans_failed_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_handle(*_args, **_kwargs):
        raise OSError("locked destination")

    monkeypatch.setattr(project_document, "write_handle", fail_handle)
    with pytest.raises(OSError, match="locked destination"):
        project_manager.create_project(tmp_path / "Failure.sbd")

    assert not (tmp_path / "Failure").exists()
    assert not list(tmp_path.glob(".sb-create-*"))


def test_new_project_api_creates_project_folder(tmp_path: Path) -> None:
    app_root = tmp_path / "app"
    app_root.mkdir()
    app = create_app(app_root)

    payload = StoryboardBackendService(app).method_new_project(
        path=str(tmp_path / "From API.sbd"),
        canvas_width=1600,
        canvas_height=900,
    )

    assert payload["project_id"] == app.state.project.project_id
    assert payload["storage_revision"] == 1
    assert payload["document_path"] == str(
        (tmp_path / "From API" / "From API.sbd").resolve()
    )
    assert payload["settings"]["canvas_width"] == 1600
    assert payload["settings"]["canvas_height"] == 900
    for removed in ("layout", "dirty", "can_convert_to_layout2"):
        assert removed not in payload


def test_new_project_remains_successful_when_post_publish_cleanup_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = make_project(tmp_path, "Source")
    app_root = tmp_path / "app-cleanup"
    app_root.mkdir()
    app = create_app(app_root)
    app.state.project = source
    app.state.project_disk_mtime = project_manager.project_disk_mtime(source)
    original_rmdir = Path.rmdir

    def fail_operation_cleanup(path: Path) -> None:
        if path.name.startswith(".sb-create-"):
            raise OSError("injected post-publish cleanup failure")
        original_rmdir(path)

    monkeypatch.setattr(Path, "rmdir", fail_operation_cleanup)

    payload = StoryboardBackendService(app).method_new_project(
        path=str(tmp_path / "Published.sbd"),
    )

    target = tmp_path / "Published"
    document = target / "Published.sbd"
    assert payload["document_path"] == str(document.resolve())
    assert app.state.project.document_path == document.resolve()
    assert app.state.last_project_transition["status"] == "committed"
    assert project_document.read_handle(document) == payload["project_id"]
    reopened = project_manager.open_project(document)
    assert reopened.storage_revision == payload["storage_revision"]
    assert source.json_path.is_file()
    assert len(list(tmp_path.glob(".sb-create-*"))) == 1
