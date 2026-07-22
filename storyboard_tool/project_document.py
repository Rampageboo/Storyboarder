"""Single-file ``.sbd`` document packaging for Storyboarder projects.

The rest of the application intentionally continues to work against an expanded
project directory.  This adapter makes that implementation detail invisible to
the user: opening extracts into a private working directory and saving replaces
the visible document atomically.
"""
from __future__ import annotations

import os
import shutil
import tempfile
import zipfile
from pathlib import Path, PurePosixPath


DOCUMENT_SUFFIX = ".sbd"
_REQUIRED_MEMBER = "project.json"

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


def create_working_root(document_path: Path) -> Path:
    stem = document_path.stem.strip() or "Storyboard"
    return Path(tempfile.mkdtemp(prefix=f"storyboarder-{stem}-"))


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
        shutil.rmtree(working_root, ignore_errors=True)
        raise ValueError(f"Invalid Storyboarder document: {exc}") from exc
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
                compress_type = (
                    zipfile.ZIP_STORED
                    if path.suffix.lower() in _STORED_SUFFIXES
                    else zipfile.ZIP_DEFLATED
                )
                archive.write(path, path.relative_to(root).as_posix(), compress_type=compress_type)
        with temporary.open("r+b") as stream:
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, document)
    finally:
        temporary.unlink(missing_ok=True)
