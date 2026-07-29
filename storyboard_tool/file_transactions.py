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
from pathlib import Path
from typing import BinaryIO, Iterator


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
