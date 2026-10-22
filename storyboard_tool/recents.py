"""Recent-project descriptions for the Home screen.

The Home screen lists projects the user has opened before *without* opening any
of them: each card reads ``shots.json`` and one board image from the project
folder next to the ``.sbd`` handle.

Domain module: no FastAPI imports, no app state.
"""
from __future__ import annotations

import base64
import json
import logging
import os
from pathlib import Path
from typing import Any

from .project_document import DOCUMENT_SUFFIX

logger = logging.getLogger(__name__)

# A board thumbnail is a display cache and should be a few KB. The cap only
# stops a large source image from pushing megabytes into the Home payload.
_THUMBNAIL_MAX_BYTES = 1_500_000
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


def _project_thumbnail(root: Path) -> tuple[str, int, float]:
    """First board image, board count and last edit time of a project folder."""
    shots_json = root / ".storyboarder" / "data" / "shots.json"
    if not shots_json.is_file():
        return "", 0, 0.0
    modified_ms = shots_json.stat().st_mtime * 1000.0
    payload = json.loads(shots_json.read_text(encoding="utf-8"))
    shot_count = len(payload.get("shots", [])) if isinstance(payload, dict) else 0
    for member in _shot_image_members(payload):
        candidate = root / member
        if not candidate.is_file() or candidate.stat().st_size > _THUMBNAIL_MAX_BYTES:
            continue
        return _data_url(candidate.read_bytes(), candidate.suffix), shot_count, modified_ms
    return "", shot_count, modified_ms


def describe(raw_path: str) -> dict[str, Any]:
    """One Home-screen card. Never raises: a broken entry is reported, not fatal."""
    path = Path(raw_path).expanduser()
    entry: dict[str, Any] = {
        "path": str(path),
        "open_path": str(path),
        "name": path.stem,
        "location": str(path.parent),
        "exists": False,
        "modified_ms": 0.0,
        "shot_count": 0,
        "thumbnail": "",
    }
    if path.suffix.lower() != DOCUMENT_SUFFIX:
        return entry
    try:
        if not path.is_file():
            return entry
        entry["exists"] = True
        entry["modified_ms"] = path.stat().st_mtime * 1000.0
        thumbnail, shot_count, modified_ms = _project_thumbnail(path.parent)
        entry["thumbnail"], entry["shot_count"] = thumbnail, shot_count
        entry["modified_ms"] = max(entry["modified_ms"], modified_ms)
    except (OSError, ValueError, json.JSONDecodeError):
        # A missing drive or a hand-edited shots.json: the card still lists the
        # path so the user can see and remove it.
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
