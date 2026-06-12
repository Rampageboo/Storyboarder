from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import BinaryIO

from .image_utils import (
    copy_and_convert_image,
    copy_and_convert_image_stream,
    create_blank_canvas,
    create_blank_psd,
    create_solid_preview_png,
    create_thumbnail,
    export_psd_composite_to_png,
    is_psd_path,
    is_solid_color_image,
    normalize_hex_color,
    save_png_data_url,
)
from .linked_sync import linked_mtime, sync_shot_from_linked_files
from .models import Project, Shot
from .shot_store import load_shots_csv, new_shot_id, save_shots_csv, shots_csv_mtime, shots_csv_path


PROJECT_JSON_VERSION = 3
DEFAULT_SETTINGS = {
    "autosave": True,
    "pdf_layout": "two_per_page",
    "recent_projects": [],
    "backup_on_save": True,
    "photoshop_path": "",
    "blender_path": "",
    "canvas_background_color": "#E8E8E8",
}

BLEND_TEMPLATE_PATH = Path(__file__).resolve().parent / "assets" / "scene_template.blend"


def create_project(parent_or_project_dir: Path) -> Project:
    root = parent_or_project_dir
    if root.name != "Storyboard_Project":
        root = root / "Storyboard_Project"

    root.mkdir(parents=True, exist_ok=True)
    _ensure_project_dirs(root)

    project = Project(root_path=root, settings=DEFAULT_SETTINGS.copy())
    save_project(project)
    ensure_project_blend_file(project)
    return project


def get_canvas_color(project: Project) -> str:
    return normalize_hex_color(str(project.settings.get("canvas_background_color", "#E8E8E8")))


def persist_canvas_color(project: Project, color: str, shot: Shot | None = None) -> str:
    normalized = normalize_hex_color(color)
    project.settings["canvas_background_color"] = normalized
    save_settings(project)
    write_canvas_color_files(project, normalized, shot)
    sync_canvas_color_to_shots(project, normalized)
    return normalized


def shot_has_artwork_preview(shot: Shot) -> bool:
    return bool(shot.preview_image_path or shot.image_path)


def sync_canvas_color_to_shots(project: Project, color: str) -> bool:
    """Keep blank-canvas shots aligned with the global canvas color."""
    normalized = normalize_hex_color(color)
    changed = False
    for shot in project.shots:
        if _sync_shot_canvas_color_assets(project, shot, normalized):
            changed = True
    if changed:
        save_project(project)
    return changed


def _sync_shot_canvas_color_assets(project: Project, shot: Shot, color: str) -> bool:
    shot_dir = get_shot_dir(project, shot)
    shot_dir.mkdir(parents=True, exist_ok=True)
    preview_path = shot_dir / f"{shot.shot_id}_preview.png"
    thumb_path = shot_dir / f"{shot.shot_id}_thumb.png"

    if not shot_has_artwork_preview(shot):
        create_solid_preview_png(preview_path, 1920, 1080, color)
        created_thumb = create_thumbnail(preview_path, thumb_path)
        shot.thumbnail_path = created_thumb.relative_to(project.root_path).as_posix()
        return True

    linked_preview = project.root_path / (shot.preview_image_path or shot.image_path)
    if linked_preview.is_file() and is_solid_color_image(linked_preview):
        create_solid_preview_png(linked_preview, 1920, 1080, color)
        created_thumb = create_thumbnail(linked_preview, thumb_path)
        shot.thumbnail_path = created_thumb.relative_to(project.root_path).as_posix()
        shot.preview_image_path = ""
        shot.image_path = ""
        return True

    return False


def write_canvas_color_files(project: Project, color: str, shot: Shot | None = None) -> None:
    normalized = normalize_hex_color(color)
    payload = {
        "canvas_background_color": normalized,
        "shot_id": shot.shot_id if shot else "",
        "source_file_path": shot.source_file_path if shot else "",
    }
    payload_text = json.dumps(payload, indent=2)
    color_text = f"{normalized}\n"

    targets = [project.root_path]
    if shot is not None:
        targets.append(get_shot_dir(project, shot))

    for target_dir in targets:
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / "canvas_color.txt").write_text(color_text, encoding="utf-8")
        (target_dir / "storyboard_bridge.json").write_text(payload_text, encoding="utf-8")


def project_disk_mtime(project: Project) -> float:
    json_mtime = project.json_path.stat().st_mtime if project.json_path.is_file() else 0.0
    csv_mtime = shots_csv_mtime(project.root_path)
    return max(json_mtime, csv_mtime)


def reload_project_if_changed(project: Project, loaded_mtime: float) -> tuple[Project, float, bool]:
    """Reload project.json from disk when the plugin or another tool updated it."""
    disk_mtime = project_disk_mtime(project)
    if disk_mtime <= loaded_mtime + 1e-6:
        return project, loaded_mtime, False
    reloaded = open_project(project.json_path)
    return reloaded, disk_mtime, True


def open_project(project_json_path: Path) -> Project:
    if not project_json_path.exists():
        raise FileNotFoundError(f"Project file not found: {project_json_path}")

    try:
        payload = json.loads(project_json_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid project.json: {exc}") from exc

    project = Project(root_path=project_json_path.parent)
    _ensure_project_dirs(project.root_path)
    project.settings = _load_settings(project)

    csv_path = shots_csv_path(project.root_path)
    if csv_path.is_file():
        project.shots = load_shots_csv(csv_path)
    else:
        shots_data = payload.get("shots")
        if isinstance(shots_data, list):
            project.shots = [Shot.from_dict(item) for item in shots_data if isinstance(item, dict)]
        else:
            project.shots = []

    for shot in project.shots:
        _ensure_shot_files(project, shot)

    migrated = _migrate_project_storage(project, payload)
    save_settings(project)
    color = get_canvas_color(project)
    write_canvas_color_files(project, color)
    sync_canvas_color_to_shots(project, color)
    ensure_project_blend_file(project)
    return project


def save_project(project: Project) -> None:
    _ensure_project_dirs(project.root_path)
    if project.settings.get("backup_on_save", True):
        _write_backup(project)
    payload = {"version": PROJECT_JSON_VERSION}
    project.json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    save_shots_csv(project.root_path, project.shots)
    save_settings(project)


def save_settings(project: Project) -> None:
    settings = DEFAULT_SETTINGS.copy()
    settings.update(project.settings)
    project.settings = settings
    project.settings_path.write_text(json.dumps(settings, indent=2), encoding="utf-8")


def add_shot(project: Project, *, after_index: int | None = None) -> Shot:
    shot = Shot(shot_id=new_shot_id())
    _ensure_shot_files(project, shot)
    create_canvas_for_shot(project, shot)
    if after_index is None:
        project.shots.append(shot)
    else:
        _require_index(project, after_index)
        project.shots.insert(after_index + 1, shot)
    return shot


def duplicate_shot(project: Project, index: int) -> Shot:
    _require_index(project, index)
    source = project.shots[index]
    duplicate = Shot.from_dict(source.to_dict())
    duplicate.shot_id = new_shot_id()
    duplicate.title = f"{source.title} Copy".strip()
    duplicate.image_path = ""
    duplicate.preview_image_path = ""
    duplicate.thumbnail_path = ""
    duplicate.source_file_path = ""
    duplicate.annotation_path = ""
    duplicate.reference_image_paths = []
    duplicate.comments = []
    _ensure_shot_files(project, duplicate)
    project.shots.insert(index + 1, duplicate)
    create_canvas_for_shot(project, duplicate)
    return duplicate


def delete_shot(project: Project, index: int) -> Shot:
    _require_index(project, index)
    return project.shots.pop(index)


def move_shot_up(project: Project, index: int) -> int:
    _require_index(project, index)
    if index <= 0:
        return index
    project.shots[index - 1], project.shots[index] = project.shots[index], project.shots[index - 1]
    return index - 1


def move_shot_down(project: Project, index: int) -> int:
    _require_index(project, index)
    if index >= len(project.shots) - 1:
        return index
    project.shots[index + 1], project.shots[index] = project.shots[index], project.shots[index + 1]
    return index + 1


def import_image_for_shot(project: Project, shot: Shot, source_path: Path) -> Path:
    shot_dir = get_shot_dir(project, shot)
    destination = shot_dir / f"{shot.shot_id}_preview.png"
    copied_path = copy_and_convert_image(source_path, destination)
    _set_shot_preview_paths(project, shot, copied_path)
    return copied_path


def import_image_stream_for_shot(
    project: Project,
    shot: Shot,
    source_stream: BinaryIO,
    source_suffix: str,
) -> Path:
    shot_dir = get_shot_dir(project, shot)
    destination = shot_dir / f"{shot.shot_id}_preview.png"
    copied_path = copy_and_convert_image_stream(source_stream, source_suffix, destination)
    _set_shot_preview_paths(project, shot, copied_path)
    return copied_path


def remove_image_for_shot(shot: Shot) -> None:
    shot.image_path = ""
    shot.preview_image_path = ""
    shot.thumbnail_path = ""


def add_reference_image_stream(
    project: Project,
    shot: Shot,
    source_stream: BinaryIO,
    source_suffix: str,
) -> Path:
    shot_dir = get_shot_dir(project, shot)
    ref_dir = shot_dir / "references"
    next_number = len(shot.reference_image_paths) + 1
    destination = ref_dir / f"{shot.shot_id}_ref_{next_number:03d}.png"
    copied_path = copy_and_convert_image_stream(source_stream, source_suffix, destination)
    shot.reference_image_paths.append(copied_path.relative_to(project.root_path).as_posix())
    return copied_path


def import_source_file_stream(
    project: Project,
    shot: Shot,
    source_stream: BinaryIO,
    filename: str,
) -> Path:
    suffix = Path(filename).suffix or ".psd"
    shot_dir = get_shot_dir(project, shot)
    destination = shot_dir / f"{shot.shot_id}{suffix}"
    with destination.open("wb") as file:
        shutil.copyfileobj(source_stream, file)
    shot.source_file_path = destination.relative_to(project.root_path).as_posix()
    if is_psd_path(destination):
        preview_path = export_psd_composite_to_png(destination, shot_dir / f"{shot.shot_id}_preview.png")
        _set_shot_preview_paths(project, shot, preview_path)
    shot.source_sync_mtime = linked_mtime(project, shot)
    return destination


def relink_preview_image(project: Project, shot: Shot, relative_path: str) -> Path:
    candidate = (project.root_path / relative_path).resolve()
    root = project.root_path.resolve()
    if root not in candidate.parents and candidate != root:
        raise ValueError("Preview path must be inside the project folder.")
    if not candidate.exists() or not candidate.is_file():
        raise FileNotFoundError(f"Preview image not found: {relative_path}")
    shot.preview_image_path = candidate.relative_to(project.root_path).as_posix()
    shot.image_path = shot.preview_image_path
    thumbnail_path = create_thumbnail(candidate, get_shot_dir(project, shot) / f"{shot.shot_id}_thumb.png")
    shot.thumbnail_path = thumbnail_path.relative_to(project.root_path).as_posix()
    return candidate


def create_canvas_for_shot(
    project: Project,
    shot: Shot,
    width: int = 1920,
    height: int = 1080,
    background_color: str | None = None,
) -> Path:
    shot_dir = get_shot_dir(project, shot)
    color = persist_canvas_color(
        project,
        background_color or get_canvas_color(project),
    )
    psd_path = create_blank_psd(
        shot_dir / f"{shot.shot_id}.psd",
        width,
        height,
        background_color=color,
    )
    preview_path = create_solid_preview_png(
        shot_dir / f"{shot.shot_id}_preview.png",
        width,
        height,
        color,
    )
    _set_shot_canvas_thumbnail(project, shot, preview_path)
    shot.source_file_path = psd_path.relative_to(project.root_path).as_posix()
    shot.source_sync_mtime = linked_mtime(project, shot)
    write_canvas_color_files(project, color, shot)
    return psd_path


def write_bridge_file(project: Project, shot: Shot | None = None) -> None:
    write_canvas_color_files(project, get_canvas_color(project), shot)


def save_drawing_for_shot(project: Project, shot: Shot, data_url: str) -> Path:
    shot_dir = get_shot_dir(project, shot)
    preview_path = save_png_data_url(data_url, shot_dir / f"{shot.shot_id}_preview.png")
    _set_shot_preview_paths(project, shot, preview_path)
    return preview_path


def sync_shot(project: Project, shot: Shot, force: bool = False) -> dict[str, object]:
    return sync_shot_from_linked_files(project, shot, force=force)


def open_project_file(
    project: Project,
    relative_path: str,
    app_path: str = "",
    shot: Shot | None = None,
) -> Path:
    if shot is not None:
        write_bridge_file(project, shot)
    file_path = (project.root_path / relative_path).resolve()
    root = project.root_path.resolve()
    if root not in file_path.parents and file_path != root:
        raise ValueError("File path must be inside the project folder.")
    if not file_path.exists() or not file_path.is_file():
        raise FileNotFoundError(f"File not found: {relative_path}")
    if app_path:
        configured_app = Path(app_path).expanduser()
        if not configured_app.exists():
            raise FileNotFoundError(f"Configured editor not found: {configured_app}")
        subprocess.Popen([str(configured_app), str(file_path)])
    elif sys.platform.startswith("win"):
        os.startfile(file_path)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(file_path)])
    else:
        subprocess.Popen(["xdg-open", str(file_path)])
    return file_path


def get_shot_dir(project: Project, shot: Shot) -> Path:
    return project.shots_dir / shot.shot_id


def _require_index(project: Project, index: int) -> None:
    if index < 0 or index >= len(project.shots):
        raise IndexError("Shot index out of range.")


SCENE3D_EXTENSIONS = {".glb", ".gltf"}


def blend_template_path() -> Path:
    return BLEND_TEMPLATE_PATH


def get_project_blend_path(project: Project) -> Path:
    return project.root_path / "scene3d" / "scene.blend"


def ensure_project_blend_file(project: Project) -> Path:
    """Copy bundled scene_template.blend into the project when scene.blend is missing."""
    scene_dir = project.root_path / "scene3d"
    scene_dir.mkdir(parents=True, exist_ok=True)
    blend_path = get_project_blend_path(project)
    if not blend_path.exists():
        template = blend_template_path()
        if template.is_file():
            shutil.copy2(template, blend_path)
    scene_settings = dict(project.settings.get("scene3d") or {})
    if blend_path.exists():
        scene_settings["blend_file_path"] = blend_path.relative_to(project.root_path).as_posix()
    project.settings["scene3d"] = scene_settings
    save_settings(project)
    return blend_path


def open_blender_scene(project: Project) -> Path:
    from .system_utils import detect_blender_paths, resolve_blender_executable

    blend_path = ensure_project_blend_file(project)
    if not blend_path.exists():
        template = blend_template_path()
        if not template.is_file():
            raise FileNotFoundError(
                "scene3d/scene.blend is missing and no template was found. "
                "Place scene_template.blend in storyboard_tool/assets/."
            )
    blender_path = str(project.settings.get("blender_path", "")).strip()
    if not blender_path:
        candidates = detect_blender_paths()
        if candidates:
            blender_path = candidates[0]
    if not blender_path:
        raise FileNotFoundError("Blender path not configured. Open Blender Setup and choose blender.exe.")
    try:
        configured = resolve_blender_executable(blender_path)
    except (FileNotFoundError, ValueError) as exc:
        raise FileNotFoundError(str(exc)) from exc
    args = [str(configured)]
    if blend_path.exists():
        args.append(str(blend_path.resolve()))
    subprocess.Popen(args)
    return blend_path


def import_scene3d_stream(project: Project, source_stream: BinaryIO, filename: str) -> dict:
    suffix = Path(filename).suffix.lower()
    if suffix not in SCENE3D_EXTENSIONS:
        raise ValueError("Only .glb and .gltf Blender exports are supported.")
    scene_dir = project.root_path / "scene3d"
    scene_dir.mkdir(exist_ok=True)
    destination = scene_dir / f"scene{suffix}"
    with destination.open("wb") as file:
        shutil.copyfileobj(source_stream, file)
    relative_path = destination.relative_to(project.root_path).as_posix()
    scene_settings = dict(project.settings.get("scene3d") or {})
    scene_settings.update(
        {
            "source": "blender",
            "file_path": relative_path,
            "file_name": Path(filename).name,
        }
    )
    project.settings["scene3d"] = scene_settings
    save_settings(project)
    return scene_settings


def get_scene3d_file_path(project: Project) -> Path | None:
    relative_path = str((project.settings.get("scene3d") or {}).get("file_path", "")).strip()
    if not relative_path:
        return None
    candidate = (project.root_path / relative_path).resolve()
    root = project.root_path.resolve()
    if root not in candidate.parents and candidate != root:
        raise ValueError("Scene file path must be inside the project folder.")
    if not candidate.exists() or not candidate.is_file():
        raise FileNotFoundError(f"Scene file not found: {relative_path}")
    return candidate


def _ensure_project_dirs(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for dirname in ("shots", "references", "exports", "scripts", "backups", "scene3d"):
        (root / dirname).mkdir(exist_ok=True)


def _ensure_shot_files(project: Project, shot: Shot) -> None:
    shot_dir = get_shot_dir(project, shot)
    shot_dir.mkdir(parents=True, exist_ok=True)
    (shot_dir / "references").mkdir(exist_ok=True)
    if not shot.annotation_path:
        annotation_path = shot_dir / f"{shot.shot_id}_annotations.json"
        if not annotation_path.exists():
            annotation_path.write_text("[]", encoding="utf-8")
        shot.annotation_path = annotation_path.relative_to(project.root_path).as_posix()
    notes_path = shot_dir / f"{shot.shot_id}_notes.json"
    if not notes_path.exists():
        notes_path.write_text(json.dumps(shot.to_dict(), indent=2), encoding="utf-8")


def _set_shot_preview_paths(project: Project, shot: Shot, preview_path: Path) -> None:
    shot.image_path = preview_path.relative_to(project.root_path).as_posix()
    shot.preview_image_path = shot.image_path
    thumbnail_path = create_thumbnail(preview_path, get_shot_dir(project, shot) / f"{shot.shot_id}_thumb.png")
    shot.thumbnail_path = thumbnail_path.relative_to(project.root_path).as_posix()


def _set_shot_canvas_thumbnail(project: Project, shot: Shot, preview_path: Path) -> None:
    """Keep the in-app canvas on the configured color until Photoshop sync adds artwork."""
    thumbnail_path = create_thumbnail(preview_path, get_shot_dir(project, shot) / f"{shot.shot_id}_thumb.png")
    shot.thumbnail_path = thumbnail_path.relative_to(project.root_path).as_posix()
    shot.preview_image_path = ""
    shot.image_path = ""


def _load_settings(project: Project) -> dict:
    if not project.settings_path.exists():
        return DEFAULT_SETTINGS.copy()
    try:
        loaded = json.loads(project.settings_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return DEFAULT_SETTINGS.copy()
    settings = DEFAULT_SETTINGS.copy()
    if isinstance(loaded, dict):
        settings.update(loaded)
    return settings


def _migrate_project_storage(project: Project, payload: dict) -> bool:
    version = int(payload.get("version", 1) or 1)
    has_inline_shots = isinstance(payload.get("shots"), list)
    csv_path = shots_csv_path(project.root_path)
    needs_csv = not csv_path.is_file() or has_inline_shots or version < PROJECT_JSON_VERSION
    if not needs_csv:
        return False
    save_project(project)
    return True


def _write_backup(project: Project) -> None:
    project.backups_dir.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if project.json_path.is_file():
        shutil.copy2(project.json_path, project.backups_dir / f"project_{stamp}.json")
    csv_path = shots_csv_path(project.root_path)
    if csv_path.is_file():
        shutil.copy2(csv_path, project.backups_dir / f"shots_{stamp}.csv")
