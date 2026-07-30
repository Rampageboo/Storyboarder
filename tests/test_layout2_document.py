from __future__ import annotations

import base64
import json
import subprocess
import sys
import uuid
import zipfile
from pathlib import Path

import pytest

from storyboard_tool import project_document, project_manager, recents
from storyboard_tool.project_layout import LayoutDisabledError


def _json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _layout2_project(tmp_path: Path, *, revision: int = 1) -> tuple[Path, Path]:
    root = tmp_path / "Portable"
    work = root / ".storyboarder" / "work"
    project_id = str(uuid.uuid4())
    _json(
        work / "project.json",
        {
            "version": 4,
            "layout": 2,
            "project_id": project_id,
            "storage_revision": revision,
        },
    )
    _json(work / "settings.json", {"canvas_width": 1920})
    _json(
        work / "shots.json",
        {
            "shots": [
                {
                    "shot_id": "shot-1",
                    "thumbnail_path": "Images/Shots/shot-1_preview.png",
                }
            ]
        },
    )
    _json(work / "annotations" / "shot-1.json", [])
    _json(work / "notes" / "production" / "day-1.json", {"note": "Ready"})
    _json(work / "scenes2d" / "scenes2d.json", {"scenes": []})
    _json(work / "scenes3d" / "scenes3d.json", {"scenes": []})
    _json(work / "generation" / "requests" / "request-1.json", {"status": "queued"})
    _json(work / "generation" / "state" / "request-1.json", {"status": "queued"})
    _json(work / "generation" / "results" / "request-1.json", {"outputs": []})
    return root, work


def _cover(path: Path, *, size: int = 64) -> Path:
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * max(0, size - 8))
    return path


def _project_payload(work: Path) -> dict[str, object]:
    return json.loads((work / "project.json").read_text(encoding="utf-8"))


def test_layout2_document_is_allowlist_only_and_cover_is_stored(tmp_path: Path) -> None:
    root, work = _layout2_project(tmp_path)
    cover = _cover(tmp_path / "cover-source.png")

    snapshot = project_document.commit_layout2_document(root, cover_path=cover)
    document = root / "Portable.sbd"

    assert snapshot.revision == 1
    assert uuid.UUID(snapshot.commit_id)
    with zipfile.ZipFile(document) as archive:
        names = set(archive.namelist())
        assert names == {
            "project.json",
            "settings.json",
            "shots.json",
            "annotations/shot-1.json",
            "notes/production/day-1.json",
            "scenes2d/scenes2d.json",
            "scenes3d/scenes3d.json",
            "generation/requests/request-1.json",
            "generation/state/request-1.json",
            "generation/results/request-1.json",
            "cover.png",
        }
        assert archive.getinfo("cover.png").compress_type == zipfile.ZIP_STORED
        manifest = json.loads(archive.read("project.json"))
        assert manifest["storage_revision"] == 1
        assert manifest["commit_id"] == snapshot.commit_id

    assert all(path.suffix == ".json" for path in work.rglob("*") if path.is_file())
    state = json.loads((root / ".storyboarder" / "state.json").read_text(encoding="utf-8"))
    assert state["global_revision"] == state["committed_revision"] == 1
    assert state["commit_id"] == snapshot.commit_id


def test_layout2_work_tree_rejects_binary_and_unknown_metadata(tmp_path: Path) -> None:
    root, work = _layout2_project(tmp_path)
    binary = work / "scenes2d" / "preview.png"
    binary.write_bytes(b"\x89PNG\r\n\x1a\n")

    with pytest.raises(project_document.Layout2DocumentError, match="not allowlisted"):
        project_document.commit_layout2_document(root)

    assert not (root / "Portable.sbd").exists()


def test_layout2_cover_cap_is_enforced_before_archive_replace(tmp_path: Path) -> None:
    root, _work = _layout2_project(tmp_path)
    cover = _cover(
        tmp_path / "large.png",
        size=project_document.LAYOUT2_COVER_MAX_BYTES + 1,
    )

    with pytest.raises(project_document.Layout2DocumentError, match="65,536"):
        project_document.commit_layout2_document(root, cover_path=cover)

    assert not (root / "Portable.sbd").exists()


def test_layout2_archive_validator_enforces_cover_cap(tmp_path: Path) -> None:
    root, work = _layout2_project(tmp_path)
    project = _project_payload(work)
    project["commit_id"] = str(uuid.uuid4())
    document = root / "Portable.sbd"
    with zipfile.ZipFile(document, "w") as archive:
        archive.writestr("project.json", json.dumps(project))
        archive.writestr("settings.json", "{}")
        archive.writestr("shots.json", '{"shots":[]}')
        archive.writestr(
            "cover.png",
            b"\x89PNG\r\n\x1a\n" + b"x" * project_document.LAYOUT2_COVER_MAX_BYTES,
        )

    with pytest.raises(project_document.Layout2DocumentError, match="size cap"):
        project_document.validate_layout2_document(document)


def test_layout2_document_validator_rejects_non_allowlisted_asset(tmp_path: Path) -> None:
    root, work = _layout2_project(tmp_path)
    project = _project_payload(work)
    project["commit_id"] = str(uuid.uuid4())
    document = root / "Portable.sbd"
    with zipfile.ZipFile(document, "w") as archive:
        archive.writestr("project.json", json.dumps(project))
        archive.writestr("settings.json", "{}")
        archive.writestr("shots.json", '{"shots":[]}')
        archive.writestr("Images/Shots/shot-1.png", b"\x89PNG\r\n\x1a\n")

    with pytest.raises(project_document.Layout2DocumentError, match="not allowlisted"):
        project_document.validate_layout2_document(document)


def test_layout2_document_validator_rejects_directory_entries(tmp_path: Path) -> None:
    root, work = _layout2_project(tmp_path)
    project = _project_payload(work)
    project["commit_id"] = str(uuid.uuid4())
    document = root / "Portable.sbd"
    with zipfile.ZipFile(document, "w") as archive:
        archive.writestr("project.json", json.dumps(project))
        archive.writestr("settings.json", "{}")
        archive.writestr("shots.json", '{"shots":[]}')
        archive.writestr("annotations/", b"")

    with pytest.raises(project_document.Layout2DocumentError, match="directory entries"):
        project_document.validate_layout2_document(document)


def test_layout2_recovery_keeps_only_newer_work_metadata(tmp_path: Path) -> None:
    root, work = _layout2_project(tmp_path)
    first = project_document.commit_layout2_document(root)
    _json(work / "settings.json", {"canvas_width": 2048})
    assert project_document.advance_layout2_work_revision(root, expected_revision=1) == 2

    recovered = project_document.recover_layout2_work(root)

    assert recovered.source == "work"
    assert recovered.work_revision == 2
    assert recovered.committed_revision == 1
    assert recovered.commit_id == first.commit_id
    assert json.loads((work / "settings.json").read_text(encoding="utf-8"))[
        "canvas_width"
    ] == 2048
    assert not list((root / ".storyboarder").rglob("*.png"))


def test_layout2_equal_revision_restores_document_as_authority(tmp_path: Path) -> None:
    root, work = _layout2_project(tmp_path)
    project_document.commit_layout2_document(root)
    _json(work / "settings.json", {"canvas_width": 999})

    recovered = project_document.recover_layout2_work(root)

    assert recovered.source == "document"
    assert json.loads((work / "settings.json").read_text(encoding="utf-8"))[
        "canvas_width"
    ] == 1920
    assert not list((root / ".storyboarder").rglob("*.png"))


def test_layout2_equal_revision_rejects_changed_member_inventory(tmp_path: Path) -> None:
    root, work = _layout2_project(tmp_path)
    project_document.commit_layout2_document(root)
    _json(work / "notes" / "late.json", {"note": "unrevisioned"})

    with pytest.raises(
        project_document.Layout2RevisionConflict,
        match="changed without advancing",
    ):
        project_document.commit_layout2_document(root)


def test_layout2_recovery_rolls_back_process_crash_inside_mutation(
    tmp_path: Path,
) -> None:
    root, work = _layout2_project(tmp_path)
    project_document.commit_layout2_document(root)
    existing_asset = root / "assets" / "scene.blend"
    existing_asset.parent.mkdir(parents=True)
    existing_asset.write_bytes(b"original-blend")
    command = "\n".join(
        (
            "import json, os",
            "from pathlib import Path",
            "from storyboard_tool import project_document",
            f"root = Path({str(root)!r})",
            "work = project_document.layout2_work_root(root)",
            "transaction = project_document.layout2_mutation_transaction(root)",
            "transaction.__enter__()",
            "existing = root / 'assets' / 'scene.blend'",
            "created = root / 'assets' / 'new-preview.png'",
            "project_document.enlist_layout2_mutation_paths(root, (existing, created))",
            "existing.write_bytes(b'changed-blend'); created.write_bytes(b'new-preview')",
            "(work / 'settings.json').write_text(json.dumps({'canvas_width': 999}), encoding='utf-8')",
            "project_document.advance_layout2_work_revision(root, expected_revision=1)",
            "os._exit(23)",
        )
    )

    crashed = subprocess.run(
        [sys.executable, "-c", command],
        cwd=Path(__file__).parents[1],
        check=False,
    )

    assert crashed.returncode == 23
    transactions = root / ".storyboarder" / "transactions"
    assert any(
        path.name.startswith("mutation-") for path in transactions.iterdir()
    )
    recovered = project_document.recover_layout2_work(root)

    assert recovered.work_revision == 1
    assert recovered.committed_revision == 1
    assert json.loads((work / "settings.json").read_text(encoding="utf-8"))[
        "canvas_width"
    ] == 1920
    assert not any(
        path.name.startswith("mutation-") for path in transactions.iterdir()
    )
    assert existing_asset.read_bytes() == b"original-blend"
    assert not (root / "assets" / "new-preview.png").exists()


def test_layout2_mutation_restores_enlisted_directory_on_failure(
    tmp_path: Path,
) -> None:
    root, _work = _layout2_project(tmp_path)
    asset_dir = root / "assets" / "scene"
    asset_dir.mkdir(parents=True)
    (asset_dir / "kept.bin").write_bytes(b"before")

    with pytest.raises(RuntimeError, match="fault"):
        with project_document.layout2_mutation_transaction(root):
            project_document.enlist_layout2_mutation_paths(root, (asset_dir,))
            (asset_dir / "kept.bin").write_bytes(b"after")
            (asset_dir / "new.bin").write_bytes(b"new")
            raise RuntimeError("fault")

    assert (asset_dir / "kept.bin").read_bytes() == b"before"
    assert not (asset_dir / "new.bin").exists()
    assert not any(
        path.name.startswith("mutation-")
        for path in (root / ".storyboarder" / "transactions").iterdir()
    )


def test_layout2_resolved_cleanup_is_never_replayed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, work = _layout2_project(tmp_path)
    project_document.commit_layout2_document(root)
    real_rmtree = project_document.shutil.rmtree
    accepted_asset = root / "assets" / "kept.bin"
    accepted_asset.parent.mkdir(parents=True)

    def leave_resolved(path, *args, **kwargs):
        if Path(path).name.startswith(".mutation-resolved-"):
            return None
        return real_rmtree(path, *args, **kwargs)

    with monkeypatch.context() as cleanup_fault:
        cleanup_fault.setattr(project_document.shutil, "rmtree", leave_resolved)
        with project_document.layout2_mutation_transaction(root):
            project_document.enlist_layout2_mutation_paths(root, (accepted_asset,))
            accepted_asset.write_bytes(b"accepted")
            (work / "settings.json").write_text(
                json.dumps({"canvas_width": 1280}),
                encoding="utf-8",
            )
            project_document.advance_layout2_work_revision(
                root,
                expected_revision=1,
            )

    transactions = root / ".storyboarder" / "transactions"
    assert any(
        path.name.startswith(".mutation-resolved-")
        for path in transactions.iterdir()
    )

    recovered = project_document.recover_layout2_work(root)

    assert recovered.work_revision == 2
    assert json.loads((work / "settings.json").read_text(encoding="utf-8"))[
        "canvas_width"
    ] == 1280
    assert not any(transactions.iterdir())

    assert accepted_asset.read_bytes() == b"accepted"


def test_layout2_recovery_rename_failure_restores_previous_work(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, work = _layout2_project(tmp_path)
    project_document.commit_layout2_document(root)
    _json(work / "settings.json", {"canvas_width": 999})
    real_replace = project_document.os.replace
    failed = False

    def fail_staged_activation(source, destination):
        nonlocal failed
        if (
            not failed
            and Path(source).name.startswith("work-")
            and Path(destination) == work
        ):
            failed = True
            raise OSError("locked destination")
        return real_replace(source, destination)

    monkeypatch.setattr(project_document.os, "replace", fail_staged_activation)

    with pytest.raises(OSError, match="locked destination"):
        project_document.recover_layout2_work(root)

    assert work.is_dir()
    assert json.loads((work / "settings.json").read_text(encoding="utf-8"))[
        "canvas_width"
    ] == 999


def test_layout2_recovery_reconciles_commit_completed_before_state_write(
    tmp_path: Path,
) -> None:
    root, work = _layout2_project(tmp_path)
    first = project_document.commit_layout2_document(root)
    _json(work / "settings.json", {"canvas_width": 2048})
    project_document.advance_layout2_work_revision(root)
    second = project_document.commit_layout2_document(root)
    state_path = root / ".storyboarder" / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["committed_revision"] = 1
    state["commit_id"] = first.commit_id
    state_path.write_text(json.dumps(state), encoding="utf-8")

    recovered = project_document.recover_layout2_work(root)

    assert recovered.source == "document"
    assert recovered.committed_revision == 2
    assert recovered.commit_id == second.commit_id
    repaired = json.loads(state_path.read_text(encoding="utf-8"))
    assert repaired["global_revision"] == repaired["committed_revision"] == 2
    assert repaired["commit_id"] == second.commit_id


def test_layout2_recovery_rejects_document_newer_than_work(tmp_path: Path) -> None:
    root, work = _layout2_project(tmp_path, revision=2)
    project_document.commit_layout2_document(root)
    project = _project_payload(work)
    project["storage_revision"] = 1
    _json(work / "project.json", project)

    with pytest.raises(
        project_document.Layout2RevisionConflict,
        match="exceeds the work revision",
    ):
        project_document.recover_layout2_work(root)


def test_layout2_recovery_rejects_state_claiming_missing_work(tmp_path: Path) -> None:
    root, _work = _layout2_project(tmp_path)
    project_document.commit_layout2_document(root)
    state_path = root / ".storyboarder" / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["global_revision"] = 2
    state_path.write_text(json.dumps(state), encoding="utf-8")

    with pytest.raises(
        project_document.Layout2RevisionConflict,
        match="missing work revision",
    ):
        project_document.recover_layout2_work(root)


def test_layout2_revision_conflict_does_not_rewrite_work_or_document(
    tmp_path: Path,
) -> None:
    root, work = _layout2_project(tmp_path)
    project_document.commit_layout2_document(root)
    document = root / "Portable.sbd"
    document_before = document.read_bytes()
    manifest_before = (work / "project.json").read_bytes()
    state_path = root / ".storyboarder" / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["global_revision"] = 2
    state_path.write_text(json.dumps(state), encoding="utf-8")

    with pytest.raises(project_document.Layout2RevisionConflict, match="missing work revision"):
        project_document.advance_layout2_work_revision(root)
    with pytest.raises(project_document.Layout2RevisionConflict, match="missing work revision"):
        project_document.commit_layout2_document(root)

    assert (work / "project.json").read_bytes() == manifest_before
    assert document.read_bytes() == document_before


def test_layout2_candidate_validation_failure_preserves_previous_document(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, work = _layout2_project(tmp_path)
    project_document.commit_layout2_document(root)
    document = root / "Portable.sbd"
    document_before = document.read_bytes()
    _json(work / "settings.json", {"canvas_width": 2048})
    project_document.advance_layout2_work_revision(root)
    real_validate = project_document.validate_layout2_document

    def reject_candidate(path: Path):
        if Path(path).name.endswith(".tmp.sbd"):
            raise project_document.Layout2DocumentError("candidate rejected")
        return real_validate(path)

    monkeypatch.setattr(project_document, "validate_layout2_document", reject_candidate)

    with pytest.raises(project_document.Layout2DocumentError, match="candidate rejected"):
        project_document.commit_layout2_document(root)

    assert document.read_bytes() == document_before
    assert not list(root.glob(".Portable.sbd.*.tmp.sbd"))


def test_layout2_recents_use_cover_without_embedded_shot_assets(tmp_path: Path) -> None:
    root, _work = _layout2_project(tmp_path)
    cover = _cover(tmp_path / "recent-cover.png")
    project_document.commit_layout2_document(root, cover_path=cover)

    entry = recents.describe(str(root / "Portable.sbd"))

    assert entry["exists"] is True
    assert entry["shot_count"] == 1
    assert entry["thumbnail"].startswith("data:image/png;base64,")
    assert base64.b64decode(entry["thumbnail"].split(",", 1)[1]) == cover.read_bytes()


def test_layout2_disabled_open_never_creates_a_temporary_asset_tree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, work = _layout2_project(tmp_path)
    document = root / "Portable.sbd"
    project_document.commit_layout2_document(root, cover_path=_cover(tmp_path / "cover.png"))
    temp_root = tmp_path / "temp"
    temp_root.mkdir()
    monkeypatch.setattr(project_document.tempfile, "tempdir", str(temp_root))
    work_before = {
        path.relative_to(work).as_posix(): path.read_bytes()
        for path in work.rglob("*")
        if path.is_file()
    }

    with pytest.raises(LayoutDisabledError, match="not enabled"):
        project_manager.open_project(document)
    with pytest.raises(project_document.Layout2DocumentError, match="temporary expanded"):
        project_document.extract_document(document)

    assert not list(temp_root.glob(f"{project_document.WORKING_ROOT_PREFIX}*"))
    assert {
        path.relative_to(work).as_posix(): path.read_bytes()
        for path in work.rglob("*")
        if path.is_file()
    } == work_before
