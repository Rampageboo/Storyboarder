from __future__ import annotations

import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from storyboard_tool import api as api_module
from storyboard_tool import project_document, project_manager


def test_create_save_and_reopen_single_file_document(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(project_document.tempfile, "tempdir", str(tmp_path))
    document = tmp_path / "My Film.sbd"

    project = project_manager.create_document(document, canvas_width=1280, canvas_height=720)
    shot = project_manager.add_shot(project)
    shot.title = "Opening image"
    # A freshly added shot has no PSD; the canvas is created on demand. Creating it
    # here verifies a shot canvas round-trips into the single-file document.
    project_manager.create_canvas_for_shot(project, shot)
    project_manager.save_project(project)

    assert document.is_file()
    assert not (tmp_path / "Storyboard_Project").exists()
    with zipfile.ZipFile(document) as archive:
        assert "project.json" in archive.namelist()
        assert "shots.json" in archive.namelist()
        assert f"shots/{shot.shot_id}/{shot.shot_id}.psd" in archive.namelist()

    reopened = project_manager.open_project(document)
    assert reopened.document_path == document.resolve()
    assert reopened.name == "My Film"
    assert reopened.shots[0].title == "Opening image"
    assert reopened.settings["canvas_width"] == 1280


def test_document_save_replaces_previous_archive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(project_document.tempfile, "tempdir", str(tmp_path))
    document = tmp_path / "Replace.sbd"
    project = project_manager.create_document(document)
    first_bytes = document.read_bytes()

    shot = project_manager.add_shot(project)
    shot.title = "Replacement"
    project_manager.save_project(project)

    assert document.read_bytes() != first_bytes
    assert not list(tmp_path.glob(".Replace.sbd.*.tmp"))
    assert project_manager.open_project(document).shots[0].title == "Replacement"


def test_rejects_unsafe_document_member(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(project_document.tempfile, "tempdir", str(tmp_path))
    document = tmp_path / "Unsafe.sbd"
    with zipfile.ZipFile(document, "w") as archive:
        archive.writestr("project.json", '{"version": 1}')
        archive.writestr("../outside.txt", "no")

    with pytest.raises(ValueError, match="unsafe archive path"):
        project_document.extract_document(document)
    assert not (tmp_path / "outside.txt").exists()


def test_document_api_create_scene_and_reopen_without_rewriting_on_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(project_document.tempfile, "tempdir", str(tmp_path))
    document = tmp_path / "API Film.sbd"
    first_app_dir = tmp_path / "app-one"
    first_app_dir.mkdir()
    client = TestClient(api_module.create_app(first_app_dir))

    created = client.post("/api/project/new", json={"path": str(document)})
    assert created.status_code == 200, created.text
    assert created.json()["project_path"] == str(document.resolve())
    assert created.json()["project_json_path"] == str(document.resolve())
    scene = client.post(
        "/api/project/scenes2d",
        json={"title": "Street", "location": "Old town", "time_of_day": "Dusk"},
    )
    assert scene.status_code == 200, scene.text
    before_open = document.read_bytes()
    with zipfile.ZipFile(document) as archive:
        assert "scenes2d/scenes2d.json" in archive.namelist()

    second_app_dir = tmp_path / "app-two"
    second_app_dir.mkdir()
    reopened = TestClient(api_module.create_app(second_app_dir)).post(
        "/api/project/open",
        json={"project_json_path": str(document)},
    )
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["name"] == "API Film"
    assert document.read_bytes() == before_open


def test_mutations_defer_sbd_pack_until_save(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(project_document.tempfile, "tempdir", str(tmp_path))
    document = tmp_path / "Deferred.sbd"
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    client = TestClient(api_module.create_app(app_dir))
    assert client.post("/api/project/new", json={"path": str(document)}).status_code == 200

    added = client.post("/api/shots")
    assert added.status_code == 200, added.text
    shot_id = added.json()["shot"]["shot_id"]

    # Interactive autosave keeps the working tree current but DEFERS the .sbd pack.
    with zipfile.ZipFile(document) as archive:
        assert not any(f"shots/{shot_id}/" in name for name in archive.namelist())

    # Manual save flushes the document.
    assert client.post("/api/project/save").status_code == 200
    with zipfile.ZipFile(document) as archive:
        assert any(f"shots/{shot_id}/" in name for name in archive.namelist())


def test_autosave_interval_setting_persists(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(project_document.tempfile, "tempdir", str(tmp_path))
    document = tmp_path / "Interval.sbd"
    app_dir = tmp_path / "app-interval"
    app_dir.mkdir()
    client = TestClient(api_module.create_app(app_dir))
    assert client.post("/api/project/new", json={"path": str(document)}).status_code == 200

    resp = client.patch("/api/project/settings", json={"autosave_interval_minutes": 10})
    assert resp.status_code == 200, resp.text
    assert resp.json()["settings"]["autosave_interval_minutes"] == 10


def test_backups_are_not_packed_into_sbd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(project_document.tempfile, "tempdir", str(tmp_path))
    document = tmp_path / "NoBackups.sbd"
    project = project_manager.create_document(document, canvas_width=1280, canvas_height=720)
    project_manager.add_shot(project)
    project_manager.save_project(project)  # backup_on_save default True -> writes backups/
    project_manager.add_shot(project)
    project_manager.save_project(project)

    # The working tree keeps local recovery snapshots...
    assert any((project.root_path / "backups").glob("shots_*.json"))
    # ...but the shared single-file document never embeds them.
    with zipfile.ZipFile(document) as archive:
        assert not any(name.startswith("backups/") for name in archive.namelist())
