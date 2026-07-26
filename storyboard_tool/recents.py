"""Recent-project descriptions for the Home screen.

The Home screen lists documents the user has opened before *without* opening any
of them. For a single-file ``.sbd`` that means reading two small members out of
the zip (``shots.json`` plus one thumbnail) instead of extracting the whole
document, which for a real project is tens of megabytes.

Domain module: no FastAPI imports, no app state.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import zipfile
from pathlib import Path
from typing import Any

from .project_document import DOCUMENT_SUFFIX

logger = logging.getLogger(__name__)

# A board thumbnail is a display cache and should be a few KB. The cap only
# stops a hand-edited document from pushing megabytes into the Home payload.
_THUMBNAIL_MAX_BYTES = 1_500_000
_SHOTS_MEMBER = "shots.json"
# Preference order: the dedicated thumbnail, then the full preview, then the
# raw image. Older documents may not carry every field.
_IMAGE_FIELDS = ("thumbnail_path", "preview_image_path", "image_path")
_MEDIA_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}

DEFAULT_LIMIT = 12


def same_path(left: str, right: str) -> bool:
    """Compare two paths the way the host filesystem does."""
    if not left or not right:
        return False
    return os.path.normcase(os.path.normpath(left)) == os.path.normcase(os.path.normpath(right))


def dedupe(paths: list[str]) -> list[str]:
    """Drop repeats, comparing the way the host filesystem does."""
    seen: set[str] = set()
    result: list[str] = []
    for raw in paths:
        text = str(raw or "").strip()
        if not text:
            continue
        key = os.path.normcase(os.path.normpath(text))
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


def _data_url(raw: bytes, suffix: str) -> str:
    media_type = _MEDIA_TYPES.get(suffix.lower(), "image/png")
    return f"data:{media_type};base64,{base64.b64encode(raw).decode('ascii')}"


def _shot_image_members(payload: Any) -> list[str]:
    """Project-relative image paths, in board order, from a shots.json payload."""
    shots = payload.get("shots") if isinstance(payload, dict) else payload
    if not isinstance(shots, list):
        return []
    members: list[str] = []
    for shot in shots:
        if not isinstance(shot, dict):
            continue
        for field in _IMAGE_FIELDS:
            value = str(shot.get(field, "") or "").strip()
            if value:
                members.append(value.replace("\\", "/"))
                break
    return members


def _document_thumbnail(document: Path) -> tuple[str, int]:
    """First board thumbnail and board count, read straight out of the ``.sbd``."""
    with zipfile.ZipFile(document, "r") as archive:
        try:
            payload = json.loads(archive.read(_SHOTS_MEMBER))
        except KeyError:
            return "", 0
        members = _shot_image_members(payload)
        names = set(archive.namelist())
        shot_count = len(payload.get("shots", [])) if isinstance(payload, dict) else len(members)
        for member in members:
            if member not in names:
                continue
            info = archive.getinfo(member)
            if info.file_size > _THUMBNAIL_MAX_BYTES:
                continue
            return _data_url(archive.read(member), Path(member).suffix), shot_count
    return "", shot_count


def _folder_thumbnail(root: Path) -> tuple[str, int]:
    shots_json = root / _SHOTS_MEMBER
    if not shots_json.is_file():
        return "", 0
    payload = json.loads(shots_json.read_text(encoding="utf-8"))
    shot_count = len(payload.get("shots", [])) if isinstance(payload, dict) else 0
    for member in _shot_image_members(payload):
        candidate = root / member
        if not candidate.is_file() or candidate.stat().st_size > _THUMBNAIL_MAX_BYTES:
            continue
        return _data_url(candidate.read_bytes(), candidate.suffix), shot_count
    return "", shot_count


def describe(raw_path: str) -> dict[str, Any]:
    """One Home-screen card. Never raises: a broken entry is reported, not fatal."""
    path = Path(raw_path).expanduser()
    is_document = path.suffix.lower() == DOCUMENT_SUFFIX
    entry: dict[str, Any] = {
        "path": str(path),
        # What method_open_project needs: the document itself, or the folder's manifest.
        "open_path": str(path if is_document else path / "project.json"),
        "name": path.stem if is_document else path.name,
        "kind": "document" if is_document else "folder",
        "location": str(path.parent),
        "exists": False,
        "modified_ms": 0.0,
        "size_bytes": 0,
        "shot_count": 0,
        "thumbnail": "",
    }

    try:
        if is_document:
            if not path.is_file():
                return entry
            stat = path.stat()
            entry["exists"] = True
            entry["modified_ms"] = stat.st_mtime * 1000.0
            entry["size_bytes"] = stat.st_size
            entry["thumbnail"], entry["shot_count"] = _document_thumbnail(path)
        else:
            manifest = path / "project.json"
            if not manifest.is_file():
                return entry
            entry["exists"] = True
            entry["modified_ms"] = manifest.stat().st_mtime * 1000.0
            entry["thumbnail"], entry["shot_count"] = _folder_thumbnail(path)
    except (OSError, ValueError, zipfile.BadZipFile, json.JSONDecodeError):
        # A missing drive, a half-written document, a hand-edited shots.json: the
        # card still lists the path so the user can see and remove it.
        logger.debug("Could not describe recent project: %s", path, exc_info=True)
    return entry


def list_recents(paths: list[str], *, limit: int = DEFAULT_LIMIT) -> list[dict[str, Any]]:
    return [describe(item) for item in dedupe(paths)[:limit]]


def forget(paths: list[str], target: str) -> list[str]:
    """Remove one entry from a recents list, matching it the way the OS would."""
    key = os.path.normcase(os.path.normpath(str(target or "").strip()))
    if not key:
        return dedupe(paths)
    return [item for item in dedupe(paths) if os.path.normcase(os.path.normpath(item)) != key]
