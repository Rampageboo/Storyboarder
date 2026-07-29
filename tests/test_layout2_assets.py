from __future__ import annotations

import io
import re
import uuid
from pathlib import Path

import pytest
from fastapi import FastAPI
from PIL import Image

from storyboard_tool import export_service, generation_service, project_manager
from storyboard_tool.file_transactions import (
    atomic_copy_stream,
    atomic_output_directory,
)
from storyboard_tool.models import Project, Shot
from storyboard_tool.plugin_service import PluginBridgeService
from storyboard_tool.project_layout import (
    ProjectPathError,
    generation_metadata_path,
    project_relative_posix,
    resolve_shot_asset,
    shot_asset_relative,
)
from storyboard_tool.reference_segments import (
    import_project_reference_stream,
    restore_boards_from_undo,
    snapshot_boards_for_undo,
)


def _project(tmp_path: Path) -> tuple[Project, Shot]:
    root = tmp_path / "Portable"
    work = root / ".storyboarder" / "work"
    work.mkdir(parents=True)
    shot = Shot(shot_id="shot-alpha")
    project = Project(
        root_path=work,
        project_root_path=root,
        document_path=root / "Portable.sbd",
        layout=2,
        project_id=str(uuid.uuid4()),
        storage_revision=4,
        shots=[shot],
        settings=dict(project_manager.DEFAULT_SETTINGS),
    )
    return project, shot


def _png_bytes(color: str = "red") -> bytes:
    stream = io.BytesIO()
    Image.new("RGB", (8, 6), color).save(stream, "PNG")
    return stream.getvalue()


def _png(path: Path, color: str = "red") -> Path:
    path.write_bytes(_png_bytes(color))
    return path


def test_layout2_exact_asset_roles_have_no_per_shot_directory(tmp_path: Path) -> None:
    project, shot = _project(tmp_path)

    assert shot_asset_relative(project, shot.shot_id, "source_psd") == "PSD/Shots/shot-alpha.psd"
    assert shot_asset_relative(project, shot.shot_id, "preview") == "Images/Shots/shot-alpha_preview.png"
    assert shot_asset_relative(project, shot.shot_id, "board_background") == (
        "Images/Shots/shot-alpha_background.png"
    )
    assert shot_asset_relative(project, shot.shot_id, "codex") == "Images/Shots/shot-alpha_codex.png"
    assert shot_asset_relative(project, shot.shot_id, "thumbnail") == (
        ".storyboarder/cache/thumbnails/shot-alpha.png"
    )
    assert project.references_dir == project.project_root / "Images" / "References"
    assert project.exports_dir == project.project_root / "Exports"
    assert project.backups_dir == project.project_root / ".storyboarder" / "backups"
    with pytest.raises(ProjectPathError, match="no Layout 2 directory alias"):
        _ = project.shots_dir

    project_manager._ensure_shot_files(project, shot)

    assert (project.project_root / "Images" / "Shots").is_dir()
    assert not (project.project_root / "shots").exists()
    assert (project.metadata_root / "annotations" / "shot-alpha.json").is_file()
    assert (project.metadata_root / "notes" / "shot-alpha.json").is_file()


def test_layout2_plugin_health_finds_canonical_psd_without_stored_path(
    tmp_path: Path,
) -> None:
    project, shot = _project(tmp_path)
    source = resolve_shot_asset(project, shot.shot_id, "source_psd")
    source.parent.mkdir(parents=True)
    source.write_bytes(b"8BPS-layout2")

    resolved = PluginBridgeService(FastAPI()).shot_psd_path(project, shot)

    assert shot.source_file_path == ""
    assert resolved == source


def test_layout2_reference_and_export_paths_are_exact(tmp_path: Path) -> None:
    project, shot = _project(tmp_path)

    shot_reference = project_manager.add_reference_image_stream(
        project, shot, io.BytesIO(_png_bytes()), ".png"
    )
    project_reference = import_project_reference_stream(
        project, io.BytesIO(_png_bytes("blue")), "board.png"
    )

    assert re.fullmatch(
        r"Images/References/[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\.png",
        project_relative_posix(project, shot_reference),
    )
    assert re.fullmatch(
        r"Images/References/[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\.png",
        project_reference["path"],
    )
    assert export_service.resolve_output_path(project, "pdf") == (
        project.project_root / "Exports" / "storyboard.pdf"
    )
    assert not (project.project_root / "references").exists()
    assert not (project.project_root / "exports").exists()


def test_layout2_reference_undo_backup_is_flat(tmp_path: Path) -> None:
    project, shot = _project(tmp_path)
    background = resolve_shot_asset(project, shot.shot_id, "board_background")
    background.parent.mkdir(parents=True)
    _png(background)

    token = snapshot_boards_for_undo(project, 0, 0)
    backup_root = project.backups_dir / "ref_undo" / token

    assert (backup_root / "shot-alpha_background.png").is_file()
    assert not (backup_root / shot.shot_id).exists()
    _png(background, "blue")
    restore_boards_from_undo(project, token)
    with Image.open(background) as restored:
        assert restored.getpixel((0, 0)) == (255, 0, 0)


def test_layout2_generation_metadata_and_artifacts_use_separate_roots(tmp_path: Path) -> None:
    project, shot = _project(tmp_path)
    request = generation_service.create_request(project, shot, "codex")
    first = _png(tmp_path / "first.png")
    second = _png(tmp_path / "second.png", "blue")

    result = generation_service.submit_result(
        project, request["request_id"], [str(first), str(second)]
    )

    request_id = request["request_id"]
    result_id = result["result_id"]
    assert generation_metadata_path(project, "requests", f"{request_id}.json").is_file()
    assert generation_metadata_path(
        project, "results", request_id, f"{result_id}.json"
    ).is_file()
    assert [item["project_relative_path"] for item in result["artifacts"]] == [
        f"Images/Generated/{request_id}_{result_id}.png",
        f"Images/Generated/{request_id}_{result_id}_002.png",
    ]
    assert [item["output_id"] for item in result["artifacts"]] == [
        result_id,
        f"{result_id}_002",
    ]
    assert not (project.project_root / "generation").exists()
    assert not (project.project_root / "shots").exists()


def test_atomic_stream_failure_preserves_existing_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "asset.glb"
    target.write_bytes(b"old")

    def fail_replace(_source: Path, _target: Path) -> None:
        raise OSError("injected replace failure")

    monkeypatch.setattr("storyboard_tool.file_transactions.os.replace", fail_replace)
    with pytest.raises(OSError, match="injected"):
        atomic_copy_stream(io.BytesIO(b"new"), target)

    assert target.read_bytes() == b"old"
    assert not target.with_suffix(".glb.tmp").exists()


def test_background_failure_preserves_previous_asset_and_cleans_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, shot = _project(tmp_path)
    source = _png(tmp_path / "source.png", "blue")
    target = resolve_shot_asset(project, shot.shot_id, "board_background")
    target.parent.mkdir(parents=True)
    _png(target, "red")
    before = target.read_bytes()

    def fail_replace(_source: Path, _target: Path) -> None:
        raise OSError("injected replace failure")

    monkeypatch.setattr("storyboard_tool.project_manager.os.replace", fail_replace)
    with pytest.raises(OSError, match="injected"):
        project_manager._apply_reference_frame_to_shot(project, shot, source, "fit")

    assert target.read_bytes() == before
    assert not target.with_suffix(".tmp.png").exists()


def test_generation_copy_failure_removes_partial_layout2_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, shot = _project(tmp_path)
    request = generation_service.create_request(project, shot, "queue")
    first = _png(tmp_path / "first.png")
    second = _png(tmp_path / "second.png", "blue")
    real_copy = generation_service._copy_image_artifact
    calls = 0

    def fail_second(source: Path, target: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected artifact failure")
        real_copy(source, target)

    monkeypatch.setattr(generation_service, "_copy_image_artifact", fail_second)
    with pytest.raises(OSError, match="injected"):
        generation_service.submit_result(
            project, request["request_id"], [str(first), str(second)]
        )

    generated = project.project_root / "Images" / "Generated"
    assert not generated.exists() or list(generated.iterdir()) == []
    results = generation_metadata_path(project, "results", request["request_id"])
    assert not results.exists() or list(results.iterdir()) == []


def test_export_file_failure_preserves_previous_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from storyboard_tool import pdf_exporter

    project, _shot = _project(tmp_path)
    target = export_service.resolve_output_path(project, "pdf")
    target.parent.mkdir(parents=True)
    target.write_bytes(b"previous pdf")

    def fail_export(_project: Project, staged: Path, *, layout: str) -> None:
        del layout
        staged.write_bytes(b"partial pdf")
        raise OSError("injected export failure")

    monkeypatch.setattr(pdf_exporter, "export_storyboard_pdf", fail_export)
    with pytest.raises(OSError, match="injected"):
        export_service.export_pdf(project)

    assert target.read_bytes() == b"previous pdf"
    assert list(target.parent.glob(".storyboard-*")) == []


def test_export_directory_failure_preserves_previous_sequence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, _shot = _project(tmp_path)
    target = export_service.resolve_output_path(project, "image_sequence")
    target.mkdir(parents=True)
    (target / "board_0001.png").write_bytes(b"previous")

    def fail_export(_project: Project, staged: Path) -> Path:
        (staged / "board_0001.png").write_bytes(b"partial")
        raise OSError("injected sequence failure")

    monkeypatch.setattr(export_service, "_export_image_sequence", fail_export)
    with pytest.raises(OSError, match="injected"):
        export_service.export_image_sequence(project)

    assert (target / "board_0001.png").read_bytes() == b"previous"
    assert [path.name for path in target.parent.iterdir() if path.name.startswith(".image_sequence-")] == []


def test_export_directory_swap_failure_rolls_back_previous_sequence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    target = tmp_path / "Exports" / "image_sequence"
    target.mkdir(parents=True)
    (target / "board_0001.png").write_bytes(b"previous")
    real_replace = os.replace
    calls = 0

    def fail_staged_swap(source: Path, destination: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected directory swap failure")
        real_replace(source, destination)

    monkeypatch.setattr("storyboard_tool.file_transactions.os.replace", fail_staged_swap)
    with pytest.raises(OSError, match="injected"):
        with atomic_output_directory(target) as staged:
            (staged / "board_0001.png").write_bytes(b"new")

    assert (target / "board_0001.png").read_bytes() == b"previous"
    assert [path.name for path in target.parent.iterdir() if path.name.startswith(".image_sequence-")] == []
