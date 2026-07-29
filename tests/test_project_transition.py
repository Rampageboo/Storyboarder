from __future__ import annotations

import threading
from pathlib import Path

import pytest
from fastapi import HTTPException

from storyboard_tool import (
    app_state,
    blender_bridge,
    project_document,
    project_manager,
)
from storyboard_tool.api import create_app
from storyboard_tool.backend_service import StoryboardBackendService


FAULT_STAGES = (
    "lock_acquired",
    "writers_quiesced",
    "mutations_frozen",
    "plugin_inbox_resolved",
    "external_blender_released",
    "builtin_blender_released",
    "backend_serialized",
    "source_durable",
    "candidate_opened",
    "candidate_validated",
    "before_swap",
)


def _isolated_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir(parents=True)
    monkeypatch.setattr(project_document.tempfile, "tempdir", str(runtime_root))
    monkeypatch.setattr(
        blender_bridge,
        "bridge_file_path",
        lambda: tmp_path / "blender-bridge.json",
    )
    monkeypatch.setattr(
        blender_bridge,
        "heartbeat_file_path",
        lambda: tmp_path / "blender-heartbeat.json",
    )
    return create_app(tmp_path / "app")


def _dirty_document(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    name: str = "Source",
):
    app = _isolated_app(tmp_path, monkeypatch)
    document = tmp_path / f"{name}.sbd"
    project = project_manager.create_document(document)
    shot = project_manager.add_shot(project)
    shot.title = "dirty-before-transition"
    project_manager.save_project(project, flush_document=False)
    app.state.project = project
    app.state.project_disk_mtime = project_manager.project_disk_mtime(project)
    app.state.dirty = True
    return app, project, document


def _closed_document(tmp_path: Path, name: str = "Target") -> Path:
    document = tmp_path / f"{name}.sbd"
    project = project_manager.create_document(document)
    assert project_manager.cleanup_document_working_root(project)
    return document


@pytest.mark.parametrize("stage", FAULT_STAGES)
def test_fault_at_every_precommit_stage_preserves_active_dirty_project(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
) -> None:
    app, source, _source_document = _dirty_document(tmp_path, monkeypatch)
    target_document = _closed_document(tmp_path)
    original_root = source.root_path
    original_session = app.state.project_session_id
    cleanup_calls: list[object] = []
    original_cleanup = project_manager.cleanup_document_working_root

    def record_cleanup(project):
        cleanup_calls.append(project)
        return original_cleanup(project)

    monkeypatch.setattr(
        project_manager,
        "cleanup_document_working_root",
        record_cleanup,
    )
    app.state.project_transition_fault = stage

    with pytest.raises(HTTPException):
        StoryboardBackendService(app).method_open_project(str(target_document))

    assert app.state.project is source
    assert app.state.dirty is True
    assert app.state.project_session_id == original_session
    assert original_root.is_dir()
    assert source.shots[0].title == "dirty-before-transition"
    assert source not in cleanup_calls
    assert app.state.last_project_transition["status"] == "failed"
    assert app.state.project_writers_quiesced is False


def test_dirty_open_saves_source_before_swap_and_cleans_old_root_last(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, source, source_document = _dirty_document(tmp_path, monkeypatch)
    target_document = _closed_document(tmp_path)
    old_root = source.root_path
    old_session = app.state.project_session_id
    cleanup_observations: list[tuple[object, object]] = []
    original_cleanup = project_manager.cleanup_document_working_root

    def record_cleanup(project):
        cleanup_observations.append((project, app.state.project))
        return original_cleanup(project)

    monkeypatch.setattr(
        project_manager,
        "cleanup_document_working_root",
        record_cleanup,
    )

    payload = StoryboardBackendService(app).method_open_project(str(target_document))

    assert payload["document_path"] == str(target_document.resolve())
    assert app.state.project is not source
    assert app.state.dirty is False
    assert app.state.project_session_id != old_session
    assert not old_root.exists()
    assert cleanup_observations[-1] == (source, app.state.project)
    reopened = project_manager.open_project(source_document)
    try:
        assert reopened.shots[0].title == "dirty-before-transition"
    finally:
        project_manager.cleanup_document_working_root(reopened)
    report = app.state.last_project_transition
    assert report["status"] == "committed"
    assert report["writers"]["plugin_inbox"] == (
        "excluded_uncommitted_layout1_no_inbox"
    )
    assert report["writers"]["transaction_log"] == (
        "drained_by_project_lock_no_persistent_log"
    )


def test_dirty_new_saves_source_before_creating_and_activating_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, source, source_document = _dirty_document(tmp_path, monkeypatch)
    destination = tmp_path / "Created.sbd"

    payload = StoryboardBackendService(app).method_new_project(path=str(destination))

    assert payload["document_path"] == str(destination.resolve())
    assert app.state.project is not source
    reopened = project_manager.open_project(source_document)
    try:
        assert reopened.shots[0].title == "dirty-before-transition"
    finally:
        project_manager.cleanup_document_working_root(reopened)


def test_writer_quiesce_timeout_aborts_without_changing_active_project(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, source, _source_document = _dirty_document(tmp_path, monkeypatch)
    target_document = _closed_document(tmp_path)
    entered = threading.Event()
    release = threading.Event()

    def hold_writer() -> None:
        with app_state.project_background_writer(app, "held-test-writer") as allowed:
            assert allowed
            entered.set()
            release.wait(timeout=5)

    thread = threading.Thread(target=hold_writer)
    thread.start()
    assert entered.wait(timeout=2)
    app.state.project_writer_quiesce_timeout = 0.01
    original_session = app.state.project_session_id
    try:
        with pytest.raises(HTTPException) as raised:
            StoryboardBackendService(app).method_open_project(str(target_document))
    finally:
        release.set()
        thread.join(timeout=2)

    assert raised.value.status_code == 409
    assert app.state.project is source
    assert app.state.dirty is True
    assert app.state.project_session_id == original_session
    assert app.state.project_writers_quiesced is False


def test_builtin_blender_save_failure_aborts_before_swap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, source, _source_document = _dirty_document(tmp_path, monkeypatch)
    target_document = _closed_document(tmp_path)
    original_session = app.state.project_session_id

    class FailingViewport:
        def save_and_stop(self):
            raise RuntimeError("built-in Blender save failed")

    app.state.bpy_viewport_manager = FailingViewport()

    with pytest.raises(HTTPException) as raised:
        StoryboardBackendService(app).method_open_project(str(target_document))

    assert raised.value.status_code == 409
    assert app.state.project is source
    assert app.state.dirty is True
    assert app.state.project_session_id == original_session
    assert source.root_path.is_dir()


def test_close_uses_transition_and_durably_saves_dirty_document(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, source, source_document = _dirty_document(tmp_path, monkeypatch)
    old_root = source.root_path

    result = StoryboardBackendService(app).method_close_project()

    assert result["closed"] is True
    assert app.state.project is None
    assert app.state.dirty is False
    assert not old_root.exists()
    reopened = project_manager.open_project(source_document)
    try:
        assert reopened.shots[0].title == "dirty-before-transition"
    finally:
        project_manager.cleanup_document_working_root(reopened)
