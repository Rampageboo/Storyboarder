"""The on-disk project format: the ``.sbd`` handle, opening, and mutation rollback."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from conftest import make_project
from storyboard_tool import project_document, project_manager
from storyboard_tool.project_document import (
    DOCUMENT_SUFFIX,
    MutationRecoveryError,
    ProjectDocumentError,
    data_root,
    enlist_mutation_paths,
    mutation_transaction,
    private_root,
    read_handle,
    recover_incomplete_mutation,
    write_handle,
)


PROJECT_ID = "5f44cc8d-cc3f-45dd-8e84-88606d69a3ef"


def _transactions(root: Path) -> Path:
    return root / ".storyboarder" / "transactions"


def _pending(root: Path) -> list[Path]:
    transactions = _transactions(root)
    if not transactions.is_dir():
        return []
    return [path for path in transactions.iterdir() if path.name.startswith("mutation-")]


def _settings(project) -> dict:
    return json.loads(project.settings_path.read_text(encoding="utf-8"))


def _write_settings(project, **changes) -> None:
    payload = _settings(project)
    payload.update(changes)
    project.settings_path.write_text(json.dumps(payload), encoding="utf-8")


# -- handle -----------------------------------------------------------------


def test_handle_write_read_round_trip(tmp_path: Path) -> None:
    handle = tmp_path / f"Demo{DOCUMENT_SUFFIX}"

    write_handle(handle, PROJECT_ID)

    assert read_handle(handle) == PROJECT_ID
    assert json.loads(handle.read_text(encoding="utf-8")) == {
        "format": "storyboarder-project",
        "version": 1,
        "project_id": PROJECT_ID,
    }
    assert [path.name for path in tmp_path.iterdir()] == ["Demo.sbd"]


def test_read_handle_rejects_old_zip_document(tmp_path: Path) -> None:
    handle = tmp_path / "Old.sbd"
    with zipfile.ZipFile(handle, "w") as archive:
        archive.writestr("project.json", json.dumps({"version": 4}))

    with pytest.raises(ProjectDocumentError, match="older Storyboarder"):
        read_handle(handle)


def test_read_handle_rejects_oversized_file(tmp_path: Path) -> None:
    handle = tmp_path / "Huge.sbd"
    payload = {"format": "storyboarder-project", "version": 1, "project_id": PROJECT_ID}
    text = json.dumps(payload)
    handle.write_text(text + " " * (64 * 1024 + 1 - len(text)), encoding="utf-8")

    with pytest.raises(ProjectDocumentError, match="older Storyboarder"):
        read_handle(handle)


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"not json at all",
        b"\xff\xfe\x00garbage",
        b"[]",
        b"null",
        json.dumps({"format": "something-else", "version": 1, "project_id": PROJECT_ID}).encode(),
        json.dumps({"format": "storyboarder-project", "version": 2, "project_id": PROJECT_ID}).encode(),
        json.dumps({"format": "storyboarder-project", "version": 1, "project_id": ""}).encode(),
        json.dumps({"format": "storyboarder-project", "version": 1, "project_id": 7}).encode(),
        json.dumps({"format": "storyboarder-project", "version": 1}).encode(),
    ],
)
def test_read_handle_rejects_garbage_and_wrong_format(tmp_path: Path, raw: bytes) -> None:
    handle = tmp_path / "Bad.sbd"
    handle.write_bytes(raw)

    with pytest.raises(ProjectDocumentError, match="not a Storyboarder project"):
        read_handle(handle)


def test_read_handle_rejects_boolean_version(tmp_path: Path) -> None:
    handle = tmp_path / "Bool.sbd"
    handle.write_text(
        json.dumps({"format": "storyboarder-project", "version": True, "project_id": PROJECT_ID}),
        encoding="utf-8",
    )

    with pytest.raises(ProjectDocumentError, match="not a Storyboarder project"):
        read_handle(handle)


def test_read_handle_requires_sbd_suffix_and_existing_file(tmp_path: Path) -> None:
    other = tmp_path / "Demo.json"
    write_handle(other, PROJECT_ID)

    with pytest.raises(ProjectDocumentError):
        read_handle(other)
    with pytest.raises(FileNotFoundError):
        read_handle(tmp_path / "Missing.sbd")


def test_roots_are_inside_the_project_folder(tmp_path: Path) -> None:
    assert private_root(tmp_path) == (tmp_path / ".storyboarder").resolve()
    assert data_root(tmp_path) == (tmp_path / ".storyboarder" / "data").resolve()


# -- open_project -----------------------------------------------------------


def test_open_project_via_handle_and_via_folder(tmp_path: Path) -> None:
    project = make_project(tmp_path, "Demo", canvas_width=640, canvas_height=360)

    by_handle = project_manager.open_project(project.document_path)
    by_folder = project_manager.open_project(project.project_root)

    for opened in (by_handle, by_folder):
        assert opened.project_id == project.project_id
        assert opened.document_path == project.document_path
        assert opened.reopen_path == project.document_path
        assert opened.project_root == project.project_root
        assert opened.settings["canvas_width"] == 640


def test_open_project_rejects_handle_for_another_project(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    write_handle(project.document_path, "910b2631-641e-4d28-aa4a-1d18d66b2425")

    with pytest.raises(ValueError, match="does not belong"):
        project_manager.open_project(project.document_path)


def test_open_project_rejects_old_zip_handle(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    with zipfile.ZipFile(project.document_path, "w") as archive:
        archive.writestr("project.json", json.dumps({"version": 4}))

    with pytest.raises(ProjectDocumentError, match="older Storyboarder"):
        project_manager.open_project(project.document_path)


# -- mutation_transaction ---------------------------------------------------


def test_mutation_transaction_restores_data_on_exception(tmp_path: Path) -> None:
    project = make_project(tmp_path, canvas_width=1920)
    root = project.project_root
    before = {
        path.relative_to(root): path.read_bytes()
        for path in data_root(root).rglob("*")
        if path.is_file()
    }

    with pytest.raises(RuntimeError, match="fault"):
        with mutation_transaction(root):
            _write_settings(project, canvas_width=999)
            (data_root(root) / "added.json").write_text("{}", encoding="utf-8")
            raise RuntimeError("fault")

    after = {
        path.relative_to(root): path.read_bytes()
        for path in data_root(root).rglob("*")
        if path.is_file()
    }
    assert after == before
    assert _settings(project)["canvas_width"] == 1920
    assert _pending(root) == []


def test_mutation_transaction_keeps_successful_changes(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    root = project.project_root

    with mutation_transaction(root):
        _write_settings(project, canvas_width=1280)

    assert _settings(project)["canvas_width"] == 1280
    assert _pending(root) == []
    assert recover_incomplete_mutation(root) is False
    assert _settings(project)["canvas_width"] == 1280


def test_recovery_rolls_back_process_crash_inside_mutation(tmp_path: Path) -> None:
    project = make_project(tmp_path, canvas_width=1920)
    root = project.project_root
    existing_asset = root / "assets" / "scene.blend"
    existing_asset.parent.mkdir(parents=True)
    existing_asset.write_bytes(b"original-blend")
    command = "\n".join(
        (
            "import json, os",
            "from pathlib import Path",
            "from storyboard_tool import project_document",
            f"root = Path({str(root)!r})",
            "transaction = project_document.mutation_transaction(root)",
            "transaction.__enter__()",
            "existing = root / 'assets' / 'scene.blend'",
            "created = root / 'assets' / 'new-preview.png'",
            "project_document.enlist_mutation_paths(root, (existing, created))",
            "existing.write_bytes(b'changed-blend'); created.write_bytes(b'new-preview')",
            "settings = project_document.data_root(root) / 'settings.json'",
            "settings.write_text(json.dumps({'canvas_width': 999}), encoding='utf-8')",
            "os._exit(23)",
        )
    )

    crashed = subprocess.run(
        [sys.executable, "-c", command],
        cwd=Path(__file__).parents[1],
        check=False,
    )

    assert crashed.returncode == 23
    assert len(_pending(root)) == 1
    assert _settings(project) == {"canvas_width": 999}

    assert recover_incomplete_mutation(root) is True

    assert _settings(project)["canvas_width"] == 1920
    assert _pending(root) == []
    assert existing_asset.read_bytes() == b"original-blend"
    assert not (root / "assets" / "new-preview.png").exists()
    assert recover_incomplete_mutation(root) is False


def test_open_project_rolls_back_a_pending_mutation(tmp_path: Path) -> None:
    project = make_project(tmp_path, canvas_width=1920)
    root = project.project_root

    # Construct the state a process leaves behind when it dies mid-mutation:
    # a pending snapshot of data/ and a data/ that was changed afterwards.
    pending = _transactions(root) / f"mutation-{'0' * 32}"
    shutil.copytree(data_root(root), pending / "data")
    (pending / "manifest.json").write_text(
        json.dumps({"version": 1, "data_present": True, "assets": []}),
        encoding="utf-8",
    )
    _write_settings(project, canvas_width=999)

    reopened = project_manager.open_project(project.document_path)

    assert reopened.settings["canvas_width"] == 1920
    assert _pending(root) == []


def test_mutation_restores_enlisted_file_on_failure(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    root = project.project_root
    asset = root / "Images" / "Shots" / "board_preview.png"
    asset.parent.mkdir(parents=True, exist_ok=True)
    asset.write_bytes(b"before")
    created = root / "Images" / "Shots" / "created.png"

    with pytest.raises(RuntimeError, match="fault"):
        with mutation_transaction(root):
            journaled = enlist_mutation_paths(root, (asset, created))
            assert set(journaled) == {
                "Images/Shots/board_preview.png",
                "Images/Shots/created.png",
            }
            asset.write_bytes(b"after")
            created.write_bytes(b"new")
            raise RuntimeError("fault")

    assert asset.read_bytes() == b"before"
    assert not created.exists()
    assert _pending(root) == []


def test_mutation_restores_enlisted_directory_on_failure(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    root = project.project_root
    asset_dir = root / "assets" / "scene"
    asset_dir.mkdir(parents=True)
    (asset_dir / "kept.bin").write_bytes(b"before")

    with pytest.raises(RuntimeError, match="fault"):
        with mutation_transaction(root):
            enlist_mutation_paths(root, (asset_dir,))
            (asset_dir / "kept.bin").write_bytes(b"after")
            (asset_dir / "new.bin").write_bytes(b"new")
            raise RuntimeError("fault")

    assert (asset_dir / "kept.bin").read_bytes() == b"before"
    assert not (asset_dir / "new.bin").exists()
    assert _pending(root) == []


def test_enlist_outside_a_transaction_is_a_no_op(tmp_path: Path) -> None:
    project = make_project(tmp_path)

    assert enlist_mutation_paths(project.project_root, (project.project_root / "x.bin",)) == ()


def test_enlist_rejects_paths_outside_the_project_and_the_journal(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    root = project.project_root

    with mutation_transaction(root):
        with pytest.raises(MutationRecoveryError, match="escapes"):
            enlist_mutation_paths(root, (tmp_path / "outside.bin",))
        with pytest.raises(MutationRecoveryError, match="transaction journal"):
            enlist_mutation_paths(root, (_transactions(root) / "anything",))


def test_resolved_transactions_are_never_replayed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = make_project(tmp_path, canvas_width=1920)
    root = project.project_root
    real_rmtree = project_document.shutil.rmtree
    accepted_asset = root / "assets" / "kept.bin"
    accepted_asset.parent.mkdir(parents=True)

    def leave_resolved(path, *args, **kwargs):
        if Path(path).name.startswith(".mutation-resolved-"):
            return None
        return real_rmtree(path, *args, **kwargs)

    with monkeypatch.context() as cleanup_fault:
        cleanup_fault.setattr(project_document.shutil, "rmtree", leave_resolved)
        with mutation_transaction(root):
            enlist_mutation_paths(root, (accepted_asset,))
            accepted_asset.write_bytes(b"accepted")
            _write_settings(project, canvas_width=1280)

    transactions = _transactions(root)
    assert any(path.name.startswith(".mutation-resolved-") for path in transactions.iterdir())
    assert _pending(root) == []

    assert recover_incomplete_mutation(root) is False
    reopened = project_manager.open_project(project.document_path)

    assert reopened.settings["canvas_width"] == 1280
    assert accepted_asset.read_bytes() == b"accepted"
    assert not any(path.name.startswith(".mutation-resolved-") for path in transactions.iterdir())


def test_multiple_pending_mutations_require_manual_recovery(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    root = project.project_root
    for token in ("a" * 32, "b" * 32):
        pending = _transactions(root) / f"mutation-{token}"
        pending.mkdir(parents=True)
        (pending / "manifest.json").write_text(
            json.dumps({"version": 1, "data_present": False, "assets": []}),
            encoding="utf-8",
        )

    with pytest.raises(MutationRecoveryError, match="Multiple"):
        recover_incomplete_mutation(root)
