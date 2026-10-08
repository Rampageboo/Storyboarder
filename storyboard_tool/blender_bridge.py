"""External-Blender session for the active Storyboarder Scene 3D.

Model
-----
A session pairs one running (or recently running) Blender with one Scene 3D:

* ``session_path`` is the file Blender edits. For Layout 2 it is a hidden sibling
  copy of the canonical asset; for Layout 1 it is the canonical file itself.
* ``canonical_path`` is the project's own ``.blend``.

Blender may save whenever the user wants. A background ``tick`` (one per second,
independent of request handlers and of the project lock except for the short copy)
notices new saves and brings them into the project:

* Layout 2 / relocated sessions: copy ``session_path`` -> ``canonical_path``, but
  only when the canonical file still matches the last state this session wrote or
  saw (``baseline``). Someone else changing the canonical file is a conflict: the
  save is kept in the session file and reported, never overwritten.
* Layout 1 in place: the save already is the canonical file; mark the project
  dirty so the next document save includes it.

The session record lives in the bridge context file, so a restarted Storyboarder
adopts a still-open Blender (or recovers saves made while it was closed) by
matching the project identity, not a per-process token.

``status`` is read-only and cheap; it returns the snapshot the tick maintains.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from . import live_bridge, project_document, project_manager, runtime_state, scene3d
from .file_transactions import atomic_copy_file, rollback_paths
from .models import Project
from .project_layout import LAYOUT_2

logger = logging.getLogger(__name__)

BRIDGE_FILENAME = "storyboard_blender_bridge.json"
HEARTBEAT_FILENAME = "storyboard_blender_heartbeat.json"
MANIFEST_FILENAME = "storyboarder_manifest.json"
HEARTBEAT_MAX_AGE_SECONDS = 7.0
# A cold Blender start can take this long before its first heartbeat.
LAUNCH_GRACE_SECONDS = 90.0
CONTEXT_VERSION = 3
SESSION_MARK = ".storyboarder-session-"

_LOCK = threading.RLock()


# ── files ────────────────────────────────────────────────────────────────────

def bridge_file_path() -> Path:
    return live_bridge.global_bridge_dir() / BRIDGE_FILENAME


def heartbeat_file_path() -> Path:
    return live_bridge.global_bridge_dir() / HEARTBEAT_FILENAME


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _resolve(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def _mtime_ns(path: str | Path) -> int:
    try:
        return Path(path).stat().st_mtime_ns
    except (OSError, ValueError):
        return 0


def manifest_file_path(project: Project, scene_id: str) -> Path:
    return scene3d.preview_file_path(project, scene_id).with_name(MANIFEST_FILENAME)


def project_identity(project: Project) -> str:
    """Stable across restarts: the document a user opens, else its folder."""
    document = getattr(project, "document_path", None)
    return str(_resolve(document if document else project.project_root))


# ── in-memory session ────────────────────────────────────────────────────────

_EMPTY: dict[str, Any] = {
    "session_id": "",
    "identity": "",
    "scene_id": "",
    "session_path": "",
    "canonical_path": "",
    "baseline_mtime_ns": 0,
    "synced_session_mtime_ns": 0,
    "started_at": 0.0,
    "heartbeat_seen": False,
    "sync_error": "",
    "conflict": False,
    "last_synced_at": 0.0,
}


def _session(app: FastAPI) -> dict[str, Any]:
    session = getattr(app.state, "blender_session", None)
    if not isinstance(session, dict):
        session = dict(_EMPTY)
        app.state.blender_session = session
    return session


def _set_session(app: FastAPI, **values: Any) -> dict[str, Any]:
    session = dict(_EMPTY)
    session.update(values)
    app.state.blender_session = session
    # Legacy attribute names other modules and tests read.
    app.state.external_blender_session_id = session["session_id"]
    app.state.external_blender_blend_path = session["session_path"]
    app.state.external_blender_target_path = session["canonical_path"]
    app.state.external_blender_scene3d_id = session["scene_id"]
    return session


def _process_running(app: FastAPI) -> bool:
    process = getattr(app.state, "external_blender_process", None)
    if process is None:
        return False
    try:
        return process.poll() is None
    except (AttributeError, OSError):
        return False


def attach_process(app: FastAPI, process: subprocess.Popen[Any]) -> None:
    app.state.external_blender_process = process


# ── context publication ──────────────────────────────────────────────────────

def _shot_links(project: Project) -> list[dict[str, Any]]:
    links: list[dict[str, Any]] = []
    for index, shot in enumerate(list(project.shots)):
        camera_data = shot.camera_data or {}
        links.append(
            {
                "shot_id": shot.shot_id,
                "title": str(shot.title or "").strip(),
                "index": index + 1,
                "camera_name": str(camera_data.get("scene3d_camera") or "").strip(),
                "scene3d_time": camera_data.get("scene3d_time"),
            }
        )
    return links


def _portable_references(project: Project, blend: Path) -> list[dict[str, str]]:
    from .external_tools import blender_portable_reference

    references: list[dict[str, str]] = []
    for link in project.settings.get("reference_links") or []:
        if not isinstance(link, dict):
            continue
        relative = str(link.get("path") or "")
        if Path(relative).suffix.lower() not in {".blend", ".glb", ".gltf"}:
            continue
        try:
            asset = scene3d._safe_rel_path(project, relative)
            references.append({"id": str(link.get("id") or ""), "path": blender_portable_reference(project, blend, asset)})
        except (OSError, ValueError):
            continue
    return references


def publish_context(app: FastAPI, project: Project) -> dict[str, Any]:
    """Write the session record Blender reads. No-op without a session."""
    with _LOCK:
        session = dict(_session(app))
    if not session["session_id"]:
        return {}
    scene_id = session["scene_id"]
    title = scene_id
    try:
        for item in scene3d.list_scenes(project, read_only=True).get("scenes", []):
            if item.get("id") == scene_id:
                title = str(item.get("title") or scene_id)
    except (OSError, ValueError):
        pass
    session_path = Path(session["session_path"])
    try:
        portable = _portable_references(project, session_path) if session_path.parent.exists() else []
    except Exception:  # references are a convenience for Blender, never fatal
        portable = []
    now = time.time()
    payload = {
        "version": CONTEXT_VERSION,
        "session_id": session["session_id"],
        "write_enabled": True,
        "project_identity": session["identity"],
        "project_name": project.name,
        "project_root": str(project.project_root.resolve()),
        "project_json_path": str(project.json_path.resolve()),
        "layout": project.layout,
        "scene3d_id": scene_id,
        "scene3d_title": title,
        "blend_path": session["session_path"],
        "canonical_blend_path": session["canonical_path"],
        "baseline_mtime_ns": session["baseline_mtime_ns"],
        "synced_session_mtime_ns": session["synced_session_mtime_ns"],
        "preview_path": str(scene3d.preview_file_path(project, scene_id).resolve()),
        "manifest_path": str(manifest_file_path(project, scene_id).resolve()),
        "selected_shot_id": runtime_state.live_selected_shot_id(app),
        "shots": _shot_links(project),
        "portable_references": portable,
        # Informational only: Blender never refuses a save because of it.
        "lease_expires_at": now + HEARTBEAT_MAX_AGE_SECONDS,
        "updated_at": now,
    }
    _write_json(bridge_file_path(), payload)
    return payload


def _revoke_context(session_id: str) -> None:
    try:
        context = _read_json(bridge_file_path())
        if session_id and str(context.get("session_id") or "") == session_id:
            context.update({"session_id": "", "write_enabled": False, "lease_expires_at": 0.0, "updated_at": time.time()})
            _write_json(bridge_file_path(), context)
    except OSError:
        pass


# ── session lifecycle ────────────────────────────────────────────────────────

def begin_session(app: FastAPI, project: Project, scene: dict[str, Any], blend_path: Path) -> dict[str, Any]:
    # Keep the token safe as a standalone argparse value: token_urlsafe() may
    # begin with "-", which Blender's add-on parser would read as an option.
    session_id = f"sb_{secrets.token_urlsafe(24)}"
    canonical = blend_path.resolve()
    scene_id = str(scene.get("id") or "")
    session_path = canonical
    if project.layout == LAYOUT_2:
        stored = str(scene.get("blend_file_path") or "")
        if not stored:
            raise ValueError("Layout 2 Scene 3D metadata has no Blender path.")
        stored_path = scene3d._safe_rel_path(project, stored).resolve()
        if stored_path.suffix.lower() != ".blend":
            raise ValueError("Layout 2 Scene 3D Blender path must be a .blend file.")
        if not stored_path.is_file():
            raise FileNotFoundError(f"Layout 2 Blender scene not found: {stored}.")
        if canonical != stored_path:
            raise ValueError("External Blender must use the persisted Scene 3D path.")
        session_path = canonical.with_name(f".{canonical.stem}{SESSION_MARK}{secrets.token_hex(12)}.blend")
        atomic_copy_file(canonical, session_path)
    with _LOCK:
        _set_session(
            app,
            session_id=session_id,
            identity=project_identity(project),
            scene_id=scene_id,
            session_path=str(session_path),
            canonical_path=str(canonical),
            baseline_mtime_ns=_mtime_ns(canonical),
            synced_session_mtime_ns=_mtime_ns(session_path),
            started_at=time.time(),
        )
        app.state.external_blender_process = None
    publish_context(app, project)
    return {
        "session_id": session_id,
        "bridge_path": str(bridge_file_path()),
        "heartbeat_path": str(heartbeat_file_path()),
        "launch_path": str(session_path),
        "canonical_path": str(canonical),
    }


def cancel_session(app: FastAPI) -> None:
    """Drop the session without syncing (launch failure or explicit abandon)."""
    with _LOCK:
        session = dict(_session(app))
        running = _process_running(app)
        _revoke_context(session["session_id"])
        _remove_session_copy(session, running=running)
        _set_session(app)
        app.state.external_blender_process = None


def _remove_session_copy(session: dict[str, Any], *, running: bool) -> None:
    path = Path(session.get("session_path") or "")
    if running or not session.get("session_path") or path == Path(session.get("canonical_path") or ""):
        return
    if SESSION_MARK in path.name and path.suffix.lower() == ".blend":
        try:
            path.unlink(missing_ok=True)
        except OSError:
            logger.warning("Could not remove Blender session copy %s", path)


def _heartbeat(session: dict[str, Any]) -> tuple[dict[str, Any], float | None]:
    path = heartbeat_file_path()
    heartbeat = _read_json(path)
    try:
        age = max(0.0, time.time() - path.stat().st_mtime)
    except OSError:
        return {}, None
    if not session["session_id"] or str(heartbeat.get("session_id") or "") != session["session_id"]:
        return {}, age
    return heartbeat, age


def _launching(session: dict[str, Any]) -> bool:
    """Blender was started by this session and has not reported in yet."""
    return (
        bool(session["session_id"])
        and not session["heartbeat_seen"]
        and time.time() - float(session["started_at"] or 0.0) < LAUNCH_GRACE_SECONDS
    )


def _adopt(app: FastAPI, project: Project) -> bool:
    """Take over a session recorded for this project by an earlier Storyboarder run."""
    context = _read_json(bridge_file_path())
    session_id = str(context.get("session_id") or "")
    if not session_id or context.get("write_enabled") is not True:
        return False
    if str(context.get("project_identity") or "") != project_identity(project):
        return False
    session_path = Path(str(context.get("blend_path") or ""))
    scene_id = str(context.get("scene3d_id") or "")
    if session_path.suffix.lower() != ".blend" or not session_path.is_file() or not scene_id:
        return False
    try:
        scene = next(item for item in scene3d.list_scenes(project, read_only=True)["scenes"] if item["id"] == scene_id)
        stored = str(scene.get("blend_file_path") or "")
        canonical = scene3d._safe_rel_path(project, stored).resolve() if stored else None
    except (StopIteration, OSError, ValueError):
        return False
    if canonical is None:
        return False
    previous_canonical = Path(str(context.get("canonical_blend_path") or ""))
    baseline = int(context.get("baseline_mtime_ns") or 0)
    if previous_canonical.resolve() != canonical:
        # Document projects expand into a fresh working root on every open. The
        # freshly extracted canonical file is the last state Storyboarder saved;
        # it is the baseline the earlier session's saves build on.
        baseline = _mtime_ns(canonical)
    _set_session(
        app,
        session_id=session_id,
        identity=project_identity(project),
        scene_id=scene_id,
        session_path=str(session_path.resolve()),
        canonical_path=str(canonical),
        baseline_mtime_ns=baseline,
        synced_session_mtime_ns=int(context.get("synced_session_mtime_ns") or 0),
        started_at=float(context.get("updated_at") or time.time()),
        heartbeat_seen=True,
    )
    app.state.external_blender_process = None
    logger.info("Adopted external Blender session for %s", scene_id)
    return True


def _sync(app: FastAPI, project: Project, heartbeat: dict[str, Any], *, blender_alive: bool) -> bool:
    """Bring one finished Blender save into the project. Returns True if synced."""
    session = _session(app)
    session_path = Path(session["session_path"])
    canonical = Path(session["canonical_path"])
    observed = _mtime_ns(session_path)
    if not observed or observed == session["synced_session_mtime_ns"]:
        return False
    if blender_alive and (heartbeat.get("dirty") is True or int(heartbeat.get("saved_mtime_ns") or 0) != observed):
        return False  # Blender is still writing, or the save is not announced yet
    if session_path.resolve() == canonical.resolve():
        # Layout 1 in place: the save is already the project's file.
        session["synced_session_mtime_ns"] = observed
        session["baseline_mtime_ns"] = observed
        session["last_synced_at"] = time.time()
        app.state.dirty = True
        return True
    if _mtime_ns(canonical) != session["baseline_mtime_ns"]:
        session["conflict"] = True
        session["sync_error"] = (
            "The project's .blend changed outside this Blender session. "
            "Your Blender save is kept in the session file and was not copied over it."
        )
        return False
    if not project_manager.PROJECT_LOCK.acquire(timeout=0.25):
        return False  # a long project operation is running; retry next tick
    try:
        if project.layout == LAYOUT_2:
            from . import app_state

            revision_before = int(project.storage_revision)
            dirty_before = bool(getattr(app.state, "dirty", False))
            try:
                with project_document.layout2_mutation_transaction(project.project_root):
                    project_document.enlist_layout2_mutation_paths(project.project_root, (canonical,))
                    with rollback_paths((canonical,)):
                        atomic_copy_file(session_path, canonical)
                        app_state.persist_project_mutation(app)
            except BaseException:
                project.storage_revision = revision_before
                app.state.dirty = dirty_before
                raise
        else:
            atomic_copy_file(session_path, canonical)
            app.state.dirty = True
    finally:
        project_manager.PROJECT_LOCK.release()
    session["synced_session_mtime_ns"] = observed
    session["baseline_mtime_ns"] = _mtime_ns(canonical)
    session["last_synced_at"] = time.time()
    session["conflict"] = False
    session["sync_error"] = ""
    return True


def tick(app: FastAPI) -> dict[str, Any]:
    """One sync step: adopt, renew context, ingest saves, close finished sessions."""
    with _LOCK:
        project = getattr(app.state, "project", None)
        session = _session(app)
        if project is None:
            return snapshot(app)
        if session["session_id"] and session["identity"] != project_identity(project):
            return snapshot(app)  # transitions refuse while a session is open
        if not session["session_id"] and not _adopt(app, project):
            return snapshot(app)
        session = _session(app)
        heartbeat, age = _heartbeat(session)
        fresh = bool(heartbeat) and age is not None and age <= HEARTBEAT_MAX_AGE_SECONDS
        if fresh:
            session["heartbeat_seen"] = True
        alive = fresh or _process_running(app) or _launching(session)
        try:
            _sync(app, project, heartbeat, blender_alive=alive)
        except Exception as exc:  # keep the session; report and retry next tick
            session["sync_error"] = f"Could not copy the Blender save into the project: {exc}"
            logger.exception("Blender session sync failed")
        if alive:
            try:
                publish_context(app, project)
            except (OSError, ValueError):
                logger.debug("Could not refresh Blender context", exc_info=True)
        else:
            settled = _mtime_ns(session["session_path"]) in (0, session["synced_session_mtime_ns"])
            if settled:
                _revoke_context(session["session_id"])
                _remove_session_copy(session, running=False)
                _set_session(app)
                app.state.external_blender_process = None
        return snapshot(app)


def sync_now(app: FastAPI) -> dict[str, Any]:
    """Run a tick synchronously (before saving or closing the project)."""
    return tick(app)


# ── status ───────────────────────────────────────────────────────────────────

def snapshot(app: FastAPI) -> dict[str, Any]:
    with _LOCK:
        session = dict(_session(app))
        project = getattr(app.state, "project", None)
    heartbeat, age = _heartbeat(session)
    fresh = bool(heartbeat) and age is not None and age <= HEARTBEAT_MAX_AGE_SECONDS
    running = _process_running(app) or _launching(session)
    active = bool(session["session_id"])
    connected = active and fresh
    owned = active and (fresh or running or _mtime_ns(session["session_path"]) != session["synced_session_mtime_ns"])
    scene_id = session["scene_id"]
    if not scene_id and project is not None:
        scene_id = str(project.settings.get("active_scene3d_id") or "")
    preview_path: Path | None = None
    manifest_path: Path | None = None
    if project is not None and scene_id:
        try:
            preview_path = scene3d.preview_file_path(project, scene_id)
            manifest_path = manifest_file_path(project, scene_id)
        except ValueError:
            preview_path = manifest_path = None
    if not active:
        state = "offline"
    elif session["conflict"]:
        state = "conflict"
    elif connected:
        state = "connected"
    elif running:
        state = "launching"
    else:
        state = "closed"
    return {
        "state": state,
        "owner": "external" if owned else "none",
        "external_blender_owned": owned,
        "external_blender_connected": connected,
        "external_blender_pending": owned and not connected,
        "external_blender_process_running": running,
        "external_blender_age_seconds": age if active else None,
        "external_blender_blend_path": session["session_path"],
        "external_blender_canonical_path": session["canonical_path"],
        "external_blender_scene3d_id": scene_id,
        "external_blender_camera": str(heartbeat.get("active_camera") or ""),
        "external_blender_dirty": bool(heartbeat.get("dirty", False)),
        "sync_error": session["sync_error"],
        "last_synced_at": session["last_synced_at"],
        "preview_path": str(preview_path or ""),
        "preview_revision": _mtime_ns(preview_path) if preview_path else 0,
        "manifest_revision": _mtime_ns(manifest_path) if manifest_path else 0,
        "preview_exporting": bool(heartbeat.get("preview_exporting", False)) if connected else False,
        "preview_error": str(heartbeat.get("preview_error") or "") if connected else "",
    }


def status(app: FastAPI, *, refresh_context: bool = True) -> dict[str, Any]:
    """Read-only session status. ``refresh_context`` is accepted for old callers."""
    del refresh_context
    return snapshot(app)


def owns_scene(app: FastAPI) -> bool:
    return bool(snapshot(app)["external_blender_owned"])


def require_released(app: FastAPI, action: str) -> None:
    if owns_scene(app):
        raise ValueError(f"Save and close the Blender scene opened from Storyboarder before {action}.")


def read_manifest(project: Project, scene_id: str) -> dict[str, Any]:
    """Scene facts Blender exported with the preview (cameras, frame range)."""
    manifest = _read_json(manifest_file_path(project, scene_id))
    cameras = manifest.get("cameras") if isinstance(manifest.get("cameras"), list) else []
    return {
        "scene3d_id": scene_id,
        "revision": _mtime_ns(manifest_file_path(project, scene_id)),
        "fps": manifest.get("fps"),
        "frame_start": manifest.get("frame_start"),
        "frame_end": manifest.get("frame_end"),
        "active_camera": str(manifest.get("active_camera") or ""),
        "cameras": [item for item in cameras if isinstance(item, dict)][:200],
        "object_count": int(manifest.get("object_count") or 0),
        "exported_at": manifest.get("exported_at"),
    }


def resolve_conflict(app: FastAPI, action: str) -> dict[str, Any]:
    """Settle a conflict: ``use_blender`` overwrites the project's .blend with the
    session save; ``discard`` drops the session and its unsynced save."""
    with _LOCK:
        session = _session(app)
        if not session["session_id"]:
            raise ValueError("There is no Blender session to resolve.")
        if action == "use_blender":
            session["baseline_mtime_ns"] = _mtime_ns(session["canonical_path"])
            session["conflict"] = False
            session["sync_error"] = ""
        elif action == "discard":
            cancel_session(app)
            return snapshot(app)
        else:
            raise ValueError("Unknown resolution; use 'use_blender' or 'discard'.")
    return tick(app)
