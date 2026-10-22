"""Project management — the single backend entry point for all project I/O.

Storage boundary (see ``project_document`` for the folder format)
-----------------------------------------------------------------
Canonical metadata, all under ``.storyboarder/data``:
  project.json   — manifest: schema version, project id, storage revision.
  shots.json     — all shot metadata; the source of truth.
  settings.json  — project-wide settings (canvas size, color, paths, etc.).

Generated outputs:
  canvas_color.txt / storyboard_bridge.json — generated from settings for the
                   Photoshop plugin's file-based IPC. Not read as metadata.

Asset files (never in project metadata), relative to the project folder:
  Images/Shots/<id>_preview.png     — artist artwork; set via relink_preview_image.
  Images/Shots/<id>_background.png  — reference plate; owned by plugin SB bg layer.
  PSD/Shots/<id>.psd                — source canvas; path stored in source_file_path.
  .storyboarder/cache/thumbnails/   — display cache; regenerated on demand.

Ownership rules:
  - Backend is the SOLE WRITER of canonical project metadata.
  - image_path / preview_image_path must never point to _background.png.
  - source_file_path must always be a .psd path.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
import threading
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any, BinaryIO

from .file_transactions import atomic_copy_file
from .image_utils import (
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
from . import project_document, story_graph
from .project_layout import (
    parse_project_manifest,
    project_relative_posix,
    project_manifest,
    resolve_project_child,
    resolve_project_path,
    resolve_reference_asset,
    resolve_root_child,
    resolve_shot_asset,
    resolve_shot_metadata,
)
from .shot_store import (
    load_shots_json,
    new_shot_id,
    save_shots_json,
    shots_json_path,
)

# ── Boundary modules extracted from this file ────────────────────────────────
# These modules were factored out of project_manager.py to reduce its scope.
# Their public names are imported here so all existing callers can continue to
# use ``project_manager.<name>`` unchanged.

from .project_storage import (  # noqa: E402
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
# shots.json, settings.json) plus a backup set; without serialization two
# concurrent saves can interleave and leave those files describing different states. Hold this lock around any full persistence pass, and reuse it to
# guard the reload-on-read swap in app_state so a save can't be torn by a reload.
PROJECT_LOCK = threading.RLock()
# Lifecycle transitions first quiesce background writers, then take
# PROJECT_LOCK to drain/freeze request mutations. Keeping a dedicated outer
# lock makes that ordering explicit and prevents two transitions from racing.
PROJECT_TRANSITION_LOCK = threading.RLock()


def validate_project_type(project_type: str) -> str:
    if project_type not in ("video", "comic"):
        raise ValueError("Project type must be video or comic.")
    return project_type


def _creation_paths(requested: Path) -> tuple[Path, Path]:
    """Resolve an unused project folder and its handle for a requested ``.sbd``."""
    from .project_save_as import _is_reparse  # noqa: PLC0415

    requested_document = Path(requested).expanduser().absolute()
    if requested_document.suffix.lower() != project_document.DOCUMENT_SUFFIX:
        requested_document = requested_document.with_suffix(project_document.DOCUMENT_SUFFIX)
    parent = requested_document.parent
    if not parent.is_dir():
        raise FileNotFoundError(f"Project parent folder not found: {parent}")
    if _is_reparse(parent):
        raise ValueError("Project destination parent cannot be a reparse point.")
    requested_document = requested_document.resolve()
    destination_root = requested_document.parent / requested_document.stem
    destination_document = destination_root / f"{destination_root.name}.sbd"
    folded_targets = {
        destination_root.name.casefold(),
        requested_document.name.casefold(),
    }
    for child in requested_document.parent.iterdir():
        if child.name.casefold() in folded_targets:
            raise FileExistsError(
                f"Project destination collides by case with an existing path: {child.name}."
            )
    return destination_root, destination_document


def create_project(
    document_path: Path,
    *,
    canvas_width: int = 1920,
    canvas_height: int = 1080,
    project_type: str = "video",
) -> Project:
    """Atomically create a project folder named after the requested ``.sbd``.

    ``Parent/Name.sbd`` becomes ``Parent/Name/Name.sbd``. The folder is built
    in a staging directory and published with one rename, so a failed create
    never leaves a half-made project behind.
    """
    from . import scene2d, scene3d  # noqa: PLC0415

    validate_project_type(project_type)
    destination_root, destination_document = _creation_paths(document_path)
    operation = Path(
        tempfile.mkdtemp(prefix=".sb-create-", dir=str(destination_root.parent))
    )
    stage = operation / destination_root.name
    try:
        _ensure_project_dirs(stage)
        width, height = normalize_canvas_size(canvas_width, canvas_height)
        settings = DEFAULT_SETTINGS.copy()
        settings["project_type"] = project_type
        settings["canvas_width"] = width
        settings["canvas_height"] = height
        project = Project(
            root_path=stage,
            settings=settings,
            document_path=resolve_root_child(stage, destination_document.name),
            project_id=str(uuid.uuid4()),
            storage_revision=1,
        )
        save_project(project)
        scene2d.initialize_metadata(project)
        scene3d.initialize_metadata(project)
        save_project(project)
        project_document.write_handle(project.document_path, project.project_id)
        os.rename(stage, destination_root)
        try:
            operation.rmdir()
        except OSError:
            logging.getLogger(__name__).warning(
                "Project was created but its empty staging directory could not be removed: %s",
                operation,
                exc_info=True,
            )
        return replace(project, root_path=destination_root, document_path=destination_document)
    except BaseException:
        if operation.exists():
            shutil.rmtree(operation, ignore_errors=True)
        raise


def reload_project_if_changed(project: Project, loaded_mtime: float) -> tuple[Project, float, bool]:
    """Reload project metadata when the plugin or another tool updated it."""
    disk_mtime = project_disk_mtime(project)
    if disk_mtime <= loaded_mtime + 1e-6:
        return project, loaded_mtime, False
    reloaded = _load_project(project.root_path, project.document_path)
    return reloaded, disk_mtime, True


def open_project(document_path: Path) -> Project:
    """Open a project through its ``.sbd`` handle (or the folder that holds it)."""
    path = Path(document_path).expanduser()
    if path.is_dir():
        handles = sorted(path.glob(f"*{project_document.DOCUMENT_SUFFIX}"))
        if len(handles) != 1:
            raise ValueError(f"{path} is not a Storyboarder project folder.")
        path = handles[0]
    document = path.resolve()
    project_id = project_document.read_handle(document)
    root = document.parent
    project_document.recover_incomplete_mutation(root)
    project = _load_project(root, document)
    if project.project_id != project_id:
        raise ValueError(f"{document.name} does not belong to the project in this folder.")
    return project


def _load_project(root: Path, document_path: Path | None) -> Project:
    project = Project(root_path=root, document_path=document_path)
    if not project.json_path.is_file():
        raise FileNotFoundError(f"Project data not found: {project.json_path}")
    try:
        payload = json.loads(project.json_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid project.json: {exc}") from exc
    manifest = parse_project_manifest(payload)
    project.project_id = manifest.project_id
    project.storage_revision = manifest.storage_revision
    project.settings = _load_settings(project)
    sync_ref_segment_settings(project)
    project.shots = load_shots_json(shots_json_path(project.metadata_root)) or []

    # Reject invalid persisted routes before open-time writes can overwrite them.
    story_graph.get_graph(project)
    for shot in project.shots:
        _ensure_shot_files(project, shot)
    save_settings(project)
    color = get_canvas_color(project)
    write_canvas_color_files(project, color)
    sync_canvas_color_to_shots(project, color)
    return project


def save_project(project: Project) -> None:
    """Write the project's metadata in place; every write is durable on return."""
    with PROJECT_LOCK:
        story_graph.get_graph(project)
        _ensure_project_dirs(project.root_path)
        if project.settings.get("backup_on_save", True):
            _write_backup(project)
        # project.json is a lightweight manifest; shots live in shots.json.
        _atomic_write_json(project.json_path, project_manifest(project))
        # Serialize a snapshot (list copy) so a concurrent mutation of
        # project.shots cannot tear the written list.
        save_shots_json(project.metadata_root, list(project.shots))
        save_settings(project)


def validate_transition_candidate(project: Project) -> None:
    """Reject an incomplete separately-opened candidate before activation.

    Missing linked artwork remains a supported, repairable state, so this gate
    is intentionally narrower than ``validate_project_integrity``.
    """
    root = project.root_path.resolve()
    if not root.is_dir():
        raise ValueError(f"Project folder not found: {root}")
    if not project.json_path.is_file():
        raise ValueError(f"Project file not found: {project.json_path}")
    if project.document_path is not None and not project.document_path.is_file():
        raise ValueError(f"Project document not found: {project.document_path}")
    shot_ids = [shot.shot_id for shot in project.shots]
    if len(shot_ids) != len(set(shot_ids)):
        raise ValueError("Project contains duplicate shot IDs.")


def add_shot(project: Project, *, after_index: int | None = None) -> Shot:
    if after_index is not None:
        _require_index(project, after_index)
    previous_ids = [item.shot_id for item in project.shots]
    after_id = previous_ids[after_index] if after_index is not None else (previous_ids[-1] if previous_ids else None)
    shot = Shot(shot_id=new_shot_id())
    _ensure_shot_files(project, shot)
    # A blank PSD is created only when the user chooses Create canvas or Open
    # in Photoshop. Creating it here makes every Add Board wait on a full PSD
    # write even though most newly created boards remain empty initially.
    if after_index is None:
        project.shots.append(shot)
    else:
        project.shots.insert(after_index + 1, shot)
    story_graph.reconcile_shots(project, previous_ids, after_id)
    return shot


def duplicate_shot(project: Project, index: int) -> Shot:
    _require_index(project, index)
    previous_ids = [item.shot_id for item in project.shots]
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
    story_graph.reconcile_shots(project, previous_ids, source.shot_id)
    create_canvas_for_shot(project, duplicate)
    return duplicate


def delete_shot(project: Project, index: int) -> Shot:
    _require_index(project, index)
    previous_ids = [item.shot_id for item in project.shots]
    shot = project.shots.pop(index)
    story_graph.reconcile_shots(project, previous_ids)
    return shot


def restore_shot(project: Project, shot_data: dict[str, Any], index: int) -> Shot:
    index = max(0, min(int(index), len(project.shots)))
    previous_ids = [item.shot_id for item in project.shots]
    shot = Shot.from_dict(shot_data)
    if any(existing.shot_id == shot.shot_id for existing in project.shots):
        raise ValueError(f"Shot already exists: {shot.shot_id}")
    project.shots.insert(index, shot)
    story_graph.reconcile_shots(project, previous_ids, previous_ids[index - 1] if index else None)
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
    destination = resolve_shot_asset(project, shot.shot_id, "preview")
    copied_path = copy_and_convert_image(source_path, destination)
    _save_board_background_copy(
        copied_path,
        resolve_shot_asset(project, shot.shot_id, "board_background"),
    )
    _set_shot_preview_paths(project, shot, copied_path)
    return copied_path


def import_image_stream_for_shot(
    project: Project,
    shot: Shot,
    source_stream: BinaryIO,
    source_suffix: str,
) -> Path:
    destination = resolve_shot_asset(project, shot.shot_id, "preview")
    copied_path = copy_and_convert_image_stream(source_stream, source_suffix, destination)
    _save_board_background_copy(
        copied_path,
        resolve_shot_asset(project, shot.shot_id, "board_background"),
    )
    _set_shot_preview_paths(project, shot, copied_path)
    return copied_path


def remove_image_for_shot(project: Project, shot: Shot) -> None:
    resolve_shot_asset(project, shot.shot_id, "board_background").unlink(
        missing_ok=True
    )
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
    source = resolve_project_path(project, shot.source_file_path)
    if not source.is_file():
        raise FileNotFoundError("Source PSD file is missing.")
    if not psd_recovery.can_open_with_psd_tools(source):
        raise ValueError("The PSD is too damaged to read — it cannot be rebuilt.")

    history = resolve_root_child(project.backups_dir, "psd_recovery")
    backup = resolve_root_child(
        history, f"{shot.shot_id}.broken-{int(time.time())}.psd"
    )
    history.mkdir(parents=True, exist_ok=True)
    atomic_copy_file(source, backup)
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
    temp = resolve_project_path(
        project, project_relative_posix(project, source.with_name(f".{shot.shot_id}.rebuilt.psd"))
    )
    try:
        info = psd_recovery.rebuild_psd(source, temp, preserve_layers=preserve_layers)
        os.replace(temp, source)
    except BaseException:
        temp.unlink(missing_ok=True)
        raise

    preview_path = resolve_shot_asset(project, shot.shot_id, "preview")
    export_psd_composite_to_png(source, preview_path)
    _set_shot_preview_paths(project, shot, preview_path)
    shot.source_sync_mtime = linked_mtime(project, shot)

    return {
        "backup": project_relative_posix(project, backup),
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

    from .canvas_settings import get_shot_canvas_size
    width, height = get_shot_canvas_size(project, shot)
    bg_color = get_canvas_color(project)
    background_path = resolve_shot_asset(project, shot.shot_id, "board_background")
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

    from .canvas_settings import get_shot_canvas_size
    width, height = get_shot_canvas_size(project, shot)
    background_path = resolve_shot_asset(project, shot.shot_id, "board_background")
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
    destination = resolve_reference_asset(project, str(uuid.uuid4()), ".png")
    copied_path = copy_and_convert_image_stream(source_stream, source_suffix, destination)
    shot.reference_image_paths.append(project_relative_posix(project, copied_path))
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
    for link in project.settings.get("reference_links") or []:
        normalized = _normalize_rel_path(link.get("path", "")) if isinstance(link, dict) else ""
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
    referenced = collect_reference_image_paths(project)
    deleted: list[str] = []
    ref_dir = project.references_dir
    if ref_dir.is_dir():
        for file_path in ref_dir.iterdir():
            if not file_path.is_file():
                continue
            try:
                rel_path = project_relative_posix(project, file_path)
            except ValueError:
                continue
            if rel_path in referenced:
                continue
            file_path.unlink(missing_ok=True)
            deleted.append(rel_path)
    return deleted


def shutdown_reference_cleanup(project: Project | None) -> list[str]:
    if project is None:
        return []
    return cleanup_orphan_reference_images(project)


def import_source_file_stream(
    project: Project,
    shot: Shot,
    source_stream: BinaryIO,
    filename: str,
) -> Path:
    suffix = Path(filename).suffix or ".psd"
    if suffix.lower() != ".psd":
        raise ValueError("Shot sources must be PSD files.")
    destination = resolve_shot_asset(project, shot.shot_id, "source_psd")
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = destination.with_suffix(suffix + ".tmp")
    try:
        with tmp.open("wb") as file:
            shutil.copyfileobj(source_stream, file)
        os.replace(tmp, destination)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    shot.source_file_path = project_relative_posix(project, destination)
    if is_psd_path(destination):
        preview_path = export_psd_composite_to_png(
            destination,
            resolve_shot_asset(project, shot.shot_id, "preview"),
        )
        _set_shot_preview_paths(project, shot, preview_path)
    shot.source_sync_mtime = linked_mtime(project, shot)
    return destination


def _validate_drawing_editor_data(editor_data: str) -> str:
    try:
        payload = json.loads(editor_data)
    except json.JSONDecodeError as exc:
        raise ValueError("Drawing editor data must be valid JSON.") from exc
    if not isinstance(payload, dict):
        raise ValueError("Drawing editor data must be a JSON object.")
    info = payload.get("info")
    layers = payload.get("layers")
    if not isinstance(info, dict) or not isinstance(layers, list):
        raise ValueError("Drawing editor data is missing info or layers.")
    return editor_data


def save_drawing_for_shot(
    project: Project,
    shot: Shot,
    data_url: str,
    editor_data: str | None = None,
) -> Path:
    validated_editor_data = (
        _validate_drawing_editor_data(editor_data)
        if editor_data is not None
        else None
    )
    preview_path = save_png_data_url(
        data_url,
        resolve_shot_asset(project, shot.shot_id, "preview"),
    )
    if validated_editor_data is not None:
        _atomic_write_text(
            resolve_shot_metadata(project, shot.shot_id, "drawing"),
            validated_editor_data,
        )
    _set_shot_preview_paths(project, shot, preview_path)
    return preview_path


def load_drawing_project_for_shot(project: Project, shot: Shot) -> str | None:
    editor_path = resolve_shot_metadata(project, shot.shot_id, "drawing")
    if not editor_path.is_file():
        return None
    preview_path = resolve_shot_preview_path(project, shot)
    try:
        if preview_path is not None and preview_path.is_file():
            if editor_path.stat().st_mtime_ns < preview_path.stat().st_mtime_ns:
                return None
        return editor_path.read_text(encoding="utf-8")
    except OSError:
        return None


def sync_shot(project: Project, shot: Shot, force: bool = False) -> dict[str, object]:
    return sync_shot_from_linked_files(project, shot, force=force)


def _require_index(project: Project, index: int) -> None:
    if index < 0 or index >= len(project.shots):
        raise IndexError("Shot index out of range.")


def _ensure_shot_files(project: Project, shot: Shot) -> None:
    shot_dir = get_shot_dir(project, shot)
    shot_dir.mkdir(parents=True, exist_ok=True)
    if not shot.annotation_path:
        annotation_path = resolve_shot_metadata(project, shot.shot_id, "annotations")
        annotation_path.parent.mkdir(parents=True, exist_ok=True)
        if not annotation_path.exists():
            _atomic_write_text(annotation_path, "[]")
        shot.annotation_path = project_relative_posix(project, annotation_path)
    notes_path = resolve_shot_metadata(project, shot.shot_id, "notes")
    notes_path.parent.mkdir(parents=True, exist_ok=True)
    if not notes_path.exists():
        _atomic_write_text(notes_path, json.dumps(shot.to_dict(), indent=2))
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

from .reference_metadata import (
    REFERENCE_IMAGE_EXTENSIONS,
    REFERENCE_MODEL_EXTENSIONS,
    REFERENCE_VIDEO_EXTENSIONS,
    ensure_reference_library,
    normalize_reference_links,
    reference_media_type,
)
from .reference_segments import (  # noqa: E402
    apply_ref_segment_3d_to_boards,
    apply_ref_segment_image_to_boards,
    apply_ref_segment_to_boards,
    clear_active_reference_image,
    clear_active_reference_model,
    clear_active_reference_video,
    delete_ref_segment,
    find_ref_segment,
    import_project_reference_stream,
    import_reference_video_stream,
    new_ref_segment_id,
    normalize_ref_segments,
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
