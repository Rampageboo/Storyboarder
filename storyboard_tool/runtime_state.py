from __future__ import annotations

import time
from typing import Any

from fastapi import FastAPI


def init_bridge_state(app: FastAPI, bridge_port: int) -> None:
    # Legacy shot-specific fields (kept for backward compat)
    app.state.live_selected_shot_id = ""
    app.state.bridge_port = bridge_port
    app.state.plugin_last_seen = 0.0
    app.state.plugin_open_shot_ids = []
    app.state.plugin_selected_shot_id = ""
    app.state.plugin_last_exported_preview = {}
    app.state.plugin_project_revision = 0
    app.state.live_focus_shot_id = ""
    app.state.live_focus_token = 0

    # Generic work-context fields
    app.state.active_work_context = {}
    app.state.focus_work_context = {}
    app.state.focus_token = 0
    app.state.plugin_active_work_key = ""
    app.state.plugin_open_work_keys = []
    app.state.plugin_change = {}

    # Per-project preview-analysis jobs: norm_root → job dict
    app.state.preview_analysis_jobs = {}


def live_selected_shot_id(app: FastAPI) -> str:
    return str(getattr(app.state, "live_selected_shot_id", "") or "")


def set_live_selected_shot_id(app: FastAPI, shot_id: str) -> None:
    app.state.live_selected_shot_id = str(shot_id or "")


def live_focus_shot_id(app: FastAPI) -> str:
    return str(getattr(app.state, "live_focus_shot_id", "") or "")


def live_focus_token(app: FastAPI) -> int:
    return int(getattr(app.state, "live_focus_token", 0) or 0)


def request_live_focus(app: FastAPI, shot_id: str) -> None:
    """Legacy shot focus — also updates the generic focus_token."""
    shot_id = str(shot_id or "")
    app.state.live_focus_shot_id = shot_id
    new_token = live_focus_token(app) + 1
    app.state.live_focus_token = new_token
    app.state.focus_token = new_token
    ctx = active_work_context(app)
    source_path = ctx.get("source_file_path", "") if ctx.get("kind") == "shot" and ctx.get("shot_id") == shot_id else ""
    app.state.focus_work_context = {
        "kind": "shot",
        "key": f"shot:{shot_id}",
        "shot_id": shot_id,
        "source_file_path": source_path,
    }


def plugin_last_seen(app: FastAPI) -> float:
    return float(getattr(app.state, "plugin_last_seen", 0.0) or 0.0)


def plugin_selected_shot_id(app: FastAPI) -> str:
    return str(getattr(app.state, "plugin_selected_shot_id", "") or "")


def plugin_open_shot_ids(app: FastAPI) -> list[str]:
    raw = getattr(app.state, "plugin_open_shot_ids", None)
    if not isinstance(raw, list):
        return []
    return [str(item) for item in raw if item]


def set_plugin_and_live_selected_shot_id(app: FastAPI, shot_id: str) -> None:
    selected = str(shot_id or "")
    app.state.plugin_selected_shot_id = selected
    app.state.live_selected_shot_id = selected


def record_plugin_heartbeat(app: FastAPI, payload: dict[str, Any] | None = None) -> None:
    data = payload if isinstance(payload, dict) else {}
    app.state.plugin_last_seen = time.time()

    # Legacy shot fields
    selected = str(data.get("selected_shot_id") or "").strip()
    if selected:
        set_plugin_and_live_selected_shot_id(app, selected)
    open_ids = data.get("open_shot_ids")
    if isinstance(open_ids, list):
        app.state.plugin_open_shot_ids = [str(item) for item in open_ids if item]

    # Generic work-context fields (Part 5)
    active_key = str(data.get("active_work_key") or "").strip()
    if active_key and (active_key.startswith("shot:") or active_key.count(":") == 2):
        app.state.plugin_active_work_key = active_key

    open_keys = data.get("open_work_keys")
    if isinstance(open_keys, list):
        app.state.plugin_open_work_keys = [
            str(k) for k in open_keys
            if str(k or "").startswith("shot:") or str(k or "").count(":") == 2
        ]


def plugin_last_exported_preview(app: FastAPI) -> dict[str, float]:
    exported = getattr(app.state, "plugin_last_exported_preview", None)
    if not isinstance(exported, dict):
        exported = {}
        app.state.plugin_last_exported_preview = exported
    return exported


def mark_plugin_preview_exported(app: FastAPI, shot_id: str) -> None:
    plugin_last_exported_preview(app)[str(shot_id)] = time.time()


def plugin_project_revision(app: FastAPI) -> int:
    return int(getattr(app.state, "plugin_project_revision", 0) or 0)


def mark_plugin_project_changed(app: FastAPI) -> None:
    app.state.plugin_project_revision = plugin_project_revision(app) + 1


# ── Generic work-context accessors ────────────────────────────────────────


def active_work_context(app: FastAPI) -> dict[str, Any]:
    ctx = getattr(app.state, "active_work_context", None)
    return dict(ctx) if isinstance(ctx, dict) else {}


def focus_work_context(app: FastAPI) -> dict[str, Any]:
    ctx = getattr(app.state, "focus_work_context", None)
    return dict(ctx) if isinstance(ctx, dict) else {}


def focus_token(app: FastAPI) -> int:
    return int(getattr(app.state, "focus_token", 0) or 0)


def plugin_active_work_key(app: FastAPI) -> str:
    return str(getattr(app.state, "plugin_active_work_key", "") or "")


def plugin_open_work_keys(app: FastAPI) -> list[str]:
    raw = getattr(app.state, "plugin_open_work_keys", None)
    if not isinstance(raw, list):
        return []
    return [str(item) for item in raw if item]


def plugin_change_payload(app: FastAPI) -> dict[str, Any]:
    payload = getattr(app.state, "plugin_change", None)
    return dict(payload) if isinstance(payload, dict) else {}


def set_active_shot_context(
    app: FastAPI,
    shot_id: str,
    source_file_path: str = "",
    preview_image_path: str = "",
) -> None:
    shot_id = str(shot_id or "").strip()
    app.state.active_work_context = {
        "kind": "shot",
        "key": f"shot:{shot_id}",
        "shot_id": shot_id,
        "source_file_path": source_file_path,
        "preview_image_path": preview_image_path,
    }
    set_live_selected_shot_id(app, shot_id)


def set_active_scene2d_context(
    app: FastAPI,
    scene_id: str,
    perspective_id: str,
    scene: dict[str, Any] | None = None,
    perspective: dict[str, Any] | None = None,
) -> None:
    scene_id = str(scene_id or "").strip()
    perspective_id = str(perspective_id or "").strip()
    source_file_path = str((perspective or {}).get("source_file_path") or "")
    preview_image_path = str((perspective or {}).get("preview_image_path") or "")

    # Build prev/next keys from the PSD-only perspective list
    perspectives = (scene or {}).get("perspectives") or []
    psd_perspectives = [p for p in perspectives if p.get("type") == "psd"]
    index = next((i for i, p in enumerate(psd_perspectives) if p.get("id") == perspective_id), -1)
    count = len(psd_perspectives)
    prev_key = f"scene2d:{scene_id}:{psd_perspectives[index - 1]['id']}" if index > 0 else ""
    next_key = f"scene2d:{scene_id}:{psd_perspectives[index + 1]['id']}" if 0 <= index < count - 1 else ""

    app.state.active_work_context = {
        "kind": "scene2d",
        "key": f"scene2d:{scene_id}:{perspective_id}",
        "scene_id": scene_id,
        "perspective_id": perspective_id,
        "scene_title": str((scene or {}).get("title") or ""),
        "perspective_title": str((perspective or {}).get("title") or ""),
        "perspective_type": str((perspective or {}).get("type") or "psd"),
        "source_file_path": source_file_path,
        "preview_image_path": preview_image_path,
        "index": index + 1 if index >= 0 else 1,
        "count": count,
        "previous_key": prev_key,
        "next_key": next_key,
    }
    # Do NOT populate live_selected_shot_id for scene2d context


def request_work_context_focus(app: FastAPI, context: dict[str, Any]) -> None:
    new_token = focus_token(app) + 1
    app.state.focus_token = new_token
    app.state.focus_work_context = dict(context)
    # Keep legacy fields in sync for shot focus
    if context.get("kind") == "shot":
        shot_id = str(context.get("shot_id") or "")
        app.state.live_focus_shot_id = shot_id
        app.state.live_focus_token = new_token


def _norm_root(root: str) -> str:
    from pathlib import Path
    return str(Path(root).resolve()).replace("\\", "/")


def get_preview_analysis_job(app: FastAPI, project_root: str) -> dict[str, Any] | None:
    """Return the analysis job for the given project root, or None."""
    jobs = getattr(app.state, "preview_analysis_jobs", {})
    return jobs.get(_norm_root(project_root))


def set_preview_analysis_job(app: FastAPI, job: dict[str, Any]) -> None:
    """Upsert a preview-analysis job keyed by its normalized project root."""
    if not hasattr(app.state, "preview_analysis_jobs"):
        app.state.preview_analysis_jobs = {}
    app.state.preview_analysis_jobs[_norm_root(job["project_root"])] = job


def preview_analysis_status_for_project(app: FastAPI, project_root: str) -> dict[str, Any] | None:
    """Return a serialisable status snapshot for the current project, or None."""
    job = get_preview_analysis_job(app, project_root)
    if job is None:
        return None
    return {
        "task_id": job["task_id"],
        "project_path": job["project_root"],
        "state": job["state"],
        "decoded_count": job.get("decoded_count", 0),
        "revision": job.get("revision", 0),
        "started_at": job.get("started_at"),
        "completed_at": job.get("completed_at"),
        "error": job.get("error"),
    }


def mark_scene2d_changed(app: FastAPI, scene_id: str, perspective_id: str) -> None:
    app.state.plugin_project_revision = plugin_project_revision(app) + 1
    app.state.plugin_change = {
        "revision": plugin_project_revision(app),
        "kind": "scene2d",
        "scene_id": str(scene_id or ""),
        "perspective_id": str(perspective_id or ""),
    }
