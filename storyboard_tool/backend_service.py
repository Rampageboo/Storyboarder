from __future__ import annotations

import functools
import io
import json
import logging
import os
import re
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, BinaryIO

from fastapi import FastAPI, HTTPException

from . import (
    app_state,
    blender_bridge,
    bpy_viewport,
    generation_service,
    project_manager,
    project_transaction,
    recents,
    reference_segments,
    runtime_state,
    scene2d,
    scene3d,
    session_store,
    shot_service,
)
from .errors import AppErrorCode, app_error
from .external_tools import preheat_photoshop
from .export_utils import missing_files
from .image_utils import normalize_hex_color
from .linked_sync import sync_project
from .plugin_service import PluginBridgeService
from .service_exports import ExportServiceMixin
from .system_utils import (
    browse_blender_executable,
    browse_folder,
    browse_photoshop_executable,
    browse_project_json,
    browse_project_save,
    detect_blender_paths,
    detect_photoshop_paths,
    validate_blender_path,
    validate_folder_path,
    validate_photoshop_path,
    validate_project_json_path,
    validate_project_save_path,
)

logger = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r'^[a-zA-Z0-9_-]{1,64}$')


_VALID_WINDOW_STATES = frozenset({"normal", "maximized", "minimized"})
_VALID_WINDOW_RESTORE_STATES = frozenset({"normal", "maximized"})


def _set_main_window_state(app: Any, state: str) -> None:
    """Set the application-owned runtime window state."""
    if state in _VALID_WINDOW_STATES:
        app.state.main_window_state = state


def _get_main_window_state(app: Any) -> str:
    """Return the application-owned runtime window state, defaulting to 'normal'."""
    return getattr(app.state, "main_window_state", "normal")


def _set_main_window_restore_state(app: Any, state: str) -> None:
    """Set the state the window should restore to (normal or maximized only)."""
    if state in _VALID_WINDOW_RESTORE_STATES:
        app.state.main_window_restore_state = state


def _get_main_window_restore_state(app: Any) -> str:
    """Return the restore state (what to come back to after un-minimizing), defaulting to 'normal'."""
    return getattr(app.state, "main_window_restore_state", "normal")


def _focus_desktop_window(
    window,
    *,
    window_state: str = "normal",
    restore_state: str = "normal",
) -> dict[str, Any]:
    """Focus a pywebview window without changing its geometry.

    window_state:   the current OS-tracked state (normal/maximized/minimized).
    restore_state:  the pre-minimized state to return to on a successful restore.

    Only calls restore() when window_state == 'minimized'. Never restores a
    normal or maximized window. Uses show() as the activation request — on
    Windows, show() performs Show + Activate. Does not call window.focus()
    (pywebview uses 'focus' as a configuration value, not a callable method).
    """
    restored = False
    shown = False
    activation_requested = False
    errors: list[str] = []

    if window_state == "minimized":
        restore_fn = getattr(window, "restore", None)
        if callable(restore_fn):
            try:
                restore_fn()
                restored = True
            except Exception:
                errors.append("restore_failed")
                logger.debug("pywebview window.restore() failed during focus request", exc_info=True)

    # pywebview restore() sets WindowState = FormWindowState.Normal on Windows —
    # it does NOT return to the previous maximized state. Call maximize() explicitly
    # so the OS window actually reaches the restore target.
    remaximized = False
    if restored and restore_state == "maximized":
        maximize_fn = getattr(window, "maximize", None)
        if callable(maximize_fn):
            try:
                maximize_fn()
                remaximized = True
            except Exception:
                errors.append("maximize_failed")
                logger.debug("pywebview window.maximize() failed during focus request", exc_info=True)

    show_fn = getattr(window, "show", None)
    if callable(show_fn):
        try:
            show_fn()
            shown = True
            activation_requested = True
        except Exception:
            errors.append("show_failed")
            logger.debug("pywebview window.show() failed during focus request", exc_info=True)

    if restored:
        # remaximized=True → OS window is maximized; False → OS window is normal
        # (either restore_state was "normal", or maximize() failed).
        window_state_after = "maximized" if remaximized else "normal"
    else:
        window_state_after = window_state

    return {
        "ok": True,
        "shown": shown,
        "activation_requested": activation_requested,
        "focused": activation_requested,
        "restored_from_minimized": restored,
        "remaximized": remaximized,
        "window_state_before": window_state,
        "window_restore_state_before": restore_state,
        "window_state_after": window_state_after,
        "errors": errors,
    }


def _normalize_upload_bytes(data: list[int] | bytes | bytearray) -> bytes:
    if isinstance(data, (bytes, bytearray)):
        return bytes(data)
    if isinstance(data, list):
        return bytes(int(value) & 0xFF for value in data)
    raise HTTPException(status_code=400, detail="Upload payload must be bytes.")


def _upload_stream(data: list[int] | bytes | bytearray) -> BinaryIO:
    return io.BytesIO(_normalize_upload_bytes(data))


class StoryboardBackendService(ExportServiceMixin):
    """Business logic shared by every REST route and the desktop bridge."""

    def __init__(self, app: FastAPI) -> None:
        self.app = app

    def call(self, method: str, args: list[Any] | None = None) -> Any:
        handler = getattr(self, f"method_{method}", None)
        if handler is None:
            raise ValueError(f"Unknown API method: {method}")
        raw_args = args if isinstance(args, list) else []
        return handler(*raw_args)

    def method_ping(self) -> str:
        return "python-backend-ready"

    def method_get_project(self) -> dict[str, Any]:
        project = app_state._refresh_project_from_disk(self.app)
        return app_state._project_payload(project, self.app.state.dirty)

    def method_get_session(self) -> dict[str, Any]:
        return session_store.read_session(self.app.state.base_dir)

    def method_update_session(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        data = payload if isinstance(payload, dict) else {}
        return session_store.update_session(
            self.app.state.base_dir,
            last_project_json_path=data.get("last_project_json_path"),
            selected_shot_id=data.get("selected_shot_id"),
            recent_projects=data.get("recent_projects"),
            timeline_scroll_left=data.get("timeline_scroll_left"),
            status_filter=data.get("status_filter"),
            revision_only=data.get("revision_only"),
            advanced_panel_open=data.get("advanced_panel_open"),
            ui_theme=data.get("ui_theme"),
        )

    def method_bootstrap(self) -> dict[str, Any]:
        """
        Single-round-trip startup: read session and describe the recent documents.

        Startup never reopens the previous document — the app lands on Home and the
        user picks. Extracting a `.sbd` is expensive and the previous document is
        not always the one wanted next. `project` is non-null only when one is
        already open (hot reload, or a second client attaching to a live backend).

        Returns {session, project, recents, opened_last_project, startup_timings}.
        """
        t_start = time.perf_counter()
        session = session_store.read_session(self.app.state.base_dir)
        t_session = time.perf_counter()
        project_payload: dict[str, Any] | None = None

        if self.app.state.project is not None:
            # Project already open (hot-reload / multiple clients).
            project_payload = app_state._project_payload(self.app.state.project, self.app.state.dirty)

        recent_entries = self._recent_entries(session)
        t_project = time.perf_counter()
        timings = {
            "session_load_ms": round((t_session - t_start) * 1000, 1),
            "recents_load_ms": round((t_project - t_session) * 1000, 1),
            "total_ms": round((t_project - t_start) * 1000, 1),
        }
        return {
            "session": session,
            "project": project_payload,
            "recents": recent_entries,
            "opened_last_project": False,
            "startup_timings": timings,
        }

    def _recent_entries(self, session: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        data = session if session is not None else session_store.read_session(self.app.state.base_dir)
        stored = data.get("recent_projects")
        paths = [str(item) for item in stored] if isinstance(stored, list) else []
        last = str(data.get("last_project_json_path", "") or "")
        # The most recent document is not always mirrored into recent_projects
        # (older sessions predate the list), so make sure it leads the Home grid.
        if last and last.lower().endswith(".sbd"):
            paths = [last, *paths]
        return recents.list_recents(paths)

    def method_list_recents(self) -> dict[str, Any]:
        return {"recents": self._recent_entries()}

    def method_forget_recent(self, path: str) -> dict[str, Any]:
        session = session_store.read_session(self.app.state.base_dir)
        stored = session.get("recent_projects")
        current = [str(item) for item in stored] if isinstance(stored, list) else []
        remaining = recents.forget(current, path)
        # The last-opened path also seeds the Home grid, so forgetting a document
        # has to clear it there too or the card comes straight back.
        last = str(session.get("last_project_json_path", "") or "")
        session_store.update_session(
            self.app.state.base_dir,
            recent_projects=remaining,
            last_project_json_path="" if recents.same_path(last, path) else None,
        )
        project = self.app.state.project
        if project is not None:
            project.settings["recent_projects"] = recents.forget(
                [str(item) for item in project.settings.get("recent_projects", [])],
                path,
            )
        return {"recents": self._recent_entries()}

    def method_close_project(self) -> dict[str, Any]:
        """Return to Home: flush the document, then drop it from app state.

        The flush is synchronous and unconditional for a dirty document — leaving
        a half-saved `.sbd` behind while the UI says "closed" would be a data-loss
        path. Clears the working tree so no temp copy of the document survives.
        """
        project = self.app.state.project
        if project is None:
            return {"closed": False, "recents": self._recent_entries()}
        try:
            app_state.transition_active_project(
                self.app,
                action="closing this project",
                candidate_factory=None,
            )
        except app_state.ProjectTransitionError as exc:
            logger.exception("Failed to save project while closing")
            status = 409 if exc.stage in {
                "writer_quiesce",
                "external_blender_release",
                "builtin_blender_release",
            } else 500
            raise app_error(
                AppErrorCode.PROJECT_SAVE_FAILED,
                str(exc.cause),
                status=status,
            ) from exc
        return {"closed": True, "recents": self._recent_entries()}

    def method_ui_ready(self) -> dict[str, Any]:
        """
        Called by the frontend once the Welcome or Board UI has painted.
        Writes the per-launch ready marker so the native splash can close.
        Safe no-op when no launch token is present.
        """
        token = os.environ.get("STORYBOARDER_LAUNCH_TOKEN", "").strip()
        if not token:
            return {"ok": True, "marker_written": False, "reason": "no_token"}
        if not _TOKEN_RE.match(token):
            logger.warning("ui-ready: ignoring invalid STORYBOARDER_LAUNCH_TOKEN format")
            return {"ok": True, "marker_written": False, "reason": "invalid_token"}
        marker = Path(tempfile.gettempdir()) / f"storyboarder-launch-{token}.ready"
        try:
            marker.write_text("ready", encoding="utf-8")
            logger.info("[startup] ui-ready marker written: %s", marker)
            return {"ok": True, "marker_written": True, "path": str(marker)}
        except OSError as exc:
            logger.warning("ui-ready: could not write marker: %s", exc)
            return {"ok": False, "marker_written": False, "reason": str(exc)}

    def method_refresh_preview_analysis(self) -> dict[str, Any]:
        """
        Trigger background preview analysis for the current project.
        Returns immediately; only one active job per project root.
        Revision increments only when at least one cache entry is written.
        """
        import uuid as _uuid
        project = self.app.state.project
        if project is None:
            return {"ok": True, "status": "no_project"}

        project_root = str(project.root_path.resolve()).replace("\\", "/")
        existing = runtime_state.get_preview_analysis_job(self.app, project_root)
        if existing and existing["state"] == "running":
            return {
                "ok": True,
                "status": "already_running",
                "task_id": existing["task_id"],
                "project_path": project_root,
                "revision": existing.get("revision", 0),
            }

        task_id = str(_uuid.uuid4())
        prior_revision = existing.get("revision", 0) if existing else 0
        job: dict[str, Any] = {
            "task_id": task_id,
            "project_root": project_root,
            "state": "running",
            "started_at": time.time(),
            "completed_at": None,
            "decoded_count": 0,
            "error": None,
            "revision": prior_revision,
        }
        runtime_state.set_preview_analysis_job(self.app, job)
        logger.info("[analysis] starting task %s for %s", task_id[:8], project_root)

        app = self.app
        captured_project = project
        captured_root = project_root

        def _run() -> None:
            decoded = 0
            try:
                with app_state.project_background_writer(
                    app,
                    f"preview_analysis:{task_id}",
                ) as allowed:
                    if not allowed:
                        return
                    decoded = app_state._analyse_uncached_previews(captured_project)
                new_rev = prior_revision + 1 if decoded > 0 else prior_revision
                logger.info("[analysis] task %s: %d decoded, revision %d→%d", task_id[:8], decoded, prior_revision, new_rev)
            except Exception as exc:
                j = runtime_state.get_preview_analysis_job(app, captured_root)
                if j and j["task_id"] == task_id:
                    j.update({"state": "failed", "completed_at": time.time(), "error": str(exc)})
                    runtime_state.set_preview_analysis_job(app, j)
                logger.debug("Preview analysis task %s failed", task_id[:8], exc_info=True)
                return

            j = runtime_state.get_preview_analysis_job(app, captured_root)
            if j and j["task_id"] == task_id:
                j.update({"state": "complete", "completed_at": time.time(), "decoded_count": decoded, "revision": new_rev})
                runtime_state.set_preview_analysis_job(app, j)

            # Only notify when work changed — zero-work jobs must not trigger project reloads
            if decoded > 0:
                current = app.state.project
                if current and str(current.root_path.resolve()).replace("\\", "/") == captured_root:
                    try:
                        app_state._touch_live_bridge(app)
                    except Exception:
                        pass

        threading.Thread(target=_run, name=f"sb-pa-{task_id[:8]}", daemon=True).start()
        return {
            "ok": True,
            "status": "started",
            "task_id": task_id,
            "project_path": project_root,
            "revision": prior_revision,
        }

    def method_preview_analysis_status(self) -> dict[str, Any]:
        """Return the current preview-analysis job status for the open project."""
        project = self.app.state.project
        if project is None:
            return {"ok": True, "status": "no_project", "job": None}
        project_root = str(project.root_path.resolve()).replace("\\", "/")
        job = runtime_state.get_preview_analysis_job(self.app, project_root)
        status = job["state"] if job else "idle"
        return {"ok": True, "status": status, "job": job}

    def method_app_focus(self) -> dict[str, Any]:
        """Best-effort desktop focus. Browser/dev mode is a clean no-op."""
        window = getattr(self.app.state, "main_window", None)
        window_state = _get_main_window_state(self.app)
        restore_state = _get_main_window_restore_state(self.app)
        if window is None:
            return {
                "ok": True,
                "shown": False,
                "activation_requested": False,
                "focused": False,
                "restored_from_minimized": False,
                "remaximized": False,
                "window_state_before": window_state,
                "window_restore_state_before": restore_state,
                "window_state_after": window_state,
                "errors": [],
            }
        result = _focus_desktop_window(
            window, window_state=window_state, restore_state=restore_state
        )
        if result.get("restored_from_minimized"):
            state_after = result["window_state_after"]
            _set_main_window_state(self.app, state_after)
            # Keep restore_state in sync. In a real env, _mark_maximized sets it when
            # remaximized=True; if remaximized=False (restore_state was "normal" or
            # maximize failed), explicitly align restore_state to the actual window state.
            if not result.get("remaximized"):
                _set_main_window_restore_state(self.app, state_after)
        return result

    def method_preheat_photoshop(self) -> dict[str, Any]:
        project = self.app.state.project
        photoshop_path = str(project.settings.get("photoshop_path", "") or "") if project else ""
        return preheat_photoshop(photoshop_path)

    def method_new_project(
        self,
        path: str | None = None,
        canvas_width: int | None = None,
        canvas_height: int | None = None,
    ) -> dict[str, Any]:
        root = Path(path).expanduser() if path else self.app.state.base_dir / "Untitled.sbd"
        try:
            creator = project_manager.create_document if root.suffix.lower() == ".sbd" else project_manager.create_project
            opened_project = app_state.transition_active_project(
                self.app,
                action="creating another project",
                candidate_factory=lambda: creator(
                    root,
                    canvas_width=canvas_width if canvas_width is not None else 1920,
                    canvas_height=canvas_height if canvas_height is not None else 1080,
                ),
            )
        except app_state.ProjectTransitionError as exc:
            logger.exception("Failed to create project: %s", root)
            status = 409 if exc.stage in {
                "writer_quiesce",
                "external_blender_release",
                "builtin_blender_release",
            } else 400 if exc.stage in {"candidate_open", "candidate_validate"} else 500
            raise app_error(
                AppErrorCode.PROJECT_OPEN_FAILED,
                str(exc.cause),
                status=status,
            ) from exc
        return app_state._project_payload(opened_project, self.app.state.dirty)

    def method_open_project(self, project_json_path: str) -> dict[str, Any]:
        try:
            opened_project = app_state.transition_active_project(
                self.app,
                action="opening another project",
                candidate_factory=lambda: project_manager.open_project(
                    Path(project_json_path).expanduser()
                ),
            )
        except app_state.ProjectTransitionError as exc:
            logger.exception("Failed to open project: %s", project_json_path)
            status = 409 if exc.stage in {
                "writer_quiesce",
                "external_blender_release",
                "builtin_blender_release",
            } else 400 if exc.stage in {"candidate_open", "candidate_validate"} else 500
            raise app_error(
                AppErrorCode.PROJECT_OPEN_FAILED,
                str(exc.cause),
                status=status,
            ) from exc
        return app_state._project_payload(opened_project, self.app.state.dirty)

    def method_save_project(self) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        try:
            blender_bridge.status(self.app)
            bpy_viewport.manager_for_app(self.app).save_if_running()
            project_manager.save_project(project)
        except Exception as exc:
            logger.exception("Failed to save project")
            raise app_error(AppErrorCode.PROJECT_SAVE_FAILED, str(exc), status=500) from exc
        self.app.state.dirty = False
        return app_state._project_payload(project, self.app.state.dirty)

    def method_save_project_as(self, path: str) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        try:
            blender_bridge.require_released(self.app, "using Save As")
        except ValueError as exc:
            raise app_error(AppErrorCode.PROJECT_SAVE_FAILED, str(exc), status=409) from exc
        bpy_viewport.stop_worker(self.app)
        try:
            destination = validate_project_save_path(path)
            if not destination:
                raise ValueError("Save As destination is required.")
            saved_project = project_manager.save_project_as(project, Path(destination))
        except Exception as exc:
            logger.exception("Failed to save project as %s", path)
            raise app_error(AppErrorCode.PROJECT_SAVE_FAILED, str(exc), status=500) from exc
        if saved_project is not project:
            app_state._track_project(self.app, saved_project)
        app_state._remember_recent(self.app.state.project)
        app_state._persist_app_session(self.app)
        app_state._touch_live_bridge(self.app)
        self.app.state.dirty = False
        return app_state._project_payload(self.app.state.project, self.app.state.dirty)

    def method_get_missing_files(self) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        return {"missing_files": missing_files(project)}

    def method_bridge_status(self) -> dict[str, Any]:
        return app_state._bridge_status_payload(self.app)

    def method_bridge_relink(self) -> dict[str, Any]:
        app_state._require_project(self.app)
        app_state._touch_live_bridge(self.app, selected_shot_id=runtime_state.live_selected_shot_id(self.app))
        return app_state._bridge_status_payload(self.app)

    def method_touch_live_bridge(self, selected_shot_id: str | None = None) -> dict[str, Any]:
        return app_state._touch_live_bridge(self.app, selected_shot_id=selected_shot_id)

    def _plugin_service(self) -> PluginBridgeService:
        return PluginBridgeService(self.app)

    def _mark_plugin_project_changed(self) -> None:
        self._plugin_service().mark_project_changed()

    def method_plugin_heartbeat(self, payload: dict[str, Any] | None = None) -> dict[str, str]:
        return self._plugin_service().heartbeat(payload)

    def method_plugin_context(self) -> dict[str, Any]:
        return self._plugin_service().context()

    def _plugin_context_payload(self, project) -> dict[str, Any]:
        return self._plugin_service().context_payload(project)

    def method_plugin_export_preview(self, shot_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._plugin_service().export_preview(shot_id, payload)

    def method_plugin_psd_saved(self, shot_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._plugin_service().psd_saved(shot_id, payload)

    def method_plugin_focus_shot(self, shot_id: str) -> dict[str, Any]:
        return self._plugin_service().focus_shot(shot_id)

    def method_plugin_next_shot(self, current_shot_id: str | None = None, auto_add: bool = False) -> dict[str, Any]:
        return self._plugin_service().next_shot(current_shot_id, auto_add)

    def _plugin_shot_payload(self, project, shot) -> dict[str, Any]:
        return self._plugin_service().shot_payload(project, shot)

    def _plugin_shot_paths(self, project, shot) -> dict[str, str]:
        return self._plugin_service().shot_paths(project, shot)

    def _plugin_shot_psd_path(self, project, shot) -> Path | None:
        return self._plugin_service().shot_psd_path(project, shot)

    def _plugin_shot_health(self, project, shot) -> dict[str, Any]:
        return self._plugin_service().shot_health(project, shot)

    def method_add_shot(self, after_shot_id: str | None = None) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        try:
            shot = shot_service.create_shot(project, after_shot_id or None)
        except ValueError as exc:
            raise app_error(AppErrorCode.SHOT_NOT_FOUND, str(exc), status=404) from exc
        app_state._autosave(self.app)
        return {"shot": shot.to_dict(), **app_state._project_payload(project, self.app.state.dirty)}

    def method_duplicate_shot(self, shot_id: str) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        try:
            duplicate = shot_service.duplicate_shot(project, shot_id)
        except ValueError as exc:
            raise app_error(AppErrorCode.SHOT_NOT_FOUND, str(exc), status=404) from exc
        app_state._autosave(self.app)
        return {"shot": duplicate.to_dict(), **app_state._project_payload(project, self.app.state.dirty)}

    def method_update_shot(self, shot_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        shot = app_state._find_shot(project, shot_id)
        shot_service.update_shot(shot, payload if isinstance(payload, dict) else {})
        app_state._autosave(self.app)
        return app_state._project_payload(project, self.app.state.dirty)

    @staticmethod
    def _unique_shot_ids(shot_ids: list[str]) -> list[str]:
        unique: list[str] = []
        seen: set[str] = set()
        for raw_id in shot_ids:
            shot_id = str(raw_id or "").strip()
            if shot_id and shot_id not in seen:
                seen.add(shot_id)
                unique.append(shot_id)
        if not unique:
            raise ValueError("At least one shot is required.")
        return unique

    def method_update_shots_batch(self, updates: list[dict[str, Any]]) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        if not isinstance(updates, list) or not updates:
            raise app_error(AppErrorCode.INVALID_REQUEST, "At least one shot update is required.")
        normalized: list[tuple[Any, dict[str, Any]]] = []
        seen: set[str] = set()
        try:
            for item in updates:
                shot_id = str(item.get("shot_id") or "").strip()
                if not shot_id or shot_id in seen:
                    raise ValueError("Batch shot ids must be non-empty and unique.")
                seen.add(shot_id)
                changes = item.get("changes")
                if not isinstance(changes, dict):
                    raise ValueError(f"Changes must be an object for shot: {shot_id}")
                normalized.append((shot_service.find_shot(project, shot_id), changes))
            with project_transaction.mutate_project(project):
                for shot, changes in normalized:
                    shot_service.update_shot(shot, changes)
                app_state._autosave(self.app)
        except ValueError as exc:
            raise app_error(AppErrorCode.INVALID_REQUEST, str(exc)) from exc
        return app_state._project_payload(project, self.app.state.dirty)

    def method_delete_shots_batch(self, shot_ids: list[str]) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        try:
            ids = self._unique_shot_ids(shot_ids)
            for shot_id in ids:
                shot_service.find_shot(project, shot_id)
            with project_transaction.mutate_project(project):
                for shot_id in ids:
                    shot_service.delete_shot(project, shot_id)
                app_state._autosave(self.app)
        except ValueError as exc:
            raise app_error(AppErrorCode.INVALID_REQUEST, str(exc)) from exc
        return app_state._project_payload(project, self.app.state.dirty)

    def method_restore_shots_batch(self, items: list[dict[str, Any]]) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        if not isinstance(items, list) or not items:
            raise app_error(AppErrorCode.INVALID_REQUEST, "At least one shot is required.")
        try:
            normalized = sorted(
                (
                    (dict(item["shot"]), int(item.get("index", 0)))
                    for item in items
                    if isinstance(item, dict)
                ),
                key=lambda item: item[1],
            )
            if len(normalized) != len(items):
                raise ValueError("Every restore item must contain a shot.")
            restore_ids = [str(shot.get("shot_id") or "") for shot, _index in normalized]
            if len(set(restore_ids)) != len(restore_ids) or any(not shot_id for shot_id in restore_ids):
                raise ValueError("Restore shot ids must be non-empty and unique.")
            existing_ids = {shot.shot_id for shot in project.shots}
            if any(shot_id in existing_ids for shot_id in restore_ids):
                raise ValueError("A restored shot already exists.")
            with project_transaction.mutate_project(project):
                for shot, index in normalized:
                    project_manager.restore_shot(project, shot, index)
                app_state._autosave(self.app)
        except (KeyError, TypeError, ValueError) as exc:
            raise app_error(AppErrorCode.INVALID_REQUEST, str(exc)) from exc
        return app_state._project_payload(project, self.app.state.dirty)

    def method_create_queue_batch_requests(self, shot_ids: list[str]) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        requests: list[dict[str, Any]] = []
        try:
            ids = self._unique_shot_ids(shot_ids)
            target_ids = set(ids)
            target_shots = [shot for shot in project.shots if shot.shot_id in target_ids]
            if len(target_shots) != len(ids):
                missing = next(shot_id for shot_id in ids if shot_id not in {shot.shot_id for shot in target_shots})
                raise ValueError(f"Shot not found: {missing}")
            with project_transaction.mutate_project(project):
                requests = [
                    generation_service.create_request(project, shot, "queue", provider="codex")
                    for shot in target_shots
                ]
                for shot, request in zip(target_shots, requests, strict=True):
                    shot.generation_state.update({
                        "execution_status": "queued",
                        "review_status": "unreviewed",
                        "freshness_status": "current",
                        "active_output_id": "",
                        "latest_attempt_id": request["request_id"],
                    })
                app_state._autosave(self.app)
        except (OSError, ValueError) as exc:
            raise app_error(AppErrorCode.GENERATION_REQUEST_FAILED, str(exc)) from exc
        return {
            "requests": generation_service.list_requests(project),
            "project": app_state._project_payload(project, self.app.state.dirty),
            "created_request_ids": [str(request["request_id"]) for request in requests],
        }

    def method_create_generation_request(
        self,
        shot_id: str,
        destination: str,
        provider: str = "codex",
        mode: str = "",
        clear_queue_on_result: bool = True,
    ) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        shot = app_state._find_shot(project, shot_id)
        request: dict[str, Any] | None = None
        try:
            with project_transaction.mutate_project(project):
                request = generation_service.create_request(
                    project,
                    shot,
                    destination,
                    provider=provider,
                    mode=mode,
                    clear_queue_on_result=clear_queue_on_result,
                )
                shot.generation_state.update({
                    "execution_status": "queued",
                    "review_status": "unreviewed",
                    "freshness_status": "current",
                    "active_output_id": "",
                    "latest_attempt_id": request["request_id"],
                })
                try:
                    app_state._autosave(self.app)
                except Exception:
                    generation_service.delete_request(project, request["request_id"])
                    raise
        except (OSError, ValueError) as exc:
            raise app_error(AppErrorCode.GENERATION_REQUEST_FAILED, str(exc)) from exc
        assert request is not None
        response = {
            "request": request,
            "requests": generation_service.list_requests(project, shot_id=shot_id),
            "project": app_state._project_payload(project, self.app.state.dirty),
        }
        if request["destination"] == "codex":
            response["codex_prompt"] = generation_service.codex_handoff_prompt(
                request["request_id"],
                provider=str(request.get("provider") or "codex"),
                mode=str(request.get("mode") or ""),
            )
        return response

    def method_create_codex_batch_requests(
        self,
        provider: str = "codex",
        clear_queue_on_result: bool = True,
        scope: str = "auto",
    ) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        pending_queue = generation_service.list_requests(
            project,
            destination="queue",
            status="queued",
        )
        queued_shot_ids = {
            str(request.get("shot_id") or "")
            for request in pending_queue
            if request.get("shot_id")
        }
        scope = str(scope or "").strip().lower()
        if scope not in {"auto", "queued", "all"}:
            raise app_error(
                AppErrorCode.INVALID_REQUEST,
                "Generation batch scope must be 'auto', 'queued', or 'all'.",
            )
        if scope == "all":
            target_shots = list(project.shots)
        elif scope == "queued":
            target_shots = [shot for shot in project.shots if shot.shot_id in queued_shot_ids]
            if not target_shots:
                raise app_error(AppErrorCode.INVALID_REQUEST, "The generation queue is empty.")
        else:
            target_shots = (
                [shot for shot in project.shots if shot.shot_id in queued_shot_ids]
                if queued_shot_ids
                else list(project.shots)
            )
        try:
            with project_transaction.mutate_project(project):
                requests = [
                    generation_service.create_request(
                        project,
                        shot,
                        "codex",
                        provider=provider,
                        clear_queue_on_result=clear_queue_on_result,
                    )
                    for shot in target_shots
                ]
                for shot, request in zip(target_shots, requests, strict=True):
                    shot.generation_state.update({
                        "execution_status": "queued",
                        "review_status": "unreviewed",
                        "freshness_status": "current",
                        "active_output_id": "",
                        "latest_attempt_id": request["request_id"],
                    })
                app_state._autosave(self.app)
        except (OSError, ValueError) as exc:
            raise app_error(AppErrorCode.GENERATION_REQUEST_FAILED, str(exc)) from exc
        return {
            "requests": generation_service.list_requests(project),
            "project": app_state._project_payload(project, self.app.state.dirty),
            "created_request_ids": [str(request["request_id"]) for request in requests],
            "codex_prompt": generation_service.codex_batch_handoff_prompt(
                [str(request["request_id"]) for request in requests],
                provider=provider,
            ),
        }

    def method_list_generation_requests(
        self,
        *,
        shot_id: str = "",
        destination: str = "",
        status: str = "",
    ) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        try:
            requests = generation_service.list_requests(
                project,
                shot_id=str(shot_id or ""),
                destination=str(destination or ""),
                status=str(status or ""),
            )
        except ValueError as exc:
            raise app_error(AppErrorCode.INVALID_REQUEST, str(exc)) from exc
        return {"requests": requests}

    def method_delete_generation_request(self, request_id: str) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        try:
            request = generation_service.get_request(project, request_id)
        except ValueError as exc:
            raise app_error(AppErrorCode.GENERATION_REQUEST_FAILED, str(exc), status=404) from exc

        try:
            with project_transaction.mutate_project(project):
                generation_service.delete_request(project, request_id)
                shot = next((candidate for candidate in project.shots if candidate.shot_id == request.get("shot_id")), None)
                if shot and shot.generation_state.get("latest_attempt_id") == request_id:
                    remaining = generation_service.list_requests(project, shot_id=shot.shot_id)
                    if remaining:
                        shot.generation_state["latest_attempt_id"] = str(remaining[-1].get("request_id") or "")
                    else:
                        shot.generation_state.update({
                            "execution_status": "idle",
                            "review_status": "unreviewed",
                            "active_output_id": "",
                            "latest_attempt_id": "",
                        })
                app_state._autosave(self.app)
        except (OSError, ValueError) as exc:
            raise app_error(AppErrorCode.GENERATION_REQUEST_FAILED, str(exc)) from exc
        return {
            "requests": generation_service.list_requests(project),
            "project": app_state._project_payload(project, self.app.state.dirty),
        }

    def method_pull_generation_results(self) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        try:
            with project_transaction.mutate_project(project):
                result = generation_service.pull_results(project)
                if result["updated_shot_ids"] or result["accepted_request_ids"]:
                    app_state._autosave(self.app)
        except (OSError, ValueError) as exc:
            raise app_error(AppErrorCode.GENERATION_REQUEST_FAILED, str(exc)) from exc
        return {
            **result,
            "requests": generation_service.list_requests(project),
            "project": app_state._project_payload(project, self.app.state.dirty),
        }

    def method_reconcile_generation_results(self) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        try:
            with project_transaction.mutate_project(project):
                result = generation_service.reconcile_results(project)
                if result["updated_shot_ids"]:
                    app_state._autosave(self.app)
        except (OSError, ValueError) as exc:
            raise app_error(AppErrorCode.GENERATION_REQUEST_FAILED, str(exc)) from exc
        return {
            **result,
            "requests": generation_service.list_requests(project),
            "project": app_state._project_payload(project, self.app.state.dirty),
        }

    def method_accept_generation_candidate(
        self,
        shot_id: str,
        request_id: str,
        result_id: str,
        artifact_path: str,
    ) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        shot = app_state._find_shot(project, shot_id)
        try:
            with project_transaction.mutate_project(project):
                generation_service.accept_candidate_as_codex_layer(
                    project,
                    shot,
                    request_id,
                    result_id,
                    artifact_path,
                )
                app_state._autosave(self.app)
        except (OSError, ValueError) as exc:
            raise app_error(AppErrorCode.GENERATION_REQUEST_FAILED, str(exc)) from exc
        return {
            "requests": generation_service.list_requests(project, shot_id=shot_id),
            "project": app_state._project_payload(project, self.app.state.dirty),
        }

    def method_delete_shot(self, shot_id: str) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        try:
            with project_transaction.mutate_project(project):
                shot_service.delete_shot(project, shot_id)
        except ValueError as exc:
            raise app_error(AppErrorCode.SHOT_NOT_FOUND, str(exc), status=404) from exc
        app_state._autosave(self.app)
        return app_state._project_payload(project, self.app.state.dirty)

    def method_restore_shot(self, shot: dict[str, Any], index: int = 0) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        if not isinstance(shot, dict):
            raise app_error(AppErrorCode.INVALID_REQUEST, "Shot payload required.")
        try:
            with project_transaction.mutate_project(project):
                project_manager.restore_shot(project, shot, int(index))
        except (KeyError, ValueError) as exc:
            raise app_error(AppErrorCode.INVALID_REQUEST, str(exc)) from exc
        app_state._autosave(self.app)
        return app_state._project_payload(project, self.app.state.dirty)

    def method_reorder_shots(self, shot_ids: list[str]) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        if not isinstance(shot_ids, list):
            raise app_error(AppErrorCode.INVALID_REQUEST, "Shot order required.")
        try:
            with project_transaction.mutate_project(project):
                shot_service.reorder_shots(project, shot_ids)
        except ValueError as exc:
            raise app_error(AppErrorCode.INVALID_REQUEST, str(exc)) from exc
        app_state._autosave(self.app)
        return app_state._project_payload(project, self.app.state.dirty)

    def method_import_image_path(self, shot_id: str, source_path: str) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        shot = app_state._find_shot(project, shot_id)
        try:
            project_manager.import_image_for_shot(project, shot, Path(str(source_path)).expanduser())
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        app_state._autosave(self.app)
        return app_state._project_payload(project, self.app.state.dirty)

    def method_apply_ref_segment(self, anchor_shot_id: str, end_shot_id: str, segment_id: str = "") -> dict[str, Any]:
        project = app_state._require_project(self.app)
        anchor = app_state._find_shot_index(project, anchor_shot_id)
        end = app_state._find_shot_index(project, end_shot_id)
        try:
            with project_transaction.mutate_project(project):
                result = project_manager.apply_ref_segment_to_boards(
                    project,
                    anchor,
                    end,
                    segment_id or None,
                )
        except (FileNotFoundError, ValueError) as exc:
            raise app_error(AppErrorCode.REF_APPLY_FAILED, str(exc)) from exc
        app_state._autosave(self.app)
        return {**result, **app_state._project_payload(project, self.app.state.dirty)}

    def method_apply_ref_segment_image(
        self,
        anchor_shot_id: str,
        end_shot_id: str,
        segment_id: str = "",
    ) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        anchor = app_state._find_shot_index(project, anchor_shot_id)
        end = app_state._find_shot_index(project, end_shot_id)
        try:
            with project_transaction.mutate_project(project):
                result = project_manager.apply_ref_segment_image_to_boards(
                    project,
                    anchor,
                    end,
                    segment_id or None,
                )
        except (FileNotFoundError, ValueError) as exc:
            raise app_error(AppErrorCode.REF_APPLY_FAILED, str(exc)) from exc
        app_state._autosave(self.app)
        return {**result, **app_state._project_payload(project, self.app.state.dirty)}

    def method_apply_ref_segment_3d(
        self,
        anchor_shot_id: str,
        end_shot_id: str,
        segment_id: str = "",
        camera_name: str = "",
    ) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        anchor = app_state._find_shot_index(project, anchor_shot_id)
        end = app_state._find_shot_index(project, end_shot_id)
        try:
            with project_transaction.mutate_project(project):
                result = project_manager.apply_ref_segment_3d_to_boards(
                    project,
                    anchor,
                    end,
                    segment_id or None,
                    camera_name=str(camera_name or ""),
                )
        except (FileNotFoundError, ValueError) as exc:
            raise app_error(AppErrorCode.REF_APPLY_FAILED, str(exc)) from exc
        app_state._autosave(self.app)
        return {**result, **app_state._project_payload(project, self.app.state.dirty)}

    def method_apply_ref_segment_model_captures(
        self,
        anchor_shot_id: str,
        end_shot_id: str,
        segment_id: str,
        camera_name: str,
        captures: list[dict[str, Any]],
    ) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        try:
            with project_transaction.mutate_project(project):
                result = reference_segments.apply_model_captures_to_boards(
                    project,
                    anchor_shot_id,
                    end_shot_id,
                    segment_id,
                    camera_name,
                    captures,
                )
        except (KeyError, FileNotFoundError, ValueError) as exc:
            raise app_error(AppErrorCode.REF_APPLY_FAILED, str(exc)) from exc
        app_state._autosave(self.app)
        return {**result, **app_state._project_payload(project, self.app.state.dirty)}

    def method_snapshot_ref_boards(self, anchor_shot_id: str, end_shot_id: str) -> dict[str, Any]:
        # Manual snapshot of a board range before a destructive bake. Returns an undo token usable
        # with method_restore_ref_apply / restore_boards_from_undo. Browser 3D apply snapshots
        # inside apply_model_captures_to_boards before writing board images.
        project = app_state._require_project(self.app)
        anchor = app_state._find_shot_index(project, anchor_shot_id)
        end = app_state._find_shot_index(project, end_shot_id)
        lo, hi = (anchor, end) if anchor <= end else (end, anchor)
        try:
            token = project_manager.snapshot_boards_for_undo(project, lo, hi)
        except (FileNotFoundError, ValueError) as exc:
            raise app_error(AppErrorCode.REF_APPLY_FAILED, str(exc)) from exc
        return {"undo_token": token}

    def method_restore_ref_apply(self, token: str) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        try:
            with project_transaction.mutate_project(project):
                result = project_manager.restore_boards_from_undo(project, token)
        except (FileNotFoundError, ValueError) as exc:
            raise app_error(AppErrorCode.REF_APPLY_FAILED, str(exc)) from exc
        app_state._autosave(self.app)
        return {**result, **app_state._project_payload(project, self.app.state.dirty)}

    def method_delete_ref_segment(self, segment_id: str) -> dict[str, Any]:
        project = app_state._refresh_project_from_disk(self.app)
        try:
            with project_transaction.mutate_project(project):
                result = project_manager.delete_ref_segment(project, segment_id)
        except (KeyError, FileNotFoundError, ValueError) as exc:
            raise app_error(AppErrorCode.REF_APPLY_FAILED, str(exc)) from exc
        app_state._autosave(self.app)
        return {**result, **app_state._project_payload(project, self.app.state.dirty)}

    def method_move_shot_up(self, shot_id: str) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        project_manager.move_shot_up(project, app_state._find_shot_index(project, shot_id))
        app_state._autosave(self.app)
        return app_state._project_payload(project, self.app.state.dirty)

    def method_move_shot_down(self, shot_id: str) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        project_manager.move_shot_down(project, app_state._find_shot_index(project, shot_id))
        app_state._autosave(self.app)
        return app_state._project_payload(project, self.app.state.dirty)

    def method_sync_shot(self, shot_id: str, force: bool = False) -> dict[str, Any]:
        project = app_state._refresh_project_from_disk(self.app)
        shot = app_state._find_shot(project, shot_id)
        if project_manager.relink_shot_preview_from_disk(project, shot):
            app_state._autosave(self.app)
        try:
            result = project_manager.sync_shot(project, shot, force=bool(force))
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if result.get("synced"):
            app_state._autosave(self.app)
        return {"result": result, **app_state._project_payload(project, self.app.state.dirty)}

    def method_get_annotations(self, shot_id: str) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        shot = app_state._find_shot(project, shot_id)
        path = app_state._annotation_path(project, shot)
        try:
            annotations = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid annotation JSON: {exc}") from exc
        if not isinstance(annotations, list):
            raise HTTPException(status_code=400, detail="Annotation file must contain a list.")
        return {"annotations": annotations}

    def method_save_annotations(self, shot_id: str, annotations: list[Any]) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        shot = app_state._find_shot(project, shot_id)
        path = app_state._annotation_path(project, shot)
        payload = annotations if isinstance(annotations, list) else []
        project_manager._atomic_write_text(path, json.dumps(payload, indent=2))
        return {"annotations": payload}

    def method_add_comment(self, shot_id: str, text: str) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        shot = app_state._find_shot(project, shot_id)
        cleaned = str(text or "").strip()
        if not cleaned:
            raise HTTPException(status_code=400, detail="Comment cannot be empty.")
        next_id = max([int(comment.get("id", 0)) for comment in shot.comments] or [0]) + 1
        shot.comments.append({"id": next_id, "text": cleaned, "resolved": False})
        app_state._autosave(self.app)
        return app_state._project_payload(project, self.app.state.dirty)

    def method_resolve_comment(self, shot_id: str, comment_id: int, resolved: bool = True) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        shot = app_state._find_shot(project, shot_id)
        for comment in shot.comments:
            if int(comment.get("id", 0)) == int(comment_id):
                comment["resolved"] = bool(resolved)
                app_state._autosave(self.app)
                return app_state._project_payload(project, self.app.state.dirty)
        raise HTTPException(status_code=404, detail="Comment not found.")

    def method_update_settings(self, payload: dict[str, Any]) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        data = payload if isinstance(payload, dict) else {}
        previous_character_bible = str(project.settings.get("character_bible_prompt") or "").strip()
        if "photoshop_path" in data:
            value = str(data.get("photoshop_path") or "").strip()
            if value:
                try:
                    value = validate_photoshop_path(value)
                except (FileNotFoundError, ValueError) as exc:
                    raise HTTPException(status_code=400, detail=str(exc)) from exc
            project.settings["photoshop_path"] = value
        if "blender_path" in data:
            value = str(data.get("blender_path") or "").strip()
            if value:
                try:
                    value = validate_blender_path(value)
                except (FileNotFoundError, ValueError) as exc:
                    raise HTTPException(status_code=400, detail=str(exc)) from exc
            project.settings["blender_path"] = value
        if "reference_video_path" in data:
            value = str(data.get("reference_video_path") or "").strip()
            if value:
                project_manager.set_active_reference_video(project, value)
            else:
                project_manager.clear_active_reference_video(project)
        if "reference_model_path" in data:
            value = str(data.get("reference_model_path") or "").strip()
            if value:
                project_manager.set_active_reference_model(project, value)
            else:
                project_manager.clear_active_reference_model(project)
        if "reference_image_path" in data:
            value = str(data.get("reference_image_path") or "").strip()
            if value:
                project_manager.set_active_reference_image(project, value)
            else:
                project_manager.clear_active_reference_image(project)
        if "reference_segment_mode" in data:
            mode = str(data.get("reference_segment_mode") or "").strip().lower()
            if mode in {"video", "model", "image"}:
                project.settings["reference_segment_mode"] = mode
        if "reference_links" in data:
            project.settings["reference_links"] = project_manager.normalize_reference_links(data.get("reference_links"))
        if "ref_segment" in data:
            segment = data.get("ref_segment")
            project.settings["ref_segment"] = segment if isinstance(segment, dict) else {}
        if "ref_segments" in data:
            segments = data.get("ref_segments")
            project.settings["ref_segments"] = segments if isinstance(segments, list) else []
            project_manager.sync_ref_segment_settings(project)
        if "active_ref_segment_id" in data:
            project.settings["active_ref_segment_id"] = str(data.get("active_ref_segment_id") or "").strip()
            project_manager.sync_ref_segment_settings(project)
        if "ref_segment_video" in data:
            raw_segment = data.get("ref_segment_video")
            segment = raw_segment if isinstance(raw_segment, dict) else {}
            project.settings["ref_segment_video"] = segment
            seg_id = str(segment.get("segment_id", "") or project.settings.get("active_ref_segment_id", "") or "").strip()
            if seg_id and "start" in segment:
                project_manager.update_ref_segment_video_start(
                    project,
                    seg_id,
                    float(segment.get("start", 0.0) or 0.0),
                )
        if "canvas_width" in data and "canvas_height" in data:
            project_manager.persist_canvas_size(
                project,
                data.get("canvas_width"),
                data.get("canvas_height"),
                apply_to_blank_shots=bool(data.get("apply_canvas_size_to_blank_shots")),
            )
            self.app.state.dirty = True
        if "canvas_background_color" in data:
            color = normalize_hex_color(str(data["canvas_background_color"]))
            project.settings["canvas_background_color"] = color
            project_manager.write_canvas_color_files(project, color)
        if "preheat_photoshop_on_open" in data:
            # TODO(preheat-photoshop): wire this stored startup preference to a lightweight
            # Photoshop warmup hook if one is added; do not launch Photoshop from settings writes.
            project.settings["preheat_photoshop_on_open"] = bool(data.get("preheat_photoshop_on_open"))
        if data.get("autosave_interval_minutes") is not None:
            try:
                minutes = int(data["autosave_interval_minutes"])
            except (TypeError, ValueError):
                minutes = 5
            project.settings["autosave_interval_minutes"] = min(60, max(1, minutes))
        if "character_bible_prompt" in data:
            project.settings["character_bible_prompt"] = str(data.get("character_bible_prompt") or "").strip()
        if "scene3d" in data:
            project.settings["scene3d"] = data["scene3d"]
        character_bible_changed = (
            "character_bible_prompt" in data
            and str(project.settings.get("character_bible_prompt") or "").strip() != previous_character_bible
        )
        if character_bible_changed:
            generation_service.mark_all_generated_shots_stale(project)
            app_state._autosave(self.app)
        else:
            project_manager.save_settings(project)
        project_manager.write_bridge_file(project)
        project_manager.sync_document(project)
        app_state._touch_live_bridge(self.app)
        return app_state._project_payload(project, self.app.state.dirty)

    def method_browse_folder(self) -> dict[str, Any]:
        return self._browse("folder", browse_folder, validate_folder_path)

    def method_browse_project_json(self) -> dict[str, Any]:
        return self._browse("project-json", browse_project_json, validate_project_json_path)

    def method_browse_project_save(self) -> dict[str, Any]:
        return self._browse("project-save", browse_project_save, validate_project_save_path)

    def method_browse_photoshop(self) -> dict[str, str]:
        return self._browse("photoshop", browse_photoshop_executable, validate_photoshop_path)

    def method_browse_blender(self) -> dict[str, str]:
        return self._browse("blender", browse_blender_executable, validate_blender_path)

    def method_photoshop_candidates(self) -> dict[str, Any]:
        project = self.app.state.project
        current = str(project.settings.get("photoshop_path", "") or "") if project else ""
        return {"candidates": detect_photoshop_paths(), "current": current}

    def method_blender_candidates(self) -> dict[str, Any]:
        project = self.app.state.project
        current = str(project.settings.get("blender_path", "") or "") if project else ""
        return {
            "candidates": detect_blender_paths(),
            "current": current,
            "template_exists": project_manager.blend_template_path().is_file(),
            "template_path": str(project_manager.blend_template_path()),
        }

    def method_remove_shot_image(self, shot_id: str) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        shot = app_state._find_shot(project, shot_id)
        project_manager.remove_image_for_shot(project, shot)
        app_state._autosave(self.app)
        return app_state._project_payload(project, self.app.state.dirty)

    def method_remove_fixed_layer(self, shot_id: str, layer_id: str) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        shot = app_state._find_shot(project, shot_id)
        cleaned = str(layer_id or "").strip().lower()
        with project_transaction.mutate_project(project):
            if cleaned == "background":
                project_manager.remove_board_background_for_shot(project, shot)
                reference_segments.clear_shot_reference_layer_state(shot)
            elif cleaned == "codex":
                project_manager.remove_codex_layer_for_shot(project, shot)
                shot.generation_state["approved_output_id"] = ""
                shot.generation_state["review_status"] = (
                    "needs-review" if shot.generation_state.get("active_output_id") else "unreviewed"
                )
            else:
                raise app_error(AppErrorCode.INVALID_REQUEST, "Only background and Codex layers can be removed here.")
            app_state._autosave(self.app)
        return app_state._project_payload(project, self.app.state.dirty)

    def method_relink_preview(self, shot_id: str, relative_path: str) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        shot = app_state._find_shot(project, shot_id)
        try:
            project_manager.relink_preview_image(project, shot, relative_path)
        except (FileNotFoundError, ValueError) as exc:
            logger.exception("Failed to relink preview for shot %s", shot_id)
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        app_state._autosave(self.app)
        return app_state._project_payload(project, self.app.state.dirty)

    def method_open_preview(self, shot_id: str) -> dict[str, str]:
        project = app_state._require_project(self.app)
        shot = app_state._find_shot(project, shot_id)
        rel_path = shot.preview_image_path or shot.image_path
        if not rel_path:
            raise app_error(AppErrorCode.MEDIA_NOT_FOUND, "No preview image linked.")
        try:
            opened = project_manager.open_project_file(project, rel_path, project.settings.get("photoshop_path", ""))
        except (FileNotFoundError, ValueError) as exc:
            logger.exception("Failed to open preview for shot %s", shot_id)
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"path": str(opened)}

    def _request_plugin_focus(self, shot_id: str) -> None:
        """Ask the connected plugin to switch to an already-open shot tab."""
        runtime_state.request_live_focus(self.app, shot_id)
        app_state._touch_live_bridge(self.app, selected_shot_id=shot_id)

    def method_open_source(self, shot_id: str) -> dict[str, str]:
        project = app_state._require_project(self.app)
        shot = app_state._find_shot(project, shot_id)
        if not shot.source_file_path:
            raise app_error(AppErrorCode.MEDIA_NOT_FOUND, "No source file linked. Create a PS canvas first.")
        # If the plugin already has this shot open as a tab, switch to it instead
        # of launching Photoshop again (which creates a confusing duplicate).
        plugin_linked, _age, open_shot_ids = app_state._plugin_link_state(self.app)
        if plugin_linked and shot_id in open_shot_ids:
            source_native_path = str((project.root_path / shot.source_file_path).resolve()).replace("\\", "/")
            runtime_state.set_active_shot_context(
                self.app,
                shot_id,
                source_file_path=shot.source_file_path,
                preview_image_path=shot.preview_image_path,
                source_native_path=source_native_path,
            )
            self._request_plugin_focus(shot_id)
            return {"path": shot.source_file_path, "switched": "true"}
        try:
            opened = project_manager.open_project_file(
                project,
                shot.source_file_path,
                project.settings.get("photoshop_path", ""),
                shot=shot,
            )
        except (FileNotFoundError, ValueError) as exc:
            logger.exception("Failed to open source file for shot %s", shot_id)
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"path": str(opened)}

    def method_recover_shot_source(self, shot_id: str, preserve_layers: bool = True) -> dict[str, Any]:
        """Rebuild a broken (Photoshop-unopenable) source PSD from its layers."""
        project = app_state._require_project(self.app)
        shot = app_state._find_shot(project, shot_id)
        try:
            result = project_manager.recover_shot_source_psd(
                project, shot, preserve_layers=bool(preserve_layers)
            )
        except (ValueError, FileNotFoundError) as exc:
            logger.exception("Failed to recover source file for shot %s", shot_id)
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 - surface rebuild failures to the caller
            logger.exception("Failed to recover source file for shot %s", shot_id)
            raise HTTPException(status_code=400, detail=f"PSD recovery failed: {exc}") from exc
        app_state._autosave(self.app)
        return {"result": result, **app_state._project_payload(project, self.app.state.dirty)}

    def method_delete_project_reference(self, ref_id: str) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        try:
            with project_transaction.mutate_project(project):
                project_manager.remove_project_reference(project, ref_id)
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        app_state._autosave(self.app)
        return app_state._project_payload(project, self.app.state.dirty)

    def method_open_blender_scene(self) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        existing = blender_bridge.status(self.app)
        if existing["external_blender_owned"]:
            opened = Path(str(existing["external_blender_blend_path"]))
            try:
                relative_path = opened.relative_to(project.root_path).as_posix()
            except ValueError:
                relative_path = ""
            return {
                "path": str(opened),
                "relative_path": relative_path,
                "blender_bridge": existing,
                **app_state._project_payload(project, self.app.state.dirty),
            }
        manager = bpy_viewport.manager_for_app(self.app)
        try:
            manager.save_if_running()
            bpy_viewport.stop_worker(self.app)
            active_scene = scene3d.ensure_active_scene(project)
            attached = str(active_scene.get("blend_file_path") or "").strip()
            blend_path = (
                (project.root_path / attached).resolve()
                if attached
                else project_manager.ensure_project_blend_file(project).resolve()
            )
            active_scene = scene3d.configure_blend_preview(
                project,
                str(active_scene["id"]),
                blend_path,
            )
            session = blender_bridge.begin_session(
                self.app,
                project,
                active_scene,
                blend_path,
            )
            bootstrap = (
                Path(__file__).resolve().parent
                / "blender_addon"
                / "register_storyboarder_addon.py"
            )
            opened = scene3d.open_blender_scene(
                project,
                python_script=bootstrap,
                script_args=[
                    "--storyboarder-bridge",
                    session["bridge_path"],
                    "--storyboarder-heartbeat",
                    session["heartbeat_path"],
                    "--storyboarder-session",
                    session["session_id"],
                ],
                on_launch=lambda process: blender_bridge.attach_process(self.app, process),
            )
        except (FileNotFoundError, ValueError) as exc:
            blender_bridge.cancel_session(self.app)
            logger.exception("Failed to open Blender scene")
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception:
            blender_bridge.cancel_session(self.app)
            raise
        app_state._touch_live_bridge(self.app)
        return {
            "path": str(opened),
            "relative_path": opened.relative_to(project.root_path).as_posix() if opened.exists() else "",
            "blender_bridge": blender_bridge.status(self.app),
            **app_state._project_payload(project, self.app.state.dirty),
        }

    def method_list_scene3d(self) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        return scene3d.list_scenes(project)

    def method_create_scene3d(self, data: dict[str, Any]) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        try:
            payload = scene3d.create_scene(
                project,
                title=str(data.get("title") or ""),
                description=str(data.get("description") or ""),
                keywords=data.get("keywords") if isinstance(data.get("keywords"), list) else None,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        project_manager.sync_document(project)
        return payload

    def method_update_scene3d(self, scene3d_id: str, data: dict[str, Any]) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        try:
            before_scene = next(
                (item for item in scene3d.list_scenes(project).get("scenes", []) if item.get("id") == scene3d_id),
                None,
            )
            payload = scene3d.update_scene(project, scene3d_id, data)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        semantic_keys = {"title", "description", "keywords"}
        scene_changed = before_scene is None or any(
            key in data and before_scene.get(key) != payload["scene"].get(key)
            for key in semantic_keys
        )
        stale_ids = generation_service.mark_generated_shots_for_asset_keywords_stale(
            project,
            [
                *generation_service.semantic_asset_keywords(before_scene),
                *generation_service.semantic_asset_keywords(payload["scene"]),
            ],
        ) if scene_changed else []
        if stale_ids:
            app_state._autosave(self.app)
        else:
            project_manager.sync_document(project)
        return payload

    def method_delete_scene3d(self, scene3d_id: str) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        try:
            blender_bridge.require_released(self.app, "deleting a Scene 3D")
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        try:
            payload = scene3d.delete_scene(project, scene3d_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        project_manager.sync_document(project)
        return payload

    def method_set_active_scene3d(self, scene3d_id: str) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        try:
            blender_bridge.require_released(self.app, "switching the active Scene 3D")
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        try:
            payload = scene3d.set_active(project, scene3d_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        project_manager.sync_document(project)
        return payload

    def method_import_scene3d_to_scene(self, scene3d_id: str, filename: str, data: list[int] | bytes | bytearray) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        try:
            blender_bridge.require_released(self.app, "replacing a Scene 3D asset")
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        try:
            before_scene = next(
                (item for item in scene3d.list_scenes(project).get("scenes", []) if item.get("id") == scene3d_id),
                None,
            )
            payload = scene3d.import_scene_file(project, scene3d_id, str(filename or "scene.glb"), _normalize_upload_bytes(data))
        except (FileNotFoundError, ValueError) as exc:
            logger.exception("Failed to import Scene3D file: %s", filename)
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        stale_ids = generation_service.mark_generated_shots_for_asset_keywords_stale(
            project,
            [
                *generation_service.semantic_asset_keywords(before_scene),
                *generation_service.semantic_asset_keywords(payload["scene"]),
            ],
        )
        if stale_ids:
            app_state._autosave(self.app)
        else:
            project_manager.sync_document(project)
        return payload

    def method_get_scene3d_file(self, scene3d_id: str | None = None) -> dict[str, str]:
        project = app_state._require_project(self.app)
        try:
            path = scene3d.file_path(project, scene3d_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if path is None:
            raise app_error(AppErrorCode.MEDIA_NOT_FOUND, "No Scene 3D file linked.", status=404)
        return {"path": str(path), "media_type": "model/gltf-binary", "filename": path.name}

    def method_list_scene2d(self) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        return {"scenes": scene2d.list_scenes(project)}

    def method_create_scene2d(self, data: dict[str, Any]) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        try:
            scene, scenes = scene2d.create_scene(
                project,
                title=str(data.get("title") or ""),
                description=str(data.get("description") or ""),
                location=str(data.get("location") or ""),
                time_of_day=str(data.get("time_of_day") or ""),
                environment_prompt=str(data.get("environment_prompt") or ""),
                consistency_anchors=data.get("consistency_anchors") if isinstance(data.get("consistency_anchors"), list) else [],
            )
        except (FileNotFoundError, ValueError) as exc:
            logger.exception("Failed to create Scene 2D")
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        project_manager.sync_document(project)
        app_state._touch_live_bridge(self.app)
        return {"scene": scene, "scenes": scenes}

    def method_update_scene2d(self, scene_id: str, data: dict[str, Any]) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        try:
            before_scene = next(
                (item for item in scene2d.list_scenes(project) if item.get("id") == scene_id),
                None,
            )
            scene, scenes = scene2d.update_scene(project, scene_id, data)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        shots_changed = False
        context_keys = {"title", "description", "location", "time_of_day", "environment_prompt", "consistency_anchors"}
        scene_context_changed = before_scene is None or any(
            key in data and before_scene.get(key) != scene.get(key)
            for key in context_keys
        )
        for shot in project.shots:
            if shot.scene_id != scene["id"]:
                continue
            if "title" in data and shot.scene != scene["title"]:
                shot.scene = scene["title"]
                shots_changed = True
            if scene_context_changed and generation_service.has_generation_activity(shot):
                shot.generation_state["freshness_status"] = "stale"
                shots_changed = True
        if shots_changed:
            app_state._autosave(self.app)
        else:
            project_manager.sync_document(project)
        app_state._touch_live_bridge(self.app)
        return {"scene": scene, "scenes": scenes}

    def method_delete_scene2d(self, scene_id: str) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        try:
            existing_scene = next(
                (item for item in scene2d.list_scenes(project) if item.get("id") == scene_id),
                None,
            )
            scenes = scene2d.delete_scene(project, scene_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        unlinked = False
        for shot in project.shots:
            if shot.scene_id != scene_id:
                continue
            shot.scene_id = ""
            if not shot.scene and existing_scene:
                shot.scene = str(existing_scene.get("title") or "")
            if generation_service.has_generation_activity(shot):
                shot.generation_state["freshness_status"] = "stale"
            unlinked = True
        if unlinked:
            app_state._autosave(self.app)
        else:
            project_manager.sync_document(project)
        app_state._touch_live_bridge(self.app)
        return {"scenes": scenes}

    def method_open_scene2d(self, scene_id: str) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        try:
            scene, opened, relative_path = scene2d.open_scene(project, scene_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            logger.exception("Failed to open Scene 2D %s", scene_id)
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        app_state._touch_live_bridge(self.app)
        return {"path": opened, "relative_path": relative_path, "scene": scene}

    def method_refresh_scene2d_preview(self, scene_id: str) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        try:
            scene, preview_exists, message = scene2d.refresh_preview(project, scene_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        project_manager.sync_document(project)
        return {"scene": scene, "preview_exists": preview_exists, "message": message}

    def method_add_scene2d_to_references(self, scene_id: str) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        try:
            reference, scene = scene2d.add_to_references(project, scene_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        project_manager.sync_document(project)
        app_state._touch_live_bridge(self.app)
        return {"reference": reference, "scene": scene, "project": app_state._project_payload(project, self.app.state.dirty)}

    def method_get_scene2d_preview(self, scene_id: str) -> dict[str, str]:
        project = app_state._require_project(self.app)
        try:
            return scene2d.preview_meta(project, scene_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    def method_list_scene2d_perspectives(self, scene_id: str) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        try:
            scene, perspectives = scene2d.list_perspectives(project, scene_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"scene": scene, "perspectives": perspectives}

    def method_create_scene2d_perspective(self, scene_id: str, data: dict[str, Any]) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        try:
            scene, perspective, scenes = scene2d.create_perspective(
                project,
                scene_id,
                title=str(data.get("title") or ""),
                perspective_type=str(data.get("type") or "psd"),
                linked_scene3d_id=str(data.get("linked_scene3d_id") or ""),
                linked_scene3d_view=data.get("linked_scene3d_view") if isinstance(data.get("linked_scene3d_view"), dict) else None,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        project_manager.sync_document(project)
        return {"scene": scene, "perspective": perspective, "scenes": scenes}

    def method_duplicate_scene2d_perspective(self, scene_id: str, perspective_id: str) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        try:
            scene, perspective, scenes = scene2d.duplicate_perspective(project, scene_id, perspective_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        project_manager.sync_document(project)
        return {"scene": scene, "perspective": perspective, "scenes": scenes}

    def method_reorder_scene2d_perspectives(self, scene_id: str, perspective_ids: list[str]) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        try:
            scene, scenes = scene2d.reorder_perspectives(project, scene_id, perspective_ids)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        project_manager.sync_document(project)
        return {"scene": scene, "scenes": scenes}

    def method_import_scene2d_perspective(
        self,
        scene_id: str,
        filename: str,
        data: list[int] | bytes | bytearray,
        title: str = "",
        linked_scene3d_id: str = "",
    ) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        try:
            scene, perspective, scenes = scene2d.import_perspective(
                project,
                scene_id,
                str(filename or "perspective"),
                _normalize_upload_bytes(data),
                title=str(title or ""),
                linked_scene3d_id=str(linked_scene3d_id or ""),
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        project_manager.sync_document(project)
        return {"scene": scene, "perspective": perspective, "scenes": scenes}

    def method_update_scene2d_perspective(self, scene_id: str, perspective_id: str, data: dict[str, Any]) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        try:
            scene, perspective, scenes = scene2d.update_perspective(project, scene_id, perspective_id, data)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        project_manager.sync_document(project)
        return {"scene": scene, "perspective": perspective, "scenes": scenes}

    def method_delete_scene2d_perspective(self, scene_id: str, perspective_id: str) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        try:
            scene, scenes = scene2d.delete_perspective(project, scene_id, perspective_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        project_manager.sync_document(project)
        return {"scene": scene, "scenes": scenes}

    def method_open_scene2d_perspective(self, scene_id: str, perspective_id: str) -> dict[str, Any]:
        from . import runtime_state
        project = app_state._require_project(self.app)

        try:
            sc, _scenes = scene2d._find_scene(project, scene_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        try:
            perspective = scene2d._find_perspective(sc, perspective_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        if perspective.get("type") != "psd":
            raise HTTPException(status_code=400, detail="Only PSD Perspectives can be opened for editing.")

        source_rel = str(perspective.get("source_file_path") or "")
        expected_source_rel = scene2d._source_rel(scene_id, perspective_id)
        if source_rel != expected_source_rel:
            raise HTTPException(status_code=400, detail="Perspective source path is not canonical.")
        source_path = project.root_path / source_rel if source_rel else None

        if not source_path or not source_path.is_file():
            raise HTTPException(status_code=400, detail=f"Source PSD not found: {source_rel}")
        opened = str(source_path)
        relative_path = source_rel

        # Set active work context before publishing bridge
        runtime_state.set_active_scene2d_context(
            self.app,
            scene_id,
            perspective_id,
            sc,
            perspective,
            source_native_path=str(source_path.resolve()).replace("\\", "/") if source_path else "",
        )

        # If plugin already has this PSD open, request focus; otherwise OS-open.
        # Use the authoritative shared helper so freshness between file and HTTP
        # heartbeats is respected: a newer explicit empty list is not overridden
        # by stale runtime state, and an unknown or cross-project key is ignored.
        work_key = f"scene2d:{scene_id}:{perspective_id}"
        _active_key, open_keys = app_state.plugin_work_key_state(self.app)
        if work_key in open_keys:
            runtime_state.request_work_context_focus(self.app, runtime_state.active_work_context(self.app))
        else:
            try:
                sc, opened, relative_path = scene2d.open_perspective(project, scene_id, perspective_id)
            except (FileNotFoundError, ValueError) as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            perspective = scene2d._find_perspective(sc, perspective_id)
            source_path = project.root_path / relative_path
            runtime_state.set_active_scene2d_context(
                self.app,
                scene_id,
                perspective_id,
                sc,
                perspective,
                source_native_path=str(source_path.resolve()).replace("\\", "/"),
            )

        app_state._touch_live_bridge(self.app)
        return {
            "path": opened,
            "relative_path": relative_path,
            "scene": scene2d._with_legacy_aliases(sc),
            "work_context": runtime_state.active_work_context(self.app),
        }

    def method_plugin_scene2d_export_preview(self, scene_id: str, perspective_id: str) -> dict[str, Any]:
        return self._plugin_service().scene2d_export_preview(scene_id, perspective_id)

    def method_plugin_scene2d_psd_saved(self, scene_id: str, perspective_id: str) -> dict[str, Any]:
        return self._plugin_service().scene2d_psd_saved(scene_id, perspective_id)

    def method_plugin_scene2d_next_perspective(self, scene_id: str, perspective_id: str) -> dict[str, Any]:
        return self._plugin_service().scene2d_next_perspective(scene_id, perspective_id)

    def method_refresh_scene2d_perspective_preview(self, scene_id: str, perspective_id: str) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        try:
            scene, perspective, _scenes = scene2d.refresh_perspective_preview(project, scene_id, perspective_id)
            preview_exists = bool((project.root_path / perspective["preview_image_path"]).is_file())
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        project_manager.sync_document(project)
        return {
            "scene": scene,
            "perspective": perspective,
            "preview_exists": preview_exists,
            "message": "Scene 2D preview refreshed." if preview_exists else "No Scene 2D preview exists yet.",
        }

    def method_set_primary_scene2d_perspective(self, scene_id: str, perspective_id: str) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        try:
            scene, scenes = scene2d.set_primary_perspective(project, scene_id, perspective_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        project_manager.sync_document(project)
        return {"scene": scene, "scenes": scenes}

    def method_move_scene2d_perspective(self, scene_id: str, perspective_id: str, target_scene_id: str) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        try:
            source_scene, target_scene, perspective, scenes = scene2d.move_perspective(
                project,
                scene_id,
                perspective_id,
                target_scene_id,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        project_manager.sync_document(project)
        return {
            "source_scene": source_scene,
            "target_scene": target_scene,
            "scene": target_scene,
            "perspective": perspective,
            "scenes": scenes,
        }

    def method_add_scene2d_perspective_to_references(self, scene_id: str, perspective_id: str) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        try:
            reference, scene = scene2d.add_perspective_to_references(project, scene_id, perspective_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        project_manager.sync_document(project)
        return {"reference": reference, "scene": scene, "project": app_state._project_payload(project, self.app.state.dirty)}

    def method_get_scene2d_perspective_preview(self, scene_id: str, perspective_id: str) -> dict[str, str]:
        project = app_state._require_project(self.app)
        try:
            return scene2d.perspective_preview_meta(project, scene_id, perspective_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    def method_get_canvas_color(self) -> dict[str, str]:
        project = app_state._require_project(self.app)
        return {"color": project_manager.get_canvas_color(project)}

    def method_set_canvas_color(self, color: str) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        try:
            normalized = project_manager.persist_canvas_color(project, color)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        app_state._touch_live_bridge(self.app)
        return {"color": normalized, **app_state._project_payload(project, self.app.state.dirty)}

    def method_remove_shot_reference_image(self, shot_id: str, path: str) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        shot = app_state._find_shot(project, shot_id)
        try:
            project_manager.remove_reference_image(project, shot, path)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        app_state._autosave(self.app)
        return app_state._project_payload(project, self.app.state.dirty)

    def method_set_shot_reference_image_paths(self, shot_id: str, paths: list[str]) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        shot = app_state._find_shot(project, shot_id)
        project_manager.set_reference_image_paths(
            project,
            shot,
            paths if isinstance(paths, list) else [],
        )
        app_state._autosave(self.app)
        return app_state._project_payload(project, self.app.state.dirty)

    def method_create_shot_canvas(
        self,
        shot_id: str,
        width: int | None = None,
        height: int | None = None,
        background_color: str | None = None,
    ) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        shot = app_state._find_shot(project, shot_id)
        default_w, default_h = project_manager.get_canvas_size(project)
        canvas_width, canvas_height = project_manager.normalize_canvas_size(
            width if width is not None else default_w,
            height if height is not None else default_h,
        )
        try:
            with project_transaction.mutate_project(project):
                project_manager.create_canvas_for_shot(
                    project,
                    shot,
                    canvas_width,
                    canvas_height,
                    background_color=background_color,
                )
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        app_state._autosave(self.app)
        return app_state._project_payload(project, self.app.state.dirty)

    def method_save_shot_drawing(self, shot_id: str, image_data: str) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        shot = app_state._find_shot(project, shot_id)
        try:
            with project_transaction.mutate_project(project):
                project_manager.save_drawing_for_shot(project, shot, str(image_data or ""))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        app_state._autosave(self.app)
        return app_state._project_payload(project, self.app.state.dirty)

    def method_sync_all_shots(self, force: bool = False) -> dict[str, Any]:
        project = app_state._refresh_project_from_disk(self.app)
        try:
            results = sync_project(project, force=bool(force))
        except (FileNotFoundError, ValueError) as exc:
            logger.exception("Failed to sync all shots")
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if results:
            app_state._autosave(self.app)
        return {"results": results, **app_state._project_payload(project, self.app.state.dirty)}

    def method_upload_project_reference(self, filename: str, data: list[int] | bytes | bytearray) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        try:
            with project_transaction.mutate_project(project):
                entry = project_manager.import_project_reference_stream(
                    project,
                    _upload_stream(data),
                    str(filename or "reference"),
                )
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        app_state._autosave(self.app)
        return {"reference": entry, **app_state._project_payload(project, self.app.state.dirty)}

    def method_upload_reference_video(self, filename: str, data: list[int] | bytes | bytearray) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        try:
            with project_transaction.mutate_project(project):
                project_manager.import_reference_video_stream(
                    project,
                    _upload_stream(data),
                    str(filename or "reference.mp4"),
                )
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        app_state._autosave(self.app)
        return app_state._project_payload(project, self.app.state.dirty)

    def method_import_scene3d(self, filename: str, data: list[int] | bytes | bytearray) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        try:
            blender_bridge.require_released(self.app, "replacing the active Scene 3D asset")
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        try:
            scene_payload = scene3d.import_active_scene_file(project, str(filename or "scene.glb"), _normalize_upload_bytes(data))
        except (FileNotFoundError, ValueError) as exc:
            logger.exception("Failed to import Scene3D file: %s", filename)
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        app_state._touch_live_bridge(self.app)
        payload = app_state._project_payload(project, self.app.state.dirty)
        return {"scene3d": project.settings.get("scene3d") or {}, "scenes3d": scene_payload, **payload}

    def method_import_shot_image(
        self,
        shot_id: str,
        filename: str,
        data: list[int] | bytes | bytearray,
    ) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        shot = app_state._find_shot(project, shot_id)
        suffix = Path(str(filename or "")).suffix
        try:
            project_manager.import_image_stream_for_shot(project, shot, _upload_stream(data), suffix)
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        app_state._autosave(self.app)
        return app_state._project_payload(project, self.app.state.dirty)

    def method_add_shot_reference_image(
        self,
        shot_id: str,
        filename: str,
        data: list[int] | bytes | bytearray,
    ) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        shot = app_state._find_shot(project, shot_id)
        suffix = Path(str(filename or "")).suffix
        try:
            project_manager.add_reference_image_stream(project, shot, _upload_stream(data), suffix)
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        app_state._autosave(self.app)
        return app_state._project_payload(project, self.app.state.dirty)

    def method_import_shot_source(
        self,
        shot_id: str,
        filename: str,
        data: list[int] | bytes | bytearray,
    ) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        shot = app_state._find_shot(project, shot_id)
        try:
            project_manager.import_source_file_stream(
                project,
                shot,
                _upload_stream(data),
                str(filename or f"{shot_id}.psd"),
            )
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        app_state._autosave(self.app)
        return app_state._project_payload(project, self.app.state.dirty)

    def _browse(self, kind: str, picker, validator) -> dict[str, Any]:
        initial_dir = app_state._dialog_initial_dir(self.app, kind)
        try:
            selected = picker(initial_dir)
        except Exception as exc:
            logger.exception("Could not open %s picker", kind)
            raise HTTPException(status_code=500, detail=f"Could not open picker: {exc}") from exc
        if not selected:
            return {"path": "", "cancelled": True}
        try:
            validated = validator(selected)
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"path": validated, "cancelled": False}


# ── Serialized project mutation ──────────────────────────────────────────────
# Every method below performs a read-modify-write-save transaction on the single
# shared app.state.project. FastAPI runs these sync endpoints on a threadpool and
# the bridge/plugin is a second concurrent client, so two mutations (or a mutation
# and a save/reload) can otherwise interleave and corrupt project.shots or persist a
# torn snapshot. Holding project_manager.PROJECT_LOCK for the whole method makes each
# transaction atomic. The lock is reentrant, so nested save_project /
# _refresh_project_from_disk calls (which also take it) compose without deadlock.


def _serialized_mutation(method):
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        with project_manager.PROJECT_LOCK:
            return method(self, *args, **kwargs)

    return wrapper


# Methods whose whole body must run under PROJECT_LOCK. Read-only endpoints
# (get_project, list_*, get_*_preview, exports) are intentionally excluded so
# concurrent reads and media serving are never blocked by a mutation.
_MUTATING_METHODS = (
    # Project lifecycle
    "method_save_project", "method_save_project_as",
    # Shot CRUD / ordering
    "method_add_shot", "method_duplicate_shot", "method_update_shot", "method_update_shots_batch",
    "method_delete_shot", "method_delete_shots_batch", "method_restore_shots_batch",
    "method_restore_shot", "method_reorder_shots", "method_move_shot_up", "method_move_shot_down",
    "method_create_generation_request", "method_create_queue_batch_requests", "method_create_codex_batch_requests", "method_delete_generation_request", "method_pull_generation_results", "method_reconcile_generation_results",
    "method_accept_generation_candidate", "method_remove_fixed_layer",
    # Shot media / sources
    "method_import_image_path", "method_import_shot_image", "method_add_shot_reference_image",
    "method_import_shot_source", "method_remove_shot_image", "method_relink_preview",
    "method_recover_shot_source", "method_set_shot_reference_image_paths",
    "method_remove_shot_reference_image", "method_create_shot_canvas", "method_save_shot_drawing",
    "method_sync_shot", "method_sync_all_shots", "method_save_annotations",
    "method_add_comment", "method_resolve_comment",
    # Settings / canvas / references
    "method_update_settings", "method_set_canvas_color", "method_delete_project_reference",
    "method_upload_project_reference", "method_upload_reference_video",
    # Reference-segment bakes (destructive; snapshot + write board images)
    "method_apply_ref_segment", "method_apply_ref_segment_image", "method_apply_ref_segment_3d",
    "method_apply_ref_segment_model_captures", "method_restore_ref_apply",
    "method_delete_ref_segment", "method_snapshot_ref_boards",
    # Scene 3D
    "method_import_scene3d", "method_import_scene3d_to_scene", "method_create_scene3d",
    "method_update_scene3d", "method_delete_scene3d", "method_set_active_scene3d",
    # Scene 2D
    "method_create_scene2d", "method_update_scene2d", "method_delete_scene2d",
    "method_open_scene2d", "method_add_scene2d_to_references",
    "method_create_scene2d_perspective", "method_update_scene2d_perspective",
    "method_delete_scene2d_perspective", "method_reorder_scene2d_perspectives",
    "method_import_scene2d_perspective", "method_duplicate_scene2d_perspective",
    "method_set_primary_scene2d_perspective", "method_move_scene2d_perspective",
    "method_open_scene2d_perspective", "method_add_scene2d_perspective_to_references",
    # Plugin-driven state updates
    "method_plugin_psd_saved", "method_plugin_next_shot", "method_plugin_scene2d_psd_saved",
    "method_plugin_scene2d_next_perspective",
)

for _name in _MUTATING_METHODS:
    _method = getattr(StoryboardBackendService, _name, None)
    if _method is not None:
        setattr(StoryboardBackendService, _name, _serialized_mutation(_method))
