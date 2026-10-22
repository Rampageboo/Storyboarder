"""On-disk project format: a folder, its ``.sbd`` handle, and mutation rollback.

A project is a folder::

    MyProject/
        MyProject.sbd      handle: identifies the folder as a project
        Images/ PSD/ Blender/ Exports/ Videos/
        .storyboarder/
            data/          the only copy of project metadata (JSON)
            transactions/  in-flight mutation snapshots
            backups/  cache/  media/

The handle holds identity only. Every metadata file lives under
``.storyboarder/data`` and is written in place, so there is nothing to pack,
extract, or flush. ``mutation_transaction`` makes a multi-file mutation atomic:
it snapshots ``data/`` (plus any asset paths a mutation enlists) and restores
the snapshot when the mutation raises or the process dies before it finishes.
"""
from __future__ import annotations

import contextlib
import json
import os
import shutil
import tempfile
import threading
import uuid
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from .project_layout import resolve_root_child, validate_project_relative_posix


DOCUMENT_SUFFIX = ".sbd"
HANDLE_FORMAT = "storyboarder-project"
HANDLE_VERSION = 1
_HANDLE_MAX_BYTES = 64 * 1024

_MUTATION_PREFIX = "mutation-"
_MUTATION_PREPARE_PREFIX = ".mutation-prepare-"
_MUTATION_RESOLVED_PREFIX = ".mutation-resolved-"
_MUTATION_RESTORE_PREFIX = ".mutation-restore-"
_MUTATION_DISCARD_PREFIX = ".mutation-discard-"
_MUTATION_ASSET_PREFIX = "asset-"
_MUTATION_LOCAL = threading.local()


class ProjectDocumentError(ValueError):
    """A project handle or folder does not match the supported format."""


class MutationRecoveryError(ProjectDocumentError):
    """A mutation snapshot cannot be applied or restored safely."""


def private_root(project_root: Path) -> Path:
    return resolve_root_child(Path(project_root).expanduser().resolve(), ".storyboarder")


def data_root(project_root: Path) -> Path:
    return resolve_root_child(Path(project_root).expanduser().resolve(), ".storyboarder", "data")


def _transactions_root(project_root: Path) -> Path:
    return resolve_root_child(
        Path(project_root).expanduser().resolve(),
        ".storyboarder",
        "transactions",
    )


def write_handle(document: Path, project_id: str) -> None:
    _atomic_write_json(
        Path(document),
        {"format": HANDLE_FORMAT, "version": HANDLE_VERSION, "project_id": project_id},
    )


def read_handle(document_path: Path) -> str:
    """Return the project id a ``.sbd`` handle names, rejecting anything else."""
    document = Path(document_path).expanduser().resolve()
    if document.suffix.lower() != DOCUMENT_SUFFIX:
        raise ProjectDocumentError(f"Storyboard projects are opened through their {DOCUMENT_SUFFIX} file.")
    if not document.is_file():
        raise FileNotFoundError(f"Storyboard project not found: {document}")
    if document.stat().st_size > _HANDLE_MAX_BYTES:
        raise ProjectDocumentError(_OLD_FORMAT_MESSAGE)
    raw = document.read_bytes()
    if raw[:2] == b"PK":
        raise ProjectDocumentError(_OLD_FORMAT_MESSAGE)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProjectDocumentError(f"{document.name} is not a Storyboarder project.") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("format") != HANDLE_FORMAT
        or type(payload.get("version")) is not int
        or payload["version"] != HANDLE_VERSION
        or not isinstance(payload.get("project_id"), str)
        or not payload["project_id"]
    ):
        raise ProjectDocumentError(f"{document.name} is not a Storyboarder project.")
    return payload["project_id"]


_OLD_FORMAT_MESSAGE = (
    "This project was saved by an older Storyboarder in a format that is no "
    "longer supported. Create a new project."
)


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(
        dir=str(path.parent),
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _read_mutation_manifest(transaction: Path) -> dict[str, Any]:
    manifest_path = resolve_root_child(transaction, "manifest.json")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MutationRecoveryError(
            f"Mutation recovery manifest is unreadable: {transaction.name}."
        ) from exc
    if not isinstance(manifest, dict) or manifest.get("version") != 1:
        raise MutationRecoveryError(
            f"Mutation recovery manifest is invalid: {transaction.name}."
        )
    assets = manifest.get("assets", [])
    if not isinstance(assets, list) or any(
        not isinstance(entry, dict) for entry in assets
    ):
        raise MutationRecoveryError(
            f"Mutation asset journal is invalid: {transaction.name}."
        )
    manifest["assets"] = assets
    return manifest


def _snapshot_asset_path(
    root: Path,
    transaction: Path,
    target: Path,
    ordinal: int,
) -> dict[str, str]:
    relative = target.relative_to(root).as_posix()
    validate_project_relative_posix(
        relative,
        field_name="Mutation asset path",
    )
    snapshot_name = f"{_MUTATION_ASSET_PREFIX}{ordinal:06d}"
    snapshot = resolve_root_child(transaction, "assets", snapshot_name)
    if target.is_symlink():
        raise MutationRecoveryError(
            f"Mutation asset cannot be a symbolic link: {relative}."
        )
    if target.is_dir():
        for child in target.rglob("*"):
            if child.is_symlink():
                raise MutationRecoveryError(
                    f"Mutation asset tree contains a symbolic link: {relative}."
                )
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(target, snapshot)
        for copied in snapshot.rglob("*"):
            if copied.is_file():
                with copied.open("rb+") as stream:
                    os.fsync(stream.fileno())
        kind = "directory"
    elif target.is_file():
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, snapshot)
        with snapshot.open("rb+") as stream:
            os.fsync(stream.fileno())
        kind = "file"
    elif target.exists():
        raise MutationRecoveryError(
            f"Mutation asset has an unsupported type: {relative}."
        )
    else:
        snapshot_name = ""
        kind = "missing"
    return {
        "path": relative,
        "kind": kind,
        "snapshot": snapshot_name,
    }


def enlist_mutation_paths(
    project_root: Path,
    paths: Iterable[Path],
) -> tuple[str, ...]:
    """Durably journal asset paths before a Mutation changes them."""
    transaction_value = getattr(_MUTATION_LOCAL, "transaction", None)
    active_root = getattr(_MUTATION_LOCAL, "project_root", None)
    if transaction_value is None or active_root is None:
        return ()
    root = Path(project_root).expanduser().resolve()
    if root != Path(active_root):
        raise MutationRecoveryError(
            "Nested Mutation attempted to journal another project."
        )
    transaction = Path(transaction_value)
    manifest = _read_mutation_manifest(transaction)
    assets = manifest["assets"]
    existing = {
        str(entry.get("path") or ""): entry
        for entry in assets
    }
    transactions_root = _transactions_root(root)
    requested: list[Path] = []
    for raw in paths:
        candidate = Path(raw)
        resolved = candidate.resolve()
        if resolved == root or root not in resolved.parents:
            raise MutationRecoveryError(
                f"Mutation asset escapes the project root: {candidate}."
            )
        if (
            resolved == transactions_root
            or transactions_root in resolved.parents
            or resolved in transactions_root.parents
        ):
            raise MutationRecoveryError(
                "Mutation assets cannot include the transaction journal."
            )
        if resolved not in requested:
            requested.append(resolved)
    requested.sort(key=lambda value: len(value.parts))
    compact = [
        candidate
        for candidate in requested
        if not any(parent in candidate.parents for parent in requested)
    ]
    journaled: list[str] = []
    for candidate in compact:
        relative = candidate.relative_to(root).as_posix()
        covering = next(
            (
                stored
                for stored in existing
                if stored
                and (
                    relative == stored
                    or PurePosixPath(stored) in PurePosixPath(relative).parents
                )
            ),
            None,
        )
        if covering is not None:
            continue
        if any(
            PurePosixPath(relative) in PurePosixPath(stored).parents
            for stored in existing
            if stored
        ):
            raise MutationRecoveryError(
                "Mutation cannot widen an asset snapshot after writes began."
            )
        entry = _snapshot_asset_path(
            root,
            transaction,
            candidate,
            len(assets) + 1,
        )
        assets.append(entry)
        _atomic_write_json(
            resolve_root_child(transaction, "manifest.json"),
            manifest,
        )
        existing[relative] = entry
        journaled.append(relative)
    return tuple(journaled)


def _restore_asset_snapshot(
    root: Path,
    transaction: Path,
    entry: dict[str, Any],
) -> None:
    relative_text = str(entry.get("path") or "")
    relative = validate_project_relative_posix(
        relative_text,
        field_name="Mutation asset path",
    )
    target = resolve_root_child(root, *relative.parts)
    kind = entry.get("kind")
    snapshot_name = str(entry.get("snapshot") or "")
    if kind not in {"missing", "file", "directory"}:
        raise MutationRecoveryError(
            f"Mutation asset kind is invalid: {relative_text}."
        )
    transactions_root = _transactions_root(root)
    discarded = resolve_root_child(
        transactions_root,
        f"{_MUTATION_DISCARD_PREFIX}{uuid.uuid4().hex}",
    )
    staged = resolve_root_child(
        transactions_root,
        f"{_MUTATION_RESTORE_PREFIX}{uuid.uuid4().hex}",
    )
    snapshot = (
        resolve_root_child(transaction, "assets", snapshot_name)
        if snapshot_name
        else None
    )
    try:
        if kind == "missing":
            if target.exists() or target.is_symlink():
                os.replace(target, discarded)
            return
        if snapshot is None or snapshot.is_symlink():
            raise MutationRecoveryError(
                f"Mutation asset snapshot is missing: {relative_text}."
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        if kind == "file":
            if not snapshot.is_file():
                raise MutationRecoveryError(
                    f"Mutation file snapshot is missing: {relative_text}."
                )
            if target.is_dir() and not target.is_symlink():
                os.replace(target, discarded)
            descriptor, name = tempfile.mkstemp(
                dir=str(target.parent),
                prefix=f".{target.name}.",
                suffix=".restore",
            )
            os.close(descriptor)
            temporary = Path(name)
            try:
                shutil.copy2(snapshot, temporary)
                with temporary.open("rb+") as stream:
                    os.fsync(stream.fileno())
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
            return
        if not snapshot.is_dir():
            raise MutationRecoveryError(
                f"Mutation directory snapshot is missing: {relative_text}."
            )
        shutil.copytree(snapshot, staged)
        if target.exists() or target.is_symlink():
            os.replace(target, discarded)
        try:
            os.replace(staged, target)
        except BaseException:
            if discarded.exists() and not target.exists():
                os.replace(discarded, target)
            raise
    finally:
        shutil.rmtree(staged, ignore_errors=True)
        if discarded.exists() or discarded.is_symlink():
            if discarded.is_dir() and not discarded.is_symlink():
                shutil.rmtree(discarded, ignore_errors=True)
            else:
                discarded.unlink(missing_ok=True)


def _restore_mutation_snapshot(project_root: Path, transaction: Path) -> None:
    root = Path(project_root).expanduser().resolve()
    manifest = _read_mutation_manifest(transaction)

    transactions_root = _transactions_root(root)
    data_dir = data_root(root)
    data_present = manifest.get("data_present") is True
    staged_restore = resolve_root_child(
        transactions_root, f"{_MUTATION_RESTORE_PREFIX}{uuid.uuid4().hex}"
    )
    discarded = resolve_root_child(
        transactions_root, f"{_MUTATION_DISCARD_PREFIX}{uuid.uuid4().hex}"
    )
    for asset_entry in reversed(manifest["assets"]):
        _restore_asset_snapshot(
            root,
            transaction,
            asset_entry,
        )
    try:
        if data_present:
            snapshot_data = resolve_root_child(transaction, "data")
            if not snapshot_data.is_dir():
                raise MutationRecoveryError(
                    "Mutation recovery is missing its data snapshot."
                )
            shutil.copytree(snapshot_data, staged_restore)
            if data_dir.exists():
                os.replace(data_dir, discarded)
            try:
                os.replace(staged_restore, data_dir)
            except BaseException:
                if discarded.exists() and not data_dir.exists():
                    os.replace(discarded, data_dir)
                raise
            shutil.rmtree(discarded, ignore_errors=True)
        elif data_dir.exists():
            os.replace(data_dir, discarded)
            shutil.rmtree(discarded, ignore_errors=True)
    finally:
        shutil.rmtree(staged_restore, ignore_errors=True)


def recover_incomplete_mutation(project_root: Path) -> bool:
    """Roll back a mutation that did not reach its response boundary."""
    root = Path(project_root).expanduser().resolve()
    transactions_root = _transactions_root(root)
    if not transactions_root.is_dir():
        return False
    for disposable_prefix in (
        _MUTATION_PREPARE_PREFIX,
        _MUTATION_RESOLVED_PREFIX,
        _MUTATION_RESTORE_PREFIX,
        _MUTATION_DISCARD_PREFIX,
    ):
        for disposable in transactions_root.glob(f"{disposable_prefix}*"):
            shutil.rmtree(disposable, ignore_errors=True)
    pending = sorted(
        path
        for path in transactions_root.glob(f"{_MUTATION_PREFIX}*")
        if path.is_dir() and not path.is_symlink()
    )
    if len(pending) > 1:
        raise MutationRecoveryError(
            "Multiple incomplete Mutations require manual recovery."
        )
    if not pending:
        return False
    _restore_mutation_snapshot(root, pending[0])
    token = pending[0].name.removeprefix(_MUTATION_PREFIX)
    resolved = resolve_root_child(
        transactions_root, f"{_MUTATION_RESOLVED_PREFIX}{token}"
    )
    os.replace(pending[0], resolved)
    shutil.rmtree(resolved, ignore_errors=True)
    return True


@contextlib.contextmanager
def mutation_transaction(project_root: Path):
    """Make work metadata and revision evidence recoverable as one mutation."""
    depth = int(getattr(_MUTATION_LOCAL, "depth", 0) or 0)
    if depth:
        _MUTATION_LOCAL.depth = depth + 1
        try:
            yield
        finally:
            _MUTATION_LOCAL.depth = depth
        return

    root = Path(project_root).expanduser().resolve()
    recover_incomplete_mutation(root)
    transactions_root = _transactions_root(root)
    transactions_root.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    preparing = resolve_root_child(
        transactions_root, f"{_MUTATION_PREPARE_PREFIX}{token}"
    )
    transaction = resolve_root_child(
        transactions_root, f"{_MUTATION_PREFIX}{token}"
    )
    resolved = resolve_root_child(
        transactions_root, f"{_MUTATION_RESOLVED_PREFIX}{token}"
    )
    preparing.mkdir()
    data_dir = data_root(root)
    cleanup_resolved = False
    try:
        if data_dir.is_dir():
            shutil.copytree(data_dir, resolve_root_child(preparing, "data"))
        _atomic_write_json(
            resolve_root_child(preparing, "manifest.json"),
            {
                "version": 1,
                "data_present": data_dir.is_dir(),
                "assets": [],
            },
        )
        os.replace(preparing, transaction)
        _MUTATION_LOCAL.depth = 1
        _MUTATION_LOCAL.project_root = root
        _MUTATION_LOCAL.transaction = transaction
        try:
            yield
        except BaseException:
            _restore_mutation_snapshot(root, transaction)
            try:
                os.replace(transaction, resolved)
            except OSError:
                # The active snapshot remains valid and will be replayed before
                # the next mutation or project recovery.
                pass
            else:
                cleanup_resolved = True
            raise
        else:
            try:
                os.replace(transaction, resolved)
            except BaseException:
                _restore_mutation_snapshot(root, transaction)
                raise
            cleanup_resolved = True
        finally:
            _MUTATION_LOCAL.depth = 0
            _MUTATION_LOCAL.project_root = None
            _MUTATION_LOCAL.transaction = None
    finally:
        shutil.rmtree(preparing, ignore_errors=True)
        if cleanup_resolved and resolved.exists():
            # The atomic rename above records the outcome. Interrupted cleanup
            # is therefore harmless and is collected during the next recovery.
            shutil.rmtree(resolved, ignore_errors=True)

