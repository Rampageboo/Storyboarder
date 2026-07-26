from __future__ import annotations

import json
import os
import threading
import time
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from storyboard_tool import api as api_module
from storyboard_tool import app_state as app_state_module
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


def test_session_marker_is_not_packed_into_sbd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(project_document.tempfile, "tempdir", str(tmp_path))
    document = tmp_path / "Marked.sbd"
    project = project_manager.create_document(document, canvas_width=1280, canvas_height=720)

    # The work tree knows which process owns it...
    marker = project.root_path / project_document.SESSION_MARKER
    assert marker.is_file()
    assert json.loads(marker.read_text(encoding="utf-8"))["pid"] == os.getpid()

    # ...but that is machine-local and must never travel inside the document.
    project_manager.save_project(project)
    with zipfile.ZipFile(document) as archive:
        assert project_document.SESSION_MARKER not in archive.namelist()

    # Reopening re-stamps the tree for the process that now owns it.
    reopened = project_manager.open_project(document)
    assert (reopened.root_path / project_document.SESSION_MARKER).is_file()


def test_failed_document_creation_leaves_no_work_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    temp_root = tmp_path / "temp"
    temp_root.mkdir()
    monkeypatch.setattr(project_document.tempfile, "tempdir", str(temp_root))

    def boom(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(project_manager, "save_project", boom)
    with pytest.raises(OSError):
        project_manager.create_document(tmp_path / "Doomed.sbd")

    assert list(temp_root.glob(f"{project_document.WORKING_ROOT_PREFIX}*")) == []


class TestSweepOrphanedWorkingRoots:
    """The sweep must reclaim abandoned trees without ever discarding unsaved work."""

    def _tree(self, temp_root: Path, name: str, *, marker: dict | None, project_json: bool) -> Path:
        root = temp_root / f"{project_document.WORKING_ROOT_PREFIX}{name}"
        root.mkdir()
        if project_json:
            (root / "project.json").write_text('{"version": 1}', encoding="utf-8")
        if marker is not None:
            (root / project_document.SESSION_MARKER).write_text(json.dumps(marker), encoding="utf-8")
        return root

    def test_empty_legacy_shell_is_removed(self, tmp_path: Path) -> None:
        root = self._tree(tmp_path, "Husk", marker=None, project_json=False)
        result = project_document.sweep_orphaned_working_roots(tmp_path)
        assert not root.exists()
        assert str(root) in result["removed"]

    def test_legacy_tree_holding_data_is_kept(self, tmp_path: Path) -> None:
        root = self._tree(tmp_path, "Legacy", marker=None, project_json=True)
        result = project_document.sweep_orphaned_working_roots(tmp_path)
        assert root.is_dir()
        assert str(root) in result["kept"]

    def test_live_owner_tree_is_untouched(self, tmp_path: Path) -> None:
        document = tmp_path / "Live.sbd"
        document.write_bytes(b"x")
        root = self._tree(
            tmp_path, "Live", marker={"pid": os.getpid(), "document_path": str(document)}, project_json=True
        )
        result = project_document.sweep_orphaned_working_roots(tmp_path)
        assert root.is_dir()
        assert str(root) not in result["removed"] and str(root) not in result["kept"]

    def test_orphan_already_flushed_is_removed(self, tmp_path: Path) -> None:
        root = self._tree(tmp_path, "Flushed", marker=None, project_json=True)
        document = tmp_path / "Flushed.sbd"
        document.write_bytes(b"x")
        # Document packed after every file in the tree: nothing here is unsaved.
        os.utime(document, (time.time() + 60, time.time() + 60))
        (root / project_document.SESSION_MARKER).write_text(
            json.dumps({"pid": 2**31 - 1, "document_path": str(document)}), encoding="utf-8"
        )
        result = project_document.sweep_orphaned_working_roots(tmp_path)
        assert not root.exists()
        assert str(root) in result["removed"]

    def test_orphan_with_unflushed_work_is_kept(self, tmp_path: Path) -> None:
        document = tmp_path / "Crashed.sbd"
        document.write_bytes(b"x")
        os.utime(document, (time.time() - 600, time.time() - 600))
        root = self._tree(
            tmp_path,
            "Crashed",
            marker={"pid": 2**31 - 1, "document_path": str(document)},
            project_json=True,
        )
        # project.json is newer than the last pack -> a crashed session's only copy.
        result = project_document.sweep_orphaned_working_roots(tmp_path)
        assert root.is_dir()
        assert str(root) in result["kept"]

    def test_orphan_whose_document_vanished_is_kept(self, tmp_path: Path) -> None:
        root = self._tree(
            tmp_path,
            "Gone",
            marker={"pid": 2**31 - 1, "document_path": str(tmp_path / "missing.sbd")},
            project_json=True,
        )
        result = project_document.sweep_orphaned_working_roots(tmp_path)
        assert root.is_dir()
        assert str(root) in result["kept"]


def test_running_app_exposes_its_background_loops_for_shutdown(tmp_path: Path) -> None:
    """Shutdown can only stop the watchers if the app publishes them.

    Both loops write into the open project's work tree, so removing that tree
    without stopping them first is what leaves undeletable TEMP directories.
    """
    with TestClient(api_module.create_app(tmp_path)) as client:
        app = client.app
        assert app.state.background_stop is not None
        assert len(app.state.background_threads) == 2
        assert all(thread.is_alive() for thread in app.state.background_threads)


def test_stop_background_loops_actually_ends_the_threads(tmp_path: Path) -> None:
    app = api_module.create_app(tmp_path)
    stop_event = threading.Event()
    exited = threading.Event()

    def loop() -> None:
        while not stop_event.wait(0.01):
            pass
        exited.set()

    thread = threading.Thread(target=loop, daemon=True)
    thread.start()
    app.state.background_stop = stop_event
    app.state.background_threads = (thread,)

    app_state_module.stop_background_loops(app)

    assert exited.is_set()
    assert not thread.is_alive()
    app_state_module.stop_background_loops(app)  # idempotent


def test_sweep_reports_trees_it_cannot_reclaim(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / f"{project_document.WORKING_ROOT_PREFIX}Stuck"
    root.mkdir()  # No project.json -> a removal candidate.
    monkeypatch.setattr(project_document, "remove_working_root", lambda _root: False)

    result = project_document.sweep_orphaned_working_roots(tmp_path)

    # Neither silently dropped nor reported as removed.
    assert result["removed"] == []
    assert str(root) in result["failed"]
