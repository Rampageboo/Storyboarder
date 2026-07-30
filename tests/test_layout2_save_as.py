from __future__ import annotations

import hashlib
import json
import os
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from storyboard_tool import (
    app_state,
    blender_bridge,
    project_document,
    project_layout,
    project_manager,
    project_save_as,
    scene2d,
    scene3d,
    shot_store,
)
from storyboard_tool.api import create_app
from storyboard_tool.backend_service import StoryboardBackendService
from storyboard_tool.models import Project, Shot
from storyboard_tool.project_layout import shot_asset_relative


def _tree_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _layout2_project(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Project:
    monkeypatch.setattr(project_layout, "LAYOUT_2_ENABLED", True)
    root = tmp_path / "Source"
    work = root / ".storyboarder" / "work"
    work.mkdir(parents=True)
    shot = Shot(shot_id="shot-save-as", title="Frozen title")
    project = Project(
        root_path=work,
        project_root_path=root,
        document_path=root / "Source.sbd",
        layout=2,
        project_id="5f44cc8d-cc3f-45dd-8e84-88606d69a3ef",
        storage_revision=4,
        shots=[shot],
        settings={**project_manager.DEFAULT_SETTINGS, "backup_on_save": False},
    )
    project_manager._ensure_shot_files(project, shot)
    source_relative = shot_asset_relative(project, shot.shot_id, "source_psd")
    preview_relative = shot_asset_relative(project, shot.shot_id, "preview")
    source = root / source_relative
    preview = root / preview_relative
    source.parent.mkdir(parents=True, exist_ok=True)
    preview.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"8BPS-frozen")
    preview.write_bytes(b"\x89PNG\r\n\x1a\npreview")
    shot.source_file_path = source_relative
    shot.image_path = preview_relative
    shot.preview_image_path = preview_relative
    project_manager.save_project(project, flush_document=False)
    project_document.commit_layout2_document(root)
    (root / "User Notes.txt").write_bytes(b"unknown-user-file")
    transaction = root / ".storyboarder" / "transactions" / "pending" / "plugin-inbox"
    transaction.mkdir(parents=True)
    scene2d.initialize_layout2_metadata(project)
    scene3d.initialize_layout2_metadata(project)
    (transaction / "pending.png").write_bytes(b"uncommitted")
    return project


def _app_for(project: Project, tmp_path: Path):
    app_root = tmp_path / "app"
    app_root.mkdir(exist_ok=True)
    app = create_app(app_root)
    app.state.project = project
    app.state.project_disk_mtime = project_manager.project_disk_mtime(project)
    app.state.dirty = True
    return app


def test_layout1_save_as_keeps_existing_document_flow(
    tmp_path: Path,
) -> None:
    source_document = tmp_path / "LegacySource.sbd"
    project = project_manager.create_document(source_document)
    app = _app_for(project, tmp_path)
    destination = tmp_path / "LegacyCopy.sbd"
    try:
        payload = StoryboardBackendService(app).method_save_project_as(
            str(destination)
        )

        assert app.state.project is project
        assert app.state.project.layout == 1
        assert app.state.project.document_path == destination.resolve()
        assert payload["document_path"] == str(destination.resolve())
        assert destination.is_file()
    finally:
        project_manager.cleanup_document_working_root(project)


def test_layout2_save_as_copies_unknown_files_and_excludes_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _layout2_project(tmp_path, monkeypatch)
    app = _app_for(project, tmp_path)
    source_before = _tree_hashes(project.project_root)
    source_session = app.state.project_session_id

    payload = StoryboardBackendService(app).method_save_project_as(
        str(tmp_path / "Copy.sbd")
    )

    destination = tmp_path / "Copy"
    document = destination / "Copy.sbd"
    assert payload["document_path"] == str(document.resolve())
    assert app.state.project.project_root == destination.resolve()
    assert app.state.project_session_id != source_session
    assert app.state.dirty is False
    assert (destination / "User Notes.txt").read_bytes() == b"unknown-user-file"
    assert not (destination / ".storyboarder" / "transactions").exists()
    assert _tree_hashes(project.project_root) == source_before
    snapshot = project_document.validate_layout2_document(document)
    assert snapshot.revision == project.storage_revision
    assert app.state.last_project_transition["status"] == "committed"
    assert app.state.last_project_transition["snapshot_hash"]


def test_layout2_save_as_snapshot_hash_is_deterministic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _layout2_project(tmp_path, monkeypatch)
    before = _tree_hashes(project.project_root)

    first = project_save_as.materialize_layout2_save_as(project, tmp_path / "One.sbd")
    second = project_save_as.materialize_layout2_save_as(project, tmp_path / "Two.sbd")

    assert first.snapshot_hash == second.snapshot_hash
    assert _tree_hashes(project.project_root) == before
    assert (first.destination_root / "User Notes.txt").read_bytes() == b"unknown-user-file"
    assert (second.destination_root / "User Notes.txt").read_bytes() == b"unknown-user-file"


def test_layout2_save_as_uses_dirty_memory_snapshot_without_changing_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _layout2_project(tmp_path, monkeypatch)
    app = _app_for(project, tmp_path)
    source_before = _tree_hashes(project.project_root)
    source_shots_path = project.metadata_root / "shots.json"
    project.shots[0].title = "Unsaved in-memory title"

    StoryboardBackendService(app).method_save_project_as(
        str(tmp_path / "DirtyCopy.sbd")
    )

    assert app.state.project.shots[0].title == "Unsaved in-memory title"
    assert _tree_hashes(project.project_root) == source_before
    source_shots = shot_store.load_shots_json(source_shots_path)
    assert source_shots is not None
    assert source_shots[0].title == "Frozen title"
    destination_shots = shot_store.load_shots_json(
        app.state.project.metadata_root / "shots.json"
    )
    assert destination_shots is not None
    assert destination_shots[0].title == "Unsaved in-memory title"


def test_layout2_save_as_rejects_existing_and_nested_destinations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _layout2_project(tmp_path, monkeypatch)
    (tmp_path / "Existing").mkdir()

    with pytest.raises(FileExistsError, match="never merged"):
        project_save_as.materialize_layout2_save_as(project, tmp_path / "Existing.sbd")
    with pytest.raises(ValueError, match="nested"):
        project_save_as.materialize_layout2_save_as(
            project,
            project.project_root / "Nested.sbd",
        )
    (tmp_path / "casecopy.SBD").write_bytes(b"existing document")
    with pytest.raises(FileExistsError, match="collides by case|already exists"):
        project_save_as.materialize_layout2_save_as(project, tmp_path / "CaseCopy.sbd")


def test_layout2_save_as_rejects_reparse_source_and_destination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _layout2_project(tmp_path, monkeypatch)
    source_link = tmp_path / "SourceLink"
    destination_target = tmp_path / "DestinationTarget"
    destination_target.mkdir()
    destination_link = tmp_path / "DestinationLink"
    try:
        os.symlink(project.project_root, source_link, target_is_directory=True)
        os.symlink(destination_target, destination_link, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"Directory symlinks are unavailable: {exc}")

    with pytest.raises(ValueError, match="regular directory"):
        project_save_as._scan_tree(source_link)
    with pytest.raises(ValueError, match="reparse point"):
        project_save_as.materialize_layout2_save_as(
            project,
            destination_link / "Copy.sbd",
        )
    assert not (destination_target / "Copy").exists()


def test_layout2_save_as_disk_preflight_fails_before_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _layout2_project(tmp_path, monkeypatch)
    monkeypatch.setattr(
        project_save_as.shutil,
        "disk_usage",
        lambda _path: SimpleNamespace(total=1, used=1, free=0),
    )

    with pytest.raises(OSError, match="Insufficient free space"):
        project_save_as.materialize_layout2_save_as(project, tmp_path / "NoSpace.sbd")

    assert not (tmp_path / "NoSpace").exists()
    assert not list(tmp_path.glob(".NoSpace.save-as-*"))


def test_layout2_save_as_copy_or_hash_fault_cleans_stage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _layout2_project(tmp_path, monkeypatch)
    original_copy = project_save_as.shutil.copy2

    def corrupt_copy(source: Path, destination: Path):
        result = original_copy(source, destination)
        if Path(source).name == "User Notes.txt":
            Path(destination).write_bytes(b"corrupt")
        return result

    monkeypatch.setattr(project_save_as.shutil, "copy2", corrupt_copy)

    with pytest.raises(project_save_as.Layout2SaveAsError, match="hash verification"):
        project_save_as.materialize_layout2_save_as(project, tmp_path / "Corrupt.sbd")

    assert not (tmp_path / "Corrupt").exists()
    assert not list(tmp_path.glob(".Corrupt.save-as-*"))


def test_layout2_save_as_reports_stage_when_cleanup_cannot_remove_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _layout2_project(tmp_path, monkeypatch)
    original_copy = project_save_as.shutil.copy2
    raised = None

    def corrupt_copy(source: Path, destination: Path):
        result = original_copy(source, destination)
        if Path(source).name == "User Notes.txt":
            Path(destination).write_bytes(b"corrupt")
        return result

    with monkeypatch.context() as patch:
        patch.setattr(project_save_as.shutil, "copy2", corrupt_copy)
        patch.setattr(project_save_as.shutil, "rmtree", lambda *_args, **_kwargs: None)
        with pytest.raises(project_save_as.Layout2SaveAsError) as raised:
            project_save_as.materialize_layout2_save_as(
                project,
                tmp_path / "CleanupBlocked.sbd",
            )

    assert raised is not None
    assert raised.value.staging_path is not None
    assert raised.value.staging_path.is_dir()
    project_save_as.shutil.rmtree(raised.value.staging_path)


def test_layout2_save_as_rename_fault_preserves_stage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _layout2_project(tmp_path, monkeypatch)
    real_rename = project_save_as.os.rename

    def fail_final_rename(source, destination):
        source_path = Path(source)
        if source_path.is_dir() and Path(destination) == tmp_path / "Locked":
            raise OSError("locked destination")
        return real_rename(source, destination)

    monkeypatch.setattr(project_save_as.os, "rename", fail_final_rename)

    with pytest.raises(project_save_as.Layout2SaveAsError, match="locked destination") as raised:
        project_save_as.materialize_layout2_save_as(project, tmp_path / "Locked.sbd")

    assert raised.value.stage == "rename"
    assert raised.value.staging_path is not None
    assert raised.value.staging_path.is_dir()
    assert not (tmp_path / "Locked").exists()


def test_layout2_save_as_does_not_replace_destination_created_during_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _layout2_project(tmp_path, monkeypatch)
    real_copy = project_save_as._copy_inventory

    def copy_then_create_destination(source: Path, stage: Path, inventory):
        real_copy(source, stage, inventory)
        destination = tmp_path / "RacedDestination"
        destination.mkdir()
        (destination / "other-process.txt").write_bytes(b"do not replace")

    monkeypatch.setattr(project_save_as, "_copy_inventory", copy_then_create_destination)

    with pytest.raises(project_save_as.Layout2SaveAsError, match="not replaced") as raised:
        project_save_as.materialize_layout2_save_as(
            project,
            tmp_path / "RacedDestination.sbd",
        )

    assert (tmp_path / "RacedDestination" / "other-process.txt").read_bytes() == b"do not replace"
    assert raised.value.stage == "rename"
    assert raised.value.staging_path is not None
    assert raised.value.staging_path.is_dir()


def test_layout2_save_as_activation_fault_preserves_target_and_source_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _layout2_project(tmp_path, monkeypatch)
    app = _app_for(project, tmp_path)
    source_session = app.state.project_session_id
    real_open = project_manager.open_project

    def fail_target_open(path: Path):
        if Path(path).name == "Activation.sbd":
            raise OSError("activation fault")
        return real_open(path)

    monkeypatch.setattr(project_manager, "open_project", fail_target_open)

    with pytest.raises(HTTPException) as raised:
        StoryboardBackendService(app).method_save_project_as(
            str(tmp_path / "Activation.sbd")
        )

    assert raised.value.status_code == 500
    assert app.state.project is project
    assert app.state.dirty is True
    assert app.state.project_session_id == source_session
    assert (tmp_path / "Activation" / "Activation.sbd").is_file()


def test_layout2_save_as_builtin_writer_blocks_before_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _layout2_project(tmp_path, monkeypatch)
    app = _app_for(project, tmp_path)
    app.state.bpy_viewport_manager = SimpleNamespace(running=True)

    with pytest.raises(HTTPException) as raised:
        StoryboardBackendService(app).method_save_project_as(
            str(tmp_path / "Blocked.sbd")
        )

    assert raised.value.status_code == 409
    assert app.state.project is project
    assert not (tmp_path / "Blocked").exists()
    assert not list(tmp_path.glob(".Blocked.save-as-*"))


def test_layout2_save_as_detects_concurrent_source_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _layout2_project(tmp_path, monkeypatch)
    real_copy = project_save_as._copy_inventory

    def copy_then_change(source: Path, stage: Path, inventory):
        real_copy(source, stage, inventory)
        (source / "User Notes.txt").write_bytes(b"changed-concurrently")

    monkeypatch.setattr(project_save_as, "_copy_inventory", copy_then_change)

    with pytest.raises(project_save_as.Layout2SaveAsError, match="changed during"):
        project_save_as.materialize_layout2_save_as(project, tmp_path / "Race.sbd")

    assert not (tmp_path / "Race").exists()
    assert not list(tmp_path.glob(".Race.save-as-*"))


def test_layout2_save_as_locked_file_fault_cleans_stage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _layout2_project(tmp_path, monkeypatch)
    real_copy = project_save_as.shutil.copy2

    def fail_locked_file(source: Path, destination: Path):
        if Path(source).name == "User Notes.txt":
            raise PermissionError("locked source file")
        return real_copy(source, destination)

    monkeypatch.setattr(project_save_as.shutil, "copy2", fail_locked_file)

    with pytest.raises(project_save_as.Layout2SaveAsError, match="locked source file"):
        project_save_as.materialize_layout2_save_as(project, tmp_path / "LockedFile.sbd")

    assert not (tmp_path / "LockedFile").exists()
    assert not list(tmp_path.glob(".LockedFile.save-as-*"))


def test_layout2_save_as_missing_stored_reference_fails_before_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _layout2_project(tmp_path, monkeypatch)
    (project.project_root / project.shots[0].source_file_path).unlink()

    with pytest.raises(FileNotFoundError, match="Stored reference is missing"):
        project_save_as.materialize_layout2_save_as(project, tmp_path / "Missing.sbd")

    assert not (tmp_path / "Missing").exists()
    assert not list(tmp_path.glob(".Missing.save-as-*"))


@pytest.mark.parametrize(
    "setting_payload",
    [
        {"reference_image_path": "References/missing.png"},
        {"ref_segments": [{"id": "missing", "reference_path": "References/missing.png"}]},
    ],
)
def test_layout2_save_as_validates_all_settings_references_before_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    setting_payload: dict[str, object],
) -> None:
    project = _layout2_project(tmp_path, monkeypatch)
    project.settings.update(setting_payload)

    with pytest.raises(FileNotFoundError, match="Stored reference is missing"):
        project_save_as.materialize_layout2_save_as(project, tmp_path / "MissingSetting.sbd")

    assert not list(tmp_path.glob(".MissingSetting.save-as-*"))


def test_layout2_save_as_external_writer_blocks_before_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _layout2_project(tmp_path, monkeypatch)
    app = _app_for(project, tmp_path)
    monkeypatch.setattr(
        blender_bridge,
        "require_released",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            ValueError("external writer owns scene")
        ),
    )

    with pytest.raises(HTTPException) as raised:
        StoryboardBackendService(app).method_save_project_as(
            str(tmp_path / "ExternalBlocked.sbd")
        )

    assert raised.value.status_code == 409
    assert app.state.project is project
    assert not (tmp_path / "ExternalBlocked").exists()


def test_layout2_save_as_writer_quiesce_timeout_fails_before_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _layout2_project(tmp_path, monkeypatch)
    app = _app_for(project, tmp_path)
    entered = threading.Event()
    release = threading.Event()

    def hold_writer() -> None:
        with app_state.project_background_writer(app, "held-save-as-writer") as allowed:
            assert allowed
            entered.set()
            release.wait(timeout=5)

    thread = threading.Thread(target=hold_writer)
    thread.start()
    assert entered.wait(timeout=2)
    app.state.project_writer_quiesce_timeout = 0.01
    try:
        with pytest.raises(HTTPException) as raised:
            StoryboardBackendService(app).method_save_project_as(
                str(tmp_path / "WriterBlocked.sbd")
            )
    finally:
        release.set()
        thread.join(timeout=2)

    assert raised.value.status_code == 409
    assert app.state.project is project
    assert app.state.dirty is True
    assert app.state.project_writers_quiesced is False
    assert not (tmp_path / "WriterBlocked").exists()
    assert not list(tmp_path.glob(".WriterBlocked.save-as-*"))


def test_layout2_autosave_advances_revision_without_writing_csv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _layout2_project(tmp_path, monkeypatch)
    app = _app_for(project, tmp_path)
    before = project.storage_revision
    project.shots[0].title = "Revision advanced"

    app_state._autosave(app)

    assert project.storage_revision == before + 1
    assert not (project.metadata_root / "shots.csv").exists()
    manifest = project_manager.parse_project_manifest(
        json.loads(project.json_path.read_text(encoding="utf-8"))
    )
    assert manifest.storage_revision == before + 1

    project_manager.sync_document(project)

    snapshot = project_document.validate_layout2_document(project.document_path)
    assert snapshot.revision == before + 1
