"""Project-level Scene 2D groups and perspectives."""
from __future__ import annotations

import copy
import hashlib
import json
import logging
import os
import re
import shutil
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import project_manager
from .file_transactions import atomic_copy_file
from .image_utils import create_blank_psd
from .models import Project
from .project_layout import (
    LAYOUT_2,
    scene2d_asset_relative,
    scene2d_metadata_path,
)

SCENE2D_ROOT = "scenes2d"
SCENE2D_INDEX = "scenes2d.json"
UUID_MIGRATION_JOURNAL = ".uuid_migration.json"
UUID_MIGRATION_BACKUP_ROOT = ".uuid_migration_backup"
PERSPECTIVE_MOVE_ROOT = ".perspective_move"
PERSPECTIVE_MOVE_JOURNAL = "journal.json"
LEGACY_SCENE_ID_RE = re.compile(r"^scene_(\d{3,})$")
LEGACY_PERSPECTIVE_ID_RE = re.compile(r"^persp_(\d{3,})$")
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
PSD_EXTENSIONS = {".psd"}
LOGGER = logging.getLogger(__name__)


@dataclass
class MoveRollbackResult:
    files_restored: bool = False
    metadata_restored: bool = False
    settings_restored: bool = False
    verified: bool = False


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def is_uuid(value: str) -> bool:
    try:
        return str(uuid.UUID(str(value or "").strip())) == str(value or "").strip().lower()
    except (TypeError, ValueError):
        return False


def new_uuid() -> str:
    return str(uuid.uuid4())


def _root_dir(project: Project) -> Path:
    return scene2d_metadata_path(project)


def _index_path(project: Project) -> Path:
    return scene2d_metadata_path(project, SCENE2D_INDEX)


def _journal_path(project: Project) -> Path:
    return scene2d_metadata_path(project, UUID_MIGRATION_JOURNAL)


def _backup_root(project: Project) -> Path:
    return scene2d_metadata_path(project, UUID_MIGRATION_BACKUP_ROOT)


def _validate_scene_id(scene_id: str) -> str:
    scene_id = str(scene_id or "").strip()
    if not is_uuid(scene_id):
        raise ValueError("Invalid Scene 2D id.")
    return scene_id


def _validate_perspective_id(perspective_id: str) -> str:
    perspective_id = str(perspective_id or "").strip()
    if not is_uuid(perspective_id):
        raise ValueError("Invalid Scene 2D perspective id.")
    return perspective_id


def _validate_scene_id_for_load(scene_id: str) -> str:
    scene_id = str(scene_id or "").strip()
    if not (is_uuid(scene_id) or LEGACY_SCENE_ID_RE.match(scene_id)):
        raise ValueError("Invalid Scene 2D id.")
    return scene_id


def _validate_perspective_id_for_load(perspective_id: str) -> str:
    perspective_id = str(perspective_id or "").strip()
    if not (is_uuid(perspective_id) or LEGACY_PERSPECTIVE_ID_RE.match(perspective_id)):
        raise ValueError("Invalid Scene 2D perspective id.")
    return perspective_id


def _scene_dir(project: Project, scene_id: str) -> Path:
    _validate_scene_id(scene_id)
    return scene2d_metadata_path(project, scene_id)


def _meta_path(project: Project, scene_id: str) -> Path:
    return scene2d_metadata_path(project, scene_id, f"{scene_id}_meta.json")


def _source_rel(scene_id: str, perspective_id: str, project: Project | None = None) -> str:
    if project is not None:
        return scene2d_asset_relative(project, scene_id, perspective_id, "source_psd")
    return f"{SCENE2D_ROOT}/{scene_id}/perspectives/{perspective_id}/source.psd"


def _preview_rel(scene_id: str, perspective_id: str, project: Project | None = None) -> str:
    if project is not None:
        return scene2d_asset_relative(project, scene_id, perspective_id, "preview")
    return f"{SCENE2D_ROOT}/{scene_id}/perspectives/{perspective_id}/preview.png"


def _image_source_rel(
    scene_id: str,
    perspective_id: str,
    suffix: str,
    project: Project | None = None,
) -> str:
    suffix = suffix if suffix in IMAGE_EXTENSIONS else ".png"
    if project is not None:
        return scene2d_asset_relative(
            project, scene_id, perspective_id, "source_image", suffix
        )
    return f"{SCENE2D_ROOT}/{scene_id}/perspectives/{perspective_id}/source{suffix}"


def _safe_rel_path(project: Project, relative_path: str) -> Path:
    rel = str(relative_path or "").strip()
    if not rel:
        raise ValueError("Scene 2D path is empty.")
    return project_manager.resolve_project_path(project, rel)


def _write_binary_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f"{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as file:
            file.write(data)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _normalize_perspective(
    raw: dict[str, Any],
    *,
    scene_id: str,
    fallback_id: str = "persp_001",
    legacy: bool = False,
    project: Project | None = None,
) -> dict[str, Any]:
    perspective_id = str(raw.get("id") or fallback_id).strip()
    perspective_id = _validate_perspective_id_for_load(perspective_id) if legacy else _validate_perspective_id(perspective_id)
    title = str(raw.get("title") or "").strip() or ("Main perspective" if perspective_id.startswith("persp_") else "Untitled Perspective")
    source = project_manager._normalize_rel_path(str(raw.get("source_file_path") or _source_rel(scene_id, perspective_id, project)).strip())
    perspective_type = str(raw.get("type") or "").strip().lower()
    if perspective_type not in {"psd", "image"}:
        perspective_type = "psd" if Path(source).suffix.lower() == ".psd" else "image"
    preview = project_manager._normalize_rel_path(str(raw.get("preview_image_path") or "").strip())
    if not preview:
        preview = source if perspective_type == "image" else _preview_rel(scene_id, perspective_id, project)
    created_at = str(raw.get("created_at") or "").strip() or _now_iso()
    updated_at = str(raw.get("updated_at") or created_at).strip() or created_at
    view = raw.get("linked_scene3d_view")
    return {
        "id": perspective_id,
        "title": title,
        "type": perspective_type,
        "source_file_path": source,
        "preview_image_path": preview,
        "linked_scene3d_id": str(raw.get("linked_scene3d_id") or "").strip(),
        "linked_scene3d_view": view if isinstance(view, dict) else None,
        "created_at": created_at,
        "updated_at": updated_at,
    }


def _primary_perspective(scene: dict[str, Any]) -> dict[str, Any] | None:
    perspectives = scene.get("perspectives") if isinstance(scene.get("perspectives"), list) else []
    primary_id = str(scene.get("primary_perspective_id") or "").strip()
    for perspective in perspectives:
        if perspective.get("id") == primary_id:
            return perspective
    return perspectives[0] if perspectives else None


def _with_legacy_aliases(scene: dict[str, Any]) -> dict[str, Any]:
    primary = _primary_perspective(scene)
    if primary:
        scene["primary_perspective_id"] = primary["id"]
        scene["source_file_path"] = primary["source_file_path"]
        scene["preview_image_path"] = primary["preview_image_path"]
    else:
        scene["primary_perspective_id"] = ""
        scene["source_file_path"] = ""
        scene["preview_image_path"] = ""
    return scene


def _normalize_scene(
    raw: dict[str, Any],
    *, legacy: bool = False,
    project: Project | None = None,
) -> dict[str, Any]:
    scene_id = _validate_scene_id_for_load(raw.get("id", "")) if legacy else _validate_scene_id(raw.get("id", ""))
    title = str(raw.get("title") or "").strip() or ("Untitled Scene" if is_uuid(scene_id) else scene_id)
    created_at = str(raw.get("created_at") or "").strip() or _now_iso()
    updated_at = str(raw.get("updated_at") or created_at).strip() or created_at
    raw_perspectives = raw.get("perspectives")
    if isinstance(raw_perspectives, list):
        perspectives = [
            _normalize_perspective(
                item,
                scene_id=scene_id,
                fallback_id=f"persp_{index + 1:03d}",
                legacy=legacy,
                project=project,
            )
            for index, item in enumerate(raw_perspectives)
            if isinstance(item, dict)
        ]
    else:
        fallback_perspective_id = "persp_001" if legacy else new_uuid()
        perspectives = [
            _normalize_perspective(
                {
                    "id": fallback_perspective_id,
                    "title": "Main perspective",
                    "type": "psd",
                    "source_file_path": raw.get("source_file_path") or _source_rel(scene_id, fallback_perspective_id, project),
                    "preview_image_path": raw.get("preview_image_path") or _preview_rel(scene_id, fallback_perspective_id, project),
                    "linked_scene3d_id": raw.get("linked_scene3d_id") or "",
                    "linked_scene3d_view": None,
                    "created_at": created_at,
                    "updated_at": updated_at,
                },
                scene_id=scene_id,
                legacy=legacy,
                project=project,
            )
        ]
    seen: set[str] = set()
    unique_perspectives: list[dict[str, Any]] = []
    for perspective in perspectives:
        if perspective["id"] in seen:
            continue
        seen.add(perspective["id"])
        unique_perspectives.append(perspective)
    primary_id = str(raw.get("primary_perspective_id") or "").strip()
    if primary_id not in {item["id"] for item in unique_perspectives}:
        primary_id = unique_perspectives[0]["id"] if unique_perspectives else ""
    raw_anchors = raw.get("consistency_anchors")
    anchors: list[str] = []
    seen_anchors: set[str] = set()
    if isinstance(raw_anchors, list):
        for value in raw_anchors:
            anchor = str(value or "").strip()
            if anchor and anchor not in seen_anchors:
                seen_anchors.add(anchor)
                anchors.append(anchor)
    scene = {
        "id": scene_id,
        "title": title,
        "description": str(raw.get("description") or ""),
        "location": str(raw.get("location") or ""),
        "time_of_day": str(raw.get("time_of_day") or ""),
        "environment_prompt": str(raw.get("environment_prompt") or ""),
        "consistency_anchors": anchors,
        "linked_scene3d_id": str(raw.get("linked_scene3d_id") or "").strip(),
        "primary_perspective_id": primary_id,
        "created_at": created_at,
        "updated_at": updated_at,
        "can_be_reference": bool(raw.get("can_be_reference", True)),
        "perspectives": unique_perspectives,
    }
    return _with_legacy_aliases(scene)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_bytes_if_exists(path: Path) -> bytes | None:
    return path.read_bytes() if path.is_file() else None


def _restore_bytes(path: Path, data: bytes | None) -> None:
    if data is None:
        if path.exists():
            path.unlink()
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f"{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as file:
            file.write(data)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _bytes_match_original(path: Path, original: bytes | None) -> bool:
    if original is None:
        return not path.exists()
    return path.is_file() and path.read_bytes() == original


@dataclass
class DuplicateRollbackResult:
    index_restored: bool = False
    meta_restored: bool = False
    metadata_verified: bool = False
    duplicate_files_removed: bool = False


def _rollback_perspective_duplicate(
    *,
    index_path: Path,
    index_bytes: bytes | None,
    meta_path: Path,
    meta_bytes: bytes | None,
    new_dir: Path,
    staging_dir: Path,
) -> DuplicateRollbackResult:
    result = DuplicateRollbackResult()

    try:
        _restore_bytes(index_path, index_bytes)
        result.index_restored = True
    except Exception:
        LOGGER.exception("Scene 2D duplicate rollback: failed to restore scenes2d.json")

    try:
        _restore_bytes(meta_path, meta_bytes)
        result.meta_restored = True
    except Exception:
        LOGGER.exception("Scene 2D duplicate rollback: failed to restore scene meta JSON")

    try:
        result.metadata_verified = (
            _bytes_match_original(index_path, index_bytes)
            and _bytes_match_original(meta_path, meta_bytes)
        )
    except OSError:
        LOGGER.exception("Scene 2D duplicate rollback: failed to verify restored metadata")
        result.metadata_verified = False

    if result.metadata_verified:
        if new_dir.is_dir():
            try:
                shutil.rmtree(new_dir)
                result.duplicate_files_removed = True
            except Exception:
                LOGGER.exception("Scene 2D duplicate rollback: failed to remove new perspective dir")
        else:
            result.duplicate_files_removed = True
        if staging_dir.is_dir():
            try:
                shutil.rmtree(staging_dir)
            except Exception:
                LOGGER.exception("Scene 2D duplicate rollback: failed to remove staging dir")

    return result


def _write_journal(project: Project, payload: dict[str, Any]) -> None:
    journal = {"version": 2, **payload}
    project_manager._atomic_write_json(_journal_path(project), journal)


def _remove_journal(project: Project) -> None:
    path = _journal_path(project)
    if path.exists():
        path.unlink()


def _remove_backup_area(project: Project) -> None:
    root = _backup_root(project)
    if root.is_dir():
        shutil.rmtree(root)


def _project_rel(project: Project, path: Path) -> str:
    return project_manager.project_relative_posix(project, path)


def _backup_rel_for_original(original_rel: str) -> str:
    rel = project_manager._normalize_rel_path(original_rel)
    if rel.startswith(f"{SCENE2D_ROOT}/"):
        rel = rel[len(SCENE2D_ROOT) + 1 :]
    return f"{SCENE2D_ROOT}/{UUID_MIGRATION_BACKUP_ROOT}/{rel}"


def _create_migration_backups(project: Project, original_paths: list[Path]) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    for original in original_paths:
        original_rel = _project_rel(project, original)
        backup_rel = _backup_rel_for_original(original_rel)
        backup = _safe_project_rel(project, backup_rel)
        entry = {"path": original_rel, "backup_path": backup_rel, "existed": original.is_file()}
        if original.is_file():
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(original, backup)
        files.append(entry)
    return files


def _validate_original_files(project: Project, original_files: Any) -> list[dict[str, Any]]:
    if not isinstance(original_files, list):
        raise ValueError("Scene 2D UUID migration journal has invalid original files.")
    result: list[dict[str, Any]] = []
    for item in original_files:
        if not isinstance(item, dict):
            raise ValueError("Scene 2D UUID migration journal has invalid original files.")
        rel = project_manager._normalize_rel_path(str(item.get("path") or ""))
        backup_rel = project_manager._normalize_rel_path(str(item.get("backup_path") or ""))
        if not rel or not backup_rel:
            raise ValueError("Scene 2D UUID migration journal has invalid original files.")
        _safe_project_rel(project, rel)
        backup_path = _safe_project_rel(project, backup_rel)
        if _backup_root(project).resolve() not in backup_path.resolve().parents:
            raise ValueError("Scene 2D UUID migration backup path is invalid.")
        result.append({"path": rel, "backup_path": backup_rel, "existed": bool(item.get("existed"))})
    return result


def _restore_original_files(project: Project, original_files: list[dict[str, Any]]) -> None:
    for item in original_files:
        target = _safe_project_rel(project, item["path"])
        backup = _safe_project_rel(project, item["backup_path"])
        if item.get("existed"):
            if not backup.is_file():
                raise ValueError("Scene 2D UUID migration backup file is missing.")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(backup, target)
        elif target.exists():
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()


def _safe_project_rel(project: Project, rel_path: str) -> Path:
    rel = str(rel_path or "").strip()
    if not rel:
        raise ValueError("Scene 2D migration path is empty.")
    return project_manager.resolve_project_path(project, rel)


def _move_root(project: Project) -> Path:
    return project_manager.resolve_project_child(
        project,
        SCENE2D_ROOT,
        PERSPECTIVE_MOVE_ROOT,
    )


def _move_journal_path(tx_dir: Path, *, project: Project | None = None) -> Path:
    if project is None:
        return project_manager.resolve_root_child(tx_dir, PERSPECTIVE_MOVE_JOURNAL)
    return project_manager.resolve_project_child(
        project,
        SCENE2D_ROOT,
        PERSPECTIVE_MOVE_ROOT,
        tx_dir.name,
        PERSPECTIVE_MOVE_JOURNAL,
    )


def _write_move_journal(
    tx_dir: Path,
    payload: dict[str, Any],
    *,
    project: Project | None = None,
) -> None:
    tx_dir.mkdir(parents=True, exist_ok=True)
    project_manager._atomic_write_json(
        _move_journal_path(tx_dir, project=project),
        {"version": 2, **payload, "updated_at": _now_iso()},
    )


def _move_backup_root_rel(project: Project, tx_dir: Path) -> str:
    return _project_rel(
        project,
        project_manager.resolve_project_child(
            project,
            SCENE2D_ROOT,
            PERSPECTIVE_MOVE_ROOT,
            tx_dir.name,
            "backup",
        ),
    )


def _move_backup_rel(project: Project, tx_dir: Path, name: str) -> str:
    return f"{_move_backup_root_rel(project, tx_dir)}/{name}"


def _move_metadata_files(project: Project, source_scene_id: str, target_scene_id: str) -> list[tuple[str, Path]]:
    return [
        ("scenes2d.json", _index_path(project)),
        ("settings.json", project.settings_path),
        ("source_scene_meta.json", _meta_path(project, source_scene_id)),
        ("target_scene_meta.json", _meta_path(project, target_scene_id)),
    ]


def _backup_move_metadata(project: Project, tx_dir: Path, source_scene_id: str, target_scene_id: str) -> list[dict[str, Any]]:
    tx_dir.mkdir(parents=True, exist_ok=True)
    originals: list[dict[str, Any]] = []
    for backup_name, path in _move_metadata_files(project, source_scene_id, target_scene_id):
        original_rel = _project_rel(project, path)
        backup_rel = _move_backup_rel(project, tx_dir, backup_name)
        backup_path = _safe_project_rel(project, backup_rel)
        entry = {"path": original_rel, "backup_path": backup_rel, "existed": path.is_file()}
        if path.is_file():
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, backup_path)
        originals.append(entry)
    return originals


def _validated_move_original_files(project: Project, tx_dir: Path, journal: dict[str, Any]) -> list[dict[str, Any]]:
    original_files = journal.get("original_files")
    if not isinstance(original_files, list):
        raise ValueError("Perspective move journal has invalid original_files.")
    tx_root = tx_dir.resolve()
    result: list[dict[str, Any]] = []
    for item in original_files:
        if not isinstance(item, dict):
            raise ValueError("Perspective move journal has invalid original file entry.")
        path_rel = project_manager._normalize_rel_path(str(item.get("path") or ""))
        backup_rel = project_manager._normalize_rel_path(str(item.get("backup_path") or ""))
        if not path_rel or not backup_rel:
            raise ValueError("Perspective move journal has empty original file paths.")
        _safe_project_rel(project, path_rel)
        backup_path = _safe_project_rel(project, backup_rel)
        if backup_path.resolve() != tx_root and tx_root not in backup_path.resolve().parents:
            raise ValueError("Perspective move backup path is outside the transaction directory.")
        result.append({"path": path_rel, "backup_path": backup_rel, "existed": bool(item.get("existed"))})
    return result


def _restore_move_metadata(project: Project, tx_dir: Path, journal: dict[str, Any]) -> MoveRollbackResult:
    result = MoveRollbackResult(files_restored=True)
    for item in _validated_move_original_files(project, tx_dir, journal):
        target = _safe_project_rel(project, item["path"])
        backup = _safe_project_rel(project, item["backup_path"])
        if item["existed"]:
            if not backup.is_file():
                raise ValueError(f"Perspective move backup is missing: {item['backup_path']}")
            _restore_bytes(target, backup.read_bytes())
        else:
            _restore_bytes(target, None)
    result.metadata_restored = True
    settings_backup = next((item for item in journal.get("original_files", []) if item.get("path") == "settings.json"), None)
    if settings_backup and settings_backup.get("existed"):
        restored = _read_json(project.settings_path)
        if not isinstance(restored, dict):
            raise ValueError("Restored settings.json is invalid.")
        project.settings = restored
    result.settings_restored = True
    return result


def _cleanup_move_tx(tx_dir: Path) -> None:
    if tx_dir.is_dir():
        shutil.rmtree(tx_dir, ignore_errors=True)


def _rollback_perspective_move(project: Project, tx_dir: Path, journal: dict[str, Any]) -> None:
    source_dir = _safe_project_rel(project, str(journal.get("source_dir") or ""))
    target_dir = _safe_project_rel(project, str(journal.get("target_dir") or ""))
    target_preexisted = bool(journal.get("target_preexisted"))
    result = MoveRollbackResult()
    try:
        if target_dir.is_dir() and not source_dir.exists():
            source_dir.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(target_dir), str(source_dir))
        elif target_dir.exists() and not target_preexisted:
            if target_dir.is_dir():
                shutil.rmtree(target_dir, ignore_errors=True)
            else:
                target_dir.unlink()
        result.files_restored = True
        metadata_result = _restore_move_metadata(project, tx_dir, journal)
        result.metadata_restored = metadata_result.metadata_restored
        result.settings_restored = metadata_result.settings_restored
        _verify_perspective_move_rollback(project, journal)
        result.verified = True
        _cleanup_move_tx(tx_dir)
    except BaseException as exc:
        LOGGER.exception("Perspective move rollback failed.")
        try:
            _write_move_journal(
                tx_dir,
                {
                    **journal,
                    "state": "rollback_failed",
                    "rollback_error": str(exc),
                    "rollback_result": {
                        "files_restored": result.files_restored,
                        "metadata_restored": result.metadata_restored,
                        "settings_restored": result.settings_restored,
                        "verified": result.verified,
                    },
                },
                project=project,
            )
        except Exception:
            LOGGER.exception("Failed to write rollback_failed journal.")
        raise RuntimeError(
            "Perspective move failed and automatic rollback was incomplete. "
            "Recovery data has been preserved. Restart Storyboarder to retry recovery."
        ) from exc


def _raw_scene_records(project: Project) -> list[dict[str, Any]]:
    data = _read_json(_index_path(project))
    raw_scenes = data.get("scenes") if isinstance(data, dict) else data
    if not isinstance(raw_scenes, list):
        raise ValueError("Scene 2D perspective move verification failed: invalid scenes2d.json.")
    return [_normalize_scene(item, project=project) for item in raw_scenes if isinstance(item, dict)]


def _scene_by_id(scenes: list[dict[str, Any]], scene_id: str) -> dict[str, Any]:
    scene = next((item for item in scenes if item.get("id") == scene_id), None)
    if not scene:
        raise ValueError(f"Scene 2D perspective move verification failed: scene {scene_id!r} missing.")
    return scene


def _perspective_occurrences(scenes: list[dict[str, Any]], perspective_id: str) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    occurrences: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for scene in scenes:
        for perspective in scene.get("perspectives") or []:
            if perspective.get("id") == perspective_id:
                occurrences.append((scene, perspective))
    return occurrences


def _assert_primary_is_valid(scene: dict[str, Any], label: str) -> None:
    perspective_ids = {item["id"] for item in scene.get("perspectives") or []}
    primary_id = str(scene.get("primary_perspective_id") or "")
    if perspective_ids and primary_id not in perspective_ids:
        raise ValueError(f"Scene 2D perspective move verification failed: {label} primary perspective is invalid.")
    if not perspective_ids and primary_id:
        raise ValueError(f"Scene 2D perspective move verification failed: empty {label} scene has a primary perspective.")


def _path_uses_scene_and_perspective(rel_path: str, scene_id: str, perspective_id: str) -> bool:
    parts = Path(project_manager._normalize_rel_path(rel_path)).parts
    return len(parts) >= 4 and parts[0] == SCENE2D_ROOT and parts[1] == scene_id and parts[2] == "perspectives" and parts[3] == perspective_id


def _assert_scene_meta_agrees(project: Project, scene: dict[str, Any], perspective_id: str, expected_source: str | None = None, expected_preview: str | None = None) -> None:
    meta_path = _meta_path(project, scene["id"])
    if not meta_path.is_file():
        raise ValueError("Scene 2D perspective move verification failed: scene meta JSON is missing.")
    meta = _normalize_scene(_read_json(meta_path), project=project)
    if meta["id"] != scene["id"]:
        raise ValueError("Scene 2D perspective move verification failed: scene meta id mismatch.")
    if meta.get("primary_perspective_id") != scene.get("primary_perspective_id"):
        raise ValueError("Scene 2D perspective move verification failed: scene meta primary mismatch.")
    index_ids = [item["id"] for item in scene.get("perspectives") or []]
    meta_ids = [item["id"] for item in meta.get("perspectives") or []]
    if meta_ids != index_ids:
        raise ValueError("Scene 2D perspective move verification failed: scene meta perspective membership mismatch.")
    if perspective_id in index_ids:
        meta_perspective = _find_perspective(meta, perspective_id)
        scene_perspective = _find_perspective(scene, perspective_id)
        if meta_perspective.get("source_file_path") != scene_perspective.get("source_file_path"):
            raise ValueError("Scene 2D perspective move verification failed: scene meta source path mismatch.")
        if meta_perspective.get("preview_image_path") != scene_perspective.get("preview_image_path"):
            raise ValueError("Scene 2D perspective move verification failed: scene meta preview path mismatch.")
        if expected_source is not None and meta_perspective.get("source_file_path") != expected_source:
            raise ValueError("Scene 2D perspective move verification failed: moved source path mismatch in scene meta.")
        if expected_preview is not None and meta_perspective.get("preview_image_path") != expected_preview:
            raise ValueError("Scene 2D perspective move verification failed: moved preview path mismatch in scene meta.")


def _verify_perspective_move_commit(project: Project, journal: dict[str, Any]) -> None:
    source_scene_id = str(journal.get("source_scene_id") or "")
    scene_id = str(journal.get("target_scene_id") or "")
    perspective_id = str(journal.get("perspective_id") or "")
    expected_source = str(journal.get("expected_source_file_path") or "")
    expected_preview = str(journal.get("expected_preview_image_path") or "")
    original_source = str(journal.get("original_source_file_path") or "")
    target_dir = _safe_project_rel(project, str(journal.get("target_dir") or ""))
    source_dir = _safe_project_rel(project, str(journal.get("source_dir") or ""))
    if not target_dir.is_dir():
        raise ValueError("Scene 2D perspective move verification failed: target folder is missing.")
    if source_dir.exists():
        raise ValueError("Scene 2D perspective move verification failed: source folder still exists.")
    expected_source_path = _safe_rel_path(project, expected_source)
    if not expected_source_path.is_file():
        raise ValueError("Scene 2D perspective move verification failed: expected source file missing.")
    if bool(journal.get("preview_existed_before")) and expected_preview != expected_source and not _safe_rel_path(project, expected_preview).is_file():
        raise ValueError("Scene 2D perspective move verification failed: expected preview file missing.")
    scenes = _raw_scene_records(project)
    source_scene = _scene_by_id(scenes, source_scene_id)
    target_scene = _scene_by_id(scenes, scene_id)
    occurrences = _perspective_occurrences(scenes, perspective_id)
    if len(occurrences) != 1 or occurrences[0][0]["id"] != scene_id:
        raise ValueError("Scene 2D perspective move verification failed: perspective ownership is inconsistent.")
    perspective = occurrences[0][1]
    if perspective.get("source_file_path") != expected_source or perspective.get("preview_image_path") != expected_preview:
        raise ValueError("Scene 2D perspective move verification failed: perspective paths not committed.")
    if not _path_uses_scene_and_perspective(expected_source, scene_id, perspective_id):
        raise ValueError("Scene 2D perspective move verification failed: source path is not canonical.")
    if not _path_uses_scene_and_perspective(expected_preview, scene_id, perspective_id):
        raise ValueError("Scene 2D perspective move verification failed: preview path is not canonical.")
    expected_canonical_source = _image_source_rel(scene_id, perspective_id, Path(original_source).suffix.lower()) if perspective.get("type") == "image" else _source_rel(scene_id, perspective_id)
    expected_canonical_preview = expected_canonical_source if perspective.get("type") == "image" else _preview_rel(scene_id, perspective_id)
    if expected_source != expected_canonical_source or expected_preview != expected_canonical_preview:
        raise ValueError("Scene 2D perspective move verification failed: expected paths are not canonical.")
    _assert_primary_is_valid(source_scene, "source")
    _assert_primary_is_valid(target_scene, "target")
    if not project.settings_path.is_file():
        raise ValueError("Scene 2D perspective move verification failed: settings.json is missing.")
    settings = _read_json(project.settings_path)
    if not isinstance(settings, dict):
        raise ValueError("Scene 2D perspective move verification failed: settings.json is invalid.")
    for expected in journal.get("expected_reference_links") or []:
        if not isinstance(expected, dict):
            continue
        found = False
        for link in project_manager.normalize_reference_links(settings.get("reference_links")):
            if str(link.get("id") or "") != str(expected.get("id") or ""):
                continue
            found = True
            if (
                str(link.get("source_scene2d_id") or "") != scene_id
                or str(link.get("source_scene2d_perspective_id") or "") != perspective_id
                or str(link.get("path") or "") != expected_preview
            ):
                raise ValueError("Scene 2D perspective move verification failed: reference link not committed.")
        if not found:
            raise ValueError("Scene 2D perspective move verification failed: reference link missing.")
    disk_normalized = dict(settings)
    memory_normalized = dict(project.settings)
    disk_normalized["reference_links"] = project_manager.normalize_reference_links(disk_normalized.get("reference_links"))
    memory_normalized["reference_links"] = project_manager.normalize_reference_links(memory_normalized.get("reference_links"))
    if disk_normalized != memory_normalized:
        raise ValueError("Scene 2D perspective move verification failed: in-memory settings differ from settings.json.")
    _assert_scene_meta_agrees(project, source_scene, perspective_id)
    _assert_scene_meta_agrees(project, target_scene, perspective_id, expected_source, expected_preview)


def _verify_perspective_move_rollback(project: Project, journal: dict[str, Any]) -> None:
    source_scene_id = str(journal.get("source_scene_id") or "")
    target_scene_id = str(journal.get("target_scene_id") or "")
    perspective_id = str(journal.get("perspective_id") or "")
    source_dir = _safe_project_rel(project, str(journal.get("source_dir") or ""))
    target_dir = _safe_project_rel(project, str(journal.get("target_dir") or ""))
    original_source = str(journal.get("original_source_file_path") or "")
    original_preview = str(journal.get("original_preview_image_path") or "")
    if not source_dir.is_dir():
        raise ValueError("Perspective move rollback verification failed: source folder is missing.")
    if target_dir.exists():
        raise ValueError("Perspective move rollback verification failed: target folder still exists.")
    if not _safe_rel_path(project, original_source).is_file():
        raise ValueError("Perspective move rollback verification failed: original source file is missing.")
    if bool(journal.get("preview_existed_before")) and original_preview != original_source and not _safe_rel_path(project, original_preview).is_file():
        raise ValueError("Perspective move rollback verification failed: original preview file is missing.")
    scenes = _raw_scene_records(project)
    source_scene = _scene_by_id(scenes, source_scene_id)
    target_scene = _scene_by_id(scenes, target_scene_id)
    occurrences = _perspective_occurrences(scenes, perspective_id)
    if len(occurrences) != 1 or occurrences[0][0]["id"] != source_scene_id:
        raise ValueError("Perspective move rollback verification failed: perspective ownership is not restored.")
    perspective = occurrences[0][1]
    if perspective.get("source_file_path") != original_source or perspective.get("preview_image_path") != original_preview:
        raise ValueError("Perspective move rollback verification failed: original paths are not restored.")
    _assert_primary_is_valid(source_scene, "source")
    _assert_primary_is_valid(target_scene, "target")
    settings = _read_json(project.settings_path)
    if not isinstance(settings, dict):
        raise ValueError("Perspective move rollback verification failed: settings.json is invalid.")
    disk_normalized = dict(settings)
    memory_normalized = dict(project.settings)
    disk_normalized["reference_links"] = project_manager.normalize_reference_links(disk_normalized.get("reference_links"))
    memory_normalized["reference_links"] = project_manager.normalize_reference_links(memory_normalized.get("reference_links"))
    if disk_normalized != memory_normalized:
        raise ValueError("Perspective move rollback verification failed: in-memory settings differ from settings.json.")
    for expected in journal.get("original_reference_links") or []:
        if not isinstance(expected, dict):
            continue
        match = next((link for link in project_manager.normalize_reference_links(settings.get("reference_links")) if str(link.get("id") or "") == str(expected.get("id") or "")), None)
        if match is None:
            raise ValueError("Perspective move rollback verification failed: original reference link is missing.")
        for key in ("source_scene2d_id", "source_scene2d_perspective_id", "path"):
            if str(match.get(key) or "") != str(expected.get(key) or ""):
                raise ValueError("Perspective move rollback verification failed: original reference link is not restored.")
    _assert_scene_meta_agrees(project, source_scene, perspective_id, original_source, original_preview)
    _assert_scene_meta_agrees(project, target_scene, perspective_id)


def _recover_perspective_moves(project: Project) -> bool:
    root = _move_root(project)
    if not root.is_dir():
        return False
    recovered = False
    for journal_path in sorted(root.glob(f"*/{PERSPECTIVE_MOVE_JOURNAL}")):
        tx_dir = journal_path.parent
        try:
            journal = _read_json(journal_path)
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("Scene 2D perspective move journal is corrupt.") from exc
        if not isinstance(journal, dict) or journal.get("version") not in {1, 2}:
            raise ValueError("Scene 2D perspective move journal is invalid.")
        state = str(journal.get("state") or "")
        if state == "prepared":
            _restore_move_metadata(project, tx_dir, journal)
            _verify_perspective_move_rollback(project, journal)
            _cleanup_move_tx(tx_dir)
            recovered = True
            continue
        if state == "files_moved":
            _rollback_perspective_move(project, tx_dir, journal)
            recovered = True
            continue
        if state == "metadata_committing":
            try:
                _verify_perspective_move_commit(project, journal)
                _write_move_journal(
                    tx_dir,
                    {**journal, "state": "metadata_committed"},
                    project=project,
                )
                _write_move_journal(tx_dir, {**journal, "state": "verified"}, project=project)
                _cleanup_move_tx(tx_dir)
            except Exception:
                _rollback_perspective_move(project, tx_dir, journal)
                recovered = True
            continue
        if state == "metadata_committed":
            try:
                _verify_perspective_move_commit(project, journal)
                _write_move_journal(tx_dir, {**journal, "state": "verified"}, project=project)
                _cleanup_move_tx(tx_dir)
                continue
            except Exception:
                _rollback_perspective_move(project, tx_dir, journal)
                recovered = True
                continue
        if state == "verified":
            _verify_perspective_move_commit(project, journal)
            _cleanup_move_tx(tx_dir)
            continue
        if state == "rollback_failed":
            try:
                _rollback_perspective_move(project, tx_dir, journal)
                recovered = True
                continue
            except Exception as exc:
                raise RuntimeError(
                    "Perspective move recovery is still incomplete. Recovery data has been preserved."
                ) from exc
        raise ValueError("Scene 2D perspective move journal has unknown state.")
    if root.is_dir() and not any(root.iterdir()):
        root.rmdir()
    return recovered


def _remove_created_paths(project: Project, rel_paths: list[str]) -> None:
    for rel_path in sorted({str(item or "") for item in rel_paths if item}, key=lambda item: len(Path(item).parts), reverse=True):
        try:
            path = _safe_project_rel(project, rel_path)
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            elif path.exists():
                path.unlink()
        except OSError:
            continue


def _cleanup_legacy_roots(project: Project, rel_roots: list[str]) -> bool:
    ok = True
    for rel_root in rel_roots:
        try:
            path = _safe_project_rel(project, rel_root)
            if path.is_dir():
                shutil.rmtree(path)
        except OSError:
            ok = False
    return ok


def _verify_migration_commit(project: Project, journal: dict[str, Any]) -> None:
    """Verify that both the Scene 2D payload AND settings are fully committed.

    Raises ValueError with a descriptive message on any failure.
    Called from _recover_uuid_migration() before rolling forward, and from
    _migrate_scene2d_storage() after committing all files.
    """
    # 1. Verify scene payload (UUID scenes, sources, previews exist)
    scene_map = journal.get("scene_map") if isinstance(journal.get("scene_map"), dict) else {}
    expected_scene_ids = {str(v) for v in scene_map.values() if is_uuid(str(v))} or None
    _verify_uuid_payload(project, expected_scene_ids)

    # 2. Verify settings only when migration changed them
    if not journal.get("settings_changed"):
        return

    settings_path = project.settings_path
    if not settings_path.is_file():
        raise ValueError("Migration commit verification failed: settings.json is missing.")
    try:
        disk_settings = _read_json(settings_path)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("Migration commit verification failed: settings.json is corrupt.") from exc
    if not isinstance(disk_settings, dict):
        raise ValueError("Migration commit verification failed: settings.json is not a dict.")

    # Hash-based check (canonical JSON, sort_keys for determinism)
    expected_hash = str(journal.get("expected_settings_hash") or "")
    if expected_hash:
        canonical = json.dumps(disk_settings, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        actual_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        if actual_hash == expected_hash:
            return  # Settings hash matches — fully committed

    # Per-link fallback verification (handles harmless formatting differences)
    expected_links = journal.get("expected_reference_links")
    if not isinstance(expected_links, list):
        raise ValueError(
            "Migration commit verification failed: expected_reference_links missing from journal."
        )
    disk_links = project_manager.normalize_reference_links(disk_settings.get("reference_links"))
    disk_by_scene_id: dict[str, dict[str, Any]] = {}
    for link in disk_links:
        sid = str(link.get("source_scene2d_id") or "")
        if sid:
            disk_by_scene_id[sid] = link

    for exp in expected_links:
        exp_scene = str(exp.get("source_scene2d_id") or "")
        exp_persp = str(exp.get("source_scene2d_perspective_id") or "")
        exp_path = str(exp.get("path") or "")
        disk_link = disk_by_scene_id.get(exp_scene)
        if disk_link is None:
            raise ValueError(
                f"Migration commit verification failed: reference link for scene {exp_scene!r} missing."
            )
        actual_persp = str(disk_link.get("source_scene2d_perspective_id") or "")
        actual_path = str(disk_link.get("path") or "")
        if actual_persp != exp_persp:
            raise ValueError(
                f"Migration commit verification failed: perspective ID mismatch for scene {exp_scene!r}."
            )
        if actual_path != exp_path:
            raise ValueError(
                f"Migration commit verification failed: path mismatch for scene {exp_scene!r}."
            )

    # Ensure no legacy scene_### or persp_### IDs remain in the affected reference links
    affected_scene_ids = {str(exp.get("source_scene2d_id") or "") for exp in expected_links}
    for link in disk_links:
        sid = str(link.get("source_scene2d_id") or "")
        pid = str(link.get("source_scene2d_perspective_id") or "")
        if sid in affected_scene_ids:
            if LEGACY_SCENE_ID_RE.match(sid) or (pid and LEGACY_PERSPECTIVE_ID_RE.match(pid)):
                raise ValueError(
                    "Migration commit verification failed: legacy ID remains in reference links."
                )


def _verify_uuid_payload(project: Project, expected_scene_ids: set[str] | None = None) -> None:
    data = _read_json(_index_path(project))
    raw_scenes = data.get("scenes") if isinstance(data, dict) else None
    if not isinstance(raw_scenes, list):
        raise ValueError("Scene 2D UUID migration verification failed: invalid scenes2d.json.")
    found = {str(item.get("id") or "") for item in raw_scenes if isinstance(item, dict)}
    if expected_scene_ids is not None and not expected_scene_ids.issubset(found):
        raise ValueError("Scene 2D UUID migration verification failed: missing migrated scenes.")
    for item in raw_scenes:
        if not isinstance(item, dict):
            raise ValueError("Scene 2D UUID migration verification failed: invalid scene record.")
        scene = _normalize_scene(item, project=project)
        for perspective in scene.get("perspectives") or []:
            if not _safe_rel_path(project, perspective["source_file_path"]).is_file():
                raise ValueError("Scene 2D UUID migration verification failed: missing source file.")
            preview_path = _safe_rel_path(project, perspective["preview_image_path"])
            if perspective["type"] == "image" and not preview_path.is_file():
                raise ValueError("Scene 2D UUID migration verification failed: missing image preview.")


def _recover_uuid_migration(project: Project) -> bool:
    path = _journal_path(project)
    if not path.is_file():
        return False
    try:
        journal = _read_json(path)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("Scene 2D UUID migration journal is corrupt.") from exc
    version = journal.get("version")
    if not isinstance(journal, dict) or version not in {1, 2}:
        raise ValueError("Scene 2D UUID migration journal is invalid.")
    state = journal.get("state")
    created_paths = journal.get("created_paths")
    legacy_roots = journal.get("legacy_roots")
    if not isinstance(created_paths, list) or not all(isinstance(item, str) for item in created_paths):
        raise ValueError("Scene 2D UUID migration journal has invalid created paths.")
    if legacy_roots is not None and (not isinstance(legacy_roots, list) or not all(isinstance(item, str) for item in legacy_roots)):
        raise ValueError("Scene 2D UUID migration journal has invalid legacy roots.")
    original_files: list[dict[str, Any]] = []
    if version == 2:
        original_files = _validate_original_files(project, journal.get("original_files"))
        backup_root = project_manager._normalize_rel_path(str(journal.get("backup_root") or ""))
        if backup_root != f"{SCENE2D_ROOT}/{UUID_MIGRATION_BACKUP_ROOT}":
            raise ValueError("Scene 2D UUID migration backup root is invalid.")
    if state in {"prepared", "files_staged"}:
        if original_files:
            _restore_original_files(project, original_files)
        _remove_created_paths(project, created_paths)
        _remove_journal(project)
        _remove_backup_area(project)
        return True
    if state == "metadata_committing":
        try:
            _verify_migration_commit(project, journal)
        except Exception:
            # Full commit not verified — roll back to the last known-good state.
            if original_files:
                _restore_original_files(project, original_files)
                # Keep disk and memory in sync after restoring settings.json.
                try:
                    restored = _read_json(project.settings_path)
                    if isinstance(restored, dict):
                        project.settings = restored
                except Exception:
                    pass
            _remove_created_paths(project, created_paths)
            _remove_journal(project)
            _remove_backup_area(project)
            return True
        _write_journal(project, {**journal, "state": "metadata_committed"})
        if _cleanup_legacy_roots(project, legacy_roots or []):
            _remove_journal(project)
            _remove_backup_area(project)
        return False
    if state in {"metadata_committed", "cleanup_pending"}:
        # Full verification before deleting any legacy data — conservative path.
        # If verification fails, raise a clear error rather than silently skipping.
        _verify_migration_commit(project, journal)
        if _cleanup_legacy_roots(project, legacy_roots or []):
            _remove_journal(project)
            _remove_backup_area(project)
        return False
    raise ValueError("Scene 2D UUID migration journal has unknown state.")


def _stable_source_rel(scene_id: str, perspective_id: str, perspective: dict[str, Any]) -> str:
    suffix = Path(str(perspective.get("source_file_path") or "")).suffix.lower()
    if perspective.get("type") == "image":
        return _image_source_rel(scene_id, perspective_id, suffix)
    return _source_rel(scene_id, perspective_id)


def _stable_preview_rel(scene_id: str, perspective_id: str, perspective: dict[str, Any], source_rel: str) -> str:
    if perspective.get("type") == "image":
        return source_rel
    return _preview_rel(scene_id, perspective_id)


def _is_stable_perspective_path(scene_id: str, perspective_id: str, perspective: dict[str, Any]) -> bool:
    source = str(perspective.get("source_file_path") or "")
    preview = str(perspective.get("preview_image_path") or "")
    expected_source = _stable_source_rel(scene_id, perspective_id, perspective)
    expected_preview = _stable_preview_rel(scene_id, perspective_id, perspective, expected_source)
    return source == expected_source and preview == expected_preview


def _needs_migration(scenes: list[dict[str, Any]]) -> bool:
    for scene in scenes:
        scene_id = str(scene.get("id") or "")
        if not is_uuid(scene_id):
            return True
        for perspective in scene.get("perspectives") or []:
            perspective_id = str(perspective.get("id") or "")
            if not is_uuid(perspective_id):
                return True
            if not _is_stable_perspective_path(scene_id, perspective_id, perspective):
                return True
    return False


def _copy_if_present(project: Project, source_rel: str, dest_rel: str, created_scene_dirs: set[Path], *, required: bool) -> None:
    source_rel = project_manager._normalize_rel_path(source_rel)
    dest_rel = project_manager._normalize_rel_path(dest_rel)
    if not source_rel:
        if required:
            raise FileNotFoundError("Scene 2D source path is empty.")
        return
    source = _safe_rel_path(project, source_rel)
    dest = _safe_rel_path(project, dest_rel)
    if source == dest:
        if required and not source.is_file():
            raise FileNotFoundError(f"Scene 2D source file not found: {source_rel}")
        return
    if not source.is_file():
        if required:
            raise FileNotFoundError(f"Scene 2D source file not found: {source_rel}")
        return
    scene_dir = dest.parent.parent.parent
    existed = scene_dir.exists()
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not existed:
        created_scene_dirs.add(scene_dir)
    shutil.copy2(source, dest)
    if not dest.is_file():
        raise OSError(f"Failed to copy Scene 2D file to: {dest_rel}")


def _legacy_scene_roots(project: Project, scenes: list[dict[str, Any]]) -> list[Path]:
    roots: list[Path] = []
    project_root = project.project_root.resolve()
    for scene in scenes:
        old_id = str(scene.get("id") or "")
        if is_uuid(old_id):
            continue
        candidate = project_manager.resolve_project_child(project, SCENE2D_ROOT, old_id)
        if candidate.is_dir() and candidate != project_root and project_root in candidate.parents:
            roots.append(candidate)
    return roots


def _migrated_settings_payload(
    settings: dict[str, Any],
    scene_map: dict[str, str],
    perspective_map: dict[tuple[str, str], str],
    perspective_preview_map: dict[tuple[str, str], str],
) -> tuple[dict[str, Any], bool]:
    migrated = dict(settings)
    links = project_manager.normalize_reference_links(migrated.get("reference_links"))
    changed = False
    for link in links:
        old_scene_id = str(link.get("source_scene2d_id") or "")
        old_perspective_id = str(link.get("source_scene2d_perspective_id") or "")
        if old_scene_id in scene_map:
            link["source_scene2d_id"] = scene_map[old_scene_id]
            changed = True
        if old_perspective_id:
            mapped = perspective_map.get((old_scene_id, old_perspective_id), "")
            if mapped:
                link["source_scene2d_perspective_id"] = mapped
                preview_path = perspective_preview_map.get((old_scene_id, old_perspective_id), "")
                if preview_path:
                    link["path"] = preview_path
                changed = True
    if changed:
        migrated["reference_links"] = project_manager.normalize_reference_links(links)
    return migrated, changed


def _migrate_scene2d_storage(project: Project, scenes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not _needs_migration(scenes):
        return _sort_scenes(scenes)

    scene_map: dict[str, str] = {}
    perspective_map: dict[tuple[str, str], str] = {}
    perspective_preview_map: dict[tuple[str, str], str] = {}
    for scene in scenes:
        old_scene_id = scene["id"]
        scene_map[old_scene_id] = old_scene_id if is_uuid(old_scene_id) else new_uuid()
        for perspective in scene.get("perspectives") or []:
            old_perspective_id = perspective["id"]
            perspective_map[(old_scene_id, old_perspective_id)] = old_perspective_id if is_uuid(old_perspective_id) else new_uuid()

    new_scenes: list[dict[str, Any]] = []
    planned_destinations: set[str] = set()
    created_scene_dirs: set[Path] = set()
    created_rel_paths: set[str] = set()
    legacy_roots = _legacy_scene_roots(project, scenes)
    legacy_root_rels = [
        project_manager.project_relative_posix(project, path) for path in legacy_roots
    ]
    original_index = _read_bytes_if_exists(_index_path(project))
    original_settings = _read_bytes_if_exists(project.settings_path)
    original_settings_memory = dict(project.settings)
    original_meta: dict[Path, bytes | None] = {}
    original_paths = [_index_path(project), project.settings_path]
    for scene in scenes:
        if is_uuid(scene["id"]):
            path = _meta_path(project, scene["id"])
        else:
            path = project_manager.resolve_project_child(
                project,
                SCENE2D_ROOT,
                scene["id"],
                f"{scene['id']}_meta.json",
            )
        original_meta[path] = _read_bytes_if_exists(path)
        original_paths.append(path)
    original_files = _create_migration_backups(project, original_paths)
    journal_base = {
        "scene_map": scene_map,
        "perspective_map": {f"{scene_id}/{perspective_id}": mapped for (scene_id, perspective_id), mapped in perspective_map.items()},
        "created_paths": [],
        "legacy_roots": legacy_root_rels,
        "backup_root": f"{SCENE2D_ROOT}/{UUID_MIGRATION_BACKUP_ROOT}",
        "original_files": original_files,
        "started_at": _now_iso(),
    }
    try:
        _write_journal(project, {"state": "prepared", **journal_base})
        for scene in scenes:
            old_scene_id = scene["id"]
            new_scene_id = scene_map[old_scene_id]
            new_scene_dir_rel = f"{SCENE2D_ROOT}/{new_scene_id}"
            new_perspectives: list[dict[str, Any]] = []
            for perspective in scene.get("perspectives") or []:
                old_perspective_id = perspective["id"]
                new_perspective_id = perspective_map[(old_scene_id, old_perspective_id)]
                source_rel = _stable_source_rel(new_scene_id, new_perspective_id, perspective)
                preview_rel = _stable_preview_rel(new_scene_id, new_perspective_id, perspective, source_rel)
                for destination in {source_rel, preview_rel}:
                    if destination in planned_destinations:
                        raise ValueError(f"Scene 2D migration path collision: {destination}")
                    planned_destinations.add(destination)
                _copy_if_present(project, perspective["source_file_path"], source_rel, created_scene_dirs, required=True)
                if project_manager.resolve_project_path(project, new_scene_dir_rel).is_dir():
                    created_rel_paths.add(new_scene_dir_rel)
                if preview_rel != source_rel:
                    _copy_if_present(project, perspective.get("preview_image_path", ""), preview_rel, created_scene_dirs, required=False)
                    if project_manager.resolve_project_path(project, new_scene_dir_rel).is_dir():
                        created_rel_paths.add(new_scene_dir_rel)
                perspective_preview_map[(old_scene_id, old_perspective_id)] = preview_rel
                new_perspective = dict(perspective)
                new_perspective.update({"id": new_perspective_id, "source_file_path": source_rel, "preview_image_path": preview_rel})
                new_perspectives.append(new_perspective)
            primary_id = str(scene.get("primary_perspective_id") or "")
            new_primary_id = perspective_map.get((old_scene_id, primary_id))
            if not new_primary_id and new_perspectives:
                new_primary_id = new_perspectives[0]["id"]
            new_scene = dict(scene)
            new_scene.update({"id": new_scene_id, "primary_perspective_id": new_primary_id or "", "perspectives": new_perspectives})
            new_scenes.append(_normalize_scene(new_scene, project=project))

        created_rel_paths.update(
            project_manager.project_relative_posix(project, path)
            for path in created_scene_dirs
            if path.exists()
        )
        _write_journal(project, {"state": "files_staged", **journal_base, "created_paths": sorted(created_rel_paths)})

        new_settings, settings_changed = _migrated_settings_payload(project.settings, scene_map, perspective_map, perspective_preview_map)
        root = _root_dir(project)
        root.mkdir(parents=True, exist_ok=True)
        normalized = _sort_scenes([_normalize_scene(scene, project=project) for scene in new_scenes])

        # Compute settings verification fields so crash recovery can validate them.
        if settings_changed:
            _settings_canon = json.dumps(new_settings, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            _expected_settings_hash = hashlib.sha256(_settings_canon.encode("utf-8")).hexdigest()
            _new_scene_uuids = set(scene_map.values())
            _expected_reference_links = [
                {
                    "source_scene2d_id": str(link.get("source_scene2d_id") or ""),
                    "source_scene2d_perspective_id": str(link.get("source_scene2d_perspective_id") or ""),
                    "path": str(link.get("path") or ""),
                }
                for link in project_manager.normalize_reference_links(new_settings.get("reference_links"))
                if str(link.get("source_scene2d_id") or "") in _new_scene_uuids
            ]
        else:
            _expected_settings_hash = ""
            _expected_reference_links = []
        _journal_settings: dict[str, Any] = {
            "settings_changed": settings_changed,
            "expected_settings_hash": _expected_settings_hash,
            "expected_reference_links": _expected_reference_links,
        }

        _write_journal(project, {"state": "metadata_committing", **journal_base, **_journal_settings, "created_paths": sorted(created_rel_paths)})
        project_manager._atomic_write_json(_index_path(project), {"scenes": normalized})
        for scene in normalized:
            scene_dir = _scene_dir(project, scene["id"])
            scene_dir.mkdir(parents=True, exist_ok=True)
            project_manager._atomic_write_json(_meta_path(project, scene["id"]), scene)
        if settings_changed:
            project_manager._atomic_write_json(project.settings_path, new_settings)
            project.settings = new_settings
        _verify_migration_commit(project, {**journal_base, **_journal_settings, "scene_map": scene_map})
        _write_journal(project, {"state": "metadata_committed", **journal_base, **_journal_settings, "created_paths": sorted(created_rel_paths)})
        if _cleanup_legacy_roots(project, legacy_root_rels):
            _remove_journal(project)
            _remove_backup_area(project)
        else:
            _write_journal(project, {"state": "cleanup_pending", **journal_base, **_journal_settings, "created_paths": sorted(created_rel_paths)})
        return _sort_scenes(new_scenes)
    except BaseException:
        try:
            _restore_bytes(_index_path(project), original_index)
            _restore_bytes(project.settings_path, original_settings)
            for path, data in original_meta.items():
                _restore_bytes(path, data)
            project.settings = original_settings_memory
        except OSError:
            pass
        for rel_path in sorted(created_rel_paths, key=lambda item: len(Path(item).parts), reverse=True):
            try:
                path = _safe_project_rel(project, rel_path)
                if path.is_dir():
                    shutil.rmtree(path, ignore_errors=True)
            except OSError:
                pass
        _remove_journal(project)
        _remove_backup_area(project)
        raise


def _load_from_meta(project: Project) -> list[dict[str, Any]]:
    root = _root_dir(project)
    if not root.is_dir():
        return []
    scenes: list[dict[str, Any]] = []
    for meta_path in sorted(root.glob("*/*_meta.json")):
        try:
            data = _read_json(meta_path)
            if isinstance(data, dict):
                scenes.append(_normalize_scene(data, legacy=True, project=project))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
    return _sort_scenes(scenes)


def _sort_scenes(scenes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted((_with_legacy_aliases(scene) for scene in scenes), key=lambda scene: (scene.get("created_at", ""), scene.get("title", ""), scene["id"]))


def list_scenes(project: Project) -> list[dict[str, Any]]:
    _recover_perspective_moves(project)
    recovered_staged = _recover_uuid_migration(project)
    index = _index_path(project)
    if not index.is_file():
        scenes = _load_from_meta(project)
        if recovered_staged or project.layout == LAYOUT_2:
            return _sort_scenes(scenes)
        return _migrate_scene2d_storage(project, scenes)
    try:
        data = _read_json(index)
    except (OSError, json.JSONDecodeError):
        scenes = _load_from_meta(project)
        if recovered_staged or project.layout == LAYOUT_2:
            return _sort_scenes(scenes)
        return _migrate_scene2d_storage(project, scenes)
    raw_scenes = data.get("scenes") if isinstance(data, dict) else data
    if not isinstance(raw_scenes, list):
        scenes = _load_from_meta(project)
        if recovered_staged or project.layout == LAYOUT_2:
            return _sort_scenes(scenes)
        return _migrate_scene2d_storage(project, scenes)
    scenes: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw_scenes:
        if not isinstance(item, dict):
            continue
        scene = _normalize_scene(item, legacy=True, project=project)
        if scene["id"] in seen:
            continue
        seen.add(scene["id"])
        scenes.append(scene)
    scenes = _sort_scenes(scenes)
    if recovered_staged or project.layout == LAYOUT_2:
        return scenes
    return _migrate_scene2d_storage(project, scenes)


def _save_scenes(project: Project, scenes: list[dict[str, Any]]) -> None:
    root = _root_dir(project)
    root.mkdir(parents=True, exist_ok=True)
    normalized = _sort_scenes([_normalize_scene(scene, project=project) for scene in scenes])
    project_manager._atomic_write_json(_index_path(project), {"scenes": normalized})
    for scene in normalized:
        scene_dir = _scene_dir(project, scene["id"])
        scene_dir.mkdir(parents=True, exist_ok=True)
        project_manager._atomic_write_json(_meta_path(project, scene["id"]), scene)


def _find_scene(project: Project, scene_id: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    scene_id = _validate_scene_id(scene_id)
    scenes = list_scenes(project)
    for scene in scenes:
        if scene["id"] == scene_id:
            return scene, scenes
    raise FileNotFoundError("Scene 2D not found.")


def _find_perspective(scene: dict[str, Any], perspective_id: str) -> dict[str, Any]:
    perspective_id = _validate_perspective_id(perspective_id)
    for perspective in scene.get("perspectives") or []:
        if perspective["id"] == perspective_id:
            return perspective
    raise FileNotFoundError("Scene 2D perspective not found.")


def _replace_scene(scenes: list[dict[str, Any]], scene: dict[str, Any]) -> list[dict[str, Any]]:
    return [scene if item["id"] == scene["id"] else item for item in scenes]


def _create_psd(project: Project, relative_path: str) -> None:
    width, height = project_manager.get_canvas_size(project)
    background = project_manager.get_canvas_color(project)
    create_blank_psd(_safe_rel_path(project, relative_path), width, height, background_color=background)


def create_scene(
    project: Project,
    title: str = "",
    description: str = "",
    location: str = "",
    time_of_day: str = "",
    environment_prompt: str = "",
    consistency_anchors: list[str] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    scenes = list_scenes(project)
    scene_id = new_uuid()
    perspective_id = new_uuid()
    timestamp = _now_iso()
    perspective = _normalize_perspective(
        {
            "id": perspective_id,
            "title": "Main perspective",
            "type": "psd",
            "source_file_path": _source_rel(scene_id, perspective_id, project),
            "preview_image_path": _preview_rel(scene_id, perspective_id, project),
            "created_at": timestamp,
            "updated_at": timestamp,
        },
        scene_id=scene_id,
    )
    scene = _normalize_scene(
        {
            "id": scene_id,
            "title": title.strip() or f"Scene {len(scenes) + 1}",
            "description": description,
            "location": location,
            "time_of_day": time_of_day,
            "environment_prompt": environment_prompt,
            "consistency_anchors": consistency_anchors or [],
            "linked_scene3d_id": "",
            "primary_perspective_id": perspective["id"],
            "created_at": timestamp,
            "updated_at": timestamp,
            "can_be_reference": True,
            "perspectives": [perspective],
        },
        project=project,
    )
    _scene_dir(project, scene_id).mkdir(parents=True, exist_ok=True)
    _create_psd(project, perspective["source_file_path"])
    scenes.append(scene)
    scenes = _sort_scenes(scenes)
    _save_scenes(project, scenes)
    return scene, scenes


def update_scene(project: Project, scene_id: str, changes: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    scene, scenes = _find_scene(project, scene_id)
    changed = False
    if "title" in changes and changes["title"] is not None:
        scene["title"] = str(changes["title"] or "").strip() or "Untitled Scene"
        changed = True
    if "description" in changes and changes["description"] is not None:
        scene["description"] = str(changes["description"] or "")
        changed = True
    if "location" in changes and changes["location"] is not None:
        scene["location"] = str(changes["location"] or "").strip()
        changed = True
    if "time_of_day" in changes and changes["time_of_day"] is not None:
        scene["time_of_day"] = str(changes["time_of_day"] or "").strip()
        changed = True
    if "environment_prompt" in changes and changes["environment_prompt"] is not None:
        scene["environment_prompt"] = str(changes["environment_prompt"] or "").strip()
        changed = True
    if "consistency_anchors" in changes and changes["consistency_anchors"] is not None:
        values = changes["consistency_anchors"] if isinstance(changes["consistency_anchors"], list) else []
        scene["consistency_anchors"] = list(dict.fromkeys(
            str(value or "").strip() for value in values if str(value or "").strip()
        ))
        changed = True
    if "linked_scene3d_id" in changes and changes["linked_scene3d_id"] is not None:
        scene["linked_scene3d_id"] = str(changes["linked_scene3d_id"] or "").strip()
        changed = True
    if "can_be_reference" in changes and changes["can_be_reference"] is not None:
        scene["can_be_reference"] = bool(changes["can_be_reference"])
        changed = True
    if changed:
        scene["updated_at"] = _now_iso()
        scenes = _replace_scene(scenes, _with_legacy_aliases(scene))
        _save_scenes(project, scenes)
    return _with_legacy_aliases(scene), scenes


def delete_scene(project: Project, scene_id: str) -> list[dict[str, Any]]:
    scene, scenes = _find_scene(project, scene_id)
    layout2_assets = {
        _safe_rel_path(project, relative)
        for perspective in scene.get("perspectives") or []
        for relative in (
            str(perspective.get("source_file_path") or ""),
            str(perspective.get("preview_image_path") or ""),
        )
        if relative
    } if project.layout == LAYOUT_2 else set()
    scenes = [item for item in scenes if item["id"] != scene["id"]]
    _save_scenes(project, scenes)
    scene_dir = _scene_dir(project, scene["id"])
    if scene_dir.is_dir():
        shutil.rmtree(scene_dir)
    for asset in layout2_assets:
        asset.unlink(missing_ok=True)
    links = project_manager.normalize_reference_links(project.settings.get("reference_links"))
    filtered = [link for link in links if str(link.get("source_scene2d_id") or "") != scene["id"]]
    if filtered != links:
        project.settings["reference_links"] = filtered
        project_manager.save_settings(project)
    return scenes


def clear_scene3d_links(project: Project, scene3d_id: str) -> int:
    scene3d_id = str(scene3d_id or "").strip()
    if not scene3d_id:
        return 0
    scenes = list_scenes(project)
    cleared = 0
    for scene in scenes:
        if str(scene.get("linked_scene3d_id") or "") == scene3d_id:
            scene["linked_scene3d_id"] = ""
            scene["updated_at"] = _now_iso()
            cleared += 1
        for perspective in scene.get("perspectives") or []:
            if str(perspective.get("linked_scene3d_id") or "") == scene3d_id:
                timestamp = _now_iso()
                perspective["linked_scene3d_id"] = ""
                perspective["updated_at"] = timestamp
                scene["updated_at"] = timestamp
                cleared += 1
    if cleared:
        _save_scenes(project, scenes)
    return cleared


def list_perspectives(project: Project, scene_id: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    scene, _scenes = _find_scene(project, scene_id)
    return scene, list(scene.get("perspectives") or [])


def create_perspective(
    project: Project,
    scene_id: str,
    *,
    title: str = "",
    perspective_type: str = "psd",
    linked_scene3d_id: str = "",
    linked_scene3d_view: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    if perspective_type != "psd":
        raise ValueError("Only blank PSD perspective creation is supported here.")
    scene, scenes = _find_scene(project, scene_id)
    perspective_id = new_uuid()
    timestamp = _now_iso()
    title = title.strip() or f"Perspective {len(scene.get('perspectives') or []) + 1}"
    source_rel = _source_rel(scene["id"], perspective_id, project)
    perspective = _normalize_perspective(
        {
            "id": perspective_id,
            "title": title,
            "type": "psd",
            "source_file_path": source_rel,
            "preview_image_path": _preview_rel(scene["id"], perspective_id, project),
            "linked_scene3d_id": linked_scene3d_id,
            "linked_scene3d_view": linked_scene3d_view,
            "created_at": timestamp,
            "updated_at": timestamp,
        },
        scene_id=scene["id"],
    )
    _create_psd(project, source_rel)
    scene["perspectives"].append(perspective)
    scene["updated_at"] = timestamp
    scenes = _replace_scene(scenes, _with_legacy_aliases(scene))
    _save_scenes(project, scenes)
    return _with_legacy_aliases(scene), perspective, scenes


def import_perspective(
    project: Project,
    scene_id: str,
    filename: str,
    data: bytes,
    *,
    title: str = "",
    linked_scene3d_id: str = "",
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    scene, scenes = _find_scene(project, scene_id)
    suffix = Path(filename or "").suffix.lower()
    if suffix not in PSD_EXTENSIONS | IMAGE_EXTENSIONS:
        raise ValueError("Only PSD, PNG, JPG, JPEG, or WEBP perspectives are supported.")
    perspective_id = new_uuid()
    timestamp = _now_iso()
    title = title.strip() or Path(filename or "").stem or f"Perspective {len(scene.get('perspectives') or []) + 1}"
    source_rel = (
        _source_rel(scene["id"], perspective_id, project)
        if suffix in PSD_EXTENSIONS
        else _image_source_rel(scene["id"], perspective_id, suffix, project)
    )
    _write_binary_atomic(_safe_rel_path(project, source_rel), bytes(data))
    perspective_type = "psd" if suffix in PSD_EXTENSIONS else "image"
    preview_rel = (
        source_rel
        if perspective_type == "image"
        else _preview_rel(scene["id"], perspective_id, project)
    )
    perspective = _normalize_perspective(
        {
            "id": perspective_id,
            "title": title,
            "type": perspective_type,
            "source_file_path": source_rel,
            "preview_image_path": preview_rel,
            "linked_scene3d_id": linked_scene3d_id,
            "created_at": timestamp,
            "updated_at": timestamp,
        },
        scene_id=scene["id"],
    )
    scene["perspectives"].append(perspective)
    scene["updated_at"] = timestamp
    scenes = _replace_scene(scenes, _with_legacy_aliases(scene))
    _save_scenes(project, scenes)
    return _with_legacy_aliases(scene), perspective, scenes


def reorder_perspectives(
    project: Project,
    scene_id: str,
    perspective_ids: list[str],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    scene, scenes = _find_scene(project, scene_id)
    ids = [_validate_perspective_id(item) for item in perspective_ids]
    current = scene.get("perspectives") or []
    current_ids = [item["id"] for item in current]
    if len(ids) != len(current_ids) or set(ids) != set(current_ids):
        raise ValueError("Perspective reorder must include every perspective in this Scene 2D group exactly once.")
    if len(ids) != len(set(ids)):
        raise ValueError("Perspective reorder contains duplicate ids.")

    by_id = {item["id"]: item for item in current}
    scene["perspectives"] = [by_id[item] for item in ids]
    scene["updated_at"] = _now_iso()
    scenes = _replace_scene(scenes, _with_legacy_aliases(scene))
    _save_scenes(project, scenes)
    return _with_legacy_aliases(scene), scenes


def update_perspective(
    project: Project,
    scene_id: str,
    perspective_id: str,
    changes: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    scene, scenes = _find_scene(project, scene_id)
    perspective = _find_perspective(scene, perspective_id)
    changed = False
    if "title" in changes and changes["title"] is not None:
        perspective["title"] = str(changes["title"] or "").strip() or "Untitled Perspective"
        changed = True
    if "linked_scene3d_id" in changes and changes["linked_scene3d_id"] is not None:
        perspective["linked_scene3d_id"] = str(changes["linked_scene3d_id"] or "").strip()
        changed = True
    if "linked_scene3d_view" in changes:
        view = changes.get("linked_scene3d_view")
        perspective["linked_scene3d_view"] = view if isinstance(view, dict) else None
        changed = True
    if changed:
        timestamp = _now_iso()
        perspective["updated_at"] = timestamp
        scene["updated_at"] = timestamp
        scenes = _replace_scene(scenes, _with_legacy_aliases(scene))
        _save_scenes(project, scenes)
    return _with_legacy_aliases(scene), perspective, scenes


def delete_perspective(project: Project, scene_id: str, perspective_id: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    scene, scenes = _find_scene(project, scene_id)
    perspective = _find_perspective(scene, perspective_id)
    layout2_assets = {
        _safe_rel_path(project, relative)
        for relative in (perspective["source_file_path"], perspective["preview_image_path"])
        if relative
    } if project.layout == LAYOUT_2 else set()
    scene["perspectives"] = [item for item in scene["perspectives"] if item["id"] != perspective["id"]]
    if scene.get("primary_perspective_id") == perspective["id"]:
        scene["primary_perspective_id"] = scene["perspectives"][0]["id"] if scene["perspectives"] else ""
    timestamp = _now_iso()
    scene["updated_at"] = timestamp
    perspective_dir = _safe_rel_path(project, perspective["source_file_path"]).parent
    scene_root = _scene_dir(project, scene["id"]).resolve()
    if perspective_dir.is_dir() and scene_root in perspective_dir.resolve().parents:
        shutil.rmtree(perspective_dir)
    for asset in layout2_assets:
        asset.unlink(missing_ok=True)
    links = project_manager.normalize_reference_links(project.settings.get("reference_links"))
    filtered = [
        link
        for link in links
        if not (
            str(link.get("source_scene2d_id") or "") == scene["id"]
            and str(link.get("source_scene2d_perspective_id") or "") == perspective["id"]
        )
    ]
    if filtered != links:
        project.settings["reference_links"] = filtered
        project_manager.save_settings(project)
    scenes = _replace_scene(scenes, _with_legacy_aliases(scene))
    _save_scenes(project, scenes)
    return _with_legacy_aliases(scene), scenes


def _duplicate_perspective_title(scene: dict[str, Any], source_title: str) -> str:
    source_stripped = str(source_title or "").strip()
    base = (source_stripped + " Copy") if source_stripped else "Untitled Perspective Copy"
    existing = {str(p.get("title") or "").strip() for p in (scene.get("perspectives") or [])}
    if base not in existing:
        return base
    for suffix in range(2, 10000):
        candidate = f"{base} {suffix}"
        if candidate not in existing:
            return candidate
    return f"{base} {uuid.uuid4().hex[:6]}"


def _verify_perspective_duplicate(
    project: Project,
    scene_id: str,
    source_perspective_id: str,
    duplicate_perspective_id: str,
    *,
    source_file_hash: bytes,
    source_preview_hash: bytes | None,
    original_primary_id: str,
    references_before: list[dict[str, Any]],
) -> None:
    # Read scenes2d.json directly — do not call list_scenes() which triggers migrations.
    index_path = _index_path(project)
    if not index_path.is_file():
        raise ValueError("Duplicate verify: scenes2d.json is missing after save.")
    try:
        index_data = _read_json(index_path)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Duplicate verify: scenes2d.json is malformed: {exc}") from exc
    if not isinstance(index_data, dict):
        raise ValueError("Duplicate verify: scenes2d.json is not a JSON object.")
    raw_scenes = index_data.get("scenes")
    if not isinstance(raw_scenes, list):
        raise ValueError("Duplicate verify: scenes2d.json has no valid scenes list.")
    index_scene_raw = next(
        (s for s in raw_scenes if isinstance(s, dict) and str(s.get("id") or "") == scene_id),
        None,
    )
    if index_scene_raw is None:
        raise ValueError(f"Duplicate verify: scene {scene_id!r} missing from scenes2d.json.")
    try:
        index_scene = _normalize_scene(index_scene_raw, legacy=True, project=project)
    except (ValueError, KeyError) as exc:
        raise ValueError(f"Duplicate verify: scenes2d.json scene is invalid: {exc}") from exc

    # Read and compare scene meta — failure is not suppressed.
    meta_path_v = _meta_path(project, scene_id)
    if not meta_path_v.is_file():
        raise ValueError(f"Duplicate verify: scene meta file missing: {meta_path_v}")
    try:
        meta_raw = _read_json(meta_path_v)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Duplicate verify: scene meta file is malformed: {exc}") from exc
    if not isinstance(meta_raw, dict):
        raise ValueError("Duplicate verify: scene meta file is not a JSON object.")
    try:
        meta_scene = _normalize_scene(meta_raw, legacy=True, project=project)
    except (ValueError, KeyError) as exc:
        raise ValueError(f"Duplicate verify: scene meta is invalid: {exc}") from exc
    if index_scene != meta_scene:
        raise ValueError("Duplicate verify: Scene meta disagrees with scenes2d.json.")

    # Work with the canonical (index) scene for all further checks.
    perspectives = index_scene.get("perspectives") or []
    ids = [p["id"] for p in perspectives]

    source_count = ids.count(source_perspective_id)
    dup_count = ids.count(duplicate_perspective_id)
    if source_count != 1:
        raise ValueError(f"Duplicate verify: source {source_perspective_id!r} count={source_count}.")
    if dup_count != 1:
        raise ValueError(f"Duplicate verify: duplicate {duplicate_perspective_id!r} count={dup_count}.")
    if source_perspective_id == duplicate_perspective_id:
        raise ValueError("Duplicate verify: source and duplicate IDs are the same.")

    source_idx = ids.index(source_perspective_id)
    dup_idx = ids.index(duplicate_perspective_id)
    if dup_idx != source_idx + 1:
        raise ValueError(f"Duplicate verify: duplicate at index {dup_idx}, expected {source_idx + 1}.")

    dup = perspectives[dup_idx]
    dup_source = _safe_rel_path(project, dup["source_file_path"])
    if not dup_source.is_file():
        raise ValueError(f"Duplicate verify: duplicate source file missing: {dup['source_file_path']!r}")

    expected_dir_fragment = f"{scene_id}/perspectives/{duplicate_perspective_id}/"
    if expected_dir_fragment not in str(dup.get("source_file_path") or "").replace("\\", "/"):
        raise ValueError("Duplicate verify: duplicate source path does not use the new UUID folder.")

    source_perspective = perspectives[source_idx]
    dup_type = dup.get("type") or "psd"
    if dup_type == "psd":
        if source_preview_hash is not None:
            dup_preview = _safe_rel_path(project, dup.get("preview_image_path") or "")
            if not dup_preview.is_file():
                raise ValueError("Duplicate verify: duplicate preview missing when source preview existed.")
        expected_preview_rel = _preview_rel(scene_id, duplicate_perspective_id)
        if str(dup.get("preview_image_path") or "") != expected_preview_rel:
            raise ValueError("Duplicate verify: PSD duplicate preview_image_path is not canonical.")
    elif dup_type == "image":
        if str(dup.get("source_file_path") or "") != str(dup.get("preview_image_path") or ""):
            raise ValueError("Duplicate verify: image duplicate preview path differs from source path.")

    if index_scene.get("primary_perspective_id") != original_primary_id:
        raise ValueError("Duplicate verify: primary_perspective_id changed during duplication.")
    if index_scene.get("primary_perspective_id") == duplicate_perspective_id:
        raise ValueError("Duplicate verify: primary was incorrectly changed to the duplicate.")

    source_file = _safe_rel_path(project, source_perspective["source_file_path"])
    if not source_file.is_file():
        raise ValueError("Duplicate verify: source perspective file is missing after duplication.")
    actual_source_hash = hashlib.sha256(source_file.read_bytes()).digest()
    if actual_source_hash != source_file_hash:
        raise ValueError("Duplicate verify: source perspective file was modified during duplication.")
    if source_preview_hash is not None:
        source_preview_file = _safe_rel_path(project, source_perspective.get("preview_image_path") or "")
        if not source_preview_file.is_file():
            raise ValueError("Duplicate verify: source preview disappeared during duplication.")
        actual_preview_hash = hashlib.sha256(source_preview_file.read_bytes()).digest()
        if actual_preview_hash != source_preview_hash:
            raise ValueError("Duplicate verify: source preview was modified during duplication.")

    references_after = project_manager.normalize_reference_links(project.settings.get("reference_links"))
    if references_after != references_before:
        raise ValueError("Duplicate verify: reference links changed during duplication.")


def _duplicate_perspective_layout2(
    project: Project,
    scene_id: str,
    perspective_id: str,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    scene, scenes = _find_scene(project, scene_id)
    source = _find_perspective(scene, perspective_id)
    source_file = _safe_rel_path(project, source["source_file_path"])
    if not source_file.is_file():
        raise FileNotFoundError(
            f"Source perspective file not found: {source['source_file_path']}"
        )

    new_id = new_uuid()
    source_type = str(source.get("type") or "psd")
    if source_type == "image":
        suffix = source_file.suffix.lower()
        new_source_rel = _image_source_rel(scene_id, new_id, suffix, project)
        new_preview_rel = new_source_rel
    else:
        new_source_rel = _source_rel(scene_id, new_id, project)
        new_preview_rel = _preview_rel(scene_id, new_id, project)

    source_preview_rel = str(source.get("preview_image_path") or "")
    source_preview = (
        _safe_rel_path(project, source_preview_rel)
        if source_preview_rel and source_preview_rel != source["source_file_path"]
        else None
    )
    new_source = _safe_rel_path(project, new_source_rel)
    new_preview = (
        _safe_rel_path(project, new_preview_rel)
        if new_preview_rel != new_source_rel
        else None
    )
    index_path = _index_path(project)
    meta_path = _meta_path(project, scene_id)
    index_bytes = _read_bytes_if_exists(index_path)
    meta_bytes = _read_bytes_if_exists(meta_path)
    original_scene = copy.deepcopy(scene)
    created: list[Path] = []
    timestamp = _now_iso()
    try:
        atomic_copy_file(source_file, new_source)
        created.append(new_source)
        if source_preview is not None and source_preview.is_file() and new_preview is not None:
            atomic_copy_file(source_preview, new_preview)
            created.append(new_preview)
        duplicate = _normalize_perspective(
            {
                "id": new_id,
                "title": _duplicate_perspective_title(
                    scene, str(source.get("title") or "")
                ),
                "type": source_type,
                "source_file_path": new_source_rel,
                "preview_image_path": new_preview_rel,
                "linked_scene3d_id": str(source.get("linked_scene3d_id") or ""),
                "linked_scene3d_view": copy.deepcopy(
                    source.get("linked_scene3d_view")
                ),
                "created_at": timestamp,
                "updated_at": timestamp,
            },
            scene_id=scene_id,
        )
        source_index = next(
            index
            for index, item in enumerate(scene["perspectives"])
            if item["id"] == perspective_id
        )
        scene["perspectives"].insert(source_index + 1, duplicate)
        scene["updated_at"] = timestamp
        scenes = _replace_scene(scenes, _with_legacy_aliases(scene))
        _save_scenes(project, scenes)

        verified_scenes = list_scenes(project)
        verified_scene = next(item for item in verified_scenes if item["id"] == scene_id)
        verified_duplicate = next(
            item
            for item in verified_scene.get("perspectives") or []
            if item["id"] == new_id
        )
        if verified_duplicate["source_file_path"] != new_source_rel:
            raise ValueError("Duplicate verify: source path was not preserved.")
        if new_source.read_bytes() != source_file.read_bytes():
            raise ValueError("Duplicate verify: copied source differs from original.")
        return _with_legacy_aliases(verified_scene), verified_duplicate, verified_scenes
    except BaseException:
        _restore_bytes(index_path, index_bytes)
        _restore_bytes(meta_path, meta_bytes)
        scene.clear()
        scene.update(original_scene)
        for path in created:
            path.unlink(missing_ok=True)
        raise


def duplicate_perspective(
    project: Project,
    scene_id: str,
    perspective_id: str,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    if project.layout == LAYOUT_2:
        return _duplicate_perspective_layout2(project, scene_id, perspective_id)

    scene, scenes = _find_scene(project, scene_id)
    source = _find_perspective(scene, perspective_id)

    source_file = _safe_rel_path(project, source["source_file_path"])
    if not source_file.is_file():
        raise FileNotFoundError(f"Source perspective file not found: {source['source_file_path']}")

    source_type = source.get("type") or "psd"
    source_preview_str = str(source.get("preview_image_path") or "")
    source_src_str = str(source.get("source_file_path") or "")
    preview_is_separate = source_preview_str != source_src_str
    source_preview_path = _safe_rel_path(project, source_preview_str) if preview_is_separate else source_file
    copy_preview = source_type == "psd" and preview_is_separate and source_preview_path.is_file()

    # Capture pre-operation state for verification and rollback.
    source_file_hash = hashlib.sha256(source_file.read_bytes()).digest()
    source_preview_hash: bytes | None = (
        hashlib.sha256(source_preview_path.read_bytes()).digest() if copy_preview else None
    )
    original_primary_id = str(scene.get("primary_perspective_id") or "")
    references_before = project_manager.normalize_reference_links(project.settings.get("reference_links"))

    new_id = new_uuid()
    timestamp = _now_iso()

    if source_type == "image":
        suffix = Path(source_src_str).suffix.lower()
        new_source_rel = _image_source_rel(scene_id, new_id, suffix)
        new_preview_rel = new_source_rel
    else:
        new_source_rel = _source_rel(scene_id, new_id)
        new_preview_rel = _preview_rel(scene_id, new_id)

    new_title = _duplicate_perspective_title(scene, source.get("title") or "")

    perspectives_parent = project_manager.resolve_project_child(
        project,
        SCENE2D_ROOT,
        scene_id,
        "perspectives",
    )
    operation_id = uuid.uuid4().hex
    staging_dir = project_manager.resolve_project_child(
        project,
        SCENE2D_ROOT,
        scene_id,
        "perspectives",
        f".duplicate-{operation_id}",
    )
    new_dir = project_manager.resolve_project_child(
        project,
        SCENE2D_ROOT,
        scene_id,
        "perspectives",
        new_id,
    )

    index_path = _index_path(project)
    meta_path = _meta_path(project, scene_id)
    index_bytes = index_path.read_bytes() if index_path.is_file() else None
    meta_bytes = meta_path.read_bytes() if meta_path.is_file() else None

    try:
        staging_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(
            source_file,
            project_manager.resolve_project_child(
                project,
                SCENE2D_ROOT,
                scene_id,
                "perspectives",
                f".duplicate-{operation_id}",
                Path(new_source_rel).name,
            ),
        )
        if copy_preview:
            shutil.copy2(
                source_preview_path,
                project_manager.resolve_project_child(
                    project,
                    SCENE2D_ROOT,
                    scene_id,
                    "perspectives",
                    f".duplicate-{operation_id}",
                    "preview.png",
                ),
            )

        staging_dir.rename(new_dir)

        duplicate = _normalize_perspective(
            {
                "id": new_id,
                "title": new_title,
                "type": source_type,
                "source_file_path": new_source_rel,
                "preview_image_path": new_preview_rel,
                "linked_scene3d_id": str(source.get("linked_scene3d_id") or "").strip(),
                "linked_scene3d_view": copy.deepcopy(source.get("linked_scene3d_view")),
                "created_at": timestamp,
                "updated_at": timestamp,
            },
            scene_id=scene_id,
        )

        source_index = next(i for i, p in enumerate(scene["perspectives"]) if p["id"] == perspective_id)
        scene["perspectives"].insert(source_index + 1, duplicate)
        scene["updated_at"] = timestamp
        scenes = _replace_scene(scenes, _with_legacy_aliases(scene))
        _save_scenes(project, scenes)
        _verify_perspective_duplicate(
            project,
            scene_id,
            perspective_id,
            new_id,
            source_file_hash=source_file_hash,
            source_preview_hash=source_preview_hash,
            original_primary_id=original_primary_id,
            references_before=references_before,
        )

    except BaseException as operation_error:
        rollback_result = _rollback_perspective_duplicate(
            index_path=index_path,
            index_bytes=index_bytes,
            meta_path=meta_path,
            meta_bytes=meta_bytes,
            new_dir=new_dir,
            staging_dir=staging_dir,
        )
        if not rollback_result.metadata_verified:
            raise RuntimeError(
                "Scene 2D Perspective duplication failed and automatic rollback "
                "could not be verified. Duplicate recovery files were preserved. "
                f"Original error: {operation_error!r}"
            ) from operation_error
        if not rollback_result.duplicate_files_removed:
            raise RuntimeError(
                "Scene 2D Perspective duplication failed. Metadata was restored "
                "but the duplicate directory could not be removed. "
                f"Original error: {operation_error!r}"
            ) from operation_error
        # Internal copy/save/verification failures are not user-input errors.
        if isinstance(operation_error, ValueError):
            raise RuntimeError(
                f"Scene 2D Perspective duplication failed: {operation_error}"
            ) from operation_error
        raise

    # Re-read from disk after successful save+verify to return canonical state.
    verified_scenes = list_scenes(project)
    verified_scene = next(s for s in verified_scenes if s["id"] == scene_id)
    verified_duplicate = next(p for p in (verified_scene.get("perspectives") or []) if p["id"] == new_id)
    return _with_legacy_aliases(verified_scene), verified_duplicate, verified_scenes


def _move_perspective_metadata_only(
    project: Project,
    scenes: list[dict[str, Any]],
    source_scene: dict[str, Any],
    target_scene: dict[str, Any],
    perspective: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    """Move Layout 2 ownership without renaming its UUID-addressed assets."""
    index_path = _index_path(project)
    source_meta = _meta_path(project, source_scene["id"])
    target_meta = _meta_path(project, target_scene["id"])
    settings_path = project.settings_path
    originals = {
        path: _read_bytes_if_exists(path)
        for path in (index_path, source_meta, target_meta, settings_path)
    }
    settings_memory = copy.deepcopy(project.settings)
    original_source = copy.deepcopy(source_scene)
    original_target = copy.deepcopy(target_scene)
    original_perspective = copy.deepcopy(perspective)
    try:
        source_scene["perspectives"] = [
            item
            for item in source_scene.get("perspectives", [])
            if item["id"] != perspective["id"]
        ]
        target_scene.setdefault("perspectives", []).append(perspective)
        timestamp = _now_iso()
        perspective["updated_at"] = timestamp
        source_scene["updated_at"] = timestamp
        target_scene["updated_at"] = timestamp
        if source_scene.get("primary_perspective_id") == perspective["id"]:
            source_scene["primary_perspective_id"] = (
                source_scene["perspectives"][0]["id"]
                if source_scene["perspectives"]
                else ""
            )
        if not target_scene.get("primary_perspective_id"):
            target_scene["primary_perspective_id"] = perspective["id"]

        links = project_manager.normalize_reference_links(
            project.settings.get("reference_links")
        )
        changed_links = False
        for link in links:
            if (
                str(link.get("source_scene2d_perspective_id") or "")
                == perspective["id"]
                and str(link.get("source_scene2d_id") or "")
                in {"", source_scene["id"]}
            ):
                link["source_scene2d_id"] = target_scene["id"]
                link["source_scene2d_perspective_id"] = perspective["id"]
                changed_links = True
        if changed_links:
            project.settings["reference_links"] = links
            project_manager.save_settings(project)

        scenes = _replace_scene(scenes, _with_legacy_aliases(source_scene))
        scenes = _replace_scene(scenes, _with_legacy_aliases(target_scene))
        _save_scenes(project, scenes)
    except BaseException:
        rollback_errors: list[BaseException] = []
        for path, data in originals.items():
            try:
                _restore_bytes(path, data)
            except BaseException as rollback_error:
                rollback_errors.append(rollback_error)
        project.settings = settings_memory
        source_scene.clear()
        source_scene.update(original_source)
        target_scene.clear()
        target_scene.update(original_target)
        perspective.clear()
        perspective.update(original_perspective)
        if rollback_errors:
            raise RuntimeError(
                "Layout 2 Scene 2D move failed and metadata rollback was incomplete."
            ) from rollback_errors[0]
        raise
    return (
        _with_legacy_aliases(source_scene),
        _with_legacy_aliases(target_scene),
        perspective,
        scenes,
    )


def move_perspective(
    project: Project,
    scene_id: str,
    perspective_id: str,
    target_scene_id: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    source_scene_id = _validate_scene_id(scene_id)
    target_scene_id = _validate_scene_id(target_scene_id)
    if source_scene_id == target_scene_id:
        raise ValueError("Perspective is already in that Scene 2D group.")

    scenes = list_scenes(project)
    source_scene = next((scene for scene in scenes if scene["id"] == source_scene_id), None)
    target_scene = next((scene for scene in scenes if scene["id"] == target_scene_id), None)
    if source_scene is None or target_scene is None:
        raise FileNotFoundError("Scene 2D not found.")

    perspective = _find_perspective(source_scene, perspective_id)
    if project.layout == LAYOUT_2:
        return _move_perspective_metadata_only(
            project,
            scenes,
            source_scene,
            target_scene,
            perspective,
        )
    source_dir = _safe_rel_path(project, perspective["source_file_path"]).parent
    target_dir = project_manager.resolve_project_child(
        project,
        SCENE2D_ROOT,
        target_scene["id"],
        "perspectives",
        perspective["id"],
    )
    if not source_dir.is_dir():
        raise FileNotFoundError("Scene 2D perspective folder not found.")
    if target_dir.exists():
        raise ValueError("Target Scene 2D already has files for this perspective.")

    suffix = Path(str(perspective.get("source_file_path") or "")).suffix.lower()
    if perspective.get("type") == "image":
        expected_source = _image_source_rel(target_scene["id"], perspective["id"], suffix)
        expected_preview = expected_source
    else:
        expected_source = _source_rel(target_scene["id"], perspective["id"])
        expected_preview = _preview_rel(target_scene["id"], perspective["id"])

    links = project_manager.normalize_reference_links(project.settings.get("reference_links"))
    expected_reference_links: list[dict[str, Any]] = []
    original_reference_links: list[dict[str, Any]] = []
    for link in links:
        link_scene_id = str(link.get("source_scene2d_id") or "")
        link_perspective_id = str(link.get("source_scene2d_perspective_id") or "")
        if link_perspective_id == perspective["id"] and link_scene_id in {"", source_scene["id"]}:
            expected_reference_links.append({"id": str(link.get("id") or "")})
            original_reference_links.append(
                {
                    "id": str(link.get("id") or ""),
                    "source_scene2d_id": str(link.get("source_scene2d_id") or ""),
                    "source_scene2d_perspective_id": str(link.get("source_scene2d_perspective_id") or ""),
                    "path": str(link.get("path") or ""),
                }
            )

    tx_dir = project_manager.resolve_project_child(
        project,
        SCENE2D_ROOT,
        PERSPECTIVE_MOVE_ROOT,
        uuid.uuid4().hex,
    )
    source_file_path = _safe_rel_path(project, perspective["source_file_path"])
    preview_file_path = _safe_rel_path(project, perspective["preview_image_path"])
    operation_id = tx_dir.name
    journal_base = {
        "operation_id": operation_id,
        "state": "prepared",
        "source_scene_id": source_scene["id"],
        "target_scene_id": target_scene["id"],
        "perspective_id": perspective["id"],
        "source_dir": _project_rel(project, source_dir),
        "target_dir": _project_rel(project, target_dir),
        "target_preexisted": False,
        "source_existed_before": source_file_path.is_file(),
        "preview_existed_before": preview_file_path.is_file(),
        "original_source_file_path": perspective["source_file_path"],
        "original_preview_image_path": perspective["preview_image_path"],
        "expected_source_file_path": expected_source,
        "expected_preview_image_path": expected_preview,
        "original_reference_links": original_reference_links,
        "expected_reference_links": expected_reference_links,
        "started_at": _now_iso(),
    }

    try:
        original_files = _backup_move_metadata(project, tx_dir, source_scene["id"], target_scene["id"])
        journal_base = {**journal_base, "original_files": original_files}
        _write_move_journal(tx_dir, journal_base, project=project)
        target_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source_dir), str(target_dir))
        _write_move_journal(
            tx_dir,
            {**journal_base, "state": "files_moved"},
            project=project,
        )

        source_scene["perspectives"] = [
            item for item in source_scene.get("perspectives", []) if item["id"] != perspective["id"]
        ]
        target_scene.setdefault("perspectives", []).append(perspective)

        perspective["source_file_path"] = expected_source
        perspective["preview_image_path"] = expected_preview

        timestamp = _now_iso()
        perspective["updated_at"] = timestamp
        source_scene["updated_at"] = timestamp
        target_scene["updated_at"] = timestamp
        if source_scene.get("primary_perspective_id") == perspective["id"]:
            source_scene["primary_perspective_id"] = source_scene["perspectives"][0]["id"] if source_scene["perspectives"] else ""
        if not target_scene.get("primary_perspective_id"):
            target_scene["primary_perspective_id"] = perspective["id"]

        changed_links = False
        for link in links:
            link_scene_id = str(link.get("source_scene2d_id") or "")
            link_perspective_id = str(link.get("source_scene2d_perspective_id") or "")
            if link_perspective_id == perspective["id"] and link_scene_id in {"", source_scene["id"]}:
                link["source_scene2d_id"] = target_scene["id"]
                link["source_scene2d_perspective_id"] = perspective["id"]
                link["path"] = expected_preview
                changed_links = True
        _write_move_journal(
            tx_dir,
            {**journal_base, "state": "metadata_committing"},
            project=project,
        )
        if changed_links:
            project.settings["reference_links"] = project_manager.normalize_reference_links(links)
            project_manager.save_settings(project)

        scenes = _replace_scene(scenes, _with_legacy_aliases(source_scene))
        scenes = _replace_scene(scenes, _with_legacy_aliases(target_scene))
        _save_scenes(project, scenes)
        final_journal = {**journal_base, "state": "metadata_committed"}
        _verify_perspective_move_commit(project, final_journal)
        _write_move_journal(tx_dir, final_journal, project=project)
        _write_move_journal(
            tx_dir,
            {**journal_base, "state": "verified"},
            project=project,
        )
        _cleanup_move_tx(tx_dir)
    except BaseException as operation_error:
        journal = {**journal_base}
        try:
            if _move_journal_path(tx_dir, project=project).is_file():
                loaded = _read_json(_move_journal_path(tx_dir, project=project))
                if isinstance(loaded, dict):
                    journal = loaded
            _rollback_perspective_move(project, tx_dir, journal)
        except BaseException as rollback_error:
            LOGGER.error(
                "Perspective move failed before rollback also failed.",
                exc_info=(type(operation_error), operation_error, operation_error.__traceback__),
            )
            raise RuntimeError(
                "Perspective move failed and automatic rollback was incomplete. "
                "Recovery data has been preserved. Restart Storyboarder to retry recovery."
            ) from rollback_error
        raise operation_error
    return _with_legacy_aliases(source_scene), _with_legacy_aliases(target_scene), perspective, scenes


def set_primary_perspective(project: Project, scene_id: str, perspective_id: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    scene, scenes = _find_scene(project, scene_id)
    _find_perspective(scene, perspective_id)
    scene["primary_perspective_id"] = perspective_id
    scene["updated_at"] = _now_iso()
    scenes = _replace_scene(scenes, _with_legacy_aliases(scene))
    _save_scenes(project, scenes)
    return _with_legacy_aliases(scene), scenes


def _ensure_perspective_source(project: Project, perspective: dict[str, Any]) -> bool:
    source = _safe_rel_path(project, perspective["source_file_path"])
    if source.is_file():
        return False
    if project.layout == LAYOUT_2:
        raise FileNotFoundError(
            f"Scene 2D perspective file not found: {perspective['source_file_path']}"
        )
    if perspective["type"] == "psd":
        _create_psd(project, perspective["source_file_path"])
        return True
    raise FileNotFoundError(f"Scene 2D perspective file not found: {perspective['source_file_path']}")


def open_scene(project: Project, scene_id: str) -> tuple[dict[str, Any], str, str]:
    scene, _scenes = _find_scene(project, scene_id)
    primary = _primary_perspective(scene)
    if not primary:
        raise FileNotFoundError("Scene 2D has no perspective to open.")
    return open_perspective(project, scene_id, primary["id"])


def open_perspective(project: Project, scene_id: str, perspective_id: str) -> tuple[dict[str, Any], str, str]:
    scene, scenes = _find_scene(project, scene_id)
    perspective = _find_perspective(scene, perspective_id)
    recreated = _ensure_perspective_source(project, perspective)
    if recreated:
        timestamp = _now_iso()
        perspective["updated_at"] = timestamp
        scene["updated_at"] = timestamp
        scenes = _replace_scene(scenes, _with_legacy_aliases(scene))
        _save_scenes(project, scenes)
    opened = project_manager.open_project_file(
        project,
        perspective["source_file_path"],
        project.settings.get("photoshop_path", "") if perspective["type"] == "psd" else "",
    )
    return _with_legacy_aliases(scene), str(opened), perspective["source_file_path"]


def _preview_exists(project: Project, perspective: dict[str, Any]) -> bool:
    return _safe_rel_path(project, perspective["preview_image_path"]).is_file()


def refresh_preview(project: Project, scene_id: str) -> tuple[dict[str, Any], bool, str]:
    scene, _scenes = _find_scene(project, scene_id)
    primary = _primary_perspective(scene)
    if not primary:
        raise FileNotFoundError("Scene 2D has no perspective.")
    scene, perspective, _scenes = refresh_perspective_preview(project, scene_id, primary["id"])
    exists = _preview_exists(project, perspective)
    return scene, exists, ("Scene 2D preview refreshed." if exists else "No Scene 2D preview exists yet.")


def refresh_perspective_preview(
    project: Project,
    scene_id: str,
    perspective_id: str,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    scene, scenes = _find_scene(project, scene_id)
    perspective = _find_perspective(scene, perspective_id)
    if perspective["type"] == "image" and _safe_rel_path(project, perspective["source_file_path"]).is_file():
        perspective["preview_image_path"] = perspective["source_file_path"]
    if _preview_exists(project, perspective):
        timestamp = _now_iso()
        perspective["updated_at"] = timestamp
        scene["updated_at"] = timestamp
        scenes = _replace_scene(scenes, _with_legacy_aliases(scene))
        _save_scenes(project, scenes)
    return _with_legacy_aliases(scene), perspective, scenes


def preview_meta(project: Project, scene_id: str) -> dict[str, str]:
    scene, _scenes = _find_scene(project, scene_id)
    primary = _primary_perspective(scene)
    if not primary:
        raise FileNotFoundError("Scene 2D has no perspective.")
    return perspective_preview_meta(project, scene_id, primary["id"])


def perspective_preview_meta(project: Project, scene_id: str, perspective_id: str) -> dict[str, str]:
    scene, _scenes = _find_scene(project, scene_id)
    perspective = _find_perspective(scene, perspective_id)
    preview = _safe_rel_path(project, perspective["preview_image_path"])
    if not preview.is_file():
        raise FileNotFoundError("Scene 2D preview not found.")
    media_type = "image/png"
    if preview.suffix.lower() in {".jpg", ".jpeg"}:
        media_type = "image/jpeg"
    elif preview.suffix.lower() == ".webp":
        media_type = "image/webp"
    return {"path": str(preview), "media_type": media_type, "filename": preview.name}


def _scene_reference_id(scene_id: str, perspective_id: str, links: list[dict[str, Any]]) -> str:
    used = {str(link.get("id") or "") for link in links}
    candidate = f"ref_{scene_id}_{perspective_id}"
    if candidate not in used:
        return candidate
    for index in range(2, 1000):
        candidate = f"ref_{scene_id}_{perspective_id}_{index}"
        if candidate not in used:
            return candidate
    return f"ref_{scene_id}_{perspective_id}_{uuid.uuid4().hex[:8]}"


def add_to_references(project: Project, scene_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    scene, _scenes = _find_scene(project, scene_id)
    primary = _primary_perspective(scene)
    if not primary:
        raise FileNotFoundError("Scene 2D has no perspective.")
    return add_perspective_to_references(project, scene_id, primary["id"])


def add_perspective_to_references(
    project: Project,
    scene_id: str,
    perspective_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    scene, _scenes = _find_scene(project, scene_id)
    perspective = _find_perspective(scene, perspective_id)
    if not scene.get("can_be_reference", True):
        raise ValueError("Scene 2D cannot be added as a reference.")
    if not _preview_exists(project, perspective):
        raise FileNotFoundError("Scene 2D preview not found.")
    links = project_manager.normalize_reference_links(project.settings.get("reference_links"))
    entry = {
        "id": _scene_reference_id(scene["id"], perspective["id"], links),
        "title": perspective["title"] or scene["title"],
        "type": "scene2d",
        "path": perspective["preview_image_path"],
        "source_scene2d_id": scene["id"],
        "source_scene2d_perspective_id": perspective["id"],
    }
    links.append(entry)
    project.settings["reference_links"] = project_manager.normalize_reference_links(links)
    project_manager.save_settings(project)
    return entry, _with_legacy_aliases(scene)
