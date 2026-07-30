"""Single-file ``.sbd`` document packaging for Storyboarder projects.

The rest of the application intentionally continues to work against an expanded
project directory.  This adapter makes that implementation detail invisible to
the user: opening extracts into a private working directory and saving replaces
the visible document atomically.
"""
from __future__ import annotations

import contextlib
import json
import logging
import os
import shutil
import stat
import sys
import tempfile
import threading
import time
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from .project_layout import (
    LAYOUT_2,
    MAX_STORAGE_REVISION,
    ProjectPathError,
    ensure_no_casefold_collisions,
    parse_project_manifest,
    resolve_root_child,
    validate_project_relative_posix,
)

logger = logging.getLogger(__name__)


DOCUMENT_SUFFIX = ".sbd"
_REQUIRED_MEMBER = "project.json"

# Names the working root of every open `.sbd`. Lets a later launch tell an
# abandoned work tree from one a running instance still owns. Session-local:
# never packed into the shared document.
WORKING_ROOT_PREFIX = "storyboarder-"
SESSION_MARKER = ".storyboarder-session.json"

# Already-compressed imports (reference images, video, nested zips): re-DEFLATE
# only burns CPU for ~0% gain, so store them verbatim. PSD canvases are raw and
# storyboard-flat, so they DO compress well (measured 89 MB -> ~1 MB) and must
# stay DEFLATE. The rest of the archive uses fast DEFLATE level 1, which is ~2x
# faster than level 6 for a negligible size increase on this content.
_STORED_SUFFIXES = frozenset({
    ".png", ".jpg", ".jpeg", ".webp", ".gif",
    ".mp4", ".mov", ".m4v", ".webm", ".mkv", ".zip",
})
_PACK_COMPRESS_LEVEL = 1

# Top-level working-tree dirs never embedded in the shared .sbd. `backups/` is a
# local, write-only recovery snapshot set (the app never reads it back); packing
# it bloats the document and slows every save.
_UNPACKED_DIRS = frozenset({"backups"})

# Layout 2 keeps durable JSON work state beside the portable assets. Its .sbd
# is a small metadata snapshot, never an expanded binary project tree.
LAYOUT2_STATE_VERSION = 1
LAYOUT2_COVER_MAX_BYTES = 65_536
LAYOUT2_JSON_MEMBER_MAX_BYTES = 16 * 1024 * 1024
LAYOUT2_ARCHIVE_MAX_UNCOMPRESSED_BYTES = 64 * 1024 * 1024
LAYOUT2_ARCHIVE_MAX_MEMBERS = 10_000
_LAYOUT2_REQUIRED_MEMBERS = frozenset({"project.json", "settings.json", "shots.json"})
_LAYOUT2_JSON_PREFIXES = frozenset({"annotations", "notes", "scenes2d", "scenes3d"})
_LAYOUT2_GENERATION_GROUPS = frozenset({"requests", "state", "results"})
_LAYOUT2_COVER_MEMBER = "cover.png"
_LAYOUT2_STATE_MEMBER = "state.json"
_LAYOUT2_MUTATION_PREFIX = "mutation-"
_LAYOUT2_MUTATION_PREPARE_PREFIX = ".mutation-prepare-"
_LAYOUT2_MUTATION_RESOLVED_PREFIX = ".mutation-resolved-"
_LAYOUT2_MUTATION_RESTORE_PREFIX = ".mutation-restore-"
_LAYOUT2_MUTATION_DISCARD_PREFIX = ".mutation-discard-"
_LAYOUT2_MUTATION_ASSET_PREFIX = "asset-"
_LAYOUT2_MUTATION_LOCAL = threading.local()


class Layout2DocumentError(ValueError):
    """A Layout 2 metadata archive or work-state contract was violated."""


class Layout2RevisionConflict(Layout2DocumentError):
    """Revision evidence cannot be reconciled without risking newer work."""


@dataclass(frozen=True)
class Layout2DocumentSnapshot:
    project_id: str
    revision: int
    commit_id: str
    members: tuple[str, ...]


@dataclass(frozen=True)
class Layout2RecoveryResult:
    source: str
    project_id: str
    work_revision: int
    committed_revision: int
    commit_id: str
    work_root: Path


def _layout2_document_path(project_root: Path, document_path: Path | None = None) -> Path:
    root = Path(project_root).expanduser().resolve()
    document = (
        resolve_root_child(root, f"{root.name}{DOCUMENT_SUFFIX}")
        if document_path is None
        else Path(document_path).expanduser().resolve()
    )
    if document.parent != root or document.name != f"{root.name}{DOCUMENT_SUFFIX}":
        raise Layout2DocumentError(
            "Layout 2 metadata document must be the project-root child named "
            f"{root.name}{DOCUMENT_SUFFIX}."
        )
    return document


def layout2_work_root(project_root: Path) -> Path:
    return resolve_root_child(Path(project_root).expanduser().resolve(), ".storyboarder", "work")


def layout2_state_path(project_root: Path) -> Path:
    return resolve_root_child(
        Path(project_root).expanduser().resolve(),
        ".storyboarder",
        _LAYOUT2_STATE_MEMBER,
    )


def _layout2_transactions_root(project_root: Path) -> Path:
    return resolve_root_child(
        Path(project_root).expanduser().resolve(),
        ".storyboarder",
        "transactions",
    )


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


def _read_layout2_mutation_manifest(transaction: Path) -> dict[str, Any]:
    manifest_path = resolve_root_child(transaction, "manifest.json")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Layout2RevisionConflict(
            f"Layout 2 mutation recovery manifest is unreadable: {transaction.name}."
        ) from exc
    if not isinstance(manifest, dict) or manifest.get("version") != 1:
        raise Layout2RevisionConflict(
            f"Layout 2 mutation recovery manifest is invalid: {transaction.name}."
        )
    assets = manifest.get("assets", [])
    if not isinstance(assets, list) or any(
        not isinstance(entry, dict) for entry in assets
    ):
        raise Layout2RevisionConflict(
            f"Layout 2 mutation asset journal is invalid: {transaction.name}."
        )
    manifest["assets"] = assets
    return manifest


def _snapshot_layout2_asset_path(
    root: Path,
    transaction: Path,
    target: Path,
    ordinal: int,
) -> dict[str, str]:
    relative = target.relative_to(root).as_posix()
    validate_project_relative_posix(
        relative,
        field_name="Layout 2 mutation asset path",
    )
    snapshot_name = f"{_LAYOUT2_MUTATION_ASSET_PREFIX}{ordinal:06d}"
    snapshot = resolve_root_child(transaction, "assets", snapshot_name)
    if target.is_symlink():
        raise Layout2RevisionConflict(
            f"Layout 2 mutation asset cannot be a symbolic link: {relative}."
        )
    if target.is_dir():
        for child in target.rglob("*"):
            if child.is_symlink():
                raise Layout2RevisionConflict(
                    f"Layout 2 mutation asset tree contains a symbolic link: {relative}."
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
        raise Layout2RevisionConflict(
            f"Layout 2 mutation asset has an unsupported type: {relative}."
        )
    else:
        snapshot_name = ""
        kind = "missing"
    return {
        "path": relative,
        "kind": kind,
        "snapshot": snapshot_name,
    }


def enlist_layout2_mutation_paths(
    project_root: Path,
    paths: Iterable[Path],
) -> tuple[str, ...]:
    """Durably journal asset paths before a Layout 2 mutation changes them."""
    transaction_value = getattr(_LAYOUT2_MUTATION_LOCAL, "transaction", None)
    active_root = getattr(_LAYOUT2_MUTATION_LOCAL, "project_root", None)
    if transaction_value is None or active_root is None:
        return ()
    root = Path(project_root).expanduser().resolve()
    if root != Path(active_root):
        raise Layout2RevisionConflict(
            "Nested Layout 2 mutation attempted to journal another project."
        )
    transaction = Path(transaction_value)
    manifest = _read_layout2_mutation_manifest(transaction)
    assets = manifest["assets"]
    existing = {
        str(entry.get("path") or ""): entry
        for entry in assets
    }
    transactions_root = _layout2_transactions_root(root)
    requested: list[Path] = []
    for raw in paths:
        candidate = Path(raw)
        resolved = candidate.resolve()
        if resolved == root or root not in resolved.parents:
            raise Layout2RevisionConflict(
                f"Layout 2 mutation asset escapes the project root: {candidate}."
            )
        if (
            resolved == transactions_root
            or transactions_root in resolved.parents
            or resolved in transactions_root.parents
        ):
            raise Layout2RevisionConflict(
                "Layout 2 mutation assets cannot include the transaction journal."
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
            raise Layout2RevisionConflict(
                "Layout 2 mutation cannot widen an asset snapshot after writes began."
            )
        entry = _snapshot_layout2_asset_path(
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


def _restore_layout2_asset_snapshot(
    root: Path,
    transaction: Path,
    entry: dict[str, Any],
) -> None:
    relative_text = str(entry.get("path") or "")
    relative = validate_project_relative_posix(
        relative_text,
        field_name="Layout 2 mutation asset path",
    )
    target = resolve_root_child(root, *relative.parts)
    kind = entry.get("kind")
    snapshot_name = str(entry.get("snapshot") or "")
    if kind not in {"missing", "file", "directory"}:
        raise Layout2RevisionConflict(
            f"Layout 2 mutation asset kind is invalid: {relative_text}."
        )
    transactions_root = _layout2_transactions_root(root)
    discarded = resolve_root_child(
        transactions_root,
        f"{_LAYOUT2_MUTATION_DISCARD_PREFIX}{uuid.uuid4().hex}",
    )
    staged = resolve_root_child(
        transactions_root,
        f"{_LAYOUT2_MUTATION_RESTORE_PREFIX}{uuid.uuid4().hex}",
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
            raise Layout2RevisionConflict(
                f"Layout 2 mutation asset snapshot is missing: {relative_text}."
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        if kind == "file":
            if not snapshot.is_file():
                raise Layout2RevisionConflict(
                    f"Layout 2 mutation file snapshot is missing: {relative_text}."
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
            raise Layout2RevisionConflict(
                f"Layout 2 mutation directory snapshot is missing: {relative_text}."
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


def _restore_layout2_mutation_snapshot(project_root: Path, transaction: Path) -> None:
    root = Path(project_root).expanduser().resolve()
    manifest = _read_layout2_mutation_manifest(transaction)

    transactions_root = _layout2_transactions_root(root)
    work_root = layout2_work_root(root)
    state_path = layout2_state_path(root)
    work_present = manifest.get("work_present") is True
    state_present = manifest.get("state_present") is True
    staged_restore = resolve_root_child(
        transactions_root, f"{_LAYOUT2_MUTATION_RESTORE_PREFIX}{uuid.uuid4().hex}"
    )
    discarded = resolve_root_child(
        transactions_root, f"{_LAYOUT2_MUTATION_DISCARD_PREFIX}{uuid.uuid4().hex}"
    )
    for asset_entry in reversed(manifest["assets"]):
        _restore_layout2_asset_snapshot(
            root,
            transaction,
            asset_entry,
        )
    try:
        if work_present:
            snapshot_work = resolve_root_child(transaction, "work")
            if not snapshot_work.is_dir():
                raise Layout2RevisionConflict(
                    "Layout 2 mutation recovery is missing its work snapshot."
                )
            shutil.copytree(snapshot_work, staged_restore)
            if work_root.exists():
                os.replace(work_root, discarded)
            try:
                os.replace(staged_restore, work_root)
            except BaseException:
                if discarded.exists() and not work_root.exists():
                    os.replace(discarded, work_root)
                raise
            shutil.rmtree(discarded, ignore_errors=True)
        elif work_root.exists():
            os.replace(work_root, discarded)
            shutil.rmtree(discarded, ignore_errors=True)

        if state_present:
            state_snapshot = resolve_root_child(transaction, "state.json")
            if not state_snapshot.is_file():
                raise Layout2RevisionConflict(
                    "Layout 2 mutation recovery is missing its state snapshot."
                )
            _atomic_write_bytes(state_path, state_snapshot.read_bytes())
        else:
            state_path.unlink(missing_ok=True)
    finally:
        shutil.rmtree(staged_restore, ignore_errors=True)


def recover_incomplete_layout2_mutation(project_root: Path) -> bool:
    """Roll back a mutation that did not reach its response boundary."""
    root = Path(project_root).expanduser().resolve()
    transactions_root = _layout2_transactions_root(root)
    if not transactions_root.is_dir():
        return False
    for disposable_prefix in (
        _LAYOUT2_MUTATION_PREPARE_PREFIX,
        _LAYOUT2_MUTATION_RESOLVED_PREFIX,
        _LAYOUT2_MUTATION_RESTORE_PREFIX,
        _LAYOUT2_MUTATION_DISCARD_PREFIX,
    ):
        for disposable in transactions_root.glob(f"{disposable_prefix}*"):
            shutil.rmtree(disposable, ignore_errors=True)
    pending = sorted(
        path
        for path in transactions_root.glob(f"{_LAYOUT2_MUTATION_PREFIX}*")
        if path.is_dir() and not path.is_symlink()
    )
    if len(pending) > 1:
        raise Layout2RevisionConflict(
            "Multiple incomplete Layout 2 mutations require manual recovery."
        )
    if not pending:
        return False
    _restore_layout2_mutation_snapshot(root, pending[0])
    token = pending[0].name.removeprefix(_LAYOUT2_MUTATION_PREFIX)
    resolved = resolve_root_child(
        transactions_root, f"{_LAYOUT2_MUTATION_RESOLVED_PREFIX}{token}"
    )
    os.replace(pending[0], resolved)
    shutil.rmtree(resolved, ignore_errors=True)
    return True


@contextlib.contextmanager
def layout2_mutation_transaction(project_root: Path):
    """Make work metadata and revision evidence recoverable as one mutation."""
    depth = int(getattr(_LAYOUT2_MUTATION_LOCAL, "depth", 0) or 0)
    if depth:
        _LAYOUT2_MUTATION_LOCAL.depth = depth + 1
        try:
            yield
        finally:
            _LAYOUT2_MUTATION_LOCAL.depth = depth
        return

    root = Path(project_root).expanduser().resolve()
    recover_incomplete_layout2_mutation(root)
    transactions_root = _layout2_transactions_root(root)
    transactions_root.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    preparing = resolve_root_child(
        transactions_root, f"{_LAYOUT2_MUTATION_PREPARE_PREFIX}{token}"
    )
    transaction = resolve_root_child(
        transactions_root, f"{_LAYOUT2_MUTATION_PREFIX}{token}"
    )
    resolved = resolve_root_child(
        transactions_root, f"{_LAYOUT2_MUTATION_RESOLVED_PREFIX}{token}"
    )
    preparing.mkdir()
    work_root = layout2_work_root(root)
    state_path = layout2_state_path(root)
    cleanup_resolved = False
    try:
        if work_root.is_dir():
            shutil.copytree(work_root, resolve_root_child(preparing, "work"))
        if state_path.is_file():
            _atomic_write_bytes(
                resolve_root_child(preparing, "state.json"),
                state_path.read_bytes(),
            )
        _atomic_write_json(
            resolve_root_child(preparing, "manifest.json"),
            {
                "version": 1,
                "work_present": work_root.is_dir(),
                "state_present": state_path.is_file(),
                "assets": [],
            },
        )
        os.replace(preparing, transaction)
        _LAYOUT2_MUTATION_LOCAL.depth = 1
        _LAYOUT2_MUTATION_LOCAL.project_root = root
        _LAYOUT2_MUTATION_LOCAL.transaction = transaction
        try:
            yield
        except BaseException:
            _restore_layout2_mutation_snapshot(root, transaction)
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
                _restore_layout2_mutation_snapshot(root, transaction)
                raise
            cleanup_resolved = True
        finally:
            _LAYOUT2_MUTATION_LOCAL.depth = 0
            _LAYOUT2_MUTATION_LOCAL.project_root = None
            _LAYOUT2_MUTATION_LOCAL.transaction = None
    finally:
        shutil.rmtree(preparing, ignore_errors=True)
        if cleanup_resolved and resolved.exists():
            # The atomic rename above records the outcome. Interrupted cleanup
            # is therefore harmless and is collected during the next recovery.
            shutil.rmtree(resolved, ignore_errors=True)


def _layout2_member_kind(name: str) -> str:
    try:
        relative = validate_project_relative_posix(name, field_name="Layout 2 archive member")
    except ProjectPathError as exc:
        raise Layout2DocumentError(str(exc)) from exc
    parts = relative.parts
    if name in _LAYOUT2_REQUIRED_MEMBERS:
        return "json"
    if name == _LAYOUT2_COVER_MEMBER:
        return "cover"
    if relative.suffix.lower() != ".json":
        raise Layout2DocumentError(f"Layout 2 archive member is not allowlisted: {name}.")
    if len(parts) >= 2 and parts[0] in _LAYOUT2_JSON_PREFIXES:
        return "json"
    if (
        len(parts) >= 3
        and parts[0] == "generation"
        and parts[1] in _LAYOUT2_GENERATION_GROUPS
    ):
        return "json"
    raise Layout2DocumentError(f"Layout 2 archive member is not allowlisted: {name}.")


def _validated_commit_id(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise Layout2DocumentError("Layout 2 project.json requires a commit_id.")
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise Layout2DocumentError("Layout 2 commit_id must be a UUID.") from exc
    canonical = str(parsed)
    if value != canonical:
        raise Layout2DocumentError("Layout 2 commit_id must use canonical UUID text.")
    return canonical


def _read_json_bytes(raw: bytes, *, member: str) -> Any:
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Layout2DocumentError(f"Layout 2 JSON member is invalid: {member}.") from exc


def inspect_document_layout(document_path: Path):
    """Read only project.json to identify a document before any extraction."""
    document = Path(document_path).expanduser().resolve()
    if not document.is_file():
        raise FileNotFoundError(f"Storyboard document not found: {document}")
    if document.suffix.lower() != DOCUMENT_SUFFIX:
        raise ValueError(f"Storyboard documents must use the {DOCUMENT_SUFFIX} extension.")
    try:
        with zipfile.ZipFile(document, "r") as archive:
            try:
                info = archive.getinfo(_REQUIRED_MEMBER)
            except KeyError as exc:
                raise ValueError(
                    "Invalid Storyboarder document: project.json is missing."
                ) from exc
            if info.file_size > LAYOUT2_JSON_MEMBER_MAX_BYTES:
                raise ValueError("Invalid Storyboarder document: project.json is too large.")
            payload = _read_json_bytes(archive.read(info), member=_REQUIRED_MEMBER)
            return parse_project_manifest(payload)
    except zipfile.BadZipFile as exc:
        raise ValueError(f"Invalid Storyboarder document: {exc}") from exc


def validate_layout2_document(document_path: Path) -> Layout2DocumentSnapshot:
    """Validate a metadata-only Layout 2 archive without extracting it."""
    document = Path(document_path).expanduser().resolve()
    if not document.is_file():
        raise FileNotFoundError(f"Storyboard document not found: {document}")
    if document.suffix.lower() != DOCUMENT_SUFFIX:
        raise Layout2DocumentError(
            f"Storyboard documents must use the {DOCUMENT_SUFFIX} extension."
        )
    try:
        with zipfile.ZipFile(document, "r") as archive:
            all_infos = archive.infolist()
            if any(info.is_dir() for info in all_infos):
                raise Layout2DocumentError(
                    "Layout 2 archives must not contain directory entries."
                )
            infos = list(all_infos)
            if len(infos) > LAYOUT2_ARCHIVE_MAX_MEMBERS:
                raise Layout2DocumentError("Layout 2 archive has too many members.")
            names = [info.filename for info in infos]
            if len(names) != len(set(names)):
                raise Layout2DocumentError("Layout 2 archive contains duplicate members.")
            try:
                ensure_no_casefold_collisions(names, field_name="Layout 2 archive members")
            except ProjectPathError as exc:
                raise Layout2DocumentError(str(exc)) from exc

            total_size = 0
            project_payload: Any = None
            for info in infos:
                kind = _layout2_member_kind(info.filename)
                mode = (info.external_attr >> 16) & 0xFFFF
                if stat.S_ISLNK(mode):
                    raise Layout2DocumentError(
                        f"Layout 2 archive contains a symbolic link: {info.filename}."
                    )
                if info.flag_bits & 0x1:
                    raise Layout2DocumentError("Encrypted Layout 2 archives are unsupported.")
                cap = (
                    LAYOUT2_COVER_MAX_BYTES
                    if kind == "cover"
                    else LAYOUT2_JSON_MEMBER_MAX_BYTES
                )
                if info.file_size > cap:
                    raise Layout2DocumentError(
                        f"Layout 2 archive member exceeds its size cap: {info.filename}."
                    )
                total_size += info.file_size
                if total_size > LAYOUT2_ARCHIVE_MAX_UNCOMPRESSED_BYTES:
                    raise Layout2DocumentError(
                        "Layout 2 archive exceeds the uncompressed metadata size cap."
                    )
                raw = archive.read(info)
                if len(raw) != info.file_size:
                    raise Layout2DocumentError(
                        f"Layout 2 archive member has an invalid size: {info.filename}."
                    )
                if kind == "cover":
                    if not raw.startswith(b"\x89PNG\r\n\x1a\n"):
                        raise Layout2DocumentError("Layout 2 cover.png is not a PNG.")
                    continue
                payload = _read_json_bytes(raw, member=info.filename)
                if info.filename == _REQUIRED_MEMBER:
                    project_payload = payload

            missing = sorted(_LAYOUT2_REQUIRED_MEMBERS.difference(names))
            if missing:
                raise Layout2DocumentError(
                    f"Layout 2 archive is missing required members: {', '.join(missing)}."
                )
            spec = parse_project_manifest(project_payload)
            if spec.layout != LAYOUT_2:
                raise Layout2DocumentError("Metadata-only archives require Layout 2.")
            commit_id = _validated_commit_id(project_payload.get("commit_id"))
            return Layout2DocumentSnapshot(
                project_id=spec.project_id,
                revision=spec.storage_revision,
                commit_id=commit_id,
                members=tuple(sorted(names)),
            )
    except zipfile.BadZipFile as exc:
        raise Layout2DocumentError(f"Invalid Storyboarder document: {exc}") from exc


def _validate_layout2_work_tree(
    work_root: Path,
) -> tuple[dict[str, Path], str, int]:
    root = Path(work_root).resolve()
    if not root.is_dir():
        raise Layout2DocumentError(f"Layout 2 work root is missing: {root}.")
    files: dict[str, Path] = {}
    total_size = 0
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise Layout2DocumentError(f"Layout 2 work state contains a link: {path}.")
        if not path.is_file():
            continue
        name = path.relative_to(root).as_posix()
        if _layout2_member_kind(name) != "json":
            raise Layout2DocumentError(
                f"Layout 2 work state may contain JSON metadata only: {name}."
            )
        size = path.stat().st_size
        if size > LAYOUT2_JSON_MEMBER_MAX_BYTES:
            raise Layout2DocumentError(
                f"Layout 2 work-state member exceeds its size cap: {name}."
            )
        total_size += size
        if total_size > LAYOUT2_ARCHIVE_MAX_UNCOMPRESSED_BYTES:
            raise Layout2DocumentError(
                "Layout 2 work state exceeds the uncompressed metadata size cap."
            )
        _read_json_bytes(path.read_bytes(), member=name)
        files[name] = path
        if len(files) > LAYOUT2_ARCHIVE_MAX_MEMBERS:
            raise Layout2DocumentError("Layout 2 work state has too many members.")
    try:
        ensure_no_casefold_collisions(files, field_name="Layout 2 work-state paths")
    except ProjectPathError as exc:
        raise Layout2DocumentError(str(exc)) from exc
    missing = sorted(_LAYOUT2_REQUIRED_MEMBERS.difference(files))
    if missing:
        raise Layout2DocumentError(
            f"Layout 2 work state is missing required members: {', '.join(missing)}."
        )
    project_payload = _read_json_bytes(files[_REQUIRED_MEMBER].read_bytes(), member=_REQUIRED_MEMBER)
    spec = parse_project_manifest(project_payload)
    if spec.layout != LAYOUT_2:
        raise Layout2DocumentError("Layout 2 work state requires a Layout 2 project.json.")
    return files, spec.project_id, spec.storage_revision


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


def _read_layout2_state(project_root: Path) -> dict[str, Any] | None:
    path = layout2_state_path(project_root)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Layout2RevisionConflict("Layout 2 state.json is unreadable.") from exc
    if not isinstance(payload, dict) or payload.get("version") != LAYOUT2_STATE_VERSION:
        raise Layout2RevisionConflict("Layout 2 state.json has an unsupported schema.")
    project_id = payload.get("project_id")
    global_revision = payload.get("global_revision")
    committed_revision = payload.get("committed_revision")
    commit_id = payload.get("commit_id")
    if not isinstance(project_id, str) or not project_id:
        raise Layout2RevisionConflict("Layout 2 state.json has an invalid project_id.")
    for field_name, value in (
        ("global_revision", global_revision),
        ("committed_revision", committed_revision),
    ):
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or value < 0
            or value > MAX_STORAGE_REVISION
        ):
            raise Layout2RevisionConflict(
                f"Layout 2 state.json has an invalid {field_name}."
            )
    if commit_id:
        try:
            _validated_commit_id(commit_id)
        except Layout2DocumentError as exc:
            raise Layout2RevisionConflict(str(exc)) from exc
    elif committed_revision:
        raise Layout2RevisionConflict(
            "Layout 2 state.json requires commit_id for a committed revision."
        )
    if committed_revision > global_revision:
        raise Layout2RevisionConflict(
            "Layout 2 committed revision exceeds global revision."
        )
    return payload


def _write_layout2_state(
    project_root: Path,
    *,
    project_id: str,
    global_revision: int,
    committed_revision: int,
    commit_id: str,
) -> None:
    _atomic_write_json(
        layout2_state_path(project_root),
        {
            "version": LAYOUT2_STATE_VERSION,
            "project_id": project_id,
            "global_revision": global_revision,
            "committed_revision": committed_revision,
            "commit_id": commit_id,
        },
    )


def _cover_bytes(cover_path: Path | None) -> bytes | None:
    if cover_path is None:
        return None
    path = Path(cover_path)
    if path.is_symlink() or not path.is_file():
        raise Layout2DocumentError("Layout 2 cover source must be a regular file.")
    if path.stat().st_size > LAYOUT2_COVER_MAX_BYTES:
        raise Layout2DocumentError("Layout 2 cover.png exceeds 65,536 bytes.")
    raw = path.read_bytes()
    if not raw.startswith(b"\x89PNG\r\n\x1a\n"):
        raise Layout2DocumentError("Layout 2 cover source is not a PNG.")
    return raw


def _existing_cover(document: Path) -> bytes | None:
    if not document.is_file():
        return None
    with zipfile.ZipFile(document, "r") as archive:
        try:
            return archive.read(_LAYOUT2_COVER_MEMBER)
        except KeyError:
            return None


def _archive_matches_work(document: Path, files: dict[str, Path]) -> bool:
    with zipfile.ZipFile(document, "r") as archive:
        archived_json = {
            info.filename
            for info in archive.infolist()
            if not info.is_dir() and info.filename != _LAYOUT2_COVER_MEMBER
        }
        if archived_json != set(files):
            return False
        for name, path in files.items():
            archived = _read_json_bytes(archive.read(name), member=name)
            working = _read_json_bytes(path.read_bytes(), member=name)
            if name == _REQUIRED_MEMBER and isinstance(archived, dict):
                archived = dict(archived)
                archived.pop("commit_id", None)
            if name == _REQUIRED_MEMBER and isinstance(working, dict):
                working = dict(working)
                working.pop("commit_id", None)
            if archived != working:
                return False
    return True


def commit_layout2_document(
    project_root: Path,
    *,
    document_path: Path | None = None,
    cover_path: Path | None = None,
) -> Layout2DocumentSnapshot:
    """Atomically commit the JSON-only work tree to a metadata-only .sbd."""
    root = Path(project_root).expanduser().resolve()
    work_root = layout2_work_root(root)
    document = _layout2_document_path(root, document_path)
    files, project_id, revision = _validate_layout2_work_tree(work_root)
    supplied_cover = _cover_bytes(cover_path)
    state = _read_layout2_state(root)
    if state is not None:
        if state["project_id"] != project_id:
            raise Layout2RevisionConflict(
                "Layout 2 state.json project_id differs from the work state."
            )
        if int(state["global_revision"]) > revision:
            raise Layout2RevisionConflict(
                "Layout 2 state.json claims a missing work revision."
            )
        if int(state["committed_revision"]) > revision:
            raise Layout2RevisionConflict(
                "Committed Layout 2 revision cannot exceed the work revision."
            )

    existing: Layout2DocumentSnapshot | None = None
    if document.is_file():
        existing = validate_layout2_document(document)
        if existing.project_id != project_id:
            raise Layout2RevisionConflict("Layout 2 document and work state project_id differ.")
        if existing.revision > revision:
            raise Layout2RevisionConflict(
                "Layout 2 document revision is newer than the work state."
            )
        if state is not None:
            if int(state["committed_revision"]) > existing.revision:
                raise Layout2RevisionConflict(
                    "Layout 2 state.json claims a missing committed revision."
                )
            if (
                int(state["committed_revision"]) == existing.revision
                and state["commit_id"] != existing.commit_id
            ):
                raise Layout2RevisionConflict(
                    "Layout 2 commit_id conflicts at the same committed revision."
                )
        if existing.revision == revision:
            if not _archive_matches_work(document, files):
                raise Layout2RevisionConflict(
                    "Layout 2 work metadata changed without advancing its revision."
                )
            archived_cover = _existing_cover(document)
            if supplied_cover is not None and supplied_cover != archived_cover:
                raise Layout2RevisionConflict(
                    "Layout 2 cover changed without advancing the work revision."
                )
            global_revision = max(
                revision,
                int(state["global_revision"]) if state is not None else revision,
            )
            _write_layout2_state(
                root,
                project_id=project_id,
                global_revision=global_revision,
                committed_revision=revision,
                commit_id=existing.commit_id,
            )
            return existing

    cover = supplied_cover
    if cover is None and existing is not None:
        cover = _existing_cover(document)
    commit_id = str(uuid.uuid4())
    document.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{document.name}.",
        suffix=".tmp.sbd",
        dir=str(document.parent),
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        with zipfile.ZipFile(
            temporary,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=_PACK_COMPRESS_LEVEL,
        ) as archive:
            for name, path in sorted(files.items()):
                raw = path.read_bytes()
                if name == _REQUIRED_MEMBER:
                    payload = _read_json_bytes(raw, member=name)
                    if not isinstance(payload, dict):
                        raise Layout2DocumentError("Layout 2 project.json must be an object.")
                    payload = dict(payload)
                    payload["commit_id"] = commit_id
                    raw = (
                        json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
                        + b"\n"
                    )
                archive.writestr(name, raw, compress_type=zipfile.ZIP_DEFLATED)
            if cover is not None:
                archive.writestr(
                    _LAYOUT2_COVER_MEMBER,
                    cover,
                    compress_type=zipfile.ZIP_STORED,
                )
        snapshot = validate_layout2_document(temporary)
        with temporary.open("r+b") as stream:
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, document)
    finally:
        temporary.unlink(missing_ok=True)

    global_revision = max(
        revision,
        int(state["global_revision"]) if state is not None else revision,
    )
    _write_layout2_state(
        root,
        project_id=project_id,
        global_revision=global_revision,
        committed_revision=revision,
        commit_id=snapshot.commit_id,
    )
    return snapshot


def advance_layout2_work_revision(
    project_root: Path,
    *,
    expected_revision: int | None = None,
) -> int:
    """Advance the one authoritative work revision after accepted metadata writes."""
    root = Path(project_root).expanduser().resolve()
    work_root = layout2_work_root(root)
    files, project_id, revision = _validate_layout2_work_tree(work_root)
    if expected_revision is not None and revision != expected_revision:
        raise Layout2RevisionConflict(
            f"Expected Layout 2 revision {expected_revision}, found {revision}."
        )
    if revision >= MAX_STORAGE_REVISION:
        raise Layout2RevisionConflict("Layout 2 revision counter is exhausted.")
    next_revision = revision + 1
    state = _read_layout2_state(root)
    if state is not None:
        if state["project_id"] != project_id:
            raise Layout2RevisionConflict(
                "Layout 2 state.json project_id differs from the work state."
            )
        if int(state["global_revision"]) > revision:
            raise Layout2RevisionConflict(
                "Layout 2 state.json claims a missing work revision."
            )
        if int(state["committed_revision"]) > revision:
            raise Layout2RevisionConflict(
                "Committed Layout 2 revision cannot exceed the work revision."
            )
    project_payload = _read_json_bytes(
        files[_REQUIRED_MEMBER].read_bytes(),
        member=_REQUIRED_MEMBER,
    )
    project_payload = dict(project_payload)
    project_payload["storage_revision"] = next_revision
    project_payload.pop("commit_id", None)
    _atomic_write_json(files[_REQUIRED_MEMBER], project_payload)

    committed_revision = int(state["committed_revision"]) if state is not None else 0
    commit_id = str(state["commit_id"]) if state is not None else ""
    if committed_revision > next_revision:
        raise Layout2RevisionConflict(
            "Committed Layout 2 revision cannot exceed the work revision."
        )
    _write_layout2_state(
        root,
        project_id=project_id,
        global_revision=next_revision,
        committed_revision=committed_revision,
        commit_id=commit_id,
    )
    return next_revision


def _extract_layout2_json(document: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    try:
        with zipfile.ZipFile(document, "r") as archive:
            for info in archive.infolist():
                if info.is_dir() or info.filename == _LAYOUT2_COVER_MEMBER:
                    continue
                if _layout2_member_kind(info.filename) != "json":
                    raise Layout2DocumentError(
                        f"Layout 2 archive member is not JSON metadata: {info.filename}."
                    )
                relative = validate_project_relative_posix(
                    info.filename,
                    field_name="Layout 2 archive member",
                )
                target = resolve_root_child(destination, *relative.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(info))
    except BaseException:
        shutil.rmtree(destination, ignore_errors=True)
        raise


def _replace_layout2_work_from_document(
    project_root: Path,
    document: Path,
    work_root: Path,
) -> None:
    recovery_root = resolve_root_child(project_root, ".storyboarder", "recovery")
    recovery_root.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    staged = resolve_root_child(recovery_root, f"work-{token}")
    previous = resolve_root_child(recovery_root, f"previous-{token}")
    _extract_layout2_json(document, staged)
    if work_root.exists():
        os.replace(work_root, previous)
    try:
        os.replace(staged, work_root)
    except BaseException:
        if previous.exists() and not work_root.exists():
            os.replace(previous, work_root)
        raise
    shutil.rmtree(previous, ignore_errors=True)


def recover_layout2_work(
    project_root: Path,
    *,
    document_path: Path | None = None,
) -> Layout2RecoveryResult:
    """Recover newer JSON work, otherwise restore the committed archive."""
    root = Path(project_root).expanduser().resolve()
    recover_incomplete_layout2_mutation(root)
    document = _layout2_document_path(root, document_path)
    snapshot = validate_layout2_document(document)
    work_root = layout2_work_root(root)
    state = _read_layout2_state(root)

    work_exists = work_root.is_dir()
    if work_exists:
        _files, work_project_id, work_revision = _validate_layout2_work_tree(work_root)
        if work_project_id != snapshot.project_id:
            raise Layout2RevisionConflict(
                "Layout 2 document and work state project_id differ."
            )
        if snapshot.revision > work_revision:
            raise Layout2RevisionConflict(
                "Layout 2 document revision exceeds the work revision invariant."
            )
    else:
        work_revision = snapshot.revision

    if state is not None:
        if state["project_id"] != snapshot.project_id:
            raise Layout2RevisionConflict(
                "Layout 2 state.json project_id differs from the document."
            )
        state_global = int(state["global_revision"])
        state_committed = int(state["committed_revision"])
        if state_committed > state_global:
            raise Layout2RevisionConflict(
                "Layout 2 committed revision exceeds global revision."
            )
        if state_committed > snapshot.revision:
            raise Layout2RevisionConflict(
                "Layout 2 state.json claims a missing committed revision."
            )
        if state_global > work_revision:
            raise Layout2RevisionConflict(
                "Layout 2 state.json claims a missing work revision."
            )
        if (
            state_committed == snapshot.revision
            and state["commit_id"] != snapshot.commit_id
        ):
            raise Layout2RevisionConflict(
                "Layout 2 commit_id conflicts at the same committed revision."
            )

    if work_exists and work_revision > snapshot.revision:
        source = "work"
        final_work_revision = work_revision
    else:
        _replace_layout2_work_from_document(root, document, work_root)
        source = "document"
        final_work_revision = snapshot.revision

    _write_layout2_state(
        root,
        project_id=snapshot.project_id,
        global_revision=final_work_revision,
        committed_revision=snapshot.revision,
        commit_id=snapshot.commit_id,
    )
    return Layout2RecoveryResult(
        source=source,
        project_id=snapshot.project_id,
        work_revision=final_work_revision,
        committed_revision=snapshot.revision,
        commit_id=snapshot.commit_id,
        work_root=work_root,
    )


def create_working_root(document_path: Path) -> Path:
    stem = document_path.stem.strip() or "Storyboard"
    root = Path(tempfile.mkdtemp(prefix=f"{WORKING_ROOT_PREFIX}{stem}-"))
    write_session_marker(root, document_path)
    return root


def write_session_marker(working_root: Path, document_path: Path) -> None:
    """Record which process owns this work tree, and which document it expands."""
    payload = {
        "pid": os.getpid(),
        "document_path": str(document_path),
        "created_at": time.time(),
    }
    try:
        (working_root / SESSION_MARKER).write_text(json.dumps(payload), encoding="utf-8")
    except OSError:
        # A missing marker only costs the next launch its ability to reclaim this
        # tree automatically; it must never block opening the document.
        logger.debug("Could not write session marker in %s", working_root, exc_info=True)


def _read_session_marker(working_root: Path) -> dict | None:
    try:
        payload = json.loads((working_root / SESSION_MARKER).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _process_is_running(pid: int) -> bool:
    """True when a process with this id exists. Errs toward True."""
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes

        # PROCESS_QUERY_LIMITED_INFORMATION: succeeds for any live process,
        # including ones this user cannot fully open.
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return ctypes.windll.kernel32.GetLastError() == 5  # ACCESS_DENIED: alive
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


def _force_writable(func, path, _exc_info) -> None:
    """rmtree onerror hook: clear the read-only bit Windows sets and retry once."""
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except OSError:
        logger.debug("Could not remove %s from a work tree", path, exc_info=True)


def remove_working_root(working_root: Path) -> bool:
    """Delete an expanded work tree, leaving no empty husk behind.

    Plain ``rmtree`` fails partway on Windows when a file is read-only or briefly
    locked, which is how empty ``storyboarder-*`` directories accumulate in TEMP.
    """
    shutil.rmtree(working_root, onerror=_force_writable)
    if not working_root.exists():
        return True
    shutil.rmtree(working_root, ignore_errors=True)
    return not working_root.exists()


def _has_unflushed_work(working_root: Path, document: Path) -> bool:
    """True when the tree holds edits the document does not — i.e. do not delete.

    Compares against the document's own timestamp: a tree written after its last
    pack is a crashed session's only copy of that work.
    """
    try:
        document_mtime = document.stat().st_mtime
    except OSError:
        return True  # Document gone or unreadable: never discard the only copy.
    try:
        for path in working_root.rglob("*"):
            if path.name == SESSION_MARKER or not path.is_file():
                continue
            if path.stat().st_mtime > document_mtime + 1.0:
                return True
    except OSError:
        return True
    return False


def sweep_orphaned_working_roots(temp_dir: Path | None = None) -> dict[str, list[str]]:
    """Reclaim work trees left by crashed or killed sessions.

    Conservative by design — a work tree can be the only copy of unsaved work, so
    a tree is removed only when it is provably safe: either it never got a
    project.json (an empty shell), or its owning process is gone *and* its
    document already contains everything the tree holds. Anything else is
    reported and left alone.
    """
    base = temp_dir or Path(tempfile.gettempdir())
    removed: list[str] = []
    kept: list[str] = []
    failed: list[str] = []
    result = {"removed": removed, "kept": kept, "failed": failed}
    try:
        candidates = sorted(base.glob(f"{WORKING_ROOT_PREFIX}*"))
    except OSError:
        return result

    def discard(root: Path) -> None:
        # A tree Windows refuses to reclaim (delete-pending ghost) is reported,
        # not retried forever and not silently dropped.
        (removed if remove_working_root(root) else failed).append(str(root))

    for root in candidates:
        if not root.is_dir():
            continue
        marker = _read_session_marker(root)
        if marker is None:
            # Predates markers, or the marker write failed. Only an empty shell
            # (no project.json) is provably worthless; keep anything with data.
            if (root / _REQUIRED_MEMBER).is_file():
                kept.append(str(root))
            else:
                discard(root)
            continue
        pid = marker.get("pid")
        if isinstance(pid, int) and _process_is_running(pid):
            continue  # A live instance owns this tree.
        document = Path(str(marker.get("document_path", "")))
        if _has_unflushed_work(root, document):
            kept.append(str(root))
        else:
            discard(root)
    return result


def extract_document(document_path: Path) -> Path:
    document = document_path.expanduser().resolve()
    if not document.is_file():
        raise FileNotFoundError(f"Storyboard document not found: {document}")
    if document.suffix.lower() != DOCUMENT_SUFFIX:
        raise ValueError(f"Storyboard documents must use the {DOCUMENT_SUFFIX} extension.")
    if inspect_document_layout(document).layout == LAYOUT_2:
        raise Layout2DocumentError(
            "Layout 2 documents must recover into .storyboarder/work; "
            "temporary expanded project trees are forbidden."
        )

    working_root = create_working_root(document)
    try:
        with zipfile.ZipFile(document, "r") as archive:
            members = archive.infolist()
            names = {member.filename.rstrip("/") for member in members}
            if _REQUIRED_MEMBER not in names:
                raise ValueError("Invalid Storyboarder document: project.json is missing.")
            for member in members:
                relative = PurePosixPath(member.filename)
                if relative.is_absolute() or ".." in relative.parts:
                    raise ValueError("Invalid Storyboarder document: unsafe archive path.")
                destination = (working_root / Path(*relative.parts)).resolve()
                try:
                    destination.relative_to(working_root.resolve())
                except ValueError as exc:
                    raise ValueError("Invalid Storyboarder document: unsafe archive path.") from exc
                if member.is_dir():
                    destination.mkdir(parents=True, exist_ok=True)
                    continue
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member, "r") as source, destination.open("wb") as target:
                    while chunk := source.read(1024 * 1024):
                        target.write(chunk)
    except (zipfile.BadZipFile, OSError, ValueError) as exc:
        remove_working_root(working_root)
        raise ValueError(f"Invalid Storyboarder document: {exc}") from exc
    # Re-stamp after extraction: this process owns the tree, whatever the archive
    # may have carried.
    write_session_marker(working_root, document)
    return working_root


def pack_document(working_root: Path, document_path: Path) -> None:
    root = working_root.resolve()
    document = document_path.expanduser().resolve()
    if document.suffix.lower() != DOCUMENT_SUFFIX:
        raise ValueError(f"Storyboard documents must use the {DOCUMENT_SUFFIX} extension.")
    if not (root / _REQUIRED_MEMBER).is_file():
        raise ValueError("Cannot save Storyboarder document: project.json is missing.")

    document.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{document.name}.", suffix=".tmp", dir=str(document.parent)
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=_PACK_COMPRESS_LEVEL) as archive:
            for path in sorted(root.rglob("*")):
                if not path.is_file() or path.is_symlink():
                    continue
                if path.name == SESSION_MARKER:
                    continue  # Session-local: names this machine's process, not the document.
                relative = path.relative_to(root)
                if relative.parts and relative.parts[0] in _UNPACKED_DIRS:
                    continue
                compress_type = (
                    zipfile.ZIP_STORED
                    if path.suffix.lower() in _STORED_SUFFIXES
                    else zipfile.ZIP_DEFLATED
                )
                archive.write(path, relative.as_posix(), compress_type=compress_type)
        with temporary.open("r+b") as stream:
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, document)
    finally:
        temporary.unlink(missing_ok=True)
