from __future__ import annotations

import os
import time
from pathlib import Path

from fastapi.testclient import TestClient

from storyboard_tool import blender_bridge, project_manager, scene3d
from storyboard_tool.api import create_app


class _Process:
    def __init__(self) -> None:
        self.returncode: int | None = None

    def poll(self) -> int | None:
        return self.returncode


class _ViewportManager:
    def __init__(self) -> None:
        self.started = False

    def status(self):
        return {"running": False, "blend_path": "", "engine": "bpy"}

    def start(self, _project):
        self.started = True
        return {"running": True, "blend_path": "", "engine": "bpy"}

    def stop(self):
        return None


def _isolated_bridge(monkeypatch, tmp_path: Path) -> tuple[Path, Path]:
    bridge = tmp_path / "bridge.json"
    heartbeat = tmp_path / "heartbeat.json"
    monkeypatch.setattr(blender_bridge, "bridge_file_path", lambda: bridge)
    monkeypatch.setattr(blender_bridge, "heartbeat_file_path", lambda: heartbeat)
    return bridge, heartbeat


def _begin(app, project, blend_path: Path) -> tuple[dict, _Process]:
    scene = scene3d.ensure_active_scene(project)
    session = blender_bridge.begin_session(app, project, scene, blend_path)
    process = _Process()
    blender_bridge.attach_process(app, process)
    return session, process


def test_external_blender_owns_until_process_and_heartbeat_end(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _bridge, heartbeat_path = _isolated_bridge(monkeypatch, tmp_path)
    project = project_manager.create_project(tmp_path / "project")
    blend_path = project.root_path / "scene3d" / "scene.blend"
    blend_path.parent.mkdir(parents=True, exist_ok=True)
    blend_path.write_bytes(b"blend")
    app = create_app(tmp_path)
    app.state.project = project
    session, process = _begin(app, project, blend_path)

    pending = blender_bridge.status(app)
    assert pending["external_blender_owned"] is True
    assert pending["external_blender_pending"] is True
    preview_path = scene3d.preview_file_path(project, "scene3d_001")
    preview_path.parent.mkdir(parents=True, exist_ok=True)
    preview_path.write_bytes(b"preview")
    preview_status = blender_bridge.status(app)
    assert preview_status["preview_path"] == str(preview_path)
    assert preview_status["preview_revision"] == preview_path.stat().st_mtime_ns

    blender_bridge._write_json(
        heartbeat_path,
        {
            "session_id": session["session_id"],
            "blend_path": str(blend_path.resolve()),
            "active_camera": "SB_PathCamera",
            "dirty": True,
        },
    )
    connected = blender_bridge.status(app)
    assert connected["external_blender_connected"] is True
    assert connected["external_blender_camera"] == "SB_PathCamera"

    process.returncode = 0
    stale = time.time() - blender_bridge.HEARTBEAT_MAX_AGE_SECONDS - 1
    os.utime(heartbeat_path, (stale, stale))
    released = blender_bridge.status(app)
    assert released["external_blender_owned"] is False


def test_fresh_heartbeat_is_adopted_after_storyboarder_restart(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _bridge, heartbeat_path = _isolated_bridge(monkeypatch, tmp_path)
    project = project_manager.create_project(tmp_path / "project")
    blend_path = project.root_path / "scene3d" / "scene.blend"
    blend_path.parent.mkdir(parents=True, exist_ok=True)
    blend_path.write_bytes(b"blend")
    first_app = create_app(tmp_path)
    first_app.state.project = project
    session, _process = _begin(first_app, project, blend_path)
    blender_bridge._write_json(
        heartbeat_path,
        {
            "session_id": session["session_id"],
            "blend_path": str(blend_path.resolve()),
            "active_camera": "Camera",
        },
    )

    restarted_app = create_app(tmp_path)
    restarted_app.state.project = project
    adopted = blender_bridge.status(restarted_app)

    assert adopted["external_blender_owned"] is True
    assert adopted["external_blender_connected"] is True
    assert restarted_app.state.external_blender_session_id == session["session_id"]


def test_built_in_viewport_refuses_to_start_while_external_blender_owns_scene(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _isolated_bridge(monkeypatch, tmp_path)
    project = project_manager.create_project(tmp_path / "project")
    blend_path = project.root_path / "scene3d" / "scene.blend"
    blend_path.parent.mkdir(parents=True, exist_ok=True)
    blend_path.write_bytes(b"blend")
    app = create_app(tmp_path)
    app.state.project = project
    _session, _process = _begin(app, project, blend_path)
    manager = _ViewportManager()
    app.state.bpy_viewport_manager = manager

    with TestClient(app) as client:
        response = client.post("/api/project/bpy-viewport/start")

    assert response.status_code == 409
    assert manager.started is False
