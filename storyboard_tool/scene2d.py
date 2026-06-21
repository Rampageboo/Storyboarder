"""Project-level Scene 2D groups and perspectives."""
from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import project_manager
from .image_utils import create_blank_psd
from .models import Project

SCENE2D_ROOT = "scenes2d"
SCENE2D_INDEX = "scenes2d.json"
LEGACY_SCENE_ID_RE = re.compile(r"^scene_(\d{3,})$")
LEGACY_PERSPECTIVE_ID_RE = re.compile(r"^persp_(\d{3,})$")
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
PSD_EXTENSIONS = {".psd"}


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
    return project.root_path / SCENE2D_ROOT


def _index_path(project: Project) -> Path:
    return _root_dir(project) / SCENE2D_INDEX


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
    return _root_dir(project) / scene_id


def _meta_path(project: Project, scene_id: str) -> Path:
    return _scene_dir(project, scene_id) / f"{scene_id}_meta.json"


def _source_rel(scene_id: str, perspective_id: str) -> str:
    return f"{SCENE2D_ROOT}/{scene_id}/perspectives/{perspective_id}/source.psd"


def _preview_rel(scene_id: str, perspective_id: str) -> str:
    return f"{SCENE2D_ROOT}/{scene_id}/perspectives/{perspective_id}/preview.png"


def _image_source_rel(scene_id: str, perspective_id: str, suffix: str) -> str:
    suffix = suffix if suffix in IMAGE_EXTENSIONS else ".png"
    return f"{SCENE2D_ROOT}/{scene_id}/perspectives/{perspective_id}/source{suffix}"


def _safe_rel_path(project: Project, relative_path: str) -> Path:
    rel = project_manager._normalize_rel_path(str(relative_path or "").strip())
    if not rel:
        raise ValueError("Scene 2D path is empty.")
    resolved = (project.root_path / rel).resolve()
    root = project.root_path.resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError("Scene 2D path escapes the project.")
    return resolved


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
) -> dict[str, Any]:
    perspective_id = str(raw.get("id") or fallback_id).strip()
    perspective_id = _validate_perspective_id_for_load(perspective_id) if legacy else _validate_perspective_id(perspective_id)
    title = str(raw.get("title") or "").strip() or ("Main perspective" if perspective_id.startswith("persp_") else "Untitled Perspective")
    source = project_manager._normalize_rel_path(str(raw.get("source_file_path") or _source_rel(scene_id, perspective_id)).strip())
    perspective_type = str(raw.get("type") or "").strip().lower()
    if perspective_type not in {"psd", "image"}:
        perspective_type = "psd" if Path(source).suffix.lower() == ".psd" else "image"
    preview = project_manager._normalize_rel_path(str(raw.get("preview_image_path") or "").strip())
    if not preview:
        preview = source if perspective_type == "image" else _preview_rel(scene_id, perspective_id)
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


def _normalize_scene(raw: dict[str, Any], *, legacy: bool = False) -> dict[str, Any]:
    scene_id = _validate_scene_id_for_load(raw.get("id", "")) if legacy else _validate_scene_id(raw.get("id", ""))
    title = str(raw.get("title") or "").strip() or ("Untitled Scene" if is_uuid(scene_id) else scene_id)
    created_at = str(raw.get("created_at") or "").strip() or _now_iso()
    updated_at = str(raw.get("updated_at") or created_at).strip() or created_at
    raw_perspectives = raw.get("perspectives")
    if isinstance(raw_perspectives, list):
        perspectives = [
            _normalize_perspective(item, scene_id=scene_id, fallback_id=f"persp_{index + 1:03d}", legacy=legacy)
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
                    "source_file_path": raw.get("source_file_path") or _source_rel(scene_id, fallback_perspective_id),
                    "preview_image_path": raw.get("preview_image_path") or _preview_rel(scene_id, fallback_perspective_id),
                    "linked_scene3d_id": raw.get("linked_scene3d_id") or "",
                    "linked_scene3d_view": None,
                    "created_at": created_at,
                    "updated_at": updated_at,
                },
                scene_id=scene_id,
                legacy=legacy,
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
    scene = {
        "id": scene_id,
        "title": title,
        "description": str(raw.get("description") or ""),
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
    project_root = project.root_path.resolve()
    for scene in scenes:
        old_id = str(scene.get("id") or "")
        if is_uuid(old_id):
            continue
        candidate = (_root_dir(project) / old_id).resolve()
        if candidate.is_dir() and candidate != project_root and project_root in candidate.parents:
            roots.append(candidate)
    return roots


def _migrate_reference_links(
    project: Project,
    scene_map: dict[str, str],
    perspective_map: dict[tuple[str, str], str],
    perspective_preview_map: dict[tuple[str, str], str],
) -> None:
    links = project_manager.normalize_reference_links(project.settings.get("reference_links"))
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
        project.settings["reference_links"] = project_manager.normalize_reference_links(links)
        project_manager.save_settings(project)


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
    legacy_roots = _legacy_scene_roots(project, scenes)
    try:
        for scene in scenes:
            old_scene_id = scene["id"]
            new_scene_id = scene_map[old_scene_id]
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
                if preview_rel != source_rel:
                    _copy_if_present(project, perspective.get("preview_image_path", ""), preview_rel, created_scene_dirs, required=False)
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
            new_scenes.append(_normalize_scene(new_scene))

        _save_scenes(project, new_scenes)
        _migrate_reference_links(project, scene_map, perspective_map, perspective_preview_map)
        for legacy_root in legacy_roots:
            if legacy_root.exists():
                shutil.rmtree(legacy_root)
        return _sort_scenes(new_scenes)
    except BaseException:
        for directory in sorted(created_scene_dirs, key=lambda path: len(path.parts), reverse=True):
            try:
                if directory.is_dir():
                    shutil.rmtree(directory, ignore_errors=True)
            except OSError:
                pass
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
                scenes.append(_normalize_scene(data, legacy=True))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
    return _sort_scenes(scenes)


def _sort_scenes(scenes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted((_with_legacy_aliases(scene) for scene in scenes), key=lambda scene: (scene.get("created_at", ""), scene.get("title", ""), scene["id"]))


def list_scenes(project: Project) -> list[dict[str, Any]]:
    index = _index_path(project)
    if not index.is_file():
        return _migrate_scene2d_storage(project, _load_from_meta(project))
    try:
        data = _read_json(index)
    except (OSError, json.JSONDecodeError):
        return _migrate_scene2d_storage(project, _load_from_meta(project))
    raw_scenes = data.get("scenes") if isinstance(data, dict) else data
    if not isinstance(raw_scenes, list):
        return _migrate_scene2d_storage(project, _load_from_meta(project))
    scenes: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw_scenes:
        if not isinstance(item, dict):
            continue
        scene = _normalize_scene(item, legacy=True)
        if scene["id"] in seen:
            continue
        seen.add(scene["id"])
        scenes.append(scene)
    return _migrate_scene2d_storage(project, _sort_scenes(scenes))


def _save_scenes(project: Project, scenes: list[dict[str, Any]]) -> None:
    root = _root_dir(project)
    root.mkdir(parents=True, exist_ok=True)
    normalized = _sort_scenes([_normalize_scene(scene) for scene in scenes])
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


def create_scene(project: Project, title: str = "", description: str = "") -> tuple[dict[str, Any], list[dict[str, Any]]]:
    scenes = list_scenes(project)
    scene_id = new_uuid()
    perspective_id = new_uuid()
    timestamp = _now_iso()
    perspective = _normalize_perspective(
        {
            "id": perspective_id,
            "title": "Main perspective",
            "type": "psd",
            "source_file_path": _source_rel(scene_id, perspective_id),
            "preview_image_path": _preview_rel(scene_id, perspective_id),
            "created_at": timestamp,
            "updated_at": timestamp,
        },
        scene_id=scene_id,
    )
    scene = _normalize_scene(
        {
            "id": scene_id,
            "title": title.strip() or f"Scene 2D {len(scenes) + 1}",
            "description": description,
            "linked_scene3d_id": "",
            "primary_perspective_id": perspective["id"],
            "created_at": timestamp,
            "updated_at": timestamp,
            "can_be_reference": True,
            "perspectives": [perspective],
        }
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
    scenes = [item for item in scenes if item["id"] != scene["id"]]
    _save_scenes(project, scenes)
    scene_dir = _scene_dir(project, scene["id"])
    if scene_dir.is_dir():
        shutil.rmtree(scene_dir)
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
    source_rel = _source_rel(scene["id"], perspective_id)
    perspective = _normalize_perspective(
        {
            "id": perspective_id,
            "title": title,
            "type": "psd",
            "source_file_path": source_rel,
            "preview_image_path": _preview_rel(scene["id"], perspective_id),
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
    source_rel = _source_rel(scene["id"], perspective_id) if suffix in PSD_EXTENSIONS else _image_source_rel(scene["id"], perspective_id, suffix)
    _write_binary_atomic(_safe_rel_path(project, source_rel), bytes(data))
    perspective_type = "psd" if suffix in PSD_EXTENSIONS else "image"
    preview_rel = source_rel if perspective_type == "image" else _preview_rel(scene["id"], perspective_id)
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
    scene["perspectives"] = [item for item in scene["perspectives"] if item["id"] != perspective["id"]]
    if scene.get("primary_perspective_id") == perspective["id"]:
        scene["primary_perspective_id"] = scene["perspectives"][0]["id"] if scene["perspectives"] else ""
    timestamp = _now_iso()
    scene["updated_at"] = timestamp
    perspective_dir = _safe_rel_path(project, perspective["source_file_path"]).parent
    scene_root = _scene_dir(project, scene["id"]).resolve()
    if perspective_dir.is_dir() and scene_root in perspective_dir.resolve().parents:
        shutil.rmtree(perspective_dir)
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
