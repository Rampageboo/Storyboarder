from __future__ import annotations

import copy
import io
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from storyboard_tool import project_document, project_layout, project_manager, story_graph
from storyboard_tool.api import create_app
from storyboard_tool.backend_service import StoryboardBackendService
from storyboard_tool.models import Project, Shot


@pytest.fixture
def graph_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    clients = []
    projects = []
    monkeypatch.setattr(project_layout, "LAYOUT_2_ENABLED", True)

    def create(kind="folder", count=3):
        index = len(clients)
        app_dir = tmp_path / f"app-{index}"
        app_dir.mkdir()
        if kind == "layout2":
            project = project_manager.create_layout2_document(tmp_path / f"Story-{index}.sbd", canvas_width=256, canvas_height=144)
        elif kind == "document":
            project = project_manager.create_document(tmp_path / f"Legacy-{index}.sbd", canvas_width=256, canvas_height=144)
        else:
            project = project_manager.create_project(tmp_path / f"Folder-{index}", canvas_width=256, canvas_height=144)
        project.settings["backup_on_save"] = False
        projects.append(project)
        app = create_app(app_dir)
        app.state.project = project
        app.state.project_disk_mtime = project_manager.project_disk_mtime(project)
        client = TestClient(app, raise_server_exceptions=False)
        clients.append(client)
        for _ in range(count):
            response = client.post("/api/shots", json={})
            assert response.status_code == 200, response.text
        return client

    yield create
    for client in clients:
        projects.append(client.app.state.project)
        client.close()
    for project in projects:
        project_manager.cleanup_document_working_root(project)


def _graph(client):
    response = client.get("/api/project")
    assert response.status_code == 200, response.text
    return response.json()["story_graph"]


def _persist_routes(client):
    graph = _graph(client)
    ids = graph["routes"][0]["shot_ids"]
    graph["routes"].append({"id": "alternate", "name": "另一个走向", "shot_ids": [ids[0], ids[-1]]})
    graph["active_route_id"] = "alternate"
    response = client.put("/api/project/story-graph", json=graph)
    assert response.status_code == 200, response.text
    return response.json()["story_graph"]


def _disk(project):
    names = ["project.json", "settings.json", "shots.json", "shots.csv"]
    return {name: (project.metadata_root / name).read_bytes() for name in names if (project.metadata_root / name).is_file()}


@pytest.mark.parametrize("kind", ["folder", "document", "layout2"])
def test_legacy_graph_is_derived_without_persisting_or_changing_dirty(graph_client, kind):
    client = graph_client(kind)
    project = client.app.state.project
    before = _disk(project)
    dirty = client.app.state.dirty
    graph = _graph(client)
    assert graph["revision"] == 0
    assert graph["routes"][0]["shot_ids"] == [shot.shot_id for shot in project.shots]
    assert "story_graph" not in project.settings
    assert "story_graph" not in json.loads(project.settings_path.read_text(encoding="utf-8"))
    assert _disk(project) == before
    assert client.app.state.dirty == dirty


@pytest.mark.parametrize("kind", ["folder", "document", "layout2"])
def test_graph_branch_save_and_reopen_preserve_routes_and_other_settings(graph_client, kind):
    client = graph_client(kind)
    project = client.app.state.project
    project.settings["unrelated_custom_setting"] = {"keep": [1, 2]}
    graph = _persist_routes(client)
    parent = graph["routes"][1]["shot_ids"][-1]
    response = client.post("/api/project/story-graph/branch", json={
        "route_id": "alternate", "from_shot_id": parent, "title": "追上列车",
    })
    assert response.status_code == 200, response.text
    payload = response.json()
    new_id = payload["shot"]["shot_id"]
    assert payload["shot"]["preview_image_path"] == ""
    accepted = payload["story_graph"]
    assert accepted["routes"][:2] == graph["routes"]
    assert accepted["routes"][-1]["shot_ids"] == graph["routes"][1]["shot_ids"] + [new_id]
    assert accepted["active_route_id"] == accepted["routes"][-1]["id"]
    assert accepted["revision"] == graph["revision"] + 1
    assert client.post("/api/project/save").status_code == 200
    reopened = project_manager.open_project(project.reopen_path)
    try:
        assert story_graph.get_graph(reopened) == accepted
        assert reopened.settings["unrelated_custom_setting"] == {"keep": [1, 2]}
    finally:
        if reopened.metadata_root != project.metadata_root:
            project_manager.cleanup_document_working_root(reopened)


@pytest.mark.parametrize("kind", ["folder", "document", "layout2"])
def test_graph_survives_save_as(graph_client, tmp_path, kind):
    client = graph_client(kind)
    graph = _persist_routes(client)
    result = client.post("/api/project/save-as", json={"path": str(tmp_path / "Copied.sbd")})
    assert result.status_code == 200, result.text
    assert result.json()["story_graph"] == graph
    reopened = project_manager.open_project(client.app.state.project.reopen_path)
    try:
        assert story_graph.get_graph(reopened) == graph
    finally:
        if reopened.metadata_root != client.app.state.project.metadata_root:
            project_manager.cleanup_document_working_root(reopened)


def test_graph_survives_layout_conversion(graph_client, tmp_path):
    # Conversion requires an existing Layout 1 document, not a folder project.
    client = graph_client("document")
    graph = _persist_routes(client)
    response = client.post("/api/project/convert", json={"path": str(tmp_path / "Converted.sbd")})
    assert response.status_code == 200, response.text
    assert response.json()["story_graph"] == graph


def test_custom_routes_survive_add_duplicate_delete_restore_and_global_reorder(graph_client):
    client = graph_client()
    graph = _persist_routes(client)
    ids = graph["routes"][0]["shot_ids"]
    added = client.post("/api/shots", json={"after_shot_id": ids[0]})
    assert added.status_code == 200, added.text
    new_id = added.json()["shot"]["shot_id"]
    custom = added.json()["story_graph"]
    assert custom["routes"][0] == graph["routes"][0]
    assert custom["routes"][1]["shot_ids"] == [ids[0], new_id, ids[-1]]
    duplicated = client.post(f"/api/shots/{new_id}/duplicate")
    assert duplicated.status_code == 200, duplicated.text
    duplicate_id = duplicated.json()["shot"]["shot_id"]
    custom = duplicated.json()["story_graph"]
    assert custom["routes"][1]["shot_ids"] == [ids[0], new_id, duplicate_id, ids[-1]]
    shots = duplicated.json()["shots"]
    order = [shot["shot_id"] for shot in reversed(shots)]
    reordered = client.post("/api/shots/reorder", json={"shot_ids": order})
    assert reordered.status_code == 200, reordered.text
    assert reordered.json()["story_graph"] == custom
    removed = next(shot for shot in shots if shot["shot_id"] == ids[0])
    deleted = client.delete(f"/api/shots/{ids[0]}")
    assert deleted.status_code == 200, deleted.text
    assert all(ids[0] not in route["shot_ids"] for route in deleted.json()["story_graph"]["routes"])
    assert ids[0] not in deleted.json()["story_graph"]["positions"]
    restored = client.post("/api/shots/restore", json={"shot": removed, "index": 0})
    assert restored.status_code == 200, restored.text
    project = client.app.state.project
    assert story_graph.validate(restored.json()["story_graph"], [shot.shot_id for shot in project.shots])


def test_deleting_all_shots_keeps_an_empty_route_then_add_works(graph_client):
    client = graph_client()
    graph = _persist_routes(client)
    ids = graph["routes"][0]["shot_ids"]
    deleted = client.request("DELETE", "/api/shots/batch", json={"shot_ids": ids})
    assert deleted.status_code == 200, deleted.text
    assert all(route["shot_ids"] == [] for route in deleted.json()["story_graph"]["routes"])
    response = client.post("/api/shots", json={})
    assert response.status_code == 200, response.text
    active = response.json()["story_graph"]["active_route_id"]
    route = next(route for route in response.json()["story_graph"]["routes"] if route["id"] == active)
    assert route["shot_ids"] == [response.json()["shot"]["shot_id"]]


@pytest.mark.parametrize("damage", ["version", "revision", "duplicate-route", "duplicate-shot", "missing-shot", "uncovered-shot", "active", "cycle", "position", "unknown-position"])
def test_invalid_graph_rejected_without_memory_or_disk_changes(graph_client, damage):
    client = graph_client()
    original = _persist_routes(client)
    graph = copy.deepcopy(original)
    ids = graph["routes"][0]["shot_ids"]
    if damage == "version": graph["version"] = 2
    elif damage == "revision": graph["revision"] = True
    elif damage == "duplicate-route": graph["routes"].append(copy.deepcopy(graph["routes"][0]))
    elif damage == "duplicate-shot": ids.append(ids[0])
    elif damage == "missing-shot": ids.append("missing")
    elif damage == "uncovered-shot": graph["routes"][0]["shot_ids"] = [ids[0], ids[-1]]
    elif damage == "active": graph["active_route_id"] = "missing"
    elif damage == "cycle": graph["routes"][1]["shot_ids"] = list(reversed(ids))
    elif damage == "position": graph["positions"][ids[0]]["x"] = "NaN"
    elif damage == "unknown-position": graph["positions"]["missing"] = {"x": 0, "y": 0}
    project = client.app.state.project
    before = _disk(project)
    response = client.put("/api/project/story-graph", json=graph)
    assert response.status_code == 400, response.text
    assert story_graph.get_graph(project) == original
    assert _disk(project) == before


def test_stale_put_and_invalid_branch_do_not_mutate(graph_client):
    client = graph_client()
    original = _persist_routes(client)
    project = client.app.state.project
    before = _disk(project)
    stale = copy.deepcopy(original)
    stale["revision"] -= 1
    assert client.put("/api/project/story-graph", json=stale).status_code == 409
    for body in [
        {"route_id": "missing", "from_shot_id": original["routes"][0]["shot_ids"][0], "title": "新分支"},
        {"route_id": "alternate", "from_shot_id": original["routes"][0]["shot_ids"][1], "title": "新分支"},
        {"route_id": "alternate", "from_shot_id": original["routes"][0]["shot_ids"][0], "title": "   "},
    ]:
        response = client.post("/api/project/story-graph/branch", json=body)
        assert response.status_code == 400, response.text
    assert story_graph.get_graph(project) == original
    assert _disk(project) == before


def test_stale_graph_after_shot_delete_reports_revision_conflict(graph_client):
    client = graph_client()
    old_graph = _persist_routes(client)
    shot_id = old_graph["routes"][0]["shot_ids"][1]
    deleted = client.delete(f"/api/shots/{shot_id}")
    assert deleted.status_code == 200, deleted.text
    response = client.put("/api/project/story-graph", json=old_graph)
    assert response.status_code == 409, response.text
    assert _graph(client) == deleted.json()["story_graph"]


@pytest.mark.parametrize("kind", ["folder", "document", "layout2"])
@pytest.mark.parametrize("operation", ["put", "branch"])
def test_disk_failure_rolls_back_graph_shots_and_app_state(graph_client, monkeypatch, kind, operation):
    client = graph_client(kind)
    original = _persist_routes(client)
    project = client.app.state.project
    before = _disk(project)
    shots_before = [shot.to_dict() for shot in project.shots]
    metadata_before = {path.relative_to(project.metadata_root).as_posix() for path in project.metadata_root.rglob("*") if path.is_file()}
    revision = project.storage_revision
    dirty, mtime = client.app.state.dirty, client.app.state.project_disk_mtime
    real_save_settings = project_manager.save_settings

    def fail_after_settings_write(current):
        real_save_settings(current)
        raise OSError("injected disk failure after graph write")

    monkeypatch.setattr(project_manager, "save_settings", fail_after_settings_write)
    if operation == "put":
        changed = copy.deepcopy(original)
        changed["routes"][0]["name"] = "Must roll back"
        response = client.put("/api/project/story-graph", json=changed)
    else:
        response = client.post("/api/project/story-graph/branch", json={
            "route_id": "alternate", "from_shot_id": original["routes"][1]["shot_ids"][-1], "title": "Must roll back",
        })
    assert response.status_code == 500, response.text
    assert story_graph.get_graph(project) == original
    assert [shot.to_dict() for shot in project.shots] == shots_before
    assert _disk(project) == before
    assert {path.relative_to(project.metadata_root).as_posix() for path in project.metadata_root.rglob("*") if path.is_file()} == metadata_before
    assert project.storage_revision == revision
    assert client.app.state.dirty == dirty
    assert client.app.state.project_disk_mtime == mtime


def test_invalid_persisted_graph_is_not_silently_replaced_on_open(graph_client):
    client = graph_client()
    project = client.app.state.project
    graph = _persist_routes(client)
    graph["routes"][0]["shot_ids"].append("missing")
    settings = json.loads(project.settings_path.read_text(encoding="utf-8"))
    settings["story_graph"] = graph
    project.settings_path.write_text(json.dumps(settings), encoding="utf-8")
    before = project.settings_path.read_bytes()
    with pytest.raises(ValueError, match="existing shots"):
        project_manager.open_project(project.reopen_path)
    assert project.settings_path.read_bytes() == before


@pytest.mark.parametrize("coordinate", [float("nan"), float("inf"), float("-inf"), True])
def test_non_finite_or_boolean_position_is_rejected(coordinate):
    project = Project(root_path=Path("unused"), shots=[Shot(shot_id="a")])
    graph = story_graph.get_graph(project)
    graph["positions"]["a"]["x"] = coordinate
    with pytest.raises(ValueError, match="finite"):
        story_graph.update_graph(project, graph)
    assert "story_graph" not in project.settings


@pytest.mark.parametrize("after_index", [-1, 1, 999])
def test_add_shot_rejects_invalid_index_before_filesystem_writes(tmp_path, after_index):
    project = Project(root_path=tmp_path, shots=[Shot(shot_id="a")])
    with pytest.raises(IndexError, match="Shot index out of range"):
        project_manager.add_shot(project, after_index=after_index)
    assert [shot.shot_id for shot in project.shots] == ["a"]
    assert list(tmp_path.iterdir()) == []


def _delete_for_exact_undo(client, batch):
    before = _persist_routes(client)
    shots = client.get("/api/project").json()["shots"]
    selected = [shots[0], shots[-1]] if batch else [shots[0]]
    items = [{"shot": shot, "index": shots.index(shot)} for shot in selected]
    if batch:
        response = client.request("DELETE", "/api/shots/batch", json={"shot_ids": [shot["shot_id"] for shot in selected]})
    else:
        response = client.delete(f"/api/shots/{selected[0]['shot_id']}")
    assert response.status_code == 200, response.text
    snapshot = copy.deepcopy(before)
    snapshot["revision"] = response.json()["story_graph"]["revision"]
    endpoint = "/api/shots/batch/restore" if batch else "/api/shots/restore"
    body = {"items": items} if batch else items[0]
    return before, endpoint, {**body, "story_graph": snapshot}


@pytest.mark.parametrize("kind", ["folder", "document", "layout2"])
@pytest.mark.parametrize("batch", [False, True])
def test_undo_restores_exact_shared_routes_and_positions_atomically(graph_client, kind, batch):
    client = graph_client(kind)
    original, endpoint, body = _delete_for_exact_undo(client, batch)
    response = client.post(endpoint, json=body)
    assert response.status_code == 200, response.text
    restored = response.json()["story_graph"]
    assert restored == {**original, "revision": body["story_graph"]["revision"] + 1}
    assert client.post("/api/project/save").status_code == 200
    project = client.app.state.project
    reopened = project_manager.open_project(project.reopen_path)
    try:
        assert story_graph.get_graph(reopened) == restored
    finally:
        if reopened.metadata_root != project.metadata_root:
            project_manager.cleanup_document_working_root(reopened)


@pytest.mark.parametrize("batch", [False, True])
@pytest.mark.parametrize("damage", ["stale", "cycle", "disk"])
def test_failed_exact_undo_preserves_deleted_state(graph_client, monkeypatch, batch, damage):
    client = graph_client()
    _original, endpoint, body = _delete_for_exact_undo(client, batch)
    project = client.app.state.project
    before_graph = story_graph.get_graph(project)
    before_shots = [shot.to_dict() for shot in project.shots]
    before_disk = _disk(project)
    if damage == "stale":
        body["story_graph"]["revision"] -= 1
        expected_status = 409
    elif damage == "cycle":
        body["story_graph"]["routes"][1]["shot_ids"] = list(reversed(body["story_graph"]["routes"][0]["shot_ids"]))
        expected_status = 400
    else:
        original_save = project_manager.save_settings

        def fail(current):
            original_save(current)
            raise OSError("injected undo disk failure")

        monkeypatch.setattr(project_manager, "save_settings", fail)
        expected_status = 500
    response = client.post(endpoint, json=body)
    assert response.status_code == expected_status, response.text
    assert story_graph.get_graph(project) == before_graph
    assert [shot.to_dict() for shot in project.shots] == before_shots
    assert _disk(project) == before_disk


def test_plugin_auto_add_failure_keeps_graph_and_shots_consistent(graph_client, monkeypatch):
    client = graph_client()
    original = _persist_routes(client)
    project = client.app.state.project
    shots_before = [shot.to_dict() for shot in project.shots]
    disk_before = _disk(project)
    original_save = project_manager.save_settings

    def fail(current):
        original_save(current)
        raise OSError("injected plugin add failure")

    monkeypatch.setattr(project_manager, "save_settings", fail)
    with pytest.raises(OSError, match="injected plugin add failure"):
        StoryboardBackendService(client.app).method_plugin_next_shot(project.shots[-1].shot_id, True)
    assert [shot.to_dict() for shot in project.shots] == shots_before
    assert story_graph.get_graph(project) == original
    assert _disk(project) == disk_before


@pytest.mark.parametrize("custom_graph", [False, True])
def test_layout2_disk_refresh_keeps_portable_root_and_imported_artwork(graph_client, custom_graph):
    client = graph_client("layout2")
    if custom_graph:
        _persist_routes(client)
    project = client.app.state.project
    root = project.project_root
    shot_id = project.shots[0].shot_id
    artwork = io.BytesIO()
    image = Image.new("RGB", (16, 12), "white")
    image.putpixel((5, 5), (0, 0, 0))
    image.save(artwork, format="PNG")
    imported = client.post(f"/api/shots/{shot_id}/image", files={"file": ("sketch.png", artwork.getvalue(), "image/png")})
    assert imported.status_code == 200, imported.text
    assert client.post("/api/project/save").status_code == 200
    # Force the polling refresh path even on coarse filesystem timestamp clocks.
    client.app.state.project_disk_mtime = 0
    response = client.get("/api/project")
    assert response.status_code == 200, response.text
    refreshed = client.app.state.project
    assert refreshed.project_root == root
    assert refreshed.metadata_root == root / ".storyboarder" / "work"
    assert refreshed.document_path == project.document_path
    shot = next(item for item in response.json()["shots"] if item["shot_id"] == shot_id)
    assert shot["has_board_background"] is True
    assert shot["preview_disk_mtime"] > 0
    assert client.get(f"/api/shots/{shot_id}/image").status_code == 200
    assert client.post("/api/project/save").status_code == 200
    reopened = project_manager.open_project(refreshed.reopen_path)
    assert reopened.project_root == root
    assert story_graph.get_graph(reopened) == response.json()["story_graph"]
    assert project_manager.resolve_shot_preview_path(reopened, reopened.shots[0]).is_file()
