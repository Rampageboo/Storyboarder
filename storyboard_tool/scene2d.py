"""Project-level Scene 2D storage and operations.

Scene 2D assets are intentionally separate from shots.  A scene owns a folder
under ``scenes2d/`` with its PSD source, optional exported preview, and metadata;
the collection index exists only to make listing cheap and durable.
"""
from __future__ import annotations

import json
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import project_manager
from .image_utils import create_blank_psd
from .models import Project

SCENE2D_ROOT = "scenes2d"
SCENE2D_INDEX = "scenes2d.json"
SCENE_ID_RE = re.compile(r"^scene_(\d{3,})$")


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _root_dir(project: Project) -> Path:
    return project.root_path / SCENE2D_ROOT


def _index_path(project: Project) -> Path:
    return _root_dir(project) / SCENE2D_INDEX


def _scene_dir(project: Project, scene_id: str) -> Path:
    _validate_scene_id(scene_id)
    return _root_dir(project) / scene_id


def _meta_path(project: Project, scene_id: str) -> Path:
    return _scene_dir(project, scene_id) / f"{scene_id}_meta.json"


def _source_rel(scene_id: str) -> str:
    return f"{SCENE2D_ROOT}/{scene_id}/{scene_id}.psd"


def _preview_rel(scene_id: str) -> str:
    return f"{SCENE2D_ROOT}/{scene_id}/{scene_id}_preview.png"


def _validate_scene_id(scene_id: str) -> str:
    scene_id = str(scene_id or "").strip()
    if not SCENE_ID_RE.match(scene_id):
        raise ValueError("Invalid Scene 2D id.")
    return scene_id


def _safe_rel_path(project: Project, relative_path: str) -> Path:
    rel = project_manager._normalize_rel_path(str(relative_path or "").strip())
    if not rel:
        raise ValueError("Scene 2D path is empty.")
    resolved = (project.root_path / rel).resolve()
    root = project.root_path.resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError("Scene 2D path escapes the project.")
    return resolved


def _normalize_scene(raw: dict[str, Any]) -> dict[str, Any]:
    scene_id = _validate_scene_id(raw.get("id", ""))
    title = str(raw.get("title") or "").strip() or scene_id
    created_at = str(raw.get("created_at") or "").strip() or _now_iso()
    updated_at = str(raw.get("updated_at") or created_at).strip() or created_at
    return {
        "id": scene_id,
        "title": title,
        "description": str(raw.get("description") or ""),
        "source_file_path": project_manager._normalize_rel_path(
            str(raw.get("source_file_path") or _source_rel(scene_id)).strip()
        ),
        "preview_image_path": project_manager._normalize_rel_path(
            str(raw.get("preview_image_path") or _preview_rel(scene_id)).strip()
        ),
        "created_at": created_at,
        "updated_at": updated_at,
        "can_be_reference": bool(raw.get("can_be_reference", True)),
    }


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_from_meta(project: Project) -> list[dict[str, Any]]:
    root = _root_dir(project)
    if not root.is_dir():
        return []
    scenes: list[dict[str, Any]] = []
    for meta_path in sorted(root.glob("scene_*/scene_*_meta.json")):
        try:
            data = _read_json(meta_path)
            if isinstance(data, dict):
                scenes.append(_normalize_scene(data))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
    return _sort_scenes(scenes)


def _sort_scenes(scenes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(scenes, key=lambda scene: scene["id"])


def list_scenes(project: Project) -> list[dict[str, Any]]:
    index = _index_path(project)
    if not index.is_file():
        return _load_from_meta(project)
    try:
        data = _read_json(index)
    except (OSError, json.JSONDecodeError):
        return _load_from_meta(project)
    raw_scenes = data.get("scenes") if isinstance(data, dict) else data
    if not isinstance(raw_scenes, list):
        return _load_from_meta(project)
    scenes: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw_scenes:
        if not isinstance(item, dict):
            continue
        try:
            scene = _normalize_scene(item)
        except ValueError:
            continue
        if scene["id"] in seen:
            continue
        seen.add(scene["id"])
        scenes.append(scene)
    return _sort_scenes(scenes)


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


def _replace_scene(scenes: list[dict[str, Any]], scene: dict[str, Any]) -> list[dict[str, Any]]:
    scene_id = scene["id"]
    return [scene if item["id"] == scene_id else item for item in scenes]


def _next_scene_id(scenes: list[dict[str, Any]]) -> str:
    used = {scene["id"] for scene in scenes}
    max_seen = 0
    for scene_id in used:
        match = SCENE_ID_RE.match(scene_id)
        if match:
            max_seen = max(max_seen, int(match.group(1)))
    candidate = max_seen + 1
    while True:
        scene_id = f"scene_{candidate:03d}"
        if scene_id not in used:
            return scene_id
        candidate += 1


def _create_scene_psd(project: Project, scene: dict[str, Any]) -> None:
    width, height = project_manager.get_canvas_size(project)
    background = project_manager.get_canvas_color(project)
    destination = _safe_rel_path(project, scene["source_file_path"])
    create_blank_psd(destination, width, height, background_color=background)


def create_scene(project: Project, title: str = "", description: str = "") -> tuple[dict[str, Any], list[dict[str, Any]]]:
    scenes = list_scenes(project)
    scene_id = _next_scene_id(scenes)
    timestamp = _now_iso()
    scene = _normalize_scene(
        {
            "id": scene_id,
            "title": title.strip() or f"Scene 2D {len(scenes) + 1}",
            "description": description,
            "source_file_path": _source_rel(scene_id),
            "preview_image_path": _preview_rel(scene_id),
            "created_at": timestamp,
            "updated_at": timestamp,
            "can_be_reference": True,
        }
    )
    _scene_dir(project, scene_id).mkdir(parents=True, exist_ok=True)
    _create_scene_psd(project, scene)
    scenes.append(scene)
    scenes = _sort_scenes(scenes)
    _save_scenes(project, scenes)
    return scene, scenes


def update_scene(project: Project, scene_id: str, changes: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    scene, scenes = _find_scene(project, scene_id)
    changed = False
    if "title" in changes and changes["title"] is not None:
        scene["title"] = str(changes["title"] or "").strip() or scene["id"]
        changed = True
    if "description" in changes and changes["description"] is not None:
        scene["description"] = str(changes["description"] or "")
        changed = True
    if "can_be_reference" in changes and changes["can_be_reference"] is not None:
        scene["can_be_reference"] = bool(changes["can_be_reference"])
        changed = True
    if changed:
        scene["updated_at"] = _now_iso()
        scenes = _replace_scene(scenes, scene)
        _save_scenes(project, scenes)
    return scene, scenes


def delete_scene(project: Project, scene_id: str) -> list[dict[str, Any]]:
    scene, scenes = _find_scene(project, scene_id)
    scenes = [item for item in scenes if item["id"] != scene["id"]]
    _save_scenes(project, scenes)
    scene_dir = _scene_dir(project, scene["id"])
    if scene_dir.is_dir():
        shutil.rmtree(scene_dir)

    links = project_manager.normalize_reference_links(project.settings.get("reference_links"))
    filtered = [
        link
        for link in links
        if not (
            link.get("type") == "scene2d"
            and (
                str(link.get("source_scene2d_id") or "") == scene["id"]
                or project_manager._normalize_rel_path(str(link.get("path") or "")) == scene["preview_image_path"]
            )
        )
    ]
    if filtered != links:
        project.settings["reference_links"] = filtered
        project_manager.save_settings(project)
    return scenes


def open_scene(project: Project, scene_id: str) -> tuple[dict[str, Any], str, str]:
    scene, scenes = _find_scene(project, scene_id)
    source = _safe_rel_path(project, scene["source_file_path"])
    if not source.is_file():
        _create_scene_psd(project, scene)
        scene["updated_at"] = _now_iso()
        scenes = _replace_scene(scenes, scene)
        _save_scenes(project, scenes)
    opened = project_manager.open_project_file(
        project,
        scene["source_file_path"],
        project.settings.get("photoshop_path", ""),
    )
    return scene, str(opened), scene["source_file_path"]


def refresh_preview(project: Project, scene_id: str) -> tuple[dict[str, Any], bool, str]:
    scene, scenes = _find_scene(project, scene_id)
    preview = _safe_rel_path(project, scene["preview_image_path"])
    if not preview.is_file():
        return scene, False, "No Scene 2D preview exists yet."
    scene["updated_at"] = _now_iso()
    scenes = _replace_scene(scenes, scene)
    _save_scenes(project, scenes)
    return scene, True, "Scene 2D preview refreshed."


def preview_meta(project: Project, scene_id: str) -> dict[str, str]:
    scene, _scenes = _find_scene(project, scene_id)
    preview = _safe_rel_path(project, scene["preview_image_path"])
    if not preview.is_file():
        raise FileNotFoundError("Scene 2D preview not found.")
    return {"path": str(preview), "media_type": "image/png", "filename": preview.name}


def _scene_reference_id(scene_id: str, links: list[dict[str, Any]]) -> str:
    used = {str(link.get("id") or "") for link in links}
    candidate = f"ref_{scene_id}"
    if candidate not in used:
        return candidate
    for index in range(2, 1000):
        candidate = f"ref_{scene_id}_{index}"
        if candidate not in used:
            return candidate
    return f"ref_{scene_id}_{uuid.uuid4().hex[:8]}"


def add_to_references(project: Project, scene_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    scene, _scenes = _find_scene(project, scene_id)
    if not scene.get("can_be_reference", True):
        raise ValueError("Scene 2D cannot be added as a reference.")
    preview = _safe_rel_path(project, scene["preview_image_path"])
    if not preview.is_file():
        raise FileNotFoundError("Scene 2D preview not found.")
    links = project_manager.normalize_reference_links(project.settings.get("reference_links"))
    entry = {
        "id": _scene_reference_id(scene["id"], links),
        "title": scene["title"],
        "type": "scene2d",
        "path": scene["preview_image_path"],
        "source_scene2d_id": scene["id"],
    }
    links.append(entry)
    project.settings["reference_links"] = project_manager.normalize_reference_links(links)
    project_manager.save_settings(project)
    return entry, scene
