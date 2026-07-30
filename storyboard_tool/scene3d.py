"""Project-level Scene 3D collection storage."""
from __future__ import annotations

import contextlib
import copy
import json
import os
import re
import shutil
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import project_document, project_manager
from .file_transactions import quarantined_deletions, rollback_paths
from .models import Project
from . import scene2d
from .project_layout import (
    LAYOUT_2,
    resolve_scene3d_asset,
    scene3d_asset_relative,
    scene3d_metadata_path,
    scene3d_preview_path,
)

SCENE3D_ROOT = "scenes3d"
SCENE3D_INDEX = "scenes3d.json"
SCENE3D_EXTENSIONS = {".glb", ".gltf", ".blend"}
SCENE3D_ID_RE = re.compile(r"^scene3d_(\d{3,})$")
PREVIEW_FILENAME = "storyboarder_preview.glb"


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _root_dir(project: Project) -> Path:
    return scene3d_metadata_path(project)


def _index_path(project: Project) -> Path:
    return scene3d_metadata_path(project, SCENE3D_INDEX)


def _scene_dir(project: Project, scene_id: str) -> Path:
    _validate_scene_id(scene_id)
    return scene3d_metadata_path(project, scene_id)


def preview_relative_path(scene_id: str) -> str:
    _validate_scene_id(scene_id)
    return f"{SCENE3D_ROOT}/{scene_id}/.preview/{PREVIEW_FILENAME}"


def preview_file_path(project: Project, scene_id: str) -> Path:
    return scene3d_preview_path(project, _validate_scene_id(scene_id))


def _meta_path(project: Project, scene_id: str) -> Path:
    return scene3d_metadata_path(project, scene_id, f"{scene_id}_meta.json")


def _validate_scene_id(scene_id: str) -> str:
    scene_id = str(scene_id or "").strip()
    if not SCENE3D_ID_RE.match(scene_id):
        raise ValueError("Invalid Scene 3D id.")
    return scene_id


def _slug(value: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "_", str(value or "").strip().lower()).strip("_")
    return text[:80]


def _normalize_keywords(value: Any) -> list[str]:
    raw_items = value.split(",") if isinstance(value, str) else value if isinstance(value, list) else []
    result: list[str] = []
    seen: set[str] = set()
    for raw in raw_items:
        keyword = str(raw or "").strip()[:80]
        folded = keyword.casefold()
        if not keyword or folded in seen:
            continue
        seen.add(folded)
        result.append(keyword)
        if len(result) >= 32:
            break
    return result


def _safe_rel_path(project: Project, relative_path: str) -> Path:
    rel = str(relative_path or "").strip()
    if not rel:
        raise ValueError("Scene 3D path is empty.")
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


def _default_display_settings(raw: dict[str, Any] | None = None) -> dict[str, Any]:
    settings = {
        "follow_camera": True,
        "program_lighting": "auto",
        "object_color_preview": True,
        "wireframe_mode": "off",
    }
    if isinstance(raw, dict):
        settings.update(raw)
    return settings


def _normalize_scene(raw: dict[str, Any]) -> dict[str, Any]:
    scene_id = _validate_scene_id(raw.get("id", ""))
    created_at = str(raw.get("created_at") or "").strip() or _now_iso()
    updated_at = str(raw.get("updated_at") or created_at).strip() or created_at
    file_path = project_manager._normalize_rel_path(str(raw.get("file_path") or "").strip())
    file_name = str(raw.get("file_name") or "").strip() or (Path(file_path).name if file_path else "")
    reference_view = raw.get("reference_view")
    return {
        "id": scene_id,
        "title": str(raw.get("title") or "").strip() or file_name or scene_id,
        "description": str(raw.get("description") or ""),
        "source_type": str(raw.get("source_type") or raw.get("source") or ("glb" if file_path else "")).strip(),
        "file_path": file_path,
        "file_name": file_name,
        "blend_file_path": project_manager._normalize_rel_path(str(raw.get("blend_file_path") or "").strip()),
        "keywords": _normalize_keywords(raw.get("keywords")),
        "reference_view": reference_view if isinstance(reference_view, dict) else {},
        "display_settings": _default_display_settings(raw.get("display_settings") if isinstance(raw.get("display_settings"), dict) else raw),
        "created_at": created_at,
        "updated_at": updated_at,
    }


def _legacy_scene(project: Project) -> dict[str, Any] | None:
    legacy = project.settings.get("scene3d")
    if not isinstance(legacy, dict) or not legacy:
        return None
    timestamp = _now_iso()
    file_name = str(legacy.get("file_name") or "").strip()
    file_path = project_manager._normalize_rel_path(str(legacy.get("file_path") or "").strip())
    return _normalize_scene(
        {
            "id": "scene3d_001",
            "title": file_name or Path(file_path).stem or "Scene 3D 1",
            "description": legacy.get("description") or "",
            "source_type": legacy.get("source_type") or legacy.get("source") or ("glb" if file_path else ""),
            "file_path": file_path,
            "file_name": file_name,
            "blend_file_path": legacy.get("blend_file_path") or "",
            "reference_view": legacy.get("reference_view") or {},
            "display_settings": legacy,
            "created_at": timestamp,
            "updated_at": timestamp,
        }
    )


def _read_index(project: Project) -> tuple[str, list[dict[str, Any]]] | None:
    index = _index_path(project)
    if not index.is_file():
        if project.layout == LAYOUT_2:
            raise FileNotFoundError("Layout 2 Scene 3D index is missing.")
        return None
    try:
        data = json.loads(index.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        if project.layout == LAYOUT_2:
            raise ValueError("Layout 2 Scene 3D index is unreadable.") from exc
        return None
    if project.layout == LAYOUT_2 and not isinstance(data, dict):
        raise ValueError("Layout 2 Scene 3D index must be an object.")
    raw_scenes = data.get("scenes") if isinstance(data, dict) else []
    if not isinstance(raw_scenes, list):
        if project.layout == LAYOUT_2:
            raise ValueError("Layout 2 Scene 3D scenes must be a list.")
        raw_scenes = []
    scenes: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw_scenes:
        if not isinstance(item, dict):
            if project.layout == LAYOUT_2:
                raise ValueError("Layout 2 Scene 3D index contains an invalid entry.")
            continue
        try:
            scene = _normalize_scene(item)
        except ValueError as exc:
            if project.layout == LAYOUT_2:
                raise ValueError("Layout 2 Scene 3D index contains an invalid scene.") from exc
            continue
        if scene["id"] in seen:
            if project.layout == LAYOUT_2:
                raise ValueError("Layout 2 Scene 3D index contains duplicate scene IDs.")
            continue
        if project.layout == LAYOUT_2:
            for field_name, suffixes in (
                ("file_path", SCENE3D_EXTENSIONS),
                ("blend_file_path", {".blend"}),
            ):
                raw_relative = item.get(field_name)
                if raw_relative in (None, ""):
                    continue
                if not isinstance(raw_relative, str):
                    raise ValueError(
                        f"Layout 2 Scene 3D {field_name} must be a string."
                    )
                resolved = _safe_rel_path(project, raw_relative)
                if resolved.suffix.lower() not in suffixes:
                    raise ValueError(
                        f"Layout 2 Scene 3D {field_name} has an invalid file type."
                    )
                relative = str(scene.get(field_name) or "")
                if not relative:
                    continue
                resolved = _safe_rel_path(project, relative)
                if resolved.suffix.lower() not in suffixes:
                    raise ValueError(
                        f"Layout 2 Scene 3D {field_name} has an invalid file type."
                    )
        seen.add(scene["id"])
        scenes.append(scene)
    active_id = str(data.get("active_scene3d_id") or "").strip() if isinstance(data, dict) else ""
    scene_ids = {scene["id"] for scene in scenes}
    if project.layout == LAYOUT_2 and (
        (bool(scenes) and active_id not in scene_ids) or (not scenes and bool(active_id))
    ):
        raise ValueError("Layout 2 Scene 3D active scene is invalid.")
    if active_id not in scene_ids:
        active_id = scenes[0]["id"] if scenes else ""
    return active_id, sorted(scenes, key=lambda scene: scene["id"])


def _mirror_active_to_settings(project: Project, scene: dict[str, Any] | None) -> None:
    if scene is None:
        project.settings["scene3d"] = {}
        project.settings["active_scene3d_id"] = ""
    else:
        mirrored = dict(scene.get("display_settings") or {})
        mirrored.update(
            {
                "id": scene["id"],
                "source": scene.get("source_type") or "",
                "source_type": scene.get("source_type") or "",
                "file_path": scene.get("file_path") or "",
                "file_name": scene.get("file_name") or "",
                "blend_file_path": scene.get("blend_file_path") or "",
                "title": scene.get("title") or "",
                "description": scene.get("description") or "",
                "keywords": list(scene.get("keywords") or []),
                "updated_at": scene.get("updated_at") or "",
                "reference_view": scene.get("reference_view") or {},
            }
        )
        project.settings["scene3d"] = mirrored
        project.settings["active_scene3d_id"] = scene["id"]
    project_manager.save_settings(project)


def _save_unchecked(
    project: Project,
    active_scene3d_id: str,
    scenes: list[dict[str, Any]],
) -> None:
    root = _root_dir(project)
    root.mkdir(parents=True, exist_ok=True)
    normalized = sorted([_normalize_scene(scene) for scene in scenes], key=lambda scene: scene["id"])
    ids = {scene["id"] for scene in normalized}
    if active_scene3d_id not in ids:
        active_scene3d_id = normalized[0]["id"] if normalized else ""
    project_manager._atomic_write_json(_index_path(project), {"active_scene3d_id": active_scene3d_id, "scenes": normalized})
    for scene in normalized:
        scene_dir = _scene_dir(project, scene["id"])
        scene_dir.mkdir(parents=True, exist_ok=True)
        project_manager._atomic_write_json(_meta_path(project, scene["id"]), scene)
    active = next((scene for scene in normalized if scene["id"] == active_scene3d_id), None)
    _mirror_active_to_settings(project, active)


def _save(project: Project, active_scene3d_id: str, scenes: list[dict[str, Any]]) -> None:
    if project.layout != LAYOUT_2:
        _save_unchecked(project, active_scene3d_id, scenes)
        return
    settings_before = copy.deepcopy(project.settings)
    try:
        with rollback_paths((_root_dir(project), project.settings_path)):
            _save_unchecked(project, active_scene3d_id, scenes)
    except BaseException:
        project.settings = settings_before
        raise


def initialize_layout2_metadata(project: Project) -> None:
    """Create the canonical empty Scene 3D index during Layout 2 initialization."""
    if project.layout != LAYOUT_2:
        raise ValueError("Scene 3D Layout 2 initialization requires Layout 2.")
    if _index_path(project).exists():
        _read_index(project)
        return
    _save(project, "", [])


def list_scenes(project: Project) -> dict[str, Any]:
    loaded = _read_index(project)
    if loaded is None:
        # First read of legacy settings.scene3d migrates it into scenes3d
        # and mirrors the active Scene 3D back for backward compatibility.
        legacy = _legacy_scene(project)
        if legacy:
            _save(project, legacy["id"], [legacy])
            loaded = _read_index(project)
        else:
            loaded = ("", [])
    active_scene3d_id, scenes = loaded
    return {"active_scene3d_id": active_scene3d_id, "scenes": scenes}


def _find_scene(project: Project, scene_id: str) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
    scene_id = _validate_scene_id(scene_id)
    payload = list_scenes(project)
    scenes = payload["scenes"]
    for scene in scenes:
        if scene["id"] == scene_id:
            return payload["active_scene3d_id"], scene, scenes
    raise FileNotFoundError("Scene 3D not found.")


def _next_scene_id(scenes: list[dict[str, Any]]) -> str:
    used = {scene["id"] for scene in scenes}
    max_seen = 0
    for scene_id in used:
        match = SCENE3D_ID_RE.match(scene_id)
        if match:
            max_seen = max(max_seen, int(match.group(1)))
    candidate = max_seen + 1
    while True:
        scene_id = f"scene3d_{candidate:03d}"
        if scene_id not in used:
            return scene_id
        candidate += 1


def create_scene(
    project: Project,
    title: str = "",
    description: str = "",
    keywords: list[str] | None = None,
) -> dict[str, Any]:
    payload = list_scenes(project)
    scenes = payload["scenes"]
    scene_id = _next_scene_id(scenes)
    timestamp = _now_iso()
    scene = _normalize_scene(
        {
            "id": scene_id,
            "title": title.strip() or f"Scene 3D {len(scenes) + 1}",
            "description": description,
            "keywords": keywords or [],
            "created_at": timestamp,
            "updated_at": timestamp,
        }
    )
    scenes.append(scene)
    active_id = payload["active_scene3d_id"] or scene_id
    _save(project, active_id, scenes)
    return {"scene": scene, **list_scenes(project)}


def update_scene(project: Project, scene_id: str, changes: dict[str, Any]) -> dict[str, Any]:
    active_id, scene, scenes = _find_scene(project, scene_id)
    if "title" in changes and changes["title"] is not None:
        scene["title"] = str(changes["title"] or "").strip() or scene["id"]
    if "description" in changes and changes["description"] is not None:
        scene["description"] = str(changes["description"] or "")
    if "keywords" in changes and changes["keywords"] is not None:
        scene["keywords"] = _normalize_keywords(changes["keywords"])
    if "reference_view" in changes:
        view = changes.get("reference_view")
        scene["reference_view"] = view if isinstance(view, dict) else {}
    if "display_settings" in changes and isinstance(changes.get("display_settings"), dict):
        scene["display_settings"] = _default_display_settings(changes["display_settings"])
    scene["updated_at"] = _now_iso()
    _save(project, active_id, scenes)
    return {"scene": scene, **list_scenes(project)}


def _delete_scene_layout2(project: Project, scene_id: str) -> dict[str, Any]:
    active_id, scene, scenes = _find_scene(project, scene_id)
    assets = {
        _safe_rel_path(project, relative)
        for relative in (
            str(scene.get("file_path") or ""),
            str(scene.get("blend_file_path") or ""),
        )
        if relative
    }
    assets.update((preview_file_path(project, scene["id"]), _scene_dir(project, scene["id"])))
    project_document.enlist_layout2_mutation_paths(
        project.project_root,
        assets,
    )
    scenes = [item for item in scenes if item["id"] != scene["id"]]
    if active_id == scene["id"]:
        active_id = scenes[0]["id"] if scenes else ""
    settings_before = copy.deepcopy(project.settings)
    try:
        with rollback_paths(
            (_root_dir(project), scene2d._root_dir(project), project.settings_path)
        ):
            with quarantined_deletions(project.project_root, assets):
                scene2d.clear_scene3d_links(project, scene["id"])
                _save(project, active_id, scenes)
    except BaseException:
        project.settings = settings_before
        raise
    return list_scenes(project)


def delete_scene(project: Project, scene_id: str) -> dict[str, Any]:
    if project.layout == LAYOUT_2:
        return _delete_scene_layout2(project, scene_id)
    active_id, scene, scenes = _find_scene(project, scene_id)
    scenes = [item for item in scenes if item["id"] != scene["id"]]
    if active_id == scene["id"]:
        active_id = scenes[0]["id"] if scenes else ""
    scene2d.clear_scene3d_links(project, scene["id"])
    scene_dir = _scene_dir(project, scene["id"])
    if scene_dir.is_dir():
        shutil.rmtree(scene_dir)
    _save(project, active_id, scenes)
    return list_scenes(project)


def set_active(project: Project, scene_id: str) -> dict[str, Any]:
    _active_id, scene, scenes = _find_scene(project, scene_id)
    _save(project, scene["id"], scenes)
    return {"scene": scene, **list_scenes(project)}


def active_scene(project: Project) -> dict[str, Any] | None:
    payload = list_scenes(project)
    active_id = payload["active_scene3d_id"]
    return next((scene for scene in payload["scenes"] if scene["id"] == active_id), None)


def ensure_active_scene(project: Project) -> dict[str, Any]:
    scene = active_scene(project)
    if scene:
        return scene
    return create_scene(project)["scene"]


def configure_blend_preview(
    project: Project,
    scene_id: str,
    blend_path: Path,
) -> dict[str, Any]:
    active_id, scene, scenes = _find_scene(project, scene_id)
    blend_relative = project_manager.project_relative_posix(project, blend_path)
    resolved_blend = project_manager.resolve_project_path(project, blend_relative)
    if project.layout == LAYOUT_2:
        stored = str(scene.get("blend_file_path") or "")
        expected = (
            _safe_rel_path(project, stored)
            if stored
            else resolve_scene3d_asset(project, scene_id, ".blend")
        )
        if resolved_blend != expected:
            raise ValueError("Blender scene path differs from its persisted target.")
        if resolved_blend.suffix.lower() != ".blend" or not resolved_blend.is_file():
            raise FileNotFoundError(f"Blender scene not found: {blend_relative}")
    preview_relative = project_manager.project_relative_posix(
        project, preview_file_path(project, scene_id)
    )
    scene.update(
        {
            "source_type": "blender",
            "file_path": preview_relative,
            "file_name": PREVIEW_FILENAME,
            "blend_file_path": blend_relative,
            "updated_at": _now_iso(),
        }
    )
    _save(project, active_id, scenes)
    return next(item for item in list_scenes(project)["scenes"] if item["id"] == scene_id)


def import_scene_file(project: Project, scene_id: str, filename: str, data: bytes) -> dict[str, Any]:
    _active_id, scene, scenes = _find_scene(project, scene_id)
    suffix = Path(filename or "").suffix.lower()
    if suffix not in SCENE3D_EXTENSIONS:
        raise ValueError("Only .blend, .glb, and .gltf Scene 3D files are supported.")
    stem = _slug(Path(filename or "").stem) or scene["id"]
    stored_rel = ""
    if project.layout == LAYOUT_2:
        if suffix == ".blend":
            stored_rel = str(scene.get("blend_file_path") or "")
        elif str(scene.get("source_type") or "") in {"glb", "gltf"}:
            stored_rel = str(scene.get("file_path") or "")
    if stored_rel:
        destination = _safe_rel_path(project, stored_rel)
        if destination.suffix.lower() != suffix:
            raise ValueError(
                "Imported Scene 3D file type differs from its persisted target."
            )
        destination_rel = stored_rel
    else:
        destination_rel = (
            scene3d_asset_relative(project, scene["id"], suffix)
            if project.layout == LAYOUT_2
            else f"{SCENE3D_ROOT}/{scene['id']}/{stem}{suffix}"
        )
        destination = _safe_rel_path(project, destination_rel)
    keywords = _normalize_keywords([*(scene.get("keywords") or []), Path(filename or "").stem])
    settings_before = copy.deepcopy(project.settings)
    if project.layout == LAYOUT_2:
        project_document.enlist_layout2_mutation_paths(
            project.project_root,
            (destination,),
        )

    try:
        paths = (destination, _root_dir(project), project.settings_path)
        with rollback_paths(paths) if project.layout == LAYOUT_2 else contextlib.nullcontext():
            _write_binary_atomic(destination, bytes(data))
            if suffix == ".blend":
                scene.update({
                    "blend_file_path": destination_rel,
                    "keywords": keywords,
                    "updated_at": _now_iso(),
                })
            else:
                scene.update(
                    {
                        "source_type": "glb" if suffix == ".glb" else "gltf",
                        "file_path": destination_rel,
                        "file_name": Path(filename or "").name or f"{stem}{suffix}",
                        "keywords": keywords,
                        "updated_at": _now_iso(),
                    }
                )
            _save(project, scene["id"], scenes)
    except BaseException:
        project.settings = settings_before
        raise
    return {"scene": scene, **list_scenes(project)}


def import_active_scene_file(project: Project, filename: str, data: bytes) -> dict[str, Any]:
    scene = ensure_active_scene(project)
    return import_scene_file(project, scene["id"], filename, data)


def file_path(project: Project, scene_id: str | None = None) -> Path | None:
    scene = active_scene(project) if scene_id is None else _find_scene(project, scene_id)[1]
    if not scene or not scene.get("file_path"):
        return None
    path = _safe_rel_path(project, scene["file_path"])
    if not path.is_file():
        raise FileNotFoundError(f"Scene 3D file not found: {scene['file_path']}")
    return path


def open_blender_scene(
    project: Project,
    *,
    python_script: Path | None = None,
    script_args: list[str] | None = None,
    on_launch=None,
) -> Path:
    scene = ensure_active_scene(project)
    attached_path = str(scene.get("blend_file_path") or "").strip()
    if attached_path:
        return project_manager.open_blender_scene(
            project,
            attached_path,
            python_script=python_script,
            script_args=script_args,
            on_launch=on_launch,
        )
    blend_path = project_manager.ensure_project_blend_file(project, scene_id=scene["id"])
    if blend_path.exists():
        payload = update_scene(project, scene["id"], {"display_settings": scene.get("display_settings") or {}})
        updated = next(item for item in payload["scenes"] if item["id"] == scene["id"])
        updated["blend_file_path"] = project_manager.project_relative_posix(
            project,
            blend_path,
        )
        _save(project, payload["active_scene3d_id"], payload["scenes"])
    relative = (
        project_manager.project_relative_posix(project, blend_path)
        if project.layout == LAYOUT_2
        else ""
    )
    return project_manager.open_blender_scene(
        project,
        relative,
        python_script=python_script,
        script_args=script_args,
        on_launch=on_launch,
    )
