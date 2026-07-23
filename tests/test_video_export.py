from __future__ import annotations

from pathlib import Path

import pytest

from storyboard_tool import export_service, project_manager, video_export


def _project_with_boards(tmp: Path, count: int = 3) -> object:
    project = project_manager.create_project(tmp, canvas_width=320, canvas_height=180)
    for _ in range(count):
        shot = project_manager.add_shot(project)
        shot.duration_seconds = 0.3
    return project


def test_export_animatic_produces_nonempty_mp4(tmp_path: Path) -> None:
    project = _project_with_boards(tmp_path)
    try:
        output = export_service.export_animatic(project, fps=8, captions=True)
    except RuntimeError as exc:  # no ffmpeg and no usable OpenCV writer in this environment
        pytest.skip(str(exc))
    assert output.exists()
    assert output.suffix == ".mp4"
    assert output.stat().st_size > 0


def test_export_animatic_rejects_empty_project(tmp_path: Path) -> None:
    project = project_manager.create_project(tmp_path, canvas_width=320, canvas_height=180)
    with pytest.raises(ValueError):
        video_export.export_animatic(project, tmp_path / "empty.mp4")


def test_animatic_export_endpoint(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from storyboard_tool import api as api_module

    app_dir = tmp_path / "app"
    app_dir.mkdir()
    client = TestClient(api_module.create_app(app_dir), raise_server_exceptions=False)
    created = client.post(
        "/api/project/new",
        json={"path": str(tmp_path / "Proj"), "canvas_width": 320, "canvas_height": 180},
    )
    assert created.status_code == 200, created.text
    client.post("/api/shots")
    client.post("/api/shots")
    resp = client.post("/api/export/animatic", json={"fps": 8, "captions": False})
    if resp.status_code == 500:
        pytest.skip("no video encoder available in this environment")
    assert resp.status_code == 200, resp.text
    assert resp.json()["download_url"] == "/api/export/animatic"


def test_open_export_missing_returns_404(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from storyboard_tool import api as api_module

    app_dir = tmp_path / "app2"
    app_dir.mkdir()
    client = TestClient(api_module.create_app(app_dir), raise_server_exceptions=False)
    assert client.post("/api/project/new", json={"path": str(tmp_path / "Proj2")}).status_code == 200
    # Never generated -> resolves before any OS open call.
    resp = client.post("/api/export/open", json={"type": "animatic"})
    assert resp.status_code == 404
