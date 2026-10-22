"""Project-level Scene 2D groups and perspectives."""
from __future__ import annotations

import copy
import json
import logging
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import project_document, project_manager
from .file_transactions import (
    atomic_copy_file,
    quarantined_deletions,
    rollback_paths,
)
from .image_utils import create_blank_psd
from .models import Project
from .project_layout import (
    scene2d_asset_relative,
    scene2d_metadata_path,
)

SCENE2D_INDEX = "scenes2d.json"
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
PSD_EXTENSIONS = {".psd"}
LOGGER = logging.getLogger(__name__)


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


def _scene_dir(project: Project, scene_id: str) -> Path:
    _validate_scene_id(scene_id)
    return scene2d_metadata_path(project, scene_id)


def _meta_path(project: Project, scene_id: str) -> Path:
    return scene2d_metadata_path(project, scene_id, f"{scene_id}_meta.json")


def _source_rel(scene_id: str, perspective_id: str, project: Project) -> str:
    return scene2d_asset_relative(project, scene_id, perspective_id, "source_psd")


def _preview_rel(scene_id: str, perspective_id: str, project: Project) -> str:
    return scene2d_asset_relative(project, scene_id, perspective_id, "preview")


def _image_source_rel(
    scene_id: str,
    perspective_id: str,
    suffix: str,
    project: Project,
) -> str:
    suffix = suffix if suffix in IMAGE_EXTENSIONS else ".png"
    return scene2d_asset_relative(
        project, scene_id, perspective_id, "source_image", suffix
    )


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
    project: Project,
) -> dict[str, Any]:
    perspective_id = _validate_perspective_id(str(raw.get("id") or "").strip())
    title = str(raw.get("title") or "").strip() or "Untitled Perspective"
    source_value = raw.get("source_file_path") or _source_rel(
        scene_id, perspective_id, project
    )
    if not isinstance(source_value, str):
        raise ValueError("Scene 2D source path must be a string.")
    source_path = _safe_rel_path(project, source_value)
    if source_path.suffix.lower() not in PSD_EXTENSIONS | IMAGE_EXTENSIONS:
        raise ValueError("Scene 2D source path has an invalid file type.")
    source = project_manager._normalize_rel_path(str(source_value).strip())
    perspective_type = str(raw.get("type") or "").strip().lower()
    if perspective_type not in {"psd", "image"}:
        perspective_type = "psd" if Path(source).suffix.lower() == ".psd" else "image"
    preview_value = raw.get("preview_image_path") or ""
    if preview_value:
        if not isinstance(preview_value, str):
            raise ValueError("Scene 2D preview path must be a string.")
        preview_path = _safe_rel_path(project, preview_value)
        allowed_preview_suffixes = (
            IMAGE_EXTENSIONS if perspective_type == "image" else {".png"}
        )
        if preview_path.suffix.lower() not in allowed_preview_suffixes:
            raise ValueError("Scene 2D preview path has an invalid file type.")
    preview = project_manager._normalize_rel_path(str(preview_value).strip())
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
    *,
    project: Project,
) -> dict[str, Any]:
    scene_id = _validate_scene_id(raw.get("id", ""))
    title = str(raw.get("title") or "").strip() or "Untitled Scene"
    created_at = str(raw.get("created_at") or "").strip() or _now_iso()
    updated_at = str(raw.get("updated_at") or created_at).strip() or created_at
    raw_perspectives = raw.get("perspectives")
    perspectives = [
        _normalize_perspective(item, scene_id=scene_id, project=project)
        for item in (raw_perspectives if isinstance(raw_perspectives, list) else [])
        if isinstance(item, dict)
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


def _sort_scenes(scenes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted((_with_legacy_aliases(scene) for scene in scenes), key=lambda scene: (scene.get("created_at", ""), scene.get("title", ""), scene["id"]))


def list_scenes(project: Project, *, read_only: bool = False) -> list[dict[str, Any]]:
    del read_only  # Listing never writes; kept for callers that state intent.
    index = _index_path(project)
    if not index.is_file():
        raise FileNotFoundError("Scene 2D index is missing.")
    try:
        data = _read_json(index)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Scene 2D index is unreadable.") from exc
    if not isinstance(data, dict) or not isinstance(data.get("scenes"), list):
        raise ValueError("Scene 2D index must contain a scenes list.")
    scenes: list[dict[str, Any]] = []
    scene_ids: set[str] = set()
    perspective_ids: set[str] = set()
    for item in data["scenes"]:
        if not isinstance(item, dict):
            raise ValueError("Scene 2D index contains an invalid entry.")
        raw_perspectives = item.get("perspectives")
        if not isinstance(raw_perspectives, list) or any(
            not isinstance(perspective, dict) for perspective in raw_perspectives
        ):
            raise ValueError("Scene 2D perspectives must be a list of objects.")
        raw_perspective_ids = [
            str(perspective.get("id") or "") for perspective in raw_perspectives
        ]
        if len(raw_perspective_ids) != len(set(raw_perspective_ids)):
            raise ValueError("Scene 2D contains duplicate perspective IDs.")
        scene = _normalize_scene(item, project=project)
        if scene["id"] in scene_ids:
            raise ValueError("Scene 2D index contains duplicate scene IDs.")
        if perspective_ids.intersection(raw_perspective_ids):
            raise ValueError("Scene 2D contains duplicate perspective IDs.")
        perspective_ids.update(raw_perspective_ids)
        primary_id = str(item.get("primary_perspective_id") or "")
        if (raw_perspectives and not primary_id) or (
            primary_id and primary_id not in set(raw_perspective_ids)
        ):
            raise ValueError("Scene 2D primary perspective is invalid.")
        meta = _meta_path(project, scene["id"])
        if not meta.is_file():
            raise FileNotFoundError(
                f"Scene 2D mirror metadata is missing: {scene['id']}."
            )
        try:
            meta_payload = _read_json(meta)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Scene 2D mirror metadata is unreadable.") from exc
        if meta_payload != item:
            raise ValueError("Scene 2D index and mirror metadata differ.")
        _normalize_scene(meta_payload, project=project)
        scene_ids.add(scene["id"])
        scenes.append(scene)
    return _sort_scenes(scenes)


def _save_scenes(project: Project, scenes: list[dict[str, Any]]) -> None:
    root = _root_dir(project)
    root.mkdir(parents=True, exist_ok=True)
    normalized = _sort_scenes([_normalize_scene(scene, project=project) for scene in scenes])
    project_manager._atomic_write_json(_index_path(project), {"scenes": normalized})
    for scene in normalized:
        scene_dir = _scene_dir(project, scene["id"])
        scene_dir.mkdir(parents=True, exist_ok=True)
        project_manager._atomic_write_json(_meta_path(project, scene["id"]), scene)


def initialize_metadata(project: Project) -> None:
    """Create and validate the canonical empty Scene 2D index."""
    if _index_path(project).exists():
        list_scenes(project)
        return
    _save_scenes(project, [])


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
    target = _safe_rel_path(project, relative_path)
    project_document.enlist_mutation_paths(project.project_root, (target,))
    width, height = project_manager.get_canvas_size(project)
    background = project_manager.get_canvas_color(project)
    create_blank_psd(target, width, height, background_color=background)


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
        project=project,
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
    assets = {
        _safe_rel_path(project, relative)
        for perspective in scene.get("perspectives") or []
        for relative in (
            str(perspective.get("source_file_path") or ""),
            str(perspective.get("preview_image_path") or ""),
        )
        if relative
    }
    assets.add(_scene_dir(project, scene["id"]))
    project_document.enlist_mutation_paths(
        project.project_root,
        assets,
    )
    remaining = [item for item in scenes if item["id"] != scene["id"]]
    links = project_manager.normalize_reference_links(
        project.settings.get("reference_links")
    )
    filtered = [
        link
        for link in links
        if str(link.get("source_scene2d_id") or "") != scene["id"]
    ]
    settings_before = copy.deepcopy(project.settings)
    try:
        with rollback_paths((_root_dir(project), project.settings_path)):
            with quarantined_deletions(project.project_root, assets):
                _save_scenes(project, remaining)
                if filtered != links:
                    project.settings["reference_links"] = filtered
                    project_manager.save_settings(project)
    except BaseException:
        project.settings = settings_before
        raise
    return remaining


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
        project=project,
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
    source_path = _safe_rel_path(project, source_rel)
    project_document.enlist_mutation_paths(
        project.project_root,
        (source_path,),
    )
    _write_binary_atomic(source_path, bytes(data))
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
        project=project,
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


def delete_perspective(
    project: Project,
    scene_id: str,
    perspective_id: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    scene, scenes = _find_scene(project, scene_id)
    perspective = _find_perspective(scene, perspective_id)
    assets = {
        _safe_rel_path(project, relative)
        for relative in (
            str(perspective.get("source_file_path") or ""),
            str(perspective.get("preview_image_path") or ""),
        )
        if relative
    }
    project_document.enlist_mutation_paths(
        project.project_root,
        assets,
    )
    scene["perspectives"] = [
        item for item in scene["perspectives"] if item["id"] != perspective["id"]
    ]
    if scene.get("primary_perspective_id") == perspective["id"]:
        scene["primary_perspective_id"] = (
            scene["perspectives"][0]["id"] if scene["perspectives"] else ""
        )
    scene["updated_at"] = _now_iso()
    scenes = _replace_scene(scenes, _with_legacy_aliases(scene))
    links = project_manager.normalize_reference_links(
        project.settings.get("reference_links")
    )
    filtered = [
        link
        for link in links
        if not (
            str(link.get("source_scene2d_id") or "") == scene["id"]
            and str(link.get("source_scene2d_perspective_id") or "")
            == perspective["id"]
        )
    ]
    settings_before = copy.deepcopy(project.settings)
    try:
        with rollback_paths((_root_dir(project), project.settings_path)):
            with quarantined_deletions(project.project_root, assets):
                _save_scenes(project, scenes)
                if filtered != links:
                    project.settings["reference_links"] = filtered
                    project_manager.save_settings(project)
    except BaseException:
        project.settings = settings_before
        raise
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


def duplicate_perspective(
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
    project_document.enlist_mutation_paths(
        project.project_root,
        tuple(
            path for path in (new_source, new_preview) if path is not None
        ),
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
            project=project,
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

        # Internal copy/save/verification failures are not user-input errors:
        # surface them as RuntimeError so the API reports a server fault.
        try:
            verified_scenes = list_scenes(project)
            verified_scene = next(item for item in verified_scenes if item["id"] == scene_id)
            verified_duplicate = next(
                item
                for item in verified_scene.get("perspectives") or []
                if item["id"] == new_id
            )
        except (ValueError, StopIteration) as exc:
            raise RuntimeError(f"Duplicate verify: saved Scene 2D metadata is inconsistent: {exc}") from exc
        if verified_duplicate["source_file_path"] != new_source_rel:
            raise RuntimeError("Duplicate verify: source path was not preserved.")
        if new_source.read_bytes() != source_file.read_bytes():
            raise RuntimeError("Duplicate verify: copied source differs from original.")
        return _with_legacy_aliases(verified_scene), verified_duplicate, verified_scenes
    except BaseException:
        _restore_bytes(index_path, index_bytes)
        _restore_bytes(meta_path, meta_bytes)
        scene.clear()
        scene.update(original_scene)
        for path in created:
            path.unlink(missing_ok=True)
        raise


def _move_perspective_metadata_only(
    project: Project,
    scenes: list[dict[str, Any]],
    source_scene: dict[str, Any],
    target_scene: dict[str, Any],
    perspective: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    """Move ownership without renaming its UUID-addressed assets."""
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
                "Scene 2D move failed and metadata rollback was incomplete."
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
    return _move_perspective_metadata_only(
        project,
        scenes,
        source_scene,
        target_scene,
        perspective,
    )


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
