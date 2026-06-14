from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, BinaryIO

from .image_utils import (
    board_background_filename,
    compose_image_to_canvas,
    copy_and_convert_image,
    copy_and_convert_image_stream,
    create_thumbnail,
    ensure_psd_board_background_layer,
    export_psd_composite_to_png,
    is_psd_path,
    is_solid_color_image,
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
    "canvas_width": 1920,
    "canvas_height": 1080,
    "reference_video_path": "",
    "reference_model_path": "",
    "reference_image_path": "",
    "reference_segment_mode": "video",
    "reference_links": [],
    "ref_segment": {},
    "ref_segments": [],
    "active_ref_segment_id": "",
    "ref_segment_video": {},
    "ref_segment_apply": {},
}


def create_project(
    parent_or_project_dir: Path,
    *,
    canvas_width: int = 1920,
    canvas_height: int = 1080,
) -> Project:
    root = parent_or_project_dir
    if root.name != "Storyboard_Project":
        root = root / "Storyboard_Project"

    root.mkdir(parents=True, exist_ok=True)
    _ensure_project_dirs(root)

    width, height = normalize_canvas_size(canvas_width, canvas_height)
    settings = DEFAULT_SETTINGS.copy()
    settings["canvas_width"] = width
    settings["canvas_height"] = height
    project = Project(root_path=root, settings=settings)
    save_project(project)
    ensure_project_blend_file(project)
    return project


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
    sync_ref_segment_settings(project)

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
    duplicate.ref_video_path = ""
    duplicate.ref_video_time = 0.0
    duplicate.ref_segment_time = 0.0
    duplicate.comments = []
    _ensure_shot_files(project, duplicate)
    project.shots.insert(index + 1, duplicate)
    create_canvas_for_shot(project, duplicate)
    return duplicate


def delete_shot(project: Project, index: int) -> Shot:
    _require_index(project, index)
    return project.shots.pop(index)


def restore_shot(project: Project, shot_data: dict[str, Any], index: int) -> Shot:
    index = max(0, min(int(index), len(project.shots)))
    shot = Shot.from_dict(shot_data)
    if any(existing.shot_id == shot.shot_id for existing in project.shots):
        raise ValueError(f"Shot already exists: {shot.shot_id}")
    project.shots.insert(index, shot)
    return shot


def reorder_shots(project: Project, shot_ids: list[str]) -> None:
    by_id = {shot.shot_id: shot for shot in project.shots}
    if len(shot_ids) != len(project.shots) or set(shot_ids) != set(by_id.keys()):
        raise ValueError("Shot order mismatch")
    project.shots = [by_id[shot_id] for shot_id in shot_ids]


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
    _save_board_background_copy(copied_path, shot_dir / board_background_filename(shot.shot_id))
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
    _save_board_background_copy(copied_path, shot_dir / board_background_filename(shot.shot_id))
    _set_shot_preview_paths(project, shot, copied_path)
    return copied_path


def remove_image_for_shot(project: Project, shot: Shot) -> None:
    shot_dir = get_shot_dir(project, shot)
    (shot_dir / board_background_filename(shot.shot_id)).unlink(missing_ok=True)
    shot.image_path = ""
    shot.preview_image_path = ""
    shot.thumbnail_path = ""


def get_shot_board_background_path(project: Project, shot: Shot) -> Path | None:
    shot_dir = get_shot_dir(project, shot)
    dedicated = shot_dir / board_background_filename(shot.shot_id)
    if dedicated.is_file():
        return dedicated
    preview_rel = shot.preview_image_path or shot.image_path
    if not preview_rel:
        return None
    preview = project.root_path / preview_rel
    if not preview.is_file() or is_solid_color_image(preview):
        return None
    return preview


def sync_psd_board_background(project: Project, shot: Shot, psd_path: Path) -> bool:
    background_path = get_shot_board_background_path(project, shot)
    if background_path is None:
        return False
    return ensure_psd_board_background_layer(psd_path, background_path)


def _save_board_background_copy(source_path: Path, destination_path: Path) -> Path:
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    if source_path.resolve() == destination_path.resolve():
        return destination_path
    shutil.copy2(source_path, destination_path)
    return destination_path


def _apply_reference_frame_to_shot(
    project: Project,
    shot: Shot,
    source_path: Path,
    fit_mode: str,
) -> Path:
    from PIL import Image

    width, height = get_canvas_size(project)
    bg_color = get_canvas_color(project)
    shot_dir = get_shot_dir(project, shot)
    preview_path = shot_dir / f"{shot.shot_id}_preview.png"
    with Image.open(source_path) as image:
        composed = compose_image_to_canvas(image, width, height, fit_mode, bg_color)
        composed.save(preview_path, "PNG")
    _save_board_background_copy(preview_path, shot_dir / board_background_filename(shot.shot_id))
    _set_shot_preview_paths(project, shot, preview_path)
    return preview_path


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


def _normalize_rel_path(path: str) -> str:
    return str(path or "").replace("\\", "/").strip()


def collect_reference_image_paths(project: Project) -> set[str]:
    referenced: set[str] = set()
    for shot in project.shots:
        for rel_path in shot.reference_image_paths:
            normalized = _normalize_rel_path(rel_path)
            if normalized:
                referenced.add(normalized)
    return referenced


def remove_reference_image(project: Project, shot: Shot, rel_path: str) -> None:
    normalized = _normalize_rel_path(rel_path)
    if not normalized:
        raise ValueError("Reference path is required.")
    current = {_normalize_rel_path(path) for path in shot.reference_image_paths}
    if normalized not in current:
        raise ValueError("Reference image not found on this board.")
    shot.reference_image_paths = [
        path for path in shot.reference_image_paths if _normalize_rel_path(path) != normalized
    ]


def set_reference_image_paths(project: Project, shot: Shot, paths: list[str]) -> None:
    shot.reference_image_paths = [
        _normalize_rel_path(path) for path in paths if _normalize_rel_path(path)
    ]


def cleanup_orphan_reference_images(project: Project) -> list[str]:
    root = project.root_path.resolve()
    referenced = collect_reference_image_paths(project)
    deleted: list[str] = []
    shots_dir = project.shots_dir
    if not shots_dir.is_dir():
        return deleted
    for ref_dir in shots_dir.glob("*/references"):
        if not ref_dir.is_dir():
            continue
        for file_path in ref_dir.iterdir():
            if not file_path.is_file():
                continue
            try:
                rel_path = file_path.relative_to(root).as_posix()
            except ValueError:
                continue
            if rel_path in referenced:
                continue
            file_path.unlink(missing_ok=True)
            deleted.append(rel_path)
    return deleted


def shutdown_reference_cleanup(project: Project | None, *, save_if_dirty: bool = True, dirty: bool = False) -> list[str]:
    if project is None:
        return []
    if save_if_dirty and dirty:
        save_project(project)
    return cleanup_orphan_reference_images(project)


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


def save_drawing_for_shot(project: Project, shot: Shot, data_url: str) -> Path:
    shot_dir = get_shot_dir(project, shot)
    preview_path = save_png_data_url(data_url, shot_dir / f"{shot.shot_id}_preview.png")
    _set_shot_preview_paths(project, shot, preview_path)
    return preview_path


def sync_shot(project: Project, shot: Shot, force: bool = False) -> dict[str, object]:
    return sync_shot_from_linked_files(project, shot, force=force)


def get_shot_dir(project: Project, shot: Shot) -> Path:
    return project.shots_dir / shot.shot_id


def _require_index(project: Project, index: int) -> None:
    if index < 0 or index >= len(project.shots):
        raise IndexError("Shot index out of range.")


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
    settings["reference_links"] = normalize_reference_links(settings.get("reference_links"))
    ensure_reference_library(settings)
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


# ---------------------------------------------------------------------------
# Backward-compatible facade.
#
# The implementations below were extracted into focused domain modules during a
# controlled refactor. They are re-imported here so existing callers can keep
# using ``project_manager.<name>`` unchanged. project_manager remains the single
# import entry point; the submodules reach back into it via ``import
# project_manager as pm`` for the shared low-level helpers defined above.
# ---------------------------------------------------------------------------

from .backups import _write_backup  # noqa: E402

from .canvas_settings import (  # noqa: E402
    create_canvas_for_shot,
    get_canvas_color,
    get_canvas_size,
    normalize_canvas_size,
    persist_canvas_color,
    persist_canvas_size,
    shot_has_artwork_preview,
    shot_is_blank_canvas,
    sync_canvas_color_to_shots,
    write_bridge_file,
    write_canvas_color_files,
)

from .external_tools import (  # noqa: E402
    BLEND_TEMPLATE_PATH,
    SCENE3D_EXTENSIONS,
    blend_template_path,
    ensure_project_blend_file,
    get_project_blend_path,
    get_scene3d_file_path,
    import_scene3d_stream,
    open_blender_scene,
    open_project_file,
)

from .reference_segments import (  # noqa: E402
    REFERENCE_IMAGE_EXTENSIONS,
    REFERENCE_MODEL_EXTENSIONS,
    REFERENCE_VIDEO_EXTENSIONS,
    apply_ref_segment_3d_to_boards,
    apply_ref_segment_image_to_boards,
    apply_ref_segment_to_boards,
    clear_active_reference_video,
    delete_ref_segment,
    ensure_reference_library,
    find_ref_segment,
    import_project_reference_stream,
    import_reference_video_stream,
    new_ref_segment_id,
    normalize_ref_segments,
    normalize_reference_links,
    reference_media_type,
    remove_project_reference,
    resolve_segment_reference,
    set_active_reference_image,
    set_active_reference_model,
    set_active_reference_video,
    sync_ref_segment_settings,
    update_ref_segment_video_start,
)
