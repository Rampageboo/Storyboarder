from __future__ import annotations

import json
import uuid
import zipfile
from pathlib import Path

import pytest

from storyboard_tool import project_document, project_layout, project_manager, scene2d, scene3d
from storyboard_tool.api import create_app
from storyboard_tool.backend_service import StoryboardBackendService


def test_create_layout2_document_publishes_portable_folder(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(project_layout, "LAYOUT_2_ENABLED", True)

    project = project_manager.create_layout2_document(
        tmp_path / "New Story.sbd",
        canvas_width=2048,
        canvas_height=858,
    )

    root = tmp_path / "New Story"
    document = root / "New Story.sbd"
    assert project.layout == project_layout.LAYOUT_2
    assert project.project_root == root.resolve()
    assert project.metadata_root == (root / ".storyboarder" / "work").resolve()
    assert project.document_path == document.resolve()
    assert uuid.UUID(project.project_id)
    assert project.storage_revision == 1
    assert project.settings["canvas_width"] == 2048
    assert project.settings["canvas_height"] == 858
    assert document.is_file()
    assert all((root / name).is_dir() for name in ("Images", "PSD", "Blender", "Exports"))
    assert not list((root / "Blender").glob("*.blend"))
    snapshot = project_document.validate_layout2_document(document)
    assert snapshot.project_id == project.project_id
    assert snapshot.revision == project.storage_revision
    with zipfile.ZipFile(document) as archive:
        assert all(name.endswith(".json") or name == "cover.png" for name in archive.namelist())
    assert scene2d.list_scenes(project) == []
    assert scene3d.list_scenes(project) == {"active_scene3d_id": "", "scenes": []}
    payload = json.loads(project.json_path.read_text(encoding="utf-8"))
    assert payload["layout"] == project_layout.LAYOUT_2


def test_create_layout2_document_accepts_a_name_without_suffix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(project_layout, "LAYOUT_2_ENABLED", True)

    project = project_manager.create_layout2_document(tmp_path / "NoSuffix")

    assert project.document_path == (tmp_path / "NoSuffix" / "NoSuffix.sbd").resolve()


def test_create_layout2_document_rejects_casefold_collision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(project_layout, "LAYOUT_2_ENABLED", True)
    (tmp_path / "EXISTING.SBD").write_text("occupied", encoding="utf-8")

    with pytest.raises(FileExistsError, match="collides by case"):
        project_manager.create_layout2_document(tmp_path / "existing.sbd")

    assert not (tmp_path / "existing").exists()


def test_create_layout2_document_cleans_failed_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(project_layout, "LAYOUT_2_ENABLED", True)

    def fail_commit(*_args, **_kwargs):
        raise OSError("locked destination")

    monkeypatch.setattr(project_document, "commit_layout2_document", fail_commit)
    with pytest.raises(OSError, match="locked destination"):
        project_manager.create_layout2_document(tmp_path / "Failure.sbd")

    assert not (tmp_path / "Failure").exists()
    assert not list(tmp_path.glob(".sb-create-*"))


def test_create_layout2_document_honors_feature_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(project_layout, "LAYOUT_2_ENABLED", False)

    with pytest.raises(project_layout.LayoutDisabledError):
        project_manager.create_layout2_document(tmp_path / "Disabled.sbd")

    assert list(tmp_path.iterdir()) == []


def test_new_project_api_defaults_sbd_to_layout2(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(project_layout, "LAYOUT_2_ENABLED", True)
    app_root = tmp_path / "app"
    app_root.mkdir()
    app = create_app(app_root)

    payload = StoryboardBackendService(app).method_new_project(
        path=str(tmp_path / "From API.sbd"),
        canvas_width=1600,
        canvas_height=900,
    )

    assert payload["layout"] == project_layout.LAYOUT_2
    assert payload["project_id"] == app.state.project.project_id
    assert payload["storage_revision"] == 1
    assert payload["document_path"] == str(
        (tmp_path / "From API" / "From API.sbd").resolve()
    )
    assert payload["settings"]["canvas_width"] == 1600
    assert payload["settings"]["canvas_height"] == 900
