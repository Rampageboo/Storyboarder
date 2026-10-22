from __future__ import annotations

import json
import os
import time
from pathlib import Path

from fastapi.testclient import TestClient

from conftest import make_project
from storyboard_tool import blender_bridge, scene3d
from storyboard_tool.api import create_app
from storyboard_tool.project_layout import resolve_scene3d_asset


class _Process:
    def __init__(self) -> None:
        self.returncode: int | None = None

    def poll(self) -> int | None:
        return self.returncode


def _isolated_bridge(monkeypatch, tmp_path: Path) -> tuple[Path, Path]:
    bridge = tmp_path / "bridge.json"
    heartbeat = tmp_path / "heartbeat.json"
    monkeypatch.setattr(blender_bridge, "bridge_file_path", lambda: bridge)
    monkeypatch.setattr(blender_bridge, "heartbeat_file_path", lambda: heartbeat)
    return bridge, heartbeat


def _project(tmp_path: Path, name: str = "Demo"):
    project = make_project(tmp_path, name)
    scene = scene3d.ensure_active_scene(project)
    blend_path = resolve_scene3d_asset(project, scene["id"], ".blend")
    blend_path.parent.mkdir(parents=True, exist_ok=True)
    blend_path.write_bytes(b"blend")
    scene3d.configure_blend_preview(project, scene["id"], blend_path)
    app = create_app(tmp_path / "app")
    app.state.project = project
    return project, blend_path, app


def _begin(app, project, blend_path: Path) -> tuple[dict, _Process]:
    scene = scene3d.ensure_active_scene(project)
    session = blender_bridge.begin_session(app, project, scene, blend_path)
    process = _Process()
    blender_bridge.attach_process(app, process)
    return session, process


def _heartbeat(path: Path, session: dict, blend: Path, **extra) -> None:
    blender_bridge._write_json(
        path,
        {
            "session_id": session["session_id"],
            "blend_path": str(blend.resolve()),
            "dirty": False,
            "saved_mtime_ns": blend.stat().st_mtime_ns,
            **extra,
        },
    )


def _blender_save(session_copy: Path, data: bytes) -> None:
    previous = session_copy.stat().st_mtime_ns
    session_copy.write_bytes(data)
    os.utime(session_copy, ns=(previous + 5_000_000, previous + 5_000_000))


def test_external_blender_session_id_is_cli_argument_safe(tmp_path: Path, monkeypatch) -> None:
    _isolated_bridge(monkeypatch, tmp_path)
    monkeypatch.setattr(blender_bridge.secrets, "token_urlsafe", lambda _length: "-option-like")
    project, blend_path, app = _project(tmp_path)

    session, _process = _begin(app, project, blend_path)

    assert session["session_id"] == "sb_-option-like"
    assert not session["session_id"].startswith("-")


def test_session_launches_a_copy_of_the_project_file(tmp_path: Path, monkeypatch) -> None:
    bridge, _heartbeat_path = _isolated_bridge(monkeypatch, tmp_path)
    project, blend_path, app = _project(tmp_path)

    session, _process = _begin(app, project, blend_path)

    launch_path = Path(session["launch_path"])
    assert launch_path != blend_path.resolve()
    assert launch_path.read_bytes() == blend_path.read_bytes()
    assert Path(session["canonical_path"]) == blend_path.resolve()
    context = json.loads(bridge.read_text(encoding="utf-8"))
    assert context["write_enabled"] is True
    assert context["project_identity"] == blender_bridge.project_identity(project)


def test_external_blender_owns_until_process_and_heartbeat_end(tmp_path: Path, monkeypatch) -> None:
    _bridge, heartbeat_path = _isolated_bridge(monkeypatch, tmp_path)
    project, blend_path, app = _project(tmp_path)
    session, process = _begin(app, project, blend_path)
    scene_id = scene3d.ensure_active_scene(project)["id"]

    pending = blender_bridge.status(app)
    assert pending["external_blender_owned"] is True
    assert pending["external_blender_pending"] is True
    assert pending["state"] == "launching"
    preview_path = scene3d.preview_file_path(project, scene_id)
    preview_path.parent.mkdir(parents=True, exist_ok=True)
    preview_path.write_bytes(b"preview")
    preview_status = blender_bridge.status(app)
    assert preview_status["preview_path"] == str(preview_path)
    assert preview_status["preview_revision"] == preview_path.stat().st_mtime_ns

    _heartbeat(heartbeat_path, session, Path(session["launch_path"]), active_camera="SB_PathCamera", dirty=True)
    blender_bridge.tick(app)
    connected = blender_bridge.status(app)
    assert connected["external_blender_connected"] is True
    assert connected["state"] == "connected"
    assert connected["external_blender_camera"] == "SB_PathCamera"

    process.returncode = 0
    stale = time.time() - blender_bridge.HEARTBEAT_MAX_AGE_SECONDS - 1
    os.utime(heartbeat_path, (stale, stale))
    released = blender_bridge.tick(app)
    assert released["external_blender_owned"] is False
    assert released["state"] == "offline"


def test_blender_save_is_synced_into_the_project(tmp_path: Path, monkeypatch) -> None:
    _bridge, heartbeat_path = _isolated_bridge(monkeypatch, tmp_path)
    project, blend_path, app = _project(tmp_path)
    session, _process = _begin(app, project, blend_path)
    session_copy = Path(session["launch_path"])
    revision_before = project.storage_revision

    _blender_save(session_copy, b"blender saved")
    _heartbeat(heartbeat_path, session, session_copy)
    blender_bridge.tick(app)

    assert blend_path.read_bytes() == b"blender saved"
    assert project.storage_revision > revision_before
    assert blender_bridge.status(app)["last_synced_at"] > 0


def test_status_has_no_side_effects(tmp_path: Path, monkeypatch) -> None:
    _bridge, heartbeat_path = _isolated_bridge(monkeypatch, tmp_path)
    project, blend_path, app = _project(tmp_path)
    session, _process = _begin(app, project, blend_path)
    session_copy = Path(session["launch_path"])
    revision_before = project.storage_revision
    _blender_save(session_copy, b"unsynced save")
    _heartbeat(heartbeat_path, session, session_copy)

    for _ in range(3):
        blender_bridge.status(app)

    assert blend_path.read_bytes() == b"blend"
    assert project.storage_revision == revision_before


def test_fresh_heartbeat_is_adopted_after_storyboarder_restart(tmp_path: Path, monkeypatch) -> None:
    _bridge, heartbeat_path = _isolated_bridge(monkeypatch, tmp_path)
    project, blend_path, first_app = _project(tmp_path)
    session, _process = _begin(first_app, project, blend_path)
    _heartbeat(heartbeat_path, session, Path(session["launch_path"]), active_camera="Camera")

    restarted_app = create_app(tmp_path / "restarted")
    restarted_app.state.project = project
    adopted = blender_bridge.tick(restarted_app)

    assert adopted["external_blender_owned"] is True
    assert adopted["external_blender_connected"] is True
    assert restarted_app.state.external_blender_session_id == session["session_id"]


def test_session_for_another_project_is_not_adopted(tmp_path: Path, monkeypatch) -> None:
    _bridge, heartbeat_path = _isolated_bridge(monkeypatch, tmp_path)
    project, blend_path, first_app = _project(tmp_path)
    session, _process = _begin(first_app, project, blend_path)
    _heartbeat(heartbeat_path, session, Path(session["launch_path"]))

    other = make_project(tmp_path, "Other")
    restarted_app = create_app(tmp_path / "restarted")
    restarted_app.state.project = other

    assert blender_bridge.tick(restarted_app)["state"] == "offline"
    assert restarted_app.state.blender_session["session_id"] == ""


def test_session_api_routes(tmp_path: Path, monkeypatch) -> None:
    _bridge, _heartbeat_path = _isolated_bridge(monkeypatch, tmp_path)
    project, _blend_path, app = _project(tmp_path)
    scene = scene3d.ensure_active_scene(project)
    manifest_path = blender_bridge.manifest_file_path(project, scene["id"])
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps({"fps": 24, "frame_start": 1, "frame_end": 48, "cameras": [{"name": "CAM_A", "lens_mm": 35}]}),
        encoding="utf-8",
    )

    with TestClient(app) as client:
        session = client.get("/api/project/scene3d/session")
        manifest = client.get(f"/api/project/scenes3d/{scene['id']}/manifest")
        resolve = client.post("/api/project/scene3d/session/resolve", json={"action": "use_blender"})

    assert session.status_code == 200
    assert session.json()["state"] == "offline"
    assert manifest.status_code == 200
    assert manifest.json()["cameras"][0]["name"] == "CAM_A"
    assert manifest.json()["frame_end"] == 48
    assert resolve.status_code == 400


def test_session_survives_until_blender_first_reports(tmp_path: Path, monkeypatch) -> None:
    """Regression: the sync loop must not end a session Blender is still starting."""
    _bridge, _heartbeat_path = _isolated_bridge(monkeypatch, tmp_path)
    project, blend_path, app = _project(tmp_path)
    scene = scene3d.ensure_active_scene(project)
    blender_bridge.begin_session(app, project, scene, blend_path)  # no process attached yet

    state = blender_bridge.tick(app)

    assert state["state"] == "launching"
    assert state["external_blender_owned"] is True

    monkeypatch.setattr(blender_bridge, "LAUNCH_GRACE_SECONDS", 0.0)
    assert blender_bridge.tick(app)["state"] == "offline"
