"""Invalid types must not flush an existing dirty project's edits."""

import pytest
from fastapi.testclient import TestClient

from storyboard_tool import project_manager
from storyboard_tool.api import create_app


@pytest.mark.parametrize("invalid", ["animation", "COMIC", "", None, True, [], {}])
def test_invalid_api_type_returns_422_without_creation_or_flushing_old_project(tmp_path, invalid):
    app = create_app(tmp_path / "runtime")
    current = project_manager.create_project(tmp_path / "Old")
    shot = project_manager.add_shot(current)
    project_manager.save_project(current)
    before = current.json_path.read_bytes()
    shot.title = "Unsaved prior edit"
    app.state.project = current
    app.state.project_disk_mtime = project_manager.project_disk_mtime(current)
    app.state.dirty = True
    destination = tmp_path / "Rejected.sbd"
    with TestClient(app) as client:
        response = client.post("/api/project/new", json={"path": str(destination), "project_type": invalid})
        assert response.status_code == 422, response.text
        assert app.state.project is current
        assert app.state.dirty
        assert shot.title == "Unsaved prior edit"
        assert current.json_path.read_bytes() == before
        assert not destination.exists()
        assert not (tmp_path / "Rejected").exists()
