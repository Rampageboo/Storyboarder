from __future__ import annotations

import hashlib
import json
import shutil
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


def _replace_snapshot_values(value, replacements: dict[str, str]):
    if isinstance(value, dict):
        return {
            key: _replace_snapshot_values(item, replacements)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_replace_snapshot_values(item, replacements) for item in value]
    if isinstance(value, str):
        return replacements.get(value, value)
    return value


def _make_scene2d_ids_legacy(project: Project) -> tuple[dict, dict, Path]:
    source_scene = scene2d.list_scenes(project)[0]
    source_perspective = source_scene["perspectives"][0]
    shot = project.shots[0]
    shot.scene_id = source_scene["id"]
    request = generation_service.create_request(
        project,
        shot,
        "codex",
        mode="clean",
        clear_queue_on_result=False,
    )

    legacy_scene_id = "scene_001"
    legacy_perspective_id = "persp_001"
    legacy_root = project.metadata_root / "scenes2d" / legacy_scene_id
    legacy_assets = legacy_root / "perspectives" / legacy_perspective_id
    legacy_assets.mkdir(parents=True)
    legacy_source = f"scenes2d/{legacy_scene_id}/perspectives/{legacy_perspective_id}/source.psd"
    legacy_preview = f"scenes2d/{legacy_scene_id}/perspectives/{legacy_perspective_id}/preview.png"
    shutil.copy2(
        project.metadata_root / source_perspective["source_file_path"],
        project.metadata_root / legacy_source,
    )
    shutil.copy2(
        project.metadata_root / source_perspective["preview_image_path"],
        project.metadata_root / legacy_preview,
    )
    replacements = {
        source_scene["id"]: legacy_scene_id,
        source_perspective["id"]: legacy_perspective_id,
        source_perspective["source_file_path"]: legacy_source,
        source_perspective["preview_image_path"]: legacy_preview,
    }
    legacy_scene = _replace_snapshot_values(source_scene, replacements)
    index = project.metadata_root / "scenes2d" / "scenes2d.json"
    index.write_text(
        json.dumps({"scenes": [legacy_scene]}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (legacy_root / f"{legacy_scene_id}_meta.json").write_text(
        json.dumps(legacy_scene, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    shutil.rmtree(project.metadata_root / "scenes2d" / source_scene["id"])
    shot.scene_id = legacy_scene_id
    project.settings["reference_links"] = [{
        "id": "legacy-scene-link",
        "title": "Legacy scene",
        "type": "scene2d",
        "path": legacy_preview,
        "source_scene2d_id": legacy_scene_id,
        "source_scene2d_perspective_id": legacy_perspective_id,
    }]
    request_path = project_layout.generation_metadata_path(
        project, "requests", f"{request['request_id']}.json"
    )
    request_payload = json.loads(request_path.read_text(encoding="utf-8"))
    request_payload = _replace_snapshot_values(request_payload, replacements)
    request_path.write_text(
        json.dumps(request_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    project_manager.save_project(project)
    return legacy_scene, request_payload, request_path


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
        assert artifact["name"] == Path(artifact["project_relative_path"]).name
        assert artifact["media_type"] == Path(artifact["name"]).suffix.lstrip(".")
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
    source_work = project.metadata_root
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
        assert not source_work.exists()
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
    source_work = project.metadata_root
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
        assert source_work.is_dir()
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


def test_convert_explicitly_maps_legacy_scene2d_and_generation_snapshots(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _legacy_project(tmp_path)
    legacy_scene, source_request, request_path = _make_scene2d_ids_legacy(project)
    source_hash = _sha(project.document_path)
    legacy_source = project.metadata_root / legacy_scene["source_file_path"]
    legacy_preview = project.metadata_root / legacy_scene["preview_image_path"]
    source_bytes = legacy_source.read_bytes()
    preview_bytes = legacy_preview.read_bytes()
    try:
        result = project_convert.materialize_layout1_to_layout2(
            project, tmp_path / "LegacySceneIds.sbd"
        )
        assert _sha(project.document_path) == source_hash
        assert legacy_source.read_bytes() == source_bytes
        assert legacy_preview.read_bytes() == preview_bytes

        monkeypatch.setattr(project_layout, "LAYOUT_2_ENABLED", True)
        converted = project_manager.open_project(result.document_path)
        converted_scene = scene2d.list_scenes(converted)[0]
        converted_perspective = converted_scene["perspectives"][0]
        assert scene2d.is_uuid(converted_scene["id"])
        assert scene2d.is_uuid(converted_perspective["id"])
        assert converted.shots[0].scene_id == converted_scene["id"]
        link = converted.settings["reference_links"][0]
        assert link["source_scene2d_id"] == converted_scene["id"]
        assert link["source_scene2d_perspective_id"] == converted_perspective["id"]
        assert link["path"] == converted_perspective["preview_image_path"]

        converted_request = json.loads(
            project_layout.generation_metadata_path(
                converted, "requests", request_path.name
            ).read_text(encoding="utf-8")
        )
        context = converted_request["scene_context"]
        assert context["id"] == converted_scene["id"]
        assert context["primary_perspective_id"] == converted_perspective["id"]
        assert context["source_file_path"] == converted_perspective["source_file_path"]
        assert context["preview_image_path"] == converted_perspective["preview_image_path"]
        assert converted_request["shot"]["scene_id"] == converted_scene["id"]
        assert converted_request["prompt"]["layers"]["scene_context"] == context
        input_fields = (
            "shot", "scene_bible", "scene_context", "character_bible",
            "prompt_config", "continuity", "references", "keyword_assets",
            "continuity_context", "canvas",
        )
        assert converted_request["input_revision"] == generation_service._canonical_hash(
            {field: converted_request[field] for field in input_fields}
        )
        assert converted_request["consistency_revision"] == generation_service._canonical_hash({
            "scene": context,
            "character_bible": converted_request["character_bible"],
        })
        assert converted_request["input_revision"] != source_request["input_revision"]
    finally:
        project_manager.cleanup_document_working_root(project)


@pytest.mark.parametrize(
    "mismatch",
    [
        "request_id",
        "shot_id",
        "state_request_id",
        "result_request_id",
        "result_id",
        "output_id",
    ],
)
def test_convert_rejects_generation_storage_identity_mismatch(
    tmp_path: Path,
    mismatch: str,
) -> None:
    project = _legacy_project(tmp_path)
    request_path = next(
        project_layout.generation_metadata_path(project, "requests").glob("*.json")
    )
    request = json.loads(request_path.read_text(encoding="utf-8"))
    result_path = next(
        project_layout.generation_metadata_path(project, "results").glob("*/*.json")
    )
    result = json.loads(result_path.read_text(encoding="utf-8"))
    if mismatch == "request_id":
        request["request_id"] = "other_request"
        request_path.write_text(json.dumps(request), encoding="utf-8")
    elif mismatch == "shot_id":
        request["shot_id"] = "missing-shot"
        request["shot"]["shot_id"] = "missing-shot"
        request_path.write_text(json.dumps(request), encoding="utf-8")
    elif mismatch == "state_request_id":
        state_path = project_layout.generation_metadata_path(
            project, "state", f"{request['request_id']}.json"
        )
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps({
            "schema_version": generation_service.SCHEMA_VERSION,
            "request_id": "other_state",
            "status": "queued",
        }), encoding="utf-8")
    elif mismatch == "result_request_id":
        result["request_id"] = "other_request"
        result_path.write_text(json.dumps(result), encoding="utf-8")
    elif mismatch == "result_id":
        result["result_id"] = "other_result"
        result_path.write_text(json.dumps(result), encoding="utf-8")
    else:
        result["artifacts"][0]["output_id"] = "other_output"
        result_path.write_text(json.dumps(result), encoding="utf-8")
    try:
        with pytest.raises(project_convert.Layout2ConvertError) as raised:
            project_convert.materialize_layout1_to_layout2(
                project, tmp_path / f"Bad-{mismatch}.sbd"
            )
        assert raised.value.stage == "classification"
        assert not (tmp_path / f"Bad-{mismatch}").exists()
    finally:
        project_manager.cleanup_document_working_root(project)


@pytest.mark.parametrize(
    "malformation",
    [
        "request_destination",
        "request_provider",
        "request_mode",
        "request_status",
        "request_clear_queue",
        "state_status",
        "result_empty",
        "result_too_many",
        "artifact_zero_bytes",
        "artifact_oversized",
        "artifact_corrupt",
        "artifact_name",
        "artifact_media_type",
    ],
)
def test_convert_rejects_generation_contract_malformation(
    tmp_path: Path,
    malformation: str,
) -> None:
    project = _legacy_project(tmp_path)
    source_hash = _sha(project.document_path)
    request_path = next(
        project_layout.generation_metadata_path(project, "requests").glob("*.json")
    )
    request = json.loads(request_path.read_text(encoding="utf-8"))
    result_path = next(
        project_layout.generation_metadata_path(project, "results").glob("*/*.json")
    )
    result = json.loads(result_path.read_text(encoding="utf-8"))
    artifact = result["artifacts"][0]
    artifact_path = project.metadata_root / artifact["project_relative_path"]

    if malformation.startswith("request_"):
        field = malformation.removeprefix("request_")
        if field == "clear_queue":
            request["clear_queue_on_result"] = "false"
        else:
            request[field] = "unsupported"
        request_path.write_text(json.dumps(request), encoding="utf-8")
    elif malformation == "state_status":
        state_path = project_layout.generation_metadata_path(
            project, "state", f"{request['request_id']}.json"
        )
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps({
            "schema_version": generation_service.SCHEMA_VERSION,
            "request_id": request["request_id"],
            "status": "unsupported",
        }), encoding="utf-8")
    elif malformation == "result_empty":
        result["artifacts"] = []
        result_path.write_text(json.dumps(result), encoding="utf-8")
    elif malformation == "result_too_many":
        result["artifacts"] = [
            dict(artifact) for _ in range(generation_service.MAX_ARTIFACTS + 1)
        ]
        result_path.write_text(json.dumps(result), encoding="utf-8")
    elif malformation == "artifact_zero_bytes":
        artifact_path.write_bytes(b"")
    elif malformation == "artifact_oversized":
        with artifact_path.open("wb") as stream:
            stream.seek(generation_service.MAX_ARTIFACT_BYTES)
            stream.write(b"\0")
    elif malformation == "artifact_corrupt":
        artifact_path.write_bytes(b"not-a-real-png")
    elif malformation == "artifact_name":
        artifact["name"] = "other.png"
        result_path.write_text(json.dumps(result), encoding="utf-8")
    else:
        artifact["media_type"] = "jpeg"
        result_path.write_text(json.dumps(result), encoding="utf-8")

    target_name = f"BadContract-{malformation}"
    try:
        with pytest.raises(project_convert.Layout2ConvertError) as raised:
            project_convert.materialize_layout1_to_layout2(
                project, tmp_path / f"{target_name}.sbd"
            )
        assert raised.value.stage == "classification"
        assert raised.value.report_path is not None
        report = json.loads(
            raised.value.report_path.read_text(encoding="utf-8")
        )
        assert report["status"] == "failed"
        assert report["stage"] == "classification"
        assert not (tmp_path / target_name).exists()
        assert _sha(project.document_path) == source_hash
    finally:
        project_manager.cleanup_document_working_root(project)


def test_convert_duplicates_one_source_across_reference_and_generated_roles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _legacy_project(tmp_path)
    result_path = next(
        project_layout.generation_metadata_path(project, "results").glob("*/*.json")
    )
    source_result = json.loads(result_path.read_text(encoding="utf-8"))
    shared_source = source_result["artifacts"][0]["project_relative_path"]
    project.shots[0].reference_image_paths.append(shared_source)
    try:
        result = project_convert.materialize_layout1_to_layout2(
            project, tmp_path / "CrossRole.sbd"
        )
        monkeypatch.setattr(project_layout, "LAYOUT_2_ENABLED", True)
        converted = project_manager.open_project(result.document_path)
        reference_path = converted.shots[0].reference_image_paths[-1]
        converted_result_path = next(
            project_layout.generation_metadata_path(converted, "results").glob("*/*.json")
        )
        converted_result = json.loads(converted_result_path.read_text(encoding="utf-8"))
        generated_path = converted_result["artifacts"][0]["project_relative_path"]
        assert reference_path.startswith("Images/References/")
        assert generated_path.startswith("Images/Generated/")
        assert reference_path != generated_path
        assert (converted.project_root / reference_path).read_bytes() == (
            converted.project_root / generated_path
        ).read_bytes()
    finally:
        project_manager.cleanup_document_working_root(project)


def test_convert_keeps_blender_preview_in_derived_cache_role(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _legacy_project(tmp_path)
    source_scene = next(
        row for row in scene3d.list_scenes(project)["scenes"]
        if row.get("blend_file_path")
    )
    blend_path = project.metadata_root / source_scene["blend_file_path"]
    configured = scene3d.configure_blend_preview(
        project, source_scene["id"], blend_path
    )
    preview = project.metadata_root / configured["file_path"]
    preview.parent.mkdir(parents=True, exist_ok=True)
    preview.write_bytes(b"derived-glb-preview")
    project_manager.save_project(project)
    try:
        result = project_convert.materialize_layout1_to_layout2(
            project, tmp_path / "BlenderPreview.sbd"
        )
        monkeypatch.setattr(project_layout, "LAYOUT_2_ENABLED", True)
        converted = project_manager.open_project(result.document_path)
        converted_scene = next(
            row for row in scene3d.list_scenes(converted)["scenes"]
            if row["id"] == source_scene["id"]
        )
        assert converted_scene["source_type"] == "blender"
        assert converted_scene["blend_file_path"] == f"Blender/{source_scene['id']}.blend"
        assert converted_scene["file_path"] == (
            f".storyboarder/cache/scene3d/{source_scene['id']}/storyboarder_preview.glb"
        )
        assert (converted.project_root / converted_scene["file_path"]).read_bytes() == (
            b"derived-glb-preview"
        )
        assert not (converted.project_root / f"Blender/{source_scene['id']}.glb").exists()
    finally:
        project_manager.cleanup_document_working_root(project)


def test_convert_excludes_legacy_psd_recovery_history(
    tmp_path: Path,
) -> None:
    project = _legacy_project(tmp_path)
    relative = "shots/shot-convert/_history/shot-convert.broken-20260730.psd"
    recovery = project.metadata_root / relative
    recovery.parent.mkdir(parents=True)
    recovery.write_bytes(b"legacy-recovery")
    try:
        result = project_convert.materialize_layout1_to_layout2(
            project, tmp_path / "RecoveryHistory.sbd"
        )
        assert relative in result.excluded_paths
        assert recovery.read_bytes() == b"legacy-recovery"
        assert not any(
            path.name == recovery.name
            for path in result.destination_root.rglob("*")
        )
        assert any(
            row["source"] == relative
            and row["kind"] == "excluded legacy PSD recovery backup"
            for row in result.report["classifications"]
        )
    finally:
        project_manager.cleanup_document_working_root(project)


def test_convert_initial_report_failure_prevents_semantic_work(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _legacy_project(tmp_path)
    copy_started = False

    def fail_report(_path, _report):
        raise OSError("injected durable report failure")

    def observe_copy(*args, **kwargs):
        nonlocal copy_started
        copy_started = True

    monkeypatch.setattr(project_convert, "_write_report", fail_report)
    monkeypatch.setattr(project_convert, "_copy_inventory", observe_copy)
    try:
        with pytest.raises(
            project_convert.Layout2ConvertError,
            match="Conversion report could not be persisted",
        ) as raised:
            project_convert.materialize_layout1_to_layout2(
                project, tmp_path / "ReportFailure.sbd"
            )
        assert raised.value.stage == "snapshot"
        assert raised.value.report_path is None
        assert copy_started is False
        assert not (tmp_path / "ReportFailure").exists()
    finally:
        project_manager.cleanup_document_working_root(project)


def test_convert_cleanup_failure_does_not_rollback_committed_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(project_layout, "LAYOUT_2_ENABLED", True)
    project = _legacy_project(tmp_path)
    app = _app_for(project, tmp_path)
    original_cleanup = project_manager.cleanup_document_working_root

    def fail_cleanup(_project):
        raise OSError("injected cleanup failure")

    monkeypatch.setattr(
        project_manager,
        "cleanup_document_working_root",
        fail_cleanup,
    )
    try:
        payload = StoryboardBackendService(app).method_convert_project(
            str(tmp_path / "CleanupWarning.sbd")
        )
        assert payload["document_path"] == str(
            (tmp_path / "CleanupWarning" / "CleanupWarning.sbd").resolve()
        )
        assert app.state.project.layout == 2
        assert app.state.last_project_transition["status"] == "committed"
        assert (tmp_path / "CleanupWarning" / "CleanupWarning.sbd").is_file()
    finally:
        original_cleanup(project)
