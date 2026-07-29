"""Transport-agnostic project/app-state helpers.

These were previously private functions on the HTTP route module (`api.py`),
which forced the service layer to reach "up" into the route layer via a lazy
import shim. They live here so both `api.py` and `backend_service.py` import
them downward, with no circular dependency.
"""

from __future__ import annotations

import contextlib
import logging
import secrets
import threading
import time
from collections.abc import Callable, Generator
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException

from . import (
    blender_bridge,
    bpy_viewport,
    live_bridge,
    preview_analysis_cache,
    project_document,
    project_manager,
    recents,
    runtime_state,
    session_store,
    shot_service,
)
from .errors import AppErrorCode, app_error
from .models import Project, SHOT_STATUSES, Shot
from .project_layout import LAYOUT_2

logger = logging.getLogger(__name__)

PROJECT_WRITER_QUIESCE_TIMEOUT_SECONDS = 5.0


class ProjectTransitionError(RuntimeError):
    """A pre-commit project transition failure with its exact stage."""

    def __init__(self, action: str, stage: str, cause: Exception) -> None:
        self.action = action
        self.stage = stage
        self.cause = cause
        super().__init__(f"{action} failed during {stage}: {cause}")


def _ensure_transition_runtime(app: FastAPI) -> None:
    """Initialize per-app writer accounting without racing request threads."""
    with project_manager.PROJECT_TRANSITION_LOCK:
        if not isinstance(
            getattr(app.state, "project_writer_condition", None),
            threading.Condition,
        ):
            app.state.project_writer_condition = threading.Condition()
            app.state.project_writers_quiesced = False
            app.state.active_project_writers = {}
        if not str(getattr(app.state, "project_session_id", "") or ""):
            app.state.project_session_id = secrets.token_urlsafe(24)
        if not hasattr(app.state, "last_project_transition"):
            app.state.last_project_transition = {}


@contextlib.contextmanager
def project_background_writer(app: FastAPI, name: str) -> Generator[bool, None, None]:
    """Register a background writer, or decline it while transitions are paused."""
    _ensure_transition_runtime(app)
    condition: threading.Condition = app.state.project_writer_condition
    registered = False
    with condition:
        if not bool(app.state.project_writers_quiesced):
            active = app.state.active_project_writers
            active[name] = int(active.get(name, 0)) + 1
            registered = True
    try:
        yield registered
    finally:
        if registered:
            with condition:
                active = app.state.active_project_writers
                remaining = int(active.get(name, 0)) - 1
                if remaining > 0:
                    active[name] = remaining
                else:
                    active.pop(name, None)
                condition.notify_all()


def quiesce_project_writers(
    app: FastAPI,
    timeout: float | None = None,
) -> dict[str, Any]:
    """Pause new background writes and wait for registered writers to exit."""
    _ensure_transition_runtime(app)
    condition: threading.Condition = app.state.project_writer_condition
    wait_seconds = (
        float(timeout)
        if timeout is not None
        else float(
            getattr(
                app.state,
                "project_writer_quiesce_timeout",
                PROJECT_WRITER_QUIESCE_TIMEOUT_SECONDS,
            )
        )
    )
    deadline = time.monotonic() + max(0.0, wait_seconds)
    with condition:
        app.state.project_writers_quiesced = True
        while app.state.active_project_writers:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                names = ", ".join(sorted(app.state.active_project_writers))
                raise TimeoutError(
                    f"Timed out waiting for project writers to quiesce: {names}"
                )
            condition.wait(timeout=remaining)
        return {
            "active": [],
            "registered": [
                "live_bridge",
                "generation_results",
                "preview_analysis",
                "plugin_http_mutations",
            ],
            "plugin_http": "frozen_by_project_lock",
            "plugin_inbox": "excluded_uncommitted_layout1_no_inbox",
            "transaction_log": "drained_by_project_lock_no_persistent_log",
        }


def resume_project_writers(app: FastAPI) -> None:
    _ensure_transition_runtime(app)
    condition: threading.Condition = app.state.project_writer_condition
    with condition:
        app.state.project_writers_quiesced = False
        condition.notify_all()


def _transition_checkpoint(
    app: FastAPI,
    report: dict[str, Any],
    stage: str,
) -> None:
    report["current_stage"] = stage
    report["stages"].append(stage)
    app.state.last_project_transition = report
    fault = getattr(app.state, "project_transition_fault", None)
    if callable(fault):
        fault(stage)
    elif str(fault or "") == stage:
        raise RuntimeError(f"Injected project transition fault at {stage}")


def transition_active_project(
    app: FastAPI,
    *,
    action: str,
    candidate_factory: Callable[[], Project] | None,
) -> Project | None:
    """Durably hand off the active project or leave the old state untouched.

    All fallible work happens before the in-memory swap. Old runtime-root
    cleanup is deliberately last and never runs on a failed transition.
    """
    _ensure_transition_runtime(app)
    report: dict[str, Any] = {
        "action": action,
        "status": "running",
        "current_stage": "",
        "stages": [],
        "writers": {},
    }
    source: Project | None = app.state.project
    candidate: Project | None = None
    source_dirty = bool(getattr(app.state, "dirty", False))
    source_disk_mtime = float(
        getattr(app.state, "project_disk_mtime", 0.0) or 0.0
    )
    source_session_id = str(getattr(app.state, "project_session_id", "") or "")
    writers_quiesced = False

    with project_manager.PROJECT_TRANSITION_LOCK:
        try:
            _transition_checkpoint(app, report, "lock_acquired")
            report["current_stage"] = "writer_quiesce"
            report["writers"] = quiesce_project_writers(app)
            writers_quiesced = True
            _transition_checkpoint(app, report, "writers_quiesced")

            with project_manager.PROJECT_LOCK:
                source = app.state.project
                source_dirty = bool(getattr(app.state, "dirty", False))
                source_disk_mtime = float(
                    getattr(app.state, "project_disk_mtime", 0.0) or 0.0
                )
                source_session_id = str(
                    getattr(app.state, "project_session_id", "") or ""
                )
                report["source_dirty_before"] = source_dirty
                _transition_checkpoint(app, report, "mutations_frozen")

                # Layout 1 has no backend-owned plugin inbox. HTTP plugin writes
                # are drained/frozen by PROJECT_LOCK; unknown direct filesystem
                # writes are explicitly excluded rather than silently ingested.
                _transition_checkpoint(app, report, "plugin_inbox_resolved")

                report["current_stage"] = "external_blender_release"
                blender_bridge.require_released(app, action)
                _transition_checkpoint(app, report, "external_blender_released")

                report["current_stage"] = "builtin_blender_release"
                built_in_save = bpy_viewport.save_and_stop_worker(app)
                report["built_in_blender_saved"] = built_in_save is not None
                _transition_checkpoint(app, report, "builtin_blender_released")

                dirty_after_writer_checks = bool(
                    getattr(app.state, "dirty", False)
                )
                report["source_dirty_after_writer_checks"] = (
                    dirty_after_writer_checks
                )
                must_persist_source = source is not None and (
                    dirty_after_writer_checks or built_in_save is not None
                )
                report["current_stage"] = "backend_serialize"
                if must_persist_source:
                    project_manager.save_project(source, flush_document=False)
                _transition_checkpoint(app, report, "backend_serialized")

                report["current_stage"] = "source_save"
                if (
                    must_persist_source
                    and source is not None
                    and source.document_path
                ):
                    project_manager.sync_document(source)
                _transition_checkpoint(app, report, "source_durable")

                if candidate_factory is not None:
                    report["current_stage"] = "candidate_open"
                    candidate = candidate_factory()
                    _transition_checkpoint(app, report, "candidate_opened")
                    report["current_stage"] = "candidate_validate"
                    project_manager.validate_transition_candidate(candidate)
                    _transition_checkpoint(app, report, "candidate_validated")

                _transition_checkpoint(app, report, "before_swap")

                # Commit point: these assignments/reset operations perform no I/O.
                if candidate is None:
                    app.state.project = None
                    app.state.project_disk_mtime = 0.0
                else:
                    _track_project(app, candidate)
                app.state.dirty = False
                runtime_state.rotate_project_session(app)
                blender_bridge.cancel_session(app)
                report["status"] = "committed"
                report["current_stage"] = "committed"
                report["project_session_id"] = app.state.project_session_id
                app.state.last_project_transition = report

            # These publications are recoverable and must not roll back the
            # already-atomic active-project swap.
            try:
                if candidate is not None:
                    _remember_recent(candidate)
                _persist_app_session(app)
                _touch_live_bridge(app)
            except Exception:
                logger.warning(
                    "Project transition committed but publication failed",
                    exc_info=True,
                )

            if source is not None and source is not candidate:
                try:
                    project_manager.cleanup_document_working_root(source)
                except Exception:
                    logger.warning(
                        "Could not clean the previous project work root",
                        exc_info=True,
                    )
            return candidate
        except Exception as exc:
            # No active-project assignment occurs before the commit point.
            app.state.project = source
            app.state.dirty = source_dirty
            app.state.project_disk_mtime = source_disk_mtime
            app.state.project_session_id = source_session_id
            if candidate is not None and candidate is not source:
                try:
                    project_manager.cleanup_document_working_root(candidate)
                except Exception:
                    logger.warning(
                        "Could not clean rejected candidate work root",
                        exc_info=True,
                    )
            report["status"] = "failed"
            report["error"] = str(exc)
            app.state.last_project_transition = report
            if isinstance(exc, ProjectTransitionError):
                raise
            raise ProjectTransitionError(
                action,
                str(report.get("current_stage") or "unknown"),
                exc,
            ) from exc
        finally:
            if writers_quiesced or bool(
                getattr(app.state, "project_writers_quiesced", False)
            ):
                resume_project_writers(app)


def _project_payload(project: Project, dirty: bool) -> dict[str, Any]:
    cache = preview_analysis_cache.load_cache(project.metadata_root)
    return {
        "project_path": str(project.visible_path),
        "project_json_path": str(project.reopen_path),
        "document_path": str(project.document_path) if project.document_path else "",
        "name": project.name,
        "dirty": dirty,
        "settings": project.settings,
        "statuses": list(SHOT_STATUSES),
        "shots": [_shot_payload(project, shot, cache) for shot in project.shots],
    }


def _shot_payload(project: Project, shot: Shot, cache: dict[str, Any] | None = None) -> dict[str, Any]:
    data = shot.to_dict()
    preview_path = project_manager.resolve_shot_preview_path(project, shot)
    if preview_path is not None:
        try:
            data["preview_disk_mtime"] = preview_path.stat().st_mtime
        except OSError:
            pass
    thumb_path = project_manager.resolve_shot_thumbnail_path(project, shot)
    if thumb_path is not None:
        try:
            data["thumbnail_disk_mtime"] = thumb_path.stat().st_mtime
        except OSError:
            pass
    board_background_path = project_manager.get_shot_board_background_path(project, shot)
    data["has_board_background"] = board_background_path is not None
    if board_background_path is not None:
        try:
            data["board_background_disk_mtime"] = board_background_path.stat().st_mtime
        except OSError:
            pass
    codex_layer_path = project_manager.get_shot_codex_layer_path(project, shot)
    data["has_codex_layer"] = codex_layer_path is not None
    if codex_layer_path is not None:
        try:
            data["codex_layer_disk_mtime"] = codex_layer_path.stat().st_mtime
        except OSError:
            pass

    if preview_path is not None and preview_path.is_file():
        hit = preview_analysis_cache.get_cached(cache or {}, preview_path)
        if hit is not None:
            data["has_artwork_preview"] = hit["has_artwork_preview"]
            data["preview_has_transparency"] = hit["preview_has_transparency"]
            data["preview_analysis_state"] = "cached"
        else:
            # Provisional: preview file exists, real result deferred to background worker
            data["has_artwork_preview"] = True
            data["preview_has_transparency"] = False
            data["preview_analysis_state"] = "provisional"
    else:
        data["has_artwork_preview"] = False
        data["preview_has_transparency"] = False
        data["preview_analysis_state"] = "missing"
    return data


def _analyse_uncached_previews(project: Project) -> int:
    """
    Analyse previews that are missing from the cache and update it.
    Called by the deferred background worker — never on the critical startup path.
    Returns the number of previews actually decoded.
    """
    from .image_utils import image_has_transparency, is_solid_color_image

    cache = preview_analysis_cache.load_cache(project.metadata_root)
    analysed = 0
    dirty = False
    # Snapshot the shot list: this runs on a background thread while request threads
    # may reorder/replace project.shots. Iterating a live reference could skip shots or
    # raise if the list is reassigned mid-pass; a shallow copy of the references is
    # enough since Shot objects are only read here.
    for shot in list(project.shots):
        preview_path = project_manager.resolve_shot_preview_path(project, shot)
        if preview_path is None or not preview_path.is_file():
            continue
        if preview_analysis_cache.get_cached(cache, preview_path) is not None:
            continue
        try:
            has_artwork = not is_solid_color_image(preview_path)
            has_alpha = image_has_transparency(preview_path)
        except Exception:
            logger.debug("Preview analysis failed for %s", preview_path, exc_info=True)
            continue
        preview_analysis_cache.set_cached(cache, preview_path, has_artwork, has_alpha)
        analysed += 1
        dirty = True

    if dirty:
        preview_analysis_cache.save_cache(project.metadata_root, cache)
    return analysed


def _require_project(app: FastAPI) -> Project:
    project = app.state.project
    if project is None:
        raise app_error(AppErrorCode.PROJECT_NOT_OPEN, "No project opened.")
    return project


def _find_shot_index(project: Project, shot_id: str) -> int:
    try:
        return shot_service.find_shot_index(project, shot_id)
    except ValueError as exc:
        raise app_error(AppErrorCode.SHOT_NOT_FOUND, str(exc), status=404) from exc


def _find_shot(project: Project, shot_id: str) -> Shot:
    try:
        return shot_service.find_shot(project, shot_id)
    except ValueError as exc:
        raise app_error(AppErrorCode.SHOT_NOT_FOUND, str(exc), status=404) from exc


def _track_project(app: FastAPI, project: Project) -> None:
    app.state.project = project
    app.state.project_disk_mtime = project_manager.project_disk_mtime(project)


def _refresh_project_from_disk(app: FastAPI) -> Project:
    # Hold the persistence lock so a reload cannot swap app.state.project while another
    # thread is mid-save (which would tear the save) or observe a half-written manifest.
    with project_manager.PROJECT_LOCK:
        project = _require_project(app)
        if app.state.dirty:
            return project
        try:
            refreshed, disk_mtime, changed = project_manager.reload_project_if_changed(
                project,
                app.state.project_disk_mtime,
            )
        except ValueError as exc:
            logger.warning("Keeping in-memory project after background refresh failed: %s", exc)
            return project
        if changed:
            app.state.project = refreshed
            app.state.project_disk_mtime = disk_mtime
            return refreshed
        return project


def stop_background_loops(app: FastAPI, timeout: float = 2.0) -> None:
    """Halt the bridge/generation watchers and wait for them to actually stop.

    Both write into the open project's work tree, so anything that removes that
    tree must call this first. Otherwise a loop recreates a file mid-delete and
    Windows leaves behind a directory that can no longer be opened or removed —
    the `storyboarder-*` husks that pile up in TEMP. Safe to call repeatedly.
    """
    stop_event = getattr(app.state, "background_stop", None)
    if stop_event is None:
        return
    stop_event.set()
    for thread in getattr(app.state, "background_threads", ()):
        if thread.is_alive():
            thread.join(timeout=timeout)


def _autosave(app: FastAPI) -> None:
    """Persist metadata after a mutation, but defer the expensive .sbd pack.

    Packing a single-file document re-zips the whole project, which is too slow to
    run on every edit. The working tree is kept current here (cheap); the .sbd is
    flushed by periodic autosave, manual save (Ctrl+S / Save), and save-on-close.
    For a plain folder project there is nothing to pack, so the metadata write is
    already the durable save and the project is not left dirty.
    """
    project = _require_project(app)
    revision = int(project.storage_revision)
    project_manager.save_project(project, flush_document=False)
    if project.layout == LAYOUT_2:
        project.storage_revision = project_document.advance_layout2_work_revision(
            project.project_root,
            expected_revision=revision,
        )
        try:
            blender_bridge.publish_context(app, project)
        except (OSError, ValueError):
            logger.warning(
                "Could not invalidate the external Blender context after mutation."
            )
    app.state.project_disk_mtime = project_manager.project_disk_mtime(project)
    app.state.dirty = bool(project.document_path)


def persist_project_mutation(app: FastAPI) -> None:
    """Persist one accepted mutation at exactly one Layout 2 revision."""
    project = _require_project(app)
    _autosave(app)
    if project.layout != LAYOUT_2:
        project_manager.sync_document(project)
        app.state.dirty = False


def _dialog_initial_dir(app: FastAPI, kind: str) -> str:
    project = app.state.project
    if project is None:
        return str(Path.home())

    if kind == "folder":
        candidate = project.visible_path.parent
    elif kind == "project-json":
        candidate = project.visible_path.parent if project.document_path else project.project_root
    elif kind == "blender":
        current = str(project.settings.get("blender_path", "") or "")
        candidate = Path(current).parent if current else Path(r"C:\Program Files\Blender Foundation")
    else:
        current = str(project.settings.get("photoshop_path", "") or "")
        candidate = Path(current).parent if current else Path(r"C:\Program Files\Adobe")

    if candidate.is_dir():
        return str(candidate.resolve())
    return str(Path.home())


def _remember_recent(project: Project) -> None:
    """Update session-facing recents without rewriting the opened document."""
    recent = [str(project.visible_path)]
    for item in project.settings.get("recent_projects", []):
        if item not in recent:
            recent.append(item)
    project.settings["recent_projects"] = recent[:10]


def _touch_live_bridge(app: FastAPI, *, selected_shot_id: str | None = None) -> dict[str, Any]:
    # Bridge publication writes into the active project root. Serialize it with
    # mutations/transitions so it can never recreate an old root during cleanup.
    with project_manager.PROJECT_LOCK:
        if selected_shot_id is not None:
            runtime_state.set_live_selected_shot_id(app, selected_shot_id)
        payload = live_bridge.publish(
            app.state.base_dir,
            app.state.project,
            selected_shot_id=runtime_state.live_selected_shot_id(app),
            port=int(app.state.bridge_port),
            focus_shot_id=runtime_state.live_focus_shot_id(app),
            focus_token=runtime_state.focus_token(app),
            work_context=runtime_state.active_work_context(app),
            focus_work_context=runtime_state.focus_work_context(app),
            plugin_change=runtime_state.plugin_change_payload(app),
        )
        if app.state.project is not None:
            try:
                blender_bridge.publish_context(app, app.state.project)
            except (OSError, ValueError):
                logger.warning("Could not refresh the external Blender bridge context.")
        return payload


def _plugin_open_shot_ids(app: FastAPI, plugin_linked: bool, file_seen: float, http_seen: float) -> list[str]:
    """Shot ids the plugin reports as open Photoshop tabs (heartbeat file or HTTP)."""
    if not plugin_linked:
        return []

    def normalize_ids(value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(item) for item in value if item]
        return []

    heartbeat = live_bridge.read_plugin_heartbeat()
    file_ids = heartbeat.get("open_shot_ids") if isinstance(heartbeat, dict) else None
    http_ids = runtime_state.plugin_open_shot_ids(app)

    file_open_ids = normalize_ids(file_ids)
    http_open_ids = normalize_ids(http_ids)
    if file_seen >= http_seen and isinstance(heartbeat, dict) and "open_shot_ids" in heartbeat:
        return file_open_ids
    primary, fallback = (file_open_ids, http_open_ids) if file_seen >= http_seen else (http_open_ids, file_open_ids)
    return primary or fallback


def _plugin_link_state(app: FastAPI) -> tuple[bool, float | None, list[str]]:
    """(linked, seconds_since_seen, open_shot_ids) — shared by status + open-source."""
    http_seen = runtime_state.plugin_last_seen(app)
    file_seen = live_bridge.read_plugin_heartbeat_mtime()
    last_seen = max(http_seen, file_seen)
    age = round(time.time() - last_seen, 1) if last_seen else None
    plugin_linked = age is not None and age <= 12.0
    open_shot_ids = _plugin_open_shot_ids(app, plugin_linked, file_seen, http_seen)
    return plugin_linked, age, open_shot_ids


def _plugin_selected_shot_id(
    app: FastAPI,
    plugin_linked: bool | None = None,
    file_seen: float | None = None,
    http_seen: float | None = None,
) -> str:
    http_seen_value = runtime_state.plugin_last_seen(app) if http_seen is None else http_seen
    file_seen_value = live_bridge.read_plugin_heartbeat_mtime() if file_seen is None else file_seen
    if plugin_linked is None:
        last_seen = max(http_seen_value, file_seen_value)
        age = time.time() - last_seen if last_seen else None
        plugin_linked = age is not None and age <= 12.0
    if not plugin_linked:
        return ""

    http_selected = runtime_state.plugin_selected_shot_id(app)
    heartbeat = live_bridge.read_plugin_heartbeat()
    file_selected = str(heartbeat.get("selected_shot_id") or "") if isinstance(heartbeat, dict) else ""
    if file_seen_value >= http_seen_value and isinstance(heartbeat, dict) and "selected_shot_id" in heartbeat:
        return file_selected
    primary, fallback = (file_selected, http_selected) if file_seen_value >= http_seen_value else (http_selected, file_selected)
    return primary or fallback


def _valid_plugin_work_keys(app: FastAPI) -> set[str]:
    project = app.state.project
    if project is None:
        return set()
    try:
        from .plugin_service import PluginBridgeService

        return {str(item.get("key") or "") for item in PluginBridgeService(app).work_items(project) if item.get("key")}
    except Exception:
        logger.debug("Could not build plugin work-key validation set.", exc_info=True)
        return set()


def _plugin_work_key_state(
    app: FastAPI,
    plugin_linked: bool,
    file_seen: float,
    http_seen: float,
) -> tuple[str, list[str]]:
    """Generic Photoshop work keys reported by the newest heartbeat source."""
    if not plugin_linked:
        return "", []

    valid_keys = _valid_plugin_work_keys(app)
    if not valid_keys:
        return "", []

    def normalize_active(value: Any) -> str:
        key = str(value or "").strip()
        return key if key in valid_keys else ""

    def normalize_open(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        seen: set[str] = set()
        accepted: list[str] = []
        for raw in value:
            key = str(raw or "").strip()
            if key in valid_keys and key not in seen:
                accepted.append(key)
                seen.add(key)
        return accepted

    heartbeat = live_bridge.read_plugin_heartbeat()
    file_has_active = isinstance(heartbeat, dict) and "active_work_key" in heartbeat
    file_has_open = isinstance(heartbeat, dict) and "open_work_keys" in heartbeat
    file_active = normalize_active(heartbeat.get("active_work_key") if isinstance(heartbeat, dict) else "")
    file_open = normalize_open(heartbeat.get("open_work_keys") if isinstance(heartbeat, dict) else None)
    http_active = normalize_active(runtime_state.plugin_active_work_key(app))
    http_open = normalize_open(runtime_state.plugin_open_work_keys(app))

    if file_seen >= http_seen:
        active = file_active if file_has_active else http_active
        open_keys = file_open if file_has_open else http_open
        return active, open_keys
    # HTTP is definitively newer — its values are authoritative.
    # Do NOT fall back to stale file state: an explicit empty [] must mean [].
    return http_active, http_open


def plugin_work_key_state(app: FastAPI) -> tuple[str, list[str]]:
    """Public: return (active_work_key, open_work_keys) from the newest validated heartbeat.

    Uses whichever of the file or HTTP/runtime heartbeat is more recent.
    All returned keys are validated against the current project's work items.
    Callers that need to decide open-vs-focus must use this instead of reading
    runtime_state directly, which may hold stale HTTP-only values.
    """
    http_seen = runtime_state.plugin_last_seen(app)
    file_seen = live_bridge.read_plugin_heartbeat_mtime()
    plugin_linked, _age, _open_shot_ids = _plugin_link_state(app)
    return _plugin_work_key_state(app, plugin_linked, file_seen, http_seen)


def _bridge_status_payload(app: FastAPI) -> dict[str, Any]:
    live = _touch_live_bridge(app)
    project = app.state.project
    work_context = dict(runtime_state.active_work_context(app))
    if project is not None and project.layout == LAYOUT_2:
        work_context.pop("source_file_path", None)
        work_context.pop("source_native_path", None)
    http_seen = runtime_state.plugin_last_seen(app)
    file_seen = live_bridge.read_plugin_heartbeat_mtime()
    plugin_linked, age, open_shot_ids = _plugin_link_state(app)
    active_work_key, open_work_keys = _plugin_work_key_state(app, plugin_linked, file_seen, http_seen)
    last_exported = runtime_state.plugin_last_exported_preview(app)
    result: dict[str, Any] = {
        "app_running": True,
        "project_open": project is not None,
        "plugin_linked": plugin_linked,
        "plugin_last_seen_seconds_ago": age,
        "plugin_selected_shot_id": _plugin_selected_shot_id(app, plugin_linked, file_seen, http_seen),
        "plugin_open_shot_ids": open_shot_ids,
        "plugin_last_exported_preview": last_exported,
        "plugin_project_revision": runtime_state.plugin_project_revision(app),
        "generation_result_revision": runtime_state.generation_result_revision(app),
        # Generic work context fields
        "work_context": work_context,
        "plugin_active_work_key": active_work_key,
        "plugin_open_work_keys": open_work_keys,
        "plugin_change": runtime_state.plugin_change_payload(app),
        "bridge_url": live.get("bridge_url", f"http://127.0.0.1:{app.state.bridge_port}/api/bridge/live"),
        "global_bridge_path": live.get("global_bridge_path", str(live_bridge.global_bridge_file_path())),
        "shared_bridge_path": live.get("shared_bridge_path", str(live_bridge.shared_bridge_file_path())),
        "plugin_heartbeat_path": live.get("plugin_heartbeat_path", str(live_bridge.plugin_heartbeat_file_path())),
        "server_port": int(app.state.bridge_port),
        "live": live,
    }
    if project is not None and project.layout != LAYOUT_2:
        pa = runtime_state.preview_analysis_status_for_project(app, str(project.project_root))
        if pa is not None:
            result["preview_analysis"] = pa
    return result


def _persist_app_session(app: FastAPI, *, selected_shot_id: str | None = None) -> None:
    project = app.state.project
    if project is None:
        return
    # Recents are app-level, but each document also carries its own list. Merge
    # both so Home keeps showing documents opened before this one, instead of
    # being reset to whatever the newest document happened to remember.
    previous = session_store.read_session(app.state.base_dir).get("recent_projects", [])
    merged = recents.dedupe(
        [
            str(project.visible_path),
            *[str(item) for item in project.settings.get("recent_projects", [])],
            *[str(item) for item in previous if isinstance(item, (str, Path))],
        ]
    )
    session_store.update_session(
        app.state.base_dir,
        last_project_json_path=str(project.reopen_path),
        selected_shot_id=selected_shot_id,
        recent_projects=merged,
    )


def _annotation_path(project: Project, shot: Shot) -> Path:
    if not shot.annotation_path:
        path = project_manager.resolve_shot_metadata(project, shot.shot_id, "annotations")
        path.parent.mkdir(parents=True, exist_ok=True)
        project_manager._atomic_write_text(path, "[]")
        shot.annotation_path = project_manager.project_relative_posix(project, path)
        project_manager.save_project(project)
        return path
    path = project_manager.resolve_project_path(project, shot.annotation_path)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        project_manager._atomic_write_text(path, "[]")
    return path
