from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from PIL import Image
from storyboard_tool import (
    app_state,
    generation_service,
    project_convert,
    project_document,
    project_layout,
    project_manager,
    scene2d,
    scene3d,
)
from storyboard_tool.api import create_app
from storyboard_tool.backend_service import StoryboardBackendService
from storyboard_tool.models import Project, Shot


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _legacy_project(tmp_path: Path) -> Project:
    document = tmp_path / "Legacy.sbd"
    project = project_manager.create_document(document)
    shot = Shot(shot_id="shot-convert", title="Saved title")
    project.shots.append(shot)
    project_manager._ensure_shot_files(project, shot)
    source = project.metadata_root / "shots" / shot.shot_id / f"{shot.shot_id}.psd"
    preview = project.metadata_root / "shots" / shot.shot_id / f"{shot.shot_id}.png"
    source.write_bytes(b"8BPS-layout-one-source")
    preview.write_bytes(b"\x89PNG\r\n\x1a\nlayout-one-preview")
    shot.source_file_path = source.relative_to(project.metadata_root).as_posix()
    shot.image_path = preview.relative_to(project.metadata_root).as_posix()
    shot.preview_image_path = shot.image_path
    project.settings["backup_on_save"] = False
    reference = project.metadata_root / "references" / "character.png"
    reference.write_bytes(b"\x89PNG\r\n\x1a\nreference")
    shot.reference_image_paths = [reference.relative_to(project.metadata_root).as_posix()]
    (project.metadata_root / "exports" / "boards.txt").write_text("export", encoding="utf-8")
    scene, _scenes = scene2d.create_scene(project, "Legacy map")
    (project.metadata_root / scene["preview_image_path"]).write_bytes(b"legacy-preview")
    scene3d.create_scene(project, title="Legacy stage")
    request = generation_service.create_request(
        project, shot, "queue", mode="clean", clear_queue_on_result=False
    )
    generated = tmp_path / "candidate.png"
    Image.new("RGB", (1, 1), "white").save(generated)
    generation_service.submit_result(project, request["request_id"], [str(generated)])
    project_manager.save_project(project)
    return project


def _app_for(project: Project, tmp_path: Path):
    app_root = tmp_path / "app"
    app_root.mkdir(exist_ok=True)
    app = create_app(app_root)
    app.state.project = project
    app.state.project_disk_mtime = project_manager.project_disk_mtime(project)
    app.state.dirty = True
    return app


def _operations(tmp_path: Path, stem: str) -> list[Path]:
    return sorted(tmp_path.glob(f".{stem}.convert-*"))


def test_convert_rewrites_representative_layout1_and_preserves_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _legacy_project(tmp_path)
    source_hash = _sha(project.document_path)
    project.shots[0].title = "Unsaved in-memory title"
    try:
        result = project_convert.materialize_layout1_to_layout2(
            project, tmp_path / "Converted.sbd"
        )

        assert _sha(project.document_path) == source_hash
        assert result.source_hash == source_hash
        assert result.destination_root == tmp_path / "Converted"
        assert result.document_path == tmp_path / "Converted" / "Converted.sbd"
        project_document.validate_layout2_document(result.document_path)
        monkeypatch.setattr(project_layout, "LAYOUT_2_ENABLED", True)
        converted = project_manager.open_project(result.document_path)
        assert converted.layout == 2
        assert converted.shots[0].title == "Unsaved in-memory title"
        assert converted.converted_from["source_hash"] == source_hash
        assert converted.converted_from["source_version"] == 4
        assert (converted.project_root / converted.shots[0].source_file_path).read_bytes() == (
            b"8BPS-layout-one-source"
        )
        assert converted.shots[0].reference_image_paths[0].startswith("Images/References/")
        assert (converted.project_root / "Exports" / "boards.txt").read_text(
            encoding="utf-8"
        ) == "export"
        converted_scene2d = scene2d.list_scenes(converted)[0]
        assert converted_scene2d["source_file_path"].startswith("PSD/Scene2D/")
        assert scene3d.list_scenes(converted)["scenes"]
        assert not (converted.project_root / "shots").exists()
        request_files = sorted(
            project_layout.generation_metadata_path(converted, "requests").glob("*.json")
        )
        result_files = sorted(
            project_layout.generation_metadata_path(converted, "results").glob("*/*.json")
        )
        assert len(request_files) == len(result_files) == 1
        converted_result = json.loads(result_files[0].read_text(encoding="utf-8"))
        artifact = converted_result["artifacts"][0]
        assert artifact["project_relative_path"].startswith("Images/Generated/")
        assert Path(artifact["absolute_path"]).is_file()
    finally:
        project_manager.cleanup_document_working_root(project)


def test_convert_unknown_member_fails_with_durable_inventory_report(
    tmp_path: Path,
) -> None:
    project = _legacy_project(tmp_path)
    source_hash = _sha(project.document_path)
    (project.metadata_root / "mystery.bin").write_bytes(b"unknown")
    try:
        with pytest.raises(project_convert.Layout2ConvertError) as raised:
            project_convert.materialize_layout1_to_layout2(
                project, tmp_path / "UnknownTarget.sbd"
            )

        error = raised.value
        assert error.stage == "classification"
        assert error.report_path is not None and error.report_path.is_file()
        report = json.loads(error.report_path.read_text(encoding="utf-8"))
        assert report["status"] == "failed"
        assert report["unknown_members"] == ["mystery.bin"]
        assert not (tmp_path / "UnknownTarget").exists()
        assert _sha(project.document_path) == source_hash
    finally:
        project_manager.cleanup_document_working_root(project)


def test_convert_missing_known_asset_fails_and_preserves_source(tmp_path: Path) -> None:
    project = _legacy_project(tmp_path)
    source_hash = _sha(project.document_path)
    project.shots[0].source_file_path = "shots/shot-convert/missing.psd"
    try:
        with pytest.raises(project_convert.Layout2ConvertError, match="Missing required"):
            project_convert.materialize_layout1_to_layout2(
                project, tmp_path / "MissingTarget.sbd"
            )
        assert _sha(project.document_path) == source_hash
        assert not (tmp_path / "MissingTarget").exists()
    finally:
        project_manager.cleanup_document_working_root(project)


def test_convert_rejects_existing_and_casefold_destination(tmp_path: Path) -> None:
    project = _legacy_project(tmp_path)
    source_hash = _sha(project.document_path)
    (tmp_path / "Existing").mkdir()
    (tmp_path / "casefold").mkdir()
    try:
        with pytest.raises(FileExistsError):
            project_convert.materialize_layout1_to_layout2(
                project, tmp_path / "Existing.sbd"
            )
        with pytest.raises(FileExistsError):
            project_convert.materialize_layout1_to_layout2(
                project, tmp_path / "CASEFOLD.sbd"
            )
        assert _sha(project.document_path) == source_hash
    finally:
        project_manager.cleanup_document_working_root(project)


def test_convert_copy_failure_preserves_stage_report_and_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _legacy_project(tmp_path)
    source_hash = _sha(project.document_path)
    original_copy2 = project_convert.shutil.copy2

    def fail_semantic_copy(source, destination, *args, **kwargs):
        if Path(source).suffix.lower() == ".psd":
            raise OSError("injected semantic copy failure")
        return original_copy2(source, destination, *args, **kwargs)

    monkeypatch.setattr(project_convert.shutil, "copy2", fail_semantic_copy)
    try:
        with pytest.raises(project_convert.Layout2ConvertError) as raised:
            project_convert.materialize_layout1_to_layout2(
                project, tmp_path / "CopyFault.sbd"
            )
        assert raised.value.operation_path is not None
        assert raised.value.report_path is not None
        assert not (tmp_path / "CopyFault").exists()
        assert _sha(project.document_path) == source_hash
    finally:
        project_manager.cleanup_document_working_root(project)


def test_convert_rename_failure_preserves_complete_stage_and_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _legacy_project(tmp_path)
    source_hash = _sha(project.document_path)

    def fail_rename(source, destination):
        raise OSError("injected rename failure")

    monkeypatch.setattr(project_convert.os, "rename", fail_rename)
    try:
        with pytest.raises(project_convert.Layout2ConvertError) as raised:
            project_convert.materialize_layout1_to_layout2(
                project, tmp_path / "RenameFault.sbd"
            )
        error = raised.value
        assert error.stage == "rename"
        assert error.operation_path is not None
        staged = error.operation_path / "target" / "RenameFault.sbd"
        assert staged.is_file()
        project_document.validate_layout2_document(staged)
        assert error.report_path is not None and error.report_path.is_file()
        assert not (tmp_path / "RenameFault").exists()
        assert _sha(project.document_path) == source_hash
    finally:
        project_manager.cleanup_document_working_root(project)


def test_convert_coordinator_activates_only_validated_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(project_layout, "LAYOUT_2_ENABLED", True)
    project = _legacy_project(tmp_path)
    source_hash = _sha(project.document_path)
    app = _app_for(project, tmp_path)
    source_session = app.state.project_session_id
    try:
        payload = StoryboardBackendService(app).method_convert_project(
            str(tmp_path / "Activated.sbd")
        )
        assert payload["document_path"] == str(
            (tmp_path / "Activated" / "Activated.sbd").resolve()
        )
        assert app.state.project.layout == 2
        assert app.state.project_session_id != source_session
        assert app.state.dirty is False
        assert _sha(project.document_path) == source_hash
        assert app.state.last_project_transition["status"] == "committed"
    finally:
        project_manager.cleanup_document_working_root(project)


def test_convert_activation_failure_leaves_source_active_and_target_complete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(project_layout, "LAYOUT_2_ENABLED", True)
    project = _legacy_project(tmp_path)
    source_hash = _sha(project.document_path)
    app = _app_for(project, tmp_path)
    monkeypatch.setattr(
        project_manager,
        "validate_transition_candidate",
        lambda candidate: (_ for _ in ()).throw(ValueError("injected activation failure")),
    )
    try:
        with pytest.raises(HTTPException):
            StoryboardBackendService(app).method_convert_project(
                str(tmp_path / "Completed.sbd")
            )
        assert app.state.project is project
        assert app.state.dirty is True
        completed = tmp_path / "Completed" / "Completed.sbd"
        assert completed.is_file()
        project_document.validate_layout2_document(completed)
        assert app.state.last_project_transition["completed_target"] == str(
            tmp_path / "Completed"
        )
        assert _sha(project.document_path) == source_hash
    finally:
        project_manager.cleanup_document_working_root(project)


@pytest.mark.parametrize("writer", ["external", "builtin"])
def test_convert_writer_block_occurs_before_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    writer: str,
) -> None:
    project = _legacy_project(tmp_path)
    source_hash = _sha(project.document_path)
    app = _app_for(project, tmp_path)
    if writer == "external":
        monkeypatch.setattr(
            app_state.blender_bridge,
            "require_released",
            lambda *args: (_ for _ in ()).throw(ValueError("external writer active")),
        )
    else:
        app.state.bpy_viewport_manager = SimpleNamespace(running=True)
    try:
        with pytest.raises(HTTPException) as raised:
            StoryboardBackendService(app).method_convert_project(
                str(tmp_path / "Blocked.sbd")
            )
        assert raised.value.status_code == 409
        assert app.state.project is project
        assert not (tmp_path / "Blocked").exists()
        assert _operations(tmp_path, "Blocked") == []
        assert _sha(project.document_path) == source_hash
    finally:
        project_manager.cleanup_document_working_root(project)


def test_convert_api_route_and_no_layout2_to_layout1(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(project_layout, "LAYOUT_2_ENABLED", True)
    project = _legacy_project(tmp_path)
    app = _app_for(project, tmp_path)
    try:
        with TestClient(app) as client:
            app.state.project = project
            response = client.post(
                "/api/project/convert", json={"path": str(tmp_path / "ViaApi.sbd")}
            )
            assert response.status_code == 200
            second = client.post(
                "/api/project/convert", json={"path": str(tmp_path / "Reverse.sbd")}
            )
            assert second.status_code == 409
            assert not (tmp_path / "Reverse").exists()
    finally:
        project_manager.cleanup_document_working_root(project)

def test_convert_reparse_preflight_creates_no_stage_and_preserves_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _legacy_project(tmp_path)
    source_hash = _sha(project.document_path)
    source_root = project.project_root.absolute()
    original_is_reparse = project_convert._is_reparse

    def injected_reparse(path: Path) -> bool:
        if Path(path).absolute() == source_root:
            return True
        return original_is_reparse(path)

    monkeypatch.setattr(project_convert, "_is_reparse", injected_reparse)
    try:
        with pytest.raises(ValueError, match="reparse point"):
            project_convert.materialize_layout1_to_layout2(
                project, tmp_path / "Reparse.sbd"
            )
        assert _operations(tmp_path, "Reparse") == []
        assert _sha(project.document_path) == source_hash
    finally:
        project_manager.cleanup_document_working_root(project)


def test_convert_disk_preflight_creates_no_stage_and_preserves_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _legacy_project(tmp_path)
    source_hash = _sha(project.document_path)
    monkeypatch.setattr(
        project_convert.shutil,
        "disk_usage",
        lambda _path: SimpleNamespace(total=1, used=1, free=0),
    )
    try:
        with pytest.raises(OSError, match="Insufficient free space"):
            project_convert.materialize_layout1_to_layout2(
                project, tmp_path / "DiskFull.sbd"
            )
        assert _operations(tmp_path, "DiskFull") == []
        assert _sha(project.document_path) == source_hash
    finally:
        project_manager.cleanup_document_working_root(project)


def test_convert_crash_preserves_report_stage_and_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _legacy_project(tmp_path)
    source_hash = _sha(project.document_path)

    def crash(_planner) -> None:
        raise KeyboardInterrupt("injected conversion crash")

    monkeypatch.setattr(project_convert, "_migrate_references", crash)
    try:
        with pytest.raises(project_convert.Layout2ConvertError) as raised:
            project_convert.materialize_layout1_to_layout2(
                project, tmp_path / "Crash.sbd"
            )
        assert raised.value.stage == "classification"
        assert raised.value.operation_path is not None
        assert raised.value.report_path is not None and raised.value.report_path.is_file()
        report = json.loads(raised.value.report_path.read_text(encoding="utf-8"))
        assert report["status"] == "failed"
        assert "injected conversion crash" in report["error"]
        assert _sha(project.document_path) == source_hash
    finally:
        project_manager.cleanup_document_working_root(project)


def test_convert_detects_source_document_change_without_publishing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _legacy_project(tmp_path)
    source_hash = _sha(project.document_path)
    source_document = project.document_path.resolve()
    original_record = project_convert._record
    source_reads = 0

    def injected_record(path: Path):
        nonlocal source_reads
        record = original_record(path)
        if Path(path).resolve() == source_document:
            source_reads += 1
            if source_reads > 1:
                return project_convert.FileRecord(record.size + 1, record.sha256)
        return record

    monkeypatch.setattr(project_convert, "_record", injected_record)
    try:
        with pytest.raises(project_convert.Layout2ConvertError) as raised:
            project_convert.materialize_layout1_to_layout2(
                project, tmp_path / "SourceChanged.sbd"
            )
        assert raised.value.stage == "source_integrity"
        assert not (tmp_path / "SourceChanged").exists()
        assert _sha(project.document_path) == source_hash
    finally:
        project_manager.cleanup_document_working_root(project)


@pytest.mark.parametrize(
    "provenance",
    [
        [],
        {"source_path": "Legacy.sbd"},
        {
            "source_path": "Legacy.sbd",
            "timestamp": "2026-07-30T00:00:00Z",
            "source_version": True,
            "source_hash": "0" * 64,
        },
        {
            "source_path": "Legacy.sbd",
            "timestamp": "2026-07-30T00:00:00Z",
            "source_version": 4,
            "source_hash": "not-a-sha",
        },
    ],
)
def test_layout2_conversion_provenance_fails_closed(provenance) -> None:
    with pytest.raises(project_layout.ProjectSchemaError, match="converted_from"):
        project_layout.parse_project_manifest(
            {
                "version": 4,
                "layout": 2,
                "project_id": "project-id",
                "storage_revision": 1,
                "converted_from": provenance,
            }
        )


def test_convert_rejects_malformed_known_generation_metadata(
    tmp_path: Path,
) -> None:
    project = _legacy_project(tmp_path)
    source_hash = _sha(project.document_path)
    request_path = next(
        project_layout.generation_metadata_path(project, "requests").glob("*.json")
    )
    payload = json.loads(request_path.read_text(encoding="utf-8"))
    payload["prompt_config"]["reference_bindings"] = "not-a-list"
    request_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    try:
        with pytest.raises(
            project_convert.Layout2ConvertError,
            match="Generation request bindings are invalid",
        ) as raised:
            project_convert.materialize_layout1_to_layout2(
                project, tmp_path / "BadGeneration.sbd"
            )
        assert raised.value.stage == "classification"
        assert raised.value.report_path is not None
        assert not (tmp_path / "BadGeneration").exists()
        assert _sha(project.document_path) == source_hash
    finally:
        project_manager.cleanup_document_working_root(project)


def test_convert_writer_quiesce_timeout_occurs_before_staging(
    tmp_path: Path,
) -> None:
    project = _legacy_project(tmp_path)
    source_hash = _sha(project.document_path)
    app = _app_for(project, tmp_path)
    app_state._ensure_transition_runtime(app)
    app.state.active_project_writers = {"preview_analysis": 1}
    app.state.project_writer_quiesce_timeout = 0.0
    try:
        with pytest.raises(HTTPException) as raised:
            StoryboardBackendService(app).method_convert_project(
                str(tmp_path / "Busy.sbd")
            )
        assert raised.value.status_code == 409
        assert app.state.project is project
        assert app.state.project_writers_quiesced is False
        assert _operations(tmp_path, "Busy") == []
        assert _sha(project.document_path) == source_hash
    finally:
        app.state.active_project_writers = {}
        project_manager.cleanup_document_working_root(project)


def test_convert_feature_gate_blocks_before_quiesce_or_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(project_layout, "LAYOUT_2_ENABLED", False)
    project = _legacy_project(tmp_path)
    source_hash = _sha(project.document_path)
    app = _app_for(project, tmp_path)
    try:
        with pytest.raises(HTTPException) as raised:
            StoryboardBackendService(app).method_convert_project(
                str(tmp_path / "Disabled.sbd")
            )
        assert raised.value.status_code == 409
        assert app.state.project is project
        assert not hasattr(app.state, "project_writers_quiesced")
        assert _operations(tmp_path, "Disabled") == []
        assert _sha(project.document_path) == source_hash
    finally:
        project_manager.cleanup_document_working_root(project)
