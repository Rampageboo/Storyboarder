from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from storyboard_tool import project_manager, scene3d
from storyboard_tool.api import create_app
from storyboard_tool.bpy_viewport import BpyViewportError, project_blend_path


class _FakeBpyManager:
    def __init__(self) -> None:
        self.running = False
        self.camera_path_payload: dict | None = None
        self.save_count = 0

    def status(self):
        return {"running": self.running, "blend_path": "", "engine": "bpy"}

    def start(self, _project):
        self.running = True
        return self.status()

    def stop(self):
        self.running = False

    def frame(self, _query):
        return b"\xff\xd8fake-jpeg", {"X-Render-ms": "12.5"}

    def create_camera_path(self, payload):
        self.camera_path_payload = payload
        return {
            "ok": True,
            "path": "SB_CameraPath",
            "camera": "SB_PathCamera",
            "target": "SB_CameraTarget",
            "blend_path": "scene.blend",
            "point_count": len(payload["points"]),
        }

    def save(self):
        self.save_count += 1
        return {"ok": True, "blend_path": "scene.blend"}

    def save_if_running(self):
        return self.save() if self.running else None


def test_project_blend_path_uses_active_attached_blend(tmp_path: Path) -> None:
    project = project_manager.create_project(tmp_path)
    created = scene3d.create_scene(project, title="Attached")["scene"]
    imported = scene3d.import_scene_file(
        project,
        created["id"],
        "attached.blend",
        b"blend",
    )["scene"]
    scene3d.set_active(project, created["id"])
    attached = project.root_path / imported["blend_file_path"]

    assert project_blend_path(project) == attached.resolve()


def test_project_blend_path_rejects_escape(tmp_path: Path, monkeypatch) -> None:
    project = project_manager.create_project(tmp_path)
    monkeypatch.setattr(
        scene3d,
        "active_scene",
        lambda _project: {"blend_file_path": "../../outside.blend"},
    )

    try:
        project_blend_path(project)
    except BpyViewportError as exc:
        assert "inside the project" in str(exc)
    else:
        raise AssertionError("Expected an escaping Blender path to be rejected.")


def test_bpy_viewport_routes_proxy_frames_and_mark_camera_path_dirty(
    tmp_path: Path,
) -> None:
    app = create_app(tmp_path)
    app.state.project = project_manager.create_project(tmp_path / "project")
    fake = _FakeBpyManager()
    app.state.bpy_viewport_manager = fake

    with TestClient(app) as client:
        started = client.post("/api/project/bpy-viewport/start")
        assert started.status_code == 200
        assert started.json()["running"] is True

        frame = client.get("/api/project/bpy-viewport/frame?width=640&height=360")
        assert frame.status_code == 200
        assert frame.content.startswith(b"\xff\xd8")
        assert frame.headers["x-render-ms"] == "12.5"

        created = client.post(
            "/api/project/bpy-viewport/camera-path",
            json={
                "points": [[0.2, 0.6], [0.5, 0.4], [0.8, 0.6]],
                "width": 640,
                "height": 360,
                "duration_frames": 48,
            },
        )
        assert created.status_code == 200
        assert created.json()["camera"] == "SB_PathCamera"
        assert fake.camera_path_payload is not None
        assert app.state.dirty is True

        saved = client.post("/api/project/save")
        assert saved.status_code == 200
        assert fake.save_count == 1
        assert fake.running is True

        stopped = client.post("/api/project/bpy-viewport/stop")
        assert stopped.status_code == 200
        assert stopped.json()["running"] is False
