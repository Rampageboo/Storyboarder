from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from storyboard_tool import api, project_manager


CREATORS = ["create_project", "create_document", "create_layout2_document"]


@pytest.mark.parametrize("creator_name", CREATORS)
@pytest.mark.parametrize("project_type", [None, "video", "comic"])
def test_project_type_is_present_at_first_save_and_reopens(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, creator_name: str, project_type: str | None
) -> None:
    expected = project_type or "video"
    original_save = project_manager.save_project
    saved_types = []

    def observe_save(project, *args, **kwargs):
        saved_types.append(project.settings.get("project_type"))
        return original_save(project, *args, **kwargs)

    monkeypatch.setattr(project_manager, "save_project", observe_save)
    options = {} if project_type is None else {"project_type": project_type}
    project = getattr(project_manager, creator_name)(tmp_path / "New.sbd", **options)

    assert saved_types and all(value == expected for value in saved_types)
    assert json.loads(project.settings_path.read_text(encoding="utf-8"))["project_type"] == expected
    reopened = project_manager.open_project(project.document_path or project.json_path)
    assert reopened.settings["project_type"] == expected


@pytest.mark.parametrize("creator_name", CREATORS)
def test_invalid_type_does_not_create_files(tmp_path: Path, creator_name: str) -> None:
    with pytest.raises(ValueError, match="Project type"):
        getattr(project_manager, creator_name)(tmp_path / "Invalid.sbd", project_type="animation")
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("creator_name", CREATORS)
def test_opening_old_project_does_not_add_type_or_rewrite_document(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, creator_name: str
) -> None:
    original_save = project_manager.save_project

    def save_old_settings(project, *args, **kwargs):
        # Model the historical writer from its first persistence pass. Removing
        # metadata after publication would require a new Layout 2 revision.
        project.settings.pop("project_type", None)
        return original_save(project, *args, **kwargs)

    with monkeypatch.context() as old_writer:
        old_writer.setattr(project_manager, "save_project", save_old_settings)
        project = getattr(project_manager, creator_name)(tmp_path / "Legacy.sbd")
    path = project.document_path or project.json_path
    before = path.read_bytes()
    settings_before = project.settings_path.read_bytes()

    reopened = project_manager.open_project(path)

    assert "project_type" not in reopened.settings
    assert path.read_bytes() == before
    assert project.settings_path.read_bytes() == settings_before


@pytest.mark.parametrize("project_type", [None, "video", "comic"])
def test_api_type_survives_save_as_and_reopen(tmp_path: Path, project_type: str | None) -> None:
    app_root = tmp_path / "app"
    app_root.mkdir()
    client = TestClient(api.create_app(app_root))
    body = {"path": str(tmp_path / "Original.sbd")}
    if project_type is not None:
        body["project_type"] = project_type
    created = client.post("/api/project/new", json=body)
    assert created.status_code == 200, created.text
    assert created.json()["settings"]["project_type"] == (project_type or "video")

    copied = client.post("/api/project/save-as", json={"path": str(tmp_path / "Copy.sbd")})
    assert copied.status_code == 200, copied.text
    copied_path = copied.json()["project_json_path"]
    reopened = client.post("/api/project/open", json={"project_json_path": copied_path})
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["settings"]["project_type"] == (project_type or "video")


def test_api_invalid_type_preserves_active_project_and_destination(tmp_path: Path) -> None:
    app_root = tmp_path / "app"
    app_root.mkdir()
    app = api.create_app(app_root)
    client = TestClient(app)
    created = client.post("/api/project/new", json={"path": str(tmp_path / "Current.sbd")})
    assert created.status_code == 200, created.text
    active = app.state.project
    before = active.document_path.read_bytes()

    rejected = client.post("/api/project/new", json={
        "path": str(tmp_path / "Invalid.sbd"), "project_type": "animation",
    })

    assert rejected.status_code == 422
    assert app.state.project is active
    assert active.document_path.read_bytes() == before
    assert not (tmp_path / "Invalid").exists()
    assert not (tmp_path / "Invalid.sbd").exists()


@pytest.mark.parametrize("project_type", ["video", "comic"])
def test_new_and_reopened_layout2_project_can_save_without_edits(tmp_path: Path, project_type: str) -> None:
    app_root = tmp_path / "app"
    app_root.mkdir()
    app = api.create_app(app_root)
    client = TestClient(app)
    created = client.post("/api/project/new", json={
        "path": str(tmp_path / "Untouched.sbd"), "project_type": project_type,
    })
    assert created.status_code == 200, created.text
    path = created.json()["project_json_path"]
    revision = created.json()["storage_revision"]
    settings_before = app.state.project.settings_path.read_bytes()
    recents = client.get("/api/app/recents")
    assert recents.status_code == 200, recents.text
    assert path in [entry["path"] for entry in recents.json()["recents"]]

    for _ in range(2):
        saved = client.post("/api/project/save")
        assert saved.status_code == 200, saved.text
        assert saved.json()["storage_revision"] == revision
        assert app.state.project.settings_path.read_bytes() == settings_before

    reopened = client.post("/api/project/open", json={"project_json_path": path})
    assert reopened.status_code == 200, reopened.text
    saved = client.post("/api/project/save")
    assert saved.status_code == 200, saved.text
    assert saved.json()["settings"]["project_type"] == project_type
    assert saved.json()["storage_revision"] == revision
    assert app.state.project.settings_path.read_bytes() == settings_before


@pytest.mark.parametrize("project_type", ["video", "comic"])
def test_forgetting_recent_does_not_mutate_layout2_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, project_type: str
) -> None:
    forgotten_path = str(tmp_path / "PreviouslyOpened.sbd")
    # Historical documents can carry recents in their settings. Forgetting a
    # Home card affects the session, not this canonical document metadata.
    monkeypatch.setitem(project_manager.DEFAULT_SETTINGS, "recent_projects", [forgotten_path])
    app_root = tmp_path / "app"
    app_root.mkdir()
    app = api.create_app(app_root)
    client = TestClient(app)
    created = client.post("/api/project/new", json={
        "path": str(tmp_path / "Current.sbd"), "project_type": project_type,
    })
    assert created.status_code == 200, created.text
    current_path = created.json()["project_json_path"]
    seeded = client.put("/api/app/session", json={"recent_projects": [current_path, forgotten_path]})
    assert seeded.status_code == 200, seeded.text
    listed = client.get("/api/app/recents")
    assert forgotten_path in [entry["path"] for entry in listed.json()["recents"]]
    settings_before = app.state.project.settings_path.read_bytes()

    forgotten = client.post("/api/app/recents/forget", json={"path": forgotten_path})
    assert forgotten.status_code == 200, forgotten.text
    assert forgotten_path not in [entry["path"] for entry in forgotten.json()["recents"]]
    saved = client.post("/api/project/save")
    assert saved.status_code == 200, saved.text
    assert saved.json()["settings"]["recent_projects"] == [forgotten_path]
    assert saved.json()["storage_revision"] == created.json()["storage_revision"]
    assert app.state.project.settings_path.read_bytes() == settings_before
    closed = client.post("/api/app/close-project")
    assert closed.status_code == 200, closed.text
    reopened = client.post("/api/project/open", json={"project_json_path": current_path})
    assert reopened.status_code == 200, reopened.text
    listed = client.get("/api/app/recents")
    assert listed.status_code == 200, listed.text
    assert forgotten_path not in [entry["path"] for entry in listed.json()["recents"]]
    assert app.state.project.settings_path.read_bytes() == settings_before
