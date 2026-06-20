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
SCENE_ID_RE = re.compile(r"^scene_(\d{3,})$")
PERSPECTIVE_ID_RE = re.compile(r"^persp_(\d{3,})$")
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
PSD_EXTENSIONS = {".psd"}


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


def _perspective_base_rel(scene_id: str, perspective_id: str, title: str, suffix: str) -> str:
    stem = _slug(title) or perspective_id
    return f"{SCENE2D_ROOT}/{scene_id}/perspectives/{perspective_id}/{stem}{suffix}"


def _perspective_preview_rel(scene_id: str, perspective_id: str, title: str) -> str:
    stem = _slug(title) or perspective_id
    return f"{SCENE2D_ROOT}/{scene_id}/perspectives/{perspective_id}/{stem}_preview.png"


def _validate_scene_id(scene_id: str) -> str:
    scene_id = str(scene_id or "").strip()
    if not SCENE_ID_RE.match(scene_id):
        raise ValueError("Invalid Scene 2D id.")
    return scene_id


def _validate_perspective_id(perspective_id: str) -> str:
    perspective_id = str(perspective_id or "").strip()
    if not PERSPECTIVE_ID_RE.match(perspective_id):
        raise ValueError("Invalid Scene 2D perspective id.")
    return perspective_id


def _slug(value: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "_", str(value or "").strip().lower()).strip("_")
    return text[:80]


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


def _normalize_perspective(raw: dict[str, Any], *, scene_id: str, fallback_id: str = "persp_001") -> dict[str, Any]:
    perspective_id = str(raw.get("id") or fallback_id).strip()
    if not PERSPECTIVE_ID_RE.match(perspective_id):
        perspective_id = fallback_id
    title = str(raw.get("title") or "").strip() or ("Main perspective" if perspective_id == "persp_001" else perspective_id)
    source = project_manager._normalize_rel_path(str(raw.get("source_file_path") or _source_rel(scene_id)).strip())
    perspective_type = str(raw.get("type") or "").strip().lower()
    if perspective_type not in {"psd", "image"}:
        perspective_type = "psd" if Path(source).suffix.lower() == ".psd" else "image"
    preview = project_manager._normalize_rel_path(str(raw.get("preview_image_path") or "").strip())
    if not preview:
        preview = source if perspective_type == "image" else _preview_rel(scene_id)
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


def _normalize_scene(raw: dict[str, Any]) -> dict[str, Any]:
    scene_id = _validate_scene_id(raw.get("id", ""))
    title = str(raw.get("title") or "").strip() or scene_id
    created_at = str(raw.get("created_at") or "").strip() or _now_iso()
    updated_at = str(raw.get("updated_at") or created_at).strip() or created_at
    raw_perspectives = raw.get("perspectives")
    if isinstance(raw_perspectives, list):
        perspectives = [
            _normalize_perspective(item, scene_id=scene_id, fallback_id=f"persp_{index + 1:03d}")
            for index, item in enumerate(raw_perspectives)
            if isinstance(item, dict)
        ]
    else:
        perspectives = [
            _normalize_perspective(
                {
                    "id": "persp_001",
                    "title": "Main perspective",
                    "type": "psd",
                    "source_file_path": raw.get("source_file_path") or _source_rel(scene_id),
                    "preview_image_path": raw.get("preview_image_path") or _preview_rel(scene_id),
                    "linked_scene3d_id": raw.get("linked_scene3d_id") or "",
                    "linked_scene3d_view": None,
                    "created_at": created_at,
                    "updated_at": updated_at,
                },
                scene_id=scene_id,
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
        "perspectives": sorted(unique_perspectives, key=lambda item: item["id"]),
    }
    return _with_legacy_aliases(scene)


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
    return sorted((_with_legacy_aliases(scene) for scene in scenes), key=lambda scene: scene["id"])


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


def _find_perspective(scene: dict[str, Any], perspective_id: str) -> dict[str, Any]:
    perspective_id = _validate_perspective_id(perspective_id)
    for perspective in scene.get("perspectives") or []:
        if perspective["id"] == perspective_id:
            return perspective
    raise FileNotFoundError("Scene 2D perspective not found.")


def _replace_scene(scenes: list[dict[str, Any]], scene: dict[str, Any]) -> list[dict[str, Any]]:
    return [scene if item["id"] == scene["id"] else item for item in scenes]


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


def _next_perspective_id(scene: dict[str, Any]) -> str:
    used = {perspective["id"] for perspective in scene.get("perspectives") or []}
    max_seen = 0
    for perspective_id in used:
        match = PERSPECTIVE_ID_RE.match(perspective_id)
        if match:
            max_seen = max(max_seen, int(match.group(1)))
    candidate = max_seen + 1
    while True:
        perspective_id = f"persp_{candidate:03d}"
        if perspective_id not in used:
            return perspective_id
        candidate += 1


def _create_psd(project: Project, relative_path: str) -> None:
    width, height = project_manager.get_canvas_size(project)
    background = project_manager.get_canvas_color(project)
    create_blank_psd(_safe_rel_path(project, relative_path), width, height, background_color=background)


def create_scene(project: Project, title: str = "", description: str = "") -> tuple[dict[str, Any], list[dict[str, Any]]]:
    scenes = list_scenes(project)
    scene_id = _next_scene_id(scenes)
    timestamp = _now_iso()
    perspective = _normalize_perspective(
        {
            "id": "persp_001",
            "title": "Main perspective",
            "type": "psd",
            "source_file_path": _source_rel(scene_id),
            "preview_image_path": _preview_rel(scene_id),
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
        scene["title"] = str(changes["title"] or "").strip() or scene["id"]
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
    perspective_id = _next_perspective_id(scene)
    timestamp = _now_iso()
    title = title.strip() or f"Perspective {len(scene.get('perspectives') or []) + 1}"
    source_rel = _perspective_base_rel(scene["id"], perspective_id, title, ".psd")
    perspective = _normalize_perspective(
        {
            "id": perspective_id,
            "title": title,
            "type": "psd",
            "source_file_path": source_rel,
            "preview_image_path": _perspective_preview_rel(scene["id"], perspective_id, title),
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
    perspective_id = _next_perspective_id(scene)
    timestamp = _now_iso()
    title = title.strip() or Path(filename or "").stem or f"Perspective {len(scene.get('perspectives') or []) + 1}"
    source_rel = _perspective_base_rel(scene["id"], perspective_id, title, suffix)
    _write_binary_atomic(_safe_rel_path(project, source_rel), bytes(data))
    perspective_type = "psd" if suffix in PSD_EXTENSIONS else "image"
    preview_rel = source_rel if perspective_type == "image" else _perspective_preview_rel(scene["id"], perspective_id, title)
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
        perspective["title"] = str(changes["title"] or "").strip() or perspective["id"]
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


def _ensure_perspective_source(project: Project, perspective: dict[str, Any]) -> None:
    source = _safe_rel_path(project, perspective["source_file_path"])
    if source.is_file():
        return
    if perspective["type"] == "psd":
        _create_psd(project, perspective["source_file_path"])
        return
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
    _ensure_perspective_source(project, perspective)
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
    return scene, _preview_exists(project, perspective), (
        "Scene 2D preview refreshed." if _preview_exists(project, perspective) else "No Scene 2D preview exists yet."
    )


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
