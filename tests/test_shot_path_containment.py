"""Regression tests: shot metadata paths must not escape the project folder.

POST /api/shots/restore builds a Shot straight from a client-supplied dict, so a
hostile ``preview_image_path`` / ``thumbnail_path`` (absolute path or ``..`` escape)
must never be served back through the image/thumbnail endpoints, which hand the
resolved path to FileResponse.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from storyboard_tool import api as api_module
from storyboard_tool import project_manager
from storyboard_tool.models import Shot
from storyboard_tool.shot_assets import resolve_shot_preview_path, resolve_shot_thumbnail_path


def _client(tmp: str) -> TestClient:
    app = api_module.create_app(Path(tmp))
    client = TestClient(app, raise_server_exceptions=False)
    client.post("/api/project/new", json={"path": tmp})
    return client


def test_restore_shot_with_absolute_preview_path_is_not_served() -> None:
    tmp = tempfile.mkdtemp()
    # A sensitive file that lives OUTSIDE the project folder.
    secret = Path(tempfile.mkdtemp()) / "secret.txt"
    secret.write_text("top secret", encoding="utf-8")

    client = _client(tmp)
    client.post(
        "/api/shots/restore",
        json={"shot": {"shot_id": "evil", "preview_image_path": str(secret)}, "index": 0},
    )

    response = client.get("/api/shots/evil/image")
    # The out-of-project absolute path must not be resolved and served.
    assert response.status_code == 404
    if response.status_code == 200:
        assert response.text != "top secret"


def test_restore_shot_with_traversal_thumbnail_path_is_not_served() -> None:
    tmp = tempfile.mkdtemp()
    outside = Path(tmp).parent / "outside_thumb.txt"
    outside.write_text("not a thumbnail", encoding="utf-8")

    client = _client(tmp)
    client.post(
        "/api/shots/restore",
        json={
            "shot": {"shot_id": "evil2", "thumbnail_path": "../../outside_thumb.txt"},
            "index": 0,
        },
    )

    response = client.get("/api/shots/evil2/thumbnail")
    assert response.status_code == 404


def test_resolve_helpers_reject_out_of_project_paths(tmp_path) -> None:
    project = project_manager.create_project(tmp_path)
    shot = Shot(shot_id="s1", preview_image_path="C:/Windows/win.ini", thumbnail_path="/etc/hosts")
    # No canonical on-disk asset exists yet, and the metadata paths escape the root,
    # so both resolvers must decline rather than point outside the project.
    assert resolve_shot_preview_path(project, shot) is None
    assert resolve_shot_thumbnail_path(project, shot) is None
