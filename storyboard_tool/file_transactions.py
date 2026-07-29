"""Atomic file-copy helpers for cross-file transaction safety.

All helpers write to a temp file beside the destination and then
call os.replace() to commit atomically.  A crash or exception leaves
at most a stale .tmp file; the destination is never partially overwritten.

Usage pattern:
  atomic_copy_file(source, destination)

The existing image_utils helpers (copy_and_convert_image, save_png_data_url,
create_thumbnail, create_blank_psd) already follow this pattern.  This
module fills the remaining gap: plain binary-copy operations that otherwise
would use shutil.copy2 directly.
"""
from __future__ import annotations

import contextlib
import os
import shutil
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Iterable, Iterator


@dataclass(frozen=True)
class _PathSnapshot:
    path: Path
    kind: str
    files: dict[str, bytes]
    directories: tuple[str, ...]


def _snapshot_path(path: Path) -> _PathSnapshot:
    target = Path(path)
    if not target.exists():
        return _PathSnapshot(target, "missing", {}, ())
    if target.is_symlink():
        raise ValueError(f"Cannot transactionally snapshot a link: {target}")
    if target.is_file():
        return _PathSnapshot(target, "file", {"": target.read_bytes()}, ())
    files = {
        item.relative_to(target).as_posix(): item.read_bytes()
        for item in sorted(target.rglob("*"))
        if item.is_file() and not item.is_symlink()
    }
    directories = tuple(
        sorted(
            item.relative_to(target).as_posix()
            for item in target.rglob("*")
            if item.is_dir() and not item.is_symlink()
        )
    )
    return _PathSnapshot(target, "directory", files, directories)


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".rollback"
    )
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _restore_snapshot(snapshot: _PathSnapshot) -> None:
    target = snapshot.path
    if snapshot.kind == "missing":
        if target.is_dir() and not target.is_symlink():
            shutil.rmtree(target)
        else:
            target.unlink(missing_ok=True)
        return
    if snapshot.kind == "file":
        if target.is_dir() and not target.is_symlink():
            shutil.rmtree(target)
        _atomic_write_bytes(target, snapshot.files[""])
        return
    if target.exists() and (not target.is_dir() or target.is_symlink()):
        target.unlink()
    target.mkdir(parents=True, exist_ok=True)
    expected_files = set(snapshot.files)
    for item in sorted(target.rglob("*"), key=lambda value: len(value.parts), reverse=True):
        relative = item.relative_to(target).as_posix()
        if item.is_file() or item.is_symlink():
            if relative not in expected_files:
                item.unlink(missing_ok=True)
        elif relative not in snapshot.directories:
            try:
                item.rmdir()
            except OSError:
                pass
    for relative in snapshot.directories:
        (target / Path(relative)).mkdir(parents=True, exist_ok=True)
    for relative, data in snapshot.files.items():
        _atomic_write_bytes(target / Path(relative), data)


@contextlib.contextmanager
def rollback_paths(paths: Iterable[Path]) -> Iterator[None]:
    """Restore small metadata files or trees exactly when the body fails."""
    snapshots = [_snapshot_path(Path(path)) for path in paths]
    try:
        yield
    except BaseException:
        try:
            for snapshot in reversed(snapshots):
                _restore_snapshot(snapshot)
        except BaseException as rollback_error:
            raise RuntimeError(
                "Metadata mutation failed and automatic rollback was incomplete."
            ) from rollback_error
        raise


@contextlib.contextmanager
def quarantined_deletions(project_root: Path, paths: Iterable[Path]) -> Iterator[Path]:
    """Move deletions aside on the project volume and restore them on failure."""
    root = Path(project_root).resolve()
    candidates: list[Path] = []
    resolved: set[Path] = set()
    for raw in paths:
        requested = Path(raw)
        if requested.is_symlink():
            raise ValueError(f"Deletion target cannot be a link: {requested}")
        candidate = requested.resolve()
        if candidate == root or root not in candidate.parents:
            raise ValueError(f"Deletion target must stay inside the project: {candidate}")
        if not candidate.exists():
            continue
        resolved.add(candidate)
    for candidate in sorted(resolved, key=lambda value: len(value.parts)):
        if any(parent == candidate or parent in candidate.parents for parent in candidates):
            continue
        candidates.append(candidate)
    transaction = (
        root / ".storyboarder" / "transactions" / f"delete-{uuid.uuid4().hex}"
    )
    moved: list[tuple[Path, Path]] = []
    try:
        for source in sorted(candidates, key=lambda value: len(value.parts)):
            staged = transaction / source.relative_to(root)
            staged.parent.mkdir(parents=True, exist_ok=True)
            os.replace(source, staged)
            moved.append((source, staged))
        yield transaction
    except BaseException:
        try:
            for source, staged in reversed(moved):
                source.parent.mkdir(parents=True, exist_ok=True)
                os.replace(staged, source)
        except BaseException as rollback_error:
            raise RuntimeError(
                f"Deletion failed and rollback is incomplete; recovery remains at {transaction}."
            ) from rollback_error
        shutil.rmtree(transaction, ignore_errors=True)
        raise
    else:
        shutil.rmtree(transaction, ignore_errors=True)


def atomic_copy_file(source: Path, destination: Path) -> Path:
    """Copy *source* to *destination* via a sibling temp file.

    Uses temp + os.replace() instead of shutil.copy2() so a crash mid-copy
    never leaves *destination* in a partial state.  If *source* and
    *destination* resolve to the same path this is a no-op.

    Raises the same exceptions as shutil.copy2 / os.replace.
    Returns *destination*.
    """
    if source.resolve() == destination.resolve():
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = destination.with_suffix(destination.suffix + ".tmp")
    try:
        shutil.copy2(source, tmp)
        os.replace(tmp, destination)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return destination


def atomic_copy_stream(source: BinaryIO, destination: Path) -> Path:
    """Copy an open binary stream via a sibling temporary file."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = destination.with_suffix(destination.suffix + ".tmp")
    try:
        with tmp.open("wb") as target:
            shutil.copyfileobj(source, target)
            target.flush()
            os.fsync(target.fileno())
        os.replace(tmp, destination)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return destination


@contextlib.contextmanager
def atomic_output_file(destination: Path) -> Iterator[Path]:
    """Yield a sibling staging file and atomically replace the destination."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(
        dir=str(destination.parent),
        prefix=f".{destination.stem}-",
        suffix=destination.suffix,
    )
    os.close(descriptor)
    staged = Path(name)
    staged.unlink()
    try:
        yield staged
        if not staged.is_file():
            raise OSError("Export did not produce its staged output file.")
        os.replace(staged, destination)
    except BaseException:
        staged.unlink(missing_ok=True)
        raise


@contextlib.contextmanager
def atomic_output_directory(destination: Path) -> Iterator[Path]:
    """Build a directory off to the side, then swap it into place with rollback."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    staged = Path(tempfile.mkdtemp(dir=str(destination.parent), prefix=f".{destination.name}-"))
    backup_root = Path(
        tempfile.mkdtemp(dir=str(destination.parent), prefix=f".{destination.name}-backup-")
    )
    backup = backup_root / "previous"
    moved_previous = False
    committed = False
    try:
        yield staged
        if destination.exists():
            os.replace(destination, backup)
            moved_previous = True
        try:
            os.replace(staged, destination)
            committed = True
        except BaseException:
            if moved_previous:
                os.replace(backup, destination)
                moved_previous = False
            raise
        if moved_previous:
            shutil.rmtree(backup_root, ignore_errors=True)
            moved_previous = False
    except BaseException:
        if moved_previous and not destination.exists():
            os.replace(backup, destination)
            moved_previous = False
        raise
    finally:
        if not committed:
            shutil.rmtree(staged, ignore_errors=True)
        if not moved_previous:
            shutil.rmtree(backup_root, ignore_errors=True)
