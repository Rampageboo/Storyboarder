from __future__ import annotations

import csv
import json
import os
import tempfile
import uuid
from pathlib import Path
from typing import Any

from .models import Shot
from .project_layout import resolve_root_child

# ── Storage boundary ──────────────────────────────────────────────────────────
#
# Canonical store (shots.json)
#   Written by:  backend only — project_manager.save_project / save_shots.
#   Read by:     backend open_project (first priority).
#   Format:      {"version": 1, "shots": [...]}
#   Guarantee:   atomic write (temp-file replace); never leaves a partial file.
#
# Compatibility snapshot (shots.csv)
#   Written by:  save_shots() after every canonical write, as a human-readable
#                side effect.  Also written by the Photoshop plugin in
#                standalone/offline mode ONLY (when not linked to the backend).
#   Read by:     open_project only when shots.json is absent (legacy projects).
#                If shots.json exists, shots.csv is IGNORED for data loading.
#   Rule:        shots.csv must NEVER be the active source of truth once
#                shots.json exists.  It is a generated export surface, not a
#                second store.  CSV import/editing goes through an explicit
#                preview/diff step — never a silent overwrite of shots.json.
#
# Legacy inline shots (project.json "shots" key)
#   Read by:     open_project only when BOTH shots.json and shots.csv are absent.
#   Written by:  old application versions only — no current code path writes this.
#
# Plugin standalone/offline writes
#   The Photoshop plugin may write shots.csv and project.json when it is NOT
#   linked to the running backend.  These writes are fallback paths for offline
#   workflows; they are suppressed in backend-linked mode by panel_storage_adapter.js
#   (see FALLBACK-OFFLINE-ONLY comments there).  The backend never reads these
#   plugin-written files preferentially over its own canonical shots.json.
SHOTS_CSV_NAME = "shots.csv"
SHOTS_JSON_NAME = "shots.json"
SHOTS_JSON_VERSION = 1

SHOT_CSV_COLUMNS = [
    "order",
    "shot_id",
    "title",
    "scene",
    "scene_id",
    "sequence",
    "description",
    "action_note",
    "camera_note",
    "character_note",
    "dialogue",
    "lighting_note",
    "transition_note",
    "duration_seconds",
    "status",
    "image_path",
    "preview_image_path",
    "thumbnail_path",
    "source_file_path",
    "source_sync_mtime",
    "annotation_path",
    "camera_data",
    "tags",
    "comments",
    "reference_image_paths",
    "ref_video_path",
    "ref_video_time",
    "ref_segment_time",
]

_JSON_COLUMNS = {"camera_data", "tags", "comments", "reference_image_paths"}


class ShotStoreError(ValueError):
    """Canonical shots.json is present but unreadable as a shot list."""


def shots_csv_path(project_root: Path) -> Path:
    return resolve_root_child(project_root, SHOTS_CSV_NAME)


def new_shot_id() -> str:
    return uuid.uuid4().hex


def load_shots_csv(path: Path) -> list[Shot]:
    """Load shots from the legacy shots.csv.

    COMPAT-READ: called ONLY when shots.json is absent (legacy project migration).
    Do not call this when shots.json exists; shots.json is the authoritative source.

    Row order in the file is the timeline order. The order column is rewritten on
    save for human reference in Excel and must not be used to resort rows on load.
    """
    if not path.is_file():
        return []

    shots: list[Shot] = []
    with path.open("r", newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        for row in reader:
            shot_id = str(row.get("shot_id", "")).strip()
            if not shot_id:
                continue
            shots.append(_shot_from_csv_row(row))
    return shots


def save_shots_csv(project_root: Path, shots: list[Shot]) -> Path:
    """Write the compatibility CSV snapshot from the current canonical shot list.

    COMPAT-GENERATED: this is a human-readable side effect of a canonical save,
    NOT an independent store.  It must not be edited in place and treated as truth
    while shots.json exists.  Always call save_shots() instead of calling this
    directly, so shots.json and shots.csv are kept in sync.
    """
    path = shots_csv_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=SHOT_CSV_COLUMNS, lineterminator="\n")
        writer.writeheader()
        for index, shot in enumerate(shots, start=1):
            writer.writerow(_shot_to_csv_row(shot, index))
    return path


def shots_csv_mtime(project_root: Path) -> float:
    path = shots_csv_path(project_root)
    if not path.is_file():
        return 0.0
    return path.stat().st_mtime


# --- Canonical JSON storage (shots.json) -----------------------------------


def shots_json_path(project_root: Path) -> Path:
    return resolve_root_child(project_root, SHOTS_JSON_NAME)


def load_shots_json(path: Path) -> list[Shot] | None:
    """Load shots from the canonical shots.json.

    Returns None only when the canonical file is absent, allowing callers to use
    legacy fallback stores. If shots.json exists but the container cannot be read
    as shot metadata, raises ShotStoreError so callers do not silently replace
    potentially recoverable data with an empty project.
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


def save_shots(project_root: Path, shots: list[Shot]) -> Path:
    """Persist shots to every store: the canonical shots.json plus the regenerated
    readable shots.csv snapshot. Returns the canonical shots.json path.

    All shot-mutating code paths should go through this so shots.json stays the
    single source of truth and shots.csv never drifts out of sync.
    """
    json_path = save_shots_json(project_root, shots)
    save_shots_csv(project_root, shots)
    return json_path


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


def _shot_from_csv_row(row: dict[str, Any]) -> Shot:
    payload: dict[str, Any] = {
        "shot_id": str(row.get("shot_id", "")).strip(),
        "title": row.get("title", ""),
        "scene": row.get("scene", ""),
        "scene_id": row.get("scene_id", ""),
        "sequence": row.get("sequence", ""),
        "description": row.get("description", ""),
        "action_note": row.get("action_note", ""),
        "camera_note": row.get("camera_note", ""),
        "character_note": row.get("character_note", ""),
        "dialogue": row.get("dialogue", ""),
        "lighting_note": row.get("lighting_note", ""),
        "transition_note": row.get("transition_note", ""),
        "duration_seconds": row.get("duration_seconds", 3.0),
        "status": row.get("status", "Draft"),
        "image_path": row.get("image_path", ""),
        "preview_image_path": row.get("preview_image_path", ""),
        "thumbnail_path": row.get("thumbnail_path", ""),
        "source_file_path": row.get("source_file_path", ""),
        "source_sync_mtime": row.get("source_sync_mtime", 0.0),
        "annotation_path": row.get("annotation_path", ""),
        "camera_data": _read_json_cell(row.get("camera_data"), {}),
        "tags": _read_json_cell(row.get("tags"), []),
        "comments": _read_json_cell(row.get("comments"), []),
        "reference_image_paths": _read_json_cell(row.get("reference_image_paths"), []),
        "ref_video_path": row.get("ref_video_path", ""),
        "ref_video_time": row.get("ref_video_time", 0.0),
        "ref_segment_time": row.get("ref_segment_time", 0.0),
    }
    return Shot.from_dict(payload)


def _shot_to_csv_row(shot: Shot, order: int) -> dict[str, str]:
    data = shot.to_dict()
    row: dict[str, str] = {}
    for column in SHOT_CSV_COLUMNS:
        if column == "order":
            row[column] = str(order)
            continue
        value = data.get(column, "")
        if column in _JSON_COLUMNS:
            row[column] = json.dumps(value if value is not None else ([] if column != "camera_data" else {}), ensure_ascii=False)
        else:
            row[column] = "" if value is None else str(value)
    return row


def _read_json_cell(raw: Any, default: Any) -> Any:
    if raw is None:
        return default
    text = str(raw).strip()
    if not text:
        return default
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        if isinstance(default, list) and text:
            return [item.strip() for item in text.split(",") if item.strip()]
        return default
