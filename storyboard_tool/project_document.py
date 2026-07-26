"""Single-file ``.sbd`` document packaging for Storyboarder projects.

The rest of the application intentionally continues to work against an expanded
project directory.  This adapter makes that implementation detail invisible to
the user: opening extracts into a private working directory and saving replaces
the visible document atomically.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import stat
import sys
import tempfile
import time
import zipfile
from pathlib import Path, PurePosixPath

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
