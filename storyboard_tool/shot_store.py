from __future__ import annotations

import json
import os
import tempfile
import uuid
from pathlib import Path

from .models import Shot
from .project_layout import resolve_root_child

# ── Storage boundary ──────────────────────────────────────────────────────────
#
# shots.json is the only shot store.
#   Written by:  backend only — project_manager.save_project / save_shots_json.
#   Read by:     backend open_project.
#   Format:      {"version": 1, "shots": [...]}
#   Guarantee:   atomic write (temp-file replace); never leaves a partial file.
SHOTS_JSON_NAME = "shots.json"
SHOTS_JSON_VERSION = 1


class ShotStoreError(ValueError):
    """Canonical shots.json is present but unreadable as a shot list."""


def new_shot_id() -> str:
    return uuid.uuid4().hex


# --- Canonical JSON storage (shots.json) -----------------------------------


def shots_json_path(project_root: Path) -> Path:
    return resolve_root_child(project_root, SHOTS_JSON_NAME)


def load_shots_json(path: Path) -> list[Shot] | None:
    """Load shots from the canonical shots.json.

    Returns None only when the file is absent. If shots.json exists but the
    container cannot be read as shot metadata, raises ShotStoreError so callers
    do not silently replace potentially recoverable data with an empty project.
    """
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ShotStoreError(
            f"shots.json is corrupt: canonical shot metadata contains invalid JSON ({exc})"
        ) from exc
    except OSError as exc:
        raise ShotStoreError(
            f"shots.json is corrupt: canonical shot metadata could not be read ({exc})"
        ) from exc
    if isinstance(payload, dict):
        raw = payload.get("shots", [])
        if "shots" in payload and not isinstance(raw, list):
            raise ShotStoreError(
                "shots.json is corrupt: canonical shot metadata field 'shots' must be a list."
            )
    elif isinstance(payload, list):
        raw = payload
    else:
        raise ShotStoreError(
            "shots.json is corrupt: canonical shot metadata must be a JSON object or list."
        )
    if not isinstance(raw, list):
        raise ShotStoreError("shots.json is corrupt: canonical shot metadata must be a shot list.")
    shots: list[Shot] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        if not str(item.get("shot_id", "")).strip():
            continue
        shots.append(Shot.from_dict(item))
    return shots


def save_shots_json(project_root: Path, shots: list[Shot]) -> Path:
    """Atomically write the canonical shots.json (UTF-8, temp file then replace)."""
    path = shots_json_path(project_root)
    payload = {
        "version": SHOTS_JSON_VERSION,
        "shots": [shot.to_dict() for shot in shots],
    }
    _atomic_write_text(path, json.dumps(payload, indent=2, ensure_ascii=False))
    return path


def shots_json_mtime(project_root: Path) -> float:
    path = shots_json_path(project_root)
    if not path.is_file():
        return 0.0
    return path.stat().st_mtime


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Write to a sibling temp file then os.replace() — atomic on the same filesystem,
    # so a crash mid-write can never leave a truncated/half-written file behind.
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f"{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as file:
            file.write(text)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
