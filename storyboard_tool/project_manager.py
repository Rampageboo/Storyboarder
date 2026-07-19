"""Project management — the single backend entry point for all project I/O.

Storage boundary
----------------
Canonical store:
  project.json   — lightweight manifest (version key only; NO inline shots).
  shots.json     — all shot metadata; the source of truth.  Written atomically
                   by save_shots_json / save_shots.  Read first in open_project.
  settings.json  — project-wide settings (canvas size, color, paths, etc.).

Compatibility / generated outputs:
  shots.csv      — regenerated from shots.json on every save.  Human-readable
                   export surface and legacy fallback for old projects.  Ignored
                   by open_project when shots.json is present.
  canvas_color.txt / storyboard_bridge.json — generated from settings for the
                   Photoshop plugin's file-based IPC.  Not read as metadata.

Asset files (never in project metadata):
  shots/<id>/<id>_preview.png  — artist artwork; set via relink_preview_image.
  shots/<id>/<id>_background.png — reference plate; owned by plugin SB bg layer.
  shots/<id>/<id>_thumb.png    — display cache; regenerated on demand.
  shots/<id>/<id>.psd          — source canvas; path stored in source_file_path.

Ownership rules:
  - Backend is the SOLE WRITER of canonical project metadata in linked mode.
  - Plugin may write shots.csv / project.json only in standalone/offline mode
    (enforced by panel_storage_adapter.js; see FALLBACK-OFFLINE-ONLY comments).
  - image_path / preview_image_path must never point to _background.png.
  - source_file_path must always be a .psd path.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
from pathlib import Path
from typing import Any, BinaryIO

from .image_utils import (
    board_background_filename,
    compose_image_to_canvas,
    copy_and_convert_image,
    copy_and_convert_image_stream,
    export_psd_composite_to_png,
    is_psd_path,
    normalize_reference_fit_mode,
    save_png_data_url,
)
from .linked_sync import linked_mtime, sync_shot_from_linked_files
from .models import Project, Shot
from . import project_document
from .shot_store import (
    load_shots_csv,
    load_shots_json,
    new_shot_id,
    save_shots,
    save_shots_json,
    shots_csv_path,
    shots_json_path,
)

# ── Boundary modules extracted from this file ────────────────────────────────
# These modules were factored out of project_manager.py to reduce its scope.
# Their public names are imported here so all existing callers can continue to
# use ``project_manager.<name>`` unchanged.

from .project_storage import (  # noqa: E402
    PROJECT_JSON_VERSION,
    DEFAULT_SETTINGS,
    ensure_project_dirs as _ensure_project_dirs,
    atomic_write_json as _atomic_write_json,
    atomic_write_text as _atomic_write_text,
    load_settings as _load_settings,
    save_settings,
    project_disk_mtime,
)
from .shot_files import (  # noqa: E402
    get_shot_dir,
    shot_has_psd_canvas,
    resolve_project_relative_path,
)
from .shot_assets import (  # noqa: E402
    get_shot_board_background_path,
    get_shot_codex_layer_path,
    remove_board_background_for_shot,
    remove_codex_layer_for_shot,
    relink_preview_image,
    relink_shot_preview_from_disk,
    render_shot_composite_image,
    resolve_shot_preview_path,
    resolve_shot_thumbnail_path,
    save_codex_layer_from_path,
    _set_shot_preview_paths,
    _save_board_background_copy,
    _refresh_thumbnail_for_shot,
)
from .asset_validation import validate_project_integrity  # noqa: E402


# Process-wide reentrant lock serializing project persistence. The FastAPI backend
# services sync endpoints on a threadpool and also runs background threads (bridge
# refresh, preview analysis, plugin heartbeats), so more than one thread can reach
# save_project concurrently. save_project writes several files (project.json,
# shots.json, shots.csv, settings.json) plus a backup set; without serialization two
# concurrent saves can interleave and leave shots.json and shots.csv describing
# different states. Hold this lock around any full persistence pass, and reuse it to
# guard the reload-on-read swap in app_state so a save can't be torn by a reload.
PROJECT_LOCK = threading.RLock()


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


def create_document(
    document_path: Path,
    *,
    canvas_width: int = 1920,
    canvas_height: int = 1080,
) -> Project:
    """Create a user-visible single-file project backed by a private work tree."""
    document = document_path.expanduser().resolve()
    if document.suffix.lower() != project_document.DOCUMENT_SUFFIX:
        document = document.with_suffix(project_document.DOCUMENT_SUFFIX)
    if document.exists():
        raise ValueError(f"A file already exists at: {document}")
    root = project_document.create_working_root(document)
    _ensure_project_dirs(root)
    width, height = normalize_canvas_size(canvas_width, canvas_height)
    settings = DEFAULT_SETTINGS.copy()
    settings["canvas_width"] = width
    settings["canvas_height"] = height
    project = Project(root_path=root, settings=settings, document_path=document)
    save_project(project)
    ensure_project_blend_file(project)
    save_project(project)
    return project


def reload_project_if_changed(project: Project, loaded_mtime: float) -> tuple[Project, float, bool]:
    """Reload project.json from disk when the plugin or another tool updated it."""
    disk_mtime = project_disk_mtime(project)
    if disk_mtime <= loaded_mtime + 1e-6:
        return project, loaded_mtime, False
    reloaded = open_project(project.json_path)
    reloaded.document_path = project.document_path
    return reloaded, disk_mtime, True


def open_project(project_json_path: Path) -> Project:
    if project_json_path.suffix.lower() == project_document.DOCUMENT_SUFFIX:
        document_path = project_json_path.expanduser().resolve()
        working_root = project_document.extract_document(document_path)
        try:
            project = _open_expanded_project(working_root / "project.json")
        except Exception:
            shutil.rmtree(working_root, ignore_errors=True)
            raise
        project.document_path = document_path
        return project
    return _open_expanded_project(project_json_path)


def _open_expanded_project(project_json_path: Path) -> Project:
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

    # ── Shot load priority (storage boundary) ──────────────────────────────
    # 1. shots.json  — canonical; always preferred when it exists.
    # 2. shots.csv   — COMPAT-READ: legacy projects only; once shots.json is
    #                  written, CSV is ignored for loading on subsequent opens.
    # 3. project.json "shots" key — COMPAT-READ: very old projects; no current
    #                  code path writes inline shots here.
    # 4. Empty list  — brand-new project.
    # Migration is non-destructive: it only ADDS shots.json; it never deletes
    # the legacy sources (CSV, inline shots) until the project is saved normally.
    json_path = shots_json_path(project.root_path)
    csv_path = shots_csv_path(project.root_path)
    needs_json_migration = False
    if json_path.is_file():
        # Canonical path — shots.csv is intentionally not consulted.
        project.shots = load_shots_json(json_path) or []
    elif csv_path.is_file():
        # COMPAT-READ: legacy CSV-only project; migrate to shots.json below.
        project.shots = load_shots_csv(csv_path)
        needs_json_migration = True
    else:
        # COMPAT-READ: very old project.json with inline shots key.
        shots_data = payload.get("shots")
        if isinstance(shots_data, list):
            project.shots = [Shot.from_dict(item) for item in shots_data if isinstance(item, dict)]
            needs_json_migration = True
        else:
            project.shots = []

    for shot in project.shots:
        _ensure_shot_files(project, shot)

    # Non-destructive migration: write the canonical shots.json so future opens
    # take the canonical path. Legacy sources (CSV, inline shots) are left on
    # disk until a full save_project() call regenerates them from canonical data.
    if needs_json_migration:
        save_shots_json(project.root_path, project.shots)
    save_settings(project)
    color = get_canvas_color(project)
    write_canvas_color_files(project, color)
    sync_canvas_color_to_shots(project, color)
    ensure_project_blend_file(project)
    return project


def save_project(project: Project) -> None:
    with PROJECT_LOCK:
        _ensure_project_dirs(project.root_path)
        if project.settings.get("backup_on_save", True):
            _write_backup(project)
        # project.json is a lightweight manifest (version only); shots live in shots.json.
        _atomic_write_json(project.json_path, {"version": PROJECT_JSON_VERSION})
        # Canonical shots.json + regenerated readable shots.csv compatibility snapshot.
        # Serialize a snapshot (list copy) so both files describe the same shot ordering
        # even if another thread mutates project.shots between the two writes.
        save_shots(project.root_path, list(project.shots))
        save_settings(project)
        if project.document_path:
            project_document.pack_document(project.root_path, project.document_path)


def sync_document(project: Project) -> None:
    """Flush direct asset/index writes into the visible document, when applicable."""
    if not project.document_path:
        return
    with PROJECT_LOCK:
        project_document.pack_document(project.root_path, project.document_path)


def cleanup_document_working_root(project: Project | None) -> bool:
    """Best-effort removal of a private expanded `.sbd` work tree."""
    if project is None or not project.document_path:
        return False
    root = project.root_path.resolve()
    temp_root = Path(tempfile.gettempdir()).resolve()
    if root.parent != temp_root or not root.name.startswith("storyboarder-"):
        return False
    try:
        shutil.rmtree(root)
    except OSError:
        return False
    return True


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


def sync_psd_board_background(project: Project, shot: Shot, psd_path: Path) -> bool:
    # The Photoshop plugin now OWNS the in-PSD `SB bg` layer and maintains it as a
    # linked smart object pointing at `<shot>_background.png`. The backend must not
    # bake a raster `SB bg` into the PSD here, for two reasons:
    #   1. A psd_tools raster layer is not a smart object and collides with /
    #      overwrites the plugin's linked layer, so the artist's PSD opens unlinked.
    #   2. `ensure_psd_board_background_layer` re-opens and `psd.save()`s the file
    #      via psd_tools; that round-trip rasterises (destroys) any linked smart
    #      object the plugin already saved, and is a prime suspect for the
    #      "PSD won't reopen" corruption.
    # The reference image itself still lives on disk as `<shot>_background.png`
    # (written by `_save_board_background_copy`); the plugin's linked smart object
    # picks up changes from that file. So there is nothing for the backend to do.
    return False


def recover_shot_source_psd(project: Project, shot: Shot, *, preserve_layers: bool = True) -> dict[str, Any]:
    """Rebuild a Photoshop-unopenable source PSD from its own layers.

    Backs the unreadable file up under the shot's ``_history`` folder, rebuilds a
    clean PSD in place, and refreshes the preview + thumbnail. ``preserve_layers``
    keeps the original layer data (blend modes, opacity, masks, text); pass False
    to force a flattened rebuild when the layer-preserving one still won't open.
    Raises ValueError/FileNotFoundError when recovery is not possible so the
    caller can fall back to a fresh canvas.
    """
    import os
    import time

    from . import psd_recovery

    if not shot.source_file_path:
        raise ValueError("No source PSD linked for this shot.")
    source = project.root_path / shot.source_file_path
    if not source.is_file():
        raise FileNotFoundError("Source PSD file is missing.")
    if not psd_recovery.can_open_with_psd_tools(source):
        raise ValueError("The PSD is too damaged to read — it cannot be rebuilt.")

    shot_dir = get_shot_dir(project, shot)
    history = shot_dir / "_history"
    history.mkdir(parents=True, exist_ok=True)
    backup = history / f"{shot.shot_id}.broken-{int(time.time())}.psd"
    shutil.copy2(source, backup)
    # PSD recovery is now rare (the old plugin's forced-save corruption that required it
    # is fixed), so keep only the most recent few broken-PSD backups. Best-effort.
    try:
        broken = sorted(
            history.glob(f"{shot.shot_id}.broken-*.psd"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for stale in broken[3:]:
            stale.unlink(missing_ok=True)
    except Exception:
        pass

    # Rebuild to a temp file first, then atomically swap it over the source so a
    # failed rebuild never destroys the (still backed-up) original.
    temp = shot_dir / f"{shot.shot_id}.rebuilt.psd"
    info = psd_recovery.rebuild_psd(source, temp, preserve_layers=preserve_layers)
    os.replace(temp, source)

    preview_path = shot_dir / f"{shot.shot_id}_preview.png"
    export_psd_composite_to_png(source, preview_path)
    _set_shot_preview_paths(project, shot, preview_path)
    shot.source_sync_mtime = linked_mtime(project, shot)

    return {
        "backup": backup.relative_to(project.root_path).as_posix(),
        "method": info.get("method", "flatten"),
        "layers_recovered": info["layers_recovered"],
        "layers_skipped": info["layers_skipped"],
        "width": info["width"],
        "height": info["height"],
    }


def _apply_reference_frame_to_shot(
    project: Project,
    shot: Shot,
    source_path: Path,
    fit_mode: str,
) -> Path:
    """Write a reference frame as the board background plate only.

    This never touches ``<shot_id>_preview.png`` (the artist's drawing) or
    ``source_file_path`` / PSD metadata.  The background file is written
    atomically via a temp file so a failed compose leaves the previous
    background intact.  Provenance metadata (ref_segment_id, etc.) is stamped
    by the caller after this returns.
    """
    from PIL import Image

    width, height = get_canvas_size(project)
    bg_color = get_canvas_color(project)
    shot_dir = get_shot_dir(project, shot)
    background_path = shot_dir / board_background_filename(shot.shot_id)
    background_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = background_path.with_suffix(".tmp.png")
    try:
        with Image.open(source_path) as image:
            composed = compose_image_to_canvas(image, width, height, fit_mode, bg_color)
            composed.save(tmp_path, "PNG")
        # Validate: ensure the temp file is a readable PNG before committing.
        with Image.open(tmp_path):
            pass
        os.replace(tmp_path, background_path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
    _refresh_thumbnail_for_shot(project, shot)
    return background_path


def _apply_model_capture_to_shot(
    project: Project,
    shot: Shot,
    source_path: Path,
    fit_mode: str,
) -> Path:
    """Write a browser-rendered GLB capture as the board background plate only.

    When the PNG already matches project canvas dimensions, pixels are preserved
    exactly (no compose pass that can shift colors).  Smaller captures go through
    the compose path.  Like ``_apply_reference_frame_to_shot``, this never writes
    ``_preview.png`` or changes ``source_file_path``.
    """
    from PIL import Image

    width, height = get_canvas_size(project)
    shot_dir = get_shot_dir(project, shot)
    background_path = shot_dir / board_background_filename(shot.shot_id)
    mode = normalize_reference_fit_mode(fit_mode)
    background_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = background_path.with_suffix(".tmp.png")
    try:
        with Image.open(source_path) as image:
            if image.size == (width, height) and mode in {"fit", "stretch"}:
                rgb = image.convert("RGB")
                rgb.save(tmp_path, "PNG")
            else:
                bg_color = get_canvas_color(project)
                composed = compose_image_to_canvas(image, width, height, mode, bg_color)
                composed.save(tmp_path, "PNG")
        with Image.open(tmp_path):
            pass
        os.replace(tmp_path, background_path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
    _refresh_thumbnail_for_shot(project, shot)
    return background_path


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
    tmp = destination.with_suffix(suffix + ".tmp")
    try:
        with tmp.open("wb") as file:
            shutil.copyfileobj(source_stream, file)
        os.replace(tmp, destination)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    shot.source_file_path = destination.relative_to(project.root_path).as_posix()
    if is_psd_path(destination):
        preview_path = export_psd_composite_to_png(destination, shot_dir / f"{shot.shot_id}_preview.png")
        _set_shot_preview_paths(project, shot, preview_path)
    shot.source_sync_mtime = linked_mtime(project, shot)
    return destination


def save_drawing_for_shot(project: Project, shot: Shot, data_url: str) -> Path:
    shot_dir = get_shot_dir(project, shot)
    preview_path = save_png_data_url(data_url, shot_dir / f"{shot.shot_id}_preview.png")
    _set_shot_preview_paths(project, shot, preview_path)
    return preview_path


def sync_shot(project: Project, shot: Shot, force: bool = False) -> dict[str, object]:
    return sync_shot_from_linked_files(project, shot, force=force)


def _require_index(project: Project, index: int) -> None:
    if index < 0 or index >= len(project.shots):
        raise IndexError("Shot index out of range.")


def _ensure_shot_files(project: Project, shot: Shot) -> None:
    shot_dir = get_shot_dir(project, shot)
    shot_dir.mkdir(parents=True, exist_ok=True)
    (shot_dir / "references").mkdir(exist_ok=True)
    if not shot.annotation_path:
        annotation_path = shot_dir / f"{shot.shot_id}_annotations.json"
        if not annotation_path.exists():
            _atomic_write_text(annotation_path, "[]")
        shot.annotation_path = annotation_path.relative_to(project.root_path).as_posix()
    notes_path = shot_dir / f"{shot.shot_id}_notes.json"
    if not notes_path.exists():
        notes_path.write_text(json.dumps(shot.to_dict(), indent=2), encoding="utf-8")
    relink_shot_preview_from_disk(project, shot)


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
    clear_active_reference_image,
    clear_active_reference_model,
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
    restore_boards_from_undo,
    snapshot_boards_for_undo,
    set_active_reference_image,
    set_active_reference_model,
    set_active_reference_video,
    sync_ref_segment_settings,
    update_ref_segment_video_start,
)
