from __future__ import annotations

import threading
from pathlib import Path

import pytest
from fastapi import HTTPException

from conftest import make_project
from storyboard_tool import (
    app_state,
    blender_bridge,
    project_manager,
)
from storyboard_tool.api import create_app
from storyboard_tool.backend_service import StoryboardBackendService


FAULT_STAGES = (
    "lock_acquired",
    "writers_quiesced",
    "mutations_frozen",
    "external_blender_released",
    "candidate_opened",
    "candidate_validated",
    "before_swap",
)


def _isolated_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
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


def _active_project(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    name: str = "Source",
):
    app = _isolated_app(tmp_path, monkeypatch)
    project = make_project(tmp_path, name)
    shot = project_manager.add_shot(project)
    shot.title = "saved-before-transition"
    project_manager.save_project(project)
    app.state.project = project
    app.state.project_disk_mtime = project_manager.project_disk_mtime(project)
    return app, project, project.document_path


def _closed_document(tmp_path: Path, name: str = "Target") -> Path:
    return make_project(tmp_path, name).document_path


@pytest.mark.parametrize("stage", FAULT_STAGES)
def test_fault_at_every_precommit_stage_preserves_active_project(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
) -> None:
    app, source, _source_document = _active_project(tmp_path, monkeypatch)
    target_document = _closed_document(tmp_path)
    original_root = source.root_path
    original_session = app.state.project_session_id
    app.state.project_transition_fault = stage

    with pytest.raises(HTTPException):
        StoryboardBackendService(app).method_open_project(str(target_document))

    assert app.state.project is source
    assert app.state.project_session_id == original_session
    assert original_root.is_dir()
    assert source.shots[0].title == "saved-before-transition"
    assert app.state.last_project_transition["status"] == "failed"
    assert app.state.last_project_transition["current_stage"] == stage
    assert app.state.project_writers_quiesced is False


def test_open_swaps_active_project_and_leaves_source_folder_intact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, source, source_document = _active_project(tmp_path, monkeypatch)
    target_document = _closed_document(tmp_path)
    old_root = source.root_path
    old_session = app.state.project_session_id

    payload = StoryboardBackendService(app).method_open_project(str(target_document))

    assert payload["document_path"] == str(target_document.resolve())
    assert app.state.project is not source
    assert app.state.project.document_path == target_document.resolve()
    assert app.state.project_session_id != old_session
    assert old_root.is_dir()
    reopened = project_manager.open_project(source_document)
    assert reopened.shots[0].title == "saved-before-transition"
    report = app.state.last_project_transition
    assert report["status"] == "committed"
    assert report["writers"]["transaction_log"] == (
        "drained_by_project_lock_no_persistent_log"
    )


def test_new_project_activates_target_and_keeps_source_on_disk(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, source, source_document = _active_project(tmp_path, monkeypatch)
    destination = tmp_path / "Created.sbd"

    payload = StoryboardBackendService(app).method_new_project(path=str(destination))

    assert payload["document_path"] == str(
        (tmp_path / "Created" / "Created.sbd").resolve()
    )
    assert app.state.project is not source
    reopened = project_manager.open_project(source_document)
    assert reopened.shots[0].title == "saved-before-transition"


def test_writer_quiesce_timeout_aborts_without_changing_active_project(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, source, _source_document = _active_project(tmp_path, monkeypatch)
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
    assert app.state.project_session_id == original_session
    assert app.state.project_writers_quiesced is False


def test_close_uses_transition_and_keeps_project_on_disk(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, source, source_document = _active_project(tmp_path, monkeypatch)
    old_root = source.root_path

    result = StoryboardBackendService(app).method_close_project()

    assert result["closed"] is True
    assert app.state.project is None
    assert app.state.last_project_transition["status"] == "committed"
    assert old_root.is_dir()
    reopened = project_manager.open_project(source_document)
    assert reopened.shots[0].title == "saved-before-transition"
