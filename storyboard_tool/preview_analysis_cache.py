"""
Persistent preview-analysis cache.

Avoids decoding every preview image on every project open by caching whether
a preview has real artwork (non-solid-color) and whether it has transparency.
Cache identity: normalized path + mtime_ns + file size.

Cache file: <project>/workspace/cache/preview_analysis.json
"""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _cache_file(project_root: Path) -> Path:
    return project_root / "workspace" / "cache" / "preview_analysis.json"


def load_cache(project_root: Path) -> dict[str, Any]:
    """Load the cache from disk. Returns empty dict on any error (including corruption)."""
    try:
        data = json.loads(_cache_file(project_root).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_cache(project_root: Path, cache: dict[str, Any]) -> None:
    """Atomically write the cache. Silently ignores write failures."""
    path = _cache_file(project_root)
    tmp: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Unique sibling temp file avoids collisions when two workers write concurrently.
        tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        tmp.write_text(json.dumps(cache), encoding="utf-8")
        tmp.replace(path)
    except Exception:
        logger.debug("Preview analysis cache write failed", exc_info=True)
        if tmp is not None:
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass


def _key(preview_path: Path) -> str:
    return str(preview_path.resolve()).replace("\\", "/")


def _stat(preview_path: Path) -> tuple[int, int] | None:
    try:
        s = preview_path.stat()
        return s.st_mtime_ns, s.st_size
    except OSError:
        return None


def get_cached(cache: dict[str, Any], preview_path: Path) -> dict[str, bool] | None:
    """
    Return cached result for preview_path if the cache entry is valid.
    Returns None on miss, missing file, or stale entry (mtime_ns/size changed).
    """
    stat = _stat(preview_path)
    if stat is None:
        return None
    mtime_ns, size = stat
    entry = cache.get("entries", {}).get(_key(preview_path))
    if not isinstance(entry, dict):
        return None
    if entry.get("mtime_ns") != mtime_ns or entry.get("size") != size:
        return None
    return {
        "has_artwork_preview": bool(entry.get("has_artwork_preview", False)),
        "preview_has_transparency": bool(entry.get("preview_has_transparency", False)),
    }


def set_cached(
    cache: dict[str, Any],
    preview_path: Path,
    has_artwork_preview: bool,
    preview_has_transparency: bool,
) -> None:
    """Update an in-memory cache dict with the analysis result for preview_path."""
    stat = _stat(preview_path)
    if stat is None:
        return
    mtime_ns, size = stat
    if "entries" not in cache:
        cache["entries"] = {}
    cache["entries"][_key(preview_path)] = {
        "mtime_ns": mtime_ns,
        "size": size,
        "has_artwork_preview": has_artwork_preview,
        "preview_has_transparency": preview_has_transparency,
    }
