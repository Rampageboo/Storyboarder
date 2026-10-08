"""Comic acceptance: persistence, panel generation contracts, and actual PNG pixels."""
from __future__ import annotations

import copy
import io
import json
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from storyboard_tool import comic, generation_service, project_layout, project_manager, reference_segments, scene2d, shot_assets, story_graph
from storyboard_tool.project_layout import project_relative_posix
from storyboard_tool.api import create_app


def _lettering(**changes):
    value = {"id": "dialogue_1", "kind": "caption", "text": "", "x": 40, "y": 60,
             "width": 100, "height": 80, "font_size": 20, "vertical": False,
             "color": "#161616", "fill": "#00ff00", "border": 0, "tail": .25}
    value.update(changes)
    return value


@pytest.fixture
def comic_client(tmp_path, monkeypatch):
    monkeypatch.setattr(project_layout, "LAYOUT_2_ENABLED", True)
    clients = []
    projects = []

    def create(kind="folder", count=3):
        index = len(clients)
        app_dir = tmp_path / f"app-{index}"
        app_dir.mkdir()
        if kind == "layout2":
            project = project_manager.create_layout2_document(tmp_path / f"Comic-{index}.sbd", canvas_width=256, canvas_height=144)
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
            result = client.post("/api/shots", json={})
            assert result.status_code == 200, result.text
        return client

    yield create
    for client in clients:
        projects.append(client.app.state.project)
        client.close()
    for project in projects:
        project_manager.cleanup_document_working_root(project)


def _document(client):
    response = client.get("/api/project")
    assert response.status_code == 200, response.text
    return response.json()["comic_document"]


def _put(client, value, project_path=None):
    return client.put("/api/project/comic", json={
        "document": value,
        "project_path": project_path if project_path is not None else str(client.app.state.project.reopen_path),
    })


def _compose(client):
    doc = _document(client)
    ids = [shot.shot_id for shot in client.app.state.project.shots]
    doc.update(style_prompt="Ink and vivid color", reading_direction="rtl", chapters=[{
        "id": "chapter_1", "title": "Arrival", "prompt": "A coastal station",
    }])
    doc["pages"] = [
        {"id": "page", "chapter_id": "chapter_1", "title": "Page", "mode": "page", "width": 240, "height": 360,
         "prompt": "Quiet suspense", "panels": [{"id": "panel_1", "shot_id": ids[0], "x": 20, "y": 20, "width": 200, "height": 300}]},
        {"id": "spread", "chapter_id": "chapter_1", "title": "Spread", "mode": "spread", "width": 480, "height": 360,
         "panels": [{"id": "panel_2", "shot_id": ids[1], "x": 260, "y": 20, "width": 200, "height": 300}]},
        {"id": "scroll", "chapter_id": "chapter_1", "title": "Scroll", "mode": "scroll", "width": 240, "height": 1200,
         "panels": [{"id": "panel_3", "shot_id": ids[2], "x": 20, "y": 820, "width": 200, "height": 300}]},
    ]
    response = _put(client, doc)
    assert response.status_code == 200, response.text
    return response.json()["comic_document"]


def _disk(project):
    return {name: (project.metadata_root / name).read_bytes() for name in
            ("project.json", "settings.json", "shots.json", "shots.csv") if (project.metadata_root / name).is_file()}


@pytest.mark.parametrize("kind", ["folder", "document", "layout2"])
def test_legacy_empty_comic_read_does_not_mutate(comic_client, kind):
    client = comic_client(kind)
    project = client.app.state.project
    before, dirty = _disk(project), client.app.state.dirty
    assert _document(client) == comic.ComicDocument().model_dump()
    assert "comic_document" not in project.settings
    assert "comic_document" not in json.loads(project.settings_path.read_text(encoding="utf-8"))
    assert _disk(project) == before
    assert client.app.state.dirty == dirty


@pytest.mark.parametrize("kind", ["folder", "document", "layout2"])
def test_geometry_save_reopen_and_storyboard_preserved(comic_client, kind):
    client = comic_client(kind)
    project = client.app.state.project
    project.settings["custom_setting"] = {"keep": [1, 2]}
    shots = [shot.to_dict() for shot in project.shots]
    graph = story_graph.get_graph(project)
    accepted = _compose(client)
    assert client.post("/api/project/save").status_code == 200
    reopened = project_manager.open_project(project.reopen_path)
    try:
        assert comic.get_document(reopened) == accepted
        assert reopened.settings["custom_setting"] == {"keep": [1, 2]}
        assert [shot.to_dict() for shot in reopened.shots] == shots
        assert story_graph.get_graph(reopened) == graph
        for page, expected in zip(accepted["pages"], [(240, 360), (480, 360), (240, 1200)]):
            response = client.get(f"/api/project/comic/pages/{page['id']}/image")
            assert response.status_code == 200, response.text
            assert response.headers["content-type"] == "image/png"
            image = Image.open(io.BytesIO(response.content))
            assert image.size == expected
            panel = page["panels"][0]
            assert image.getpixel((panel["x"], panel["y"])) == (0, 0, 0)
            assert image.getpixel((0, 0)) == (255, 255, 255)
    finally:
        if reopened.metadata_root != project.metadata_root:
            project_manager.cleanup_document_working_root(reopened)


@pytest.mark.parametrize("damage", ["missing-shot", "missing-chapter", "duplicate-panel", "duplicate-placement", "out-of-page", "negative-position", "pixel-cap", "bad-fit", "bad-mode"])
def test_invalid_document_does_not_change_memory_or_disk(comic_client, damage):
    client = comic_client()
    original = _compose(client)
    value = copy.deepcopy(original)
    panel = value["pages"][0]["panels"][0]
    if damage == "missing-shot": panel["shot_id"] = "missing"
    elif damage == "missing-chapter": value["pages"][0]["chapter_id"] = "missing"
    elif damage == "duplicate-panel": value["pages"][1]["panels"][0]["id"] = panel["id"]
    elif damage == "duplicate-placement": value["pages"][1]["panels"][0]["shot_id"] = panel["shot_id"]
    elif damage == "out-of-page": panel["x"] = 230
    elif damage == "negative-position": panel["y"] = -1
    elif damage == "pixel-cap": value["pages"][0].update(width=8192, height=32000)
    elif damage == "bad-fit": panel["fit"] = "stretch"
    elif damage == "bad-mode": value["pages"][0]["mode"] = "unknown"
    before = _disk(client.app.state.project)
    response = _put(client, value)
    assert response.status_code == 400, response.text
    assert _document(client) == original
    assert _disk(client.app.state.project) == before


def test_revision_conflict_and_cross_project_write_are_rejected(comic_client):
    client = comic_client()
    original = _compose(client)
    before = _disk(client.app.state.project)
    stale = copy.deepcopy(original)
    stale["revision"] -= 1
    assert _put(client, stale).status_code == 409
    assert _put(client, original, "C:\\different-project").status_code == 409
    assert _put(client, original, "").status_code == 409
    assert _document(client) == original
    assert _disk(client.app.state.project) == before


def test_deleted_board_leaves_no_ghost_panel(comic_client):
    client = comic_client()
    original = _compose(client)
    shot_id = original["pages"][0]["panels"][0]["shot_id"]
    deleted = client.delete(f"/api/shots/{shot_id}")
    assert deleted.status_code == 200, deleted.text
    assert _document(client)["pages"][0]["panels"] == []
    assert client.get("/api/project/comic/pages/page/image").status_code == 200
    assert _put(client, original).status_code in (400, 409)


@pytest.mark.parametrize("mode", ["auto", "manual"])
def test_generation_inherits_comic_prompt_and_preserves_snapshot(comic_client, mode):
    client = comic_client()
    doc = _compose(client)
    shot_id = doc["pages"][0]["panels"][0]["shot_id"]
    result = client.patch(f"/api/shots/{shot_id}", json={
        "description": "Detective approaches the platform", "prompt_config": {
            "mode": mode, "manual_prompt": "Single character beneath a red umbrella",
            "prompt_extra": "Rain crosses the frame", "negative_prompt": "lettering, watermark",
        },
    })
    assert result.status_code == 200, result.text
    generated = client.post(f"/api/shots/{shot_id}/generation-requests", json={"destination": "queue"})
    assert generated.status_code == 200, generated.text
    request = generated.json()["request"]
    prompt = request["prompt"]
    for expected in ("Ink and vivid color", "A coastal station", "Quiet suspense", "rtl", "Rain crosses the frame"):
        assert expected in prompt["compiled_prompt"]
    assert prompt["mode"] == mode
    assert prompt["negative_prompt"] == "lettering, watermark"
    assert request["canvas"] == {"width": 200, "height": 300}
    assert request["output_contract"]["kind"] == "comic-panel-image"
    assert (request["output_contract"]["width"], request["output_contract"]["height"]) == (200, 300)
    assert prompt["aspect_ratio"] == "200:300"
    if mode == "manual": assert "Single character beneath a red umbrella" in prompt["compiled_prompt"]
    else: assert "Detective approaches the platform" in prompt["compiled_prompt"]
    snapshot = copy.deepcopy(request)
    changed = copy.deepcopy(doc)
    changed["style_prompt"] = "Watercolor"
    assert _put(client, changed).status_code == 200
    loaded = generation_service.get_request(client.app.state.project, request["request_id"])
    assert {key: loaded[key] for key in snapshot} == snapshot
    shot = next(s for s in client.app.state.project.shots if s.shot_id == shot_id)
    assert shot.generation_state["freshness_status"] == "stale"


def test_unplaced_storyboard_generation_keeps_existing_contract(comic_client):
    client = comic_client()
    _compose(client)
    added = client.post("/api/shots", json={})
    assert added.status_code == 200, added.text
    shot_id = added.json()["shot"]["shot_id"]
    generated = client.post(f"/api/shots/{shot_id}/generation-requests", json={"destination": "queue"})
    assert generated.status_code == 200, generated.text
    request = generated.json()["request"]
    assert request["output_contract"]["kind"] == "storyboard-image"
    assert request["canvas"] == {key: client.app.state.project.settings[f"canvas_{key}"] for key in ("width", "height")}
    assert "comic_context" not in request
    assert "COMIC PANEL" not in request["prompt"]["compiled_prompt"]


@pytest.mark.parametrize("kind", ["folder", "document", "layout2"])
def test_autosave_failure_rolls_back_comic_and_generated_shot_state(comic_client, monkeypatch, kind):
    client = comic_client(kind)
    original = _compose(client)
    project = client.app.state.project
    shot_id = original["pages"][0]["panels"][0]["shot_id"]
    assert client.post(f"/api/shots/{shot_id}/generation-requests", json={"destination": "queue"}).status_code == 200
    shots_before = [shot.to_dict() for shot in project.shots]
    before, revision = _disk(project), project.storage_revision
    dirty, mtime = client.app.state.dirty, client.app.state.project_disk_mtime
    real_save_settings = project_manager.save_settings

    def fail_after_write(current):
        real_save_settings(current)
        raise OSError("injected comic disk failure")

    monkeypatch.setattr(project_manager, "save_settings", fail_after_write)
    changed = copy.deepcopy(original)
    changed["style_prompt"] = "Must roll back"
    response = _put(client, changed)
    assert response.status_code == 500, response.text
    project = client.app.state.project
    assert comic.get_document(project) == original
    assert [shot.to_dict() for shot in project.shots] == shots_before
    assert _disk(project) == before
    assert project.storage_revision == revision
    assert client.app.state.dirty == dirty
    assert client.app.state.project_disk_mtime == mtime


@pytest.mark.parametrize("fit", ["contain", "cover"])
def test_render_uses_art_pixels_with_correct_fit(comic_client, tmp_path, monkeypatch, fit):
    client = comic_client()
    project = client.app.state.project
    doc = _compose(client)
    page = doc["pages"][0]
    page.update(width=120, height=120)
    page["panels"][0].update(x=10, y=10, width=100, height=100, fit=fit, border=0)
    assert _put(client, doc).status_code == 200
    art = Image.new("RGBA", (200, 100), "blue")
    art.paste("red", (0, 0, 50, 100))
    art.paste("green", (150, 0, 200, 100))
    art_path = tmp_path / "art.png"
    art.save(art_path)
    monkeypatch.setattr(shot_assets, "get_shot_board_background_path", lambda *_: None)
    monkeypatch.setattr(shot_assets, "get_shot_codex_layer_path", lambda *_: art_path)
    monkeypatch.setattr(project_manager, "resolve_shot_preview_path", lambda *_: None)
    image = Image.open(io.BytesIO(comic.render_page(project, "page")))
    assert image.size == (120, 120)
    assert image.getpixel((60, 60)) == (0, 0, 255)
    assert image.getpixel((0, 0)) == (255, 255, 255)
    if fit == "contain":
        assert image.getpixel((60, 15)) == (255, 255, 255)
        assert image.getpixel((15, 60)) == (255, 0, 0)
        assert image.getpixel((105, 60)) == (0, 128, 0)
    else:
        assert image.getpixel((60, 15)) == (0, 0, 255)
        assert image.getpixel((15, 60)) == (0, 0, 255)
        assert image.getpixel((105, 60)) == (0, 0, 255)


def test_export_composites_background_generated_layer_and_transparent_drawing(comic_client, tmp_path, monkeypatch):
    client = comic_client()
    _compose(client)
    paths = []
    for name, color in [("background", "red"), ("generated", (0, 0, 255, 128)), ("drawing", (0, 0, 0, 0))]:
        path = tmp_path / f"{name}.png"
        image = Image.new("RGBA", (200, 300), color)
        if name == "drawing": image.paste("green", (0, 0, 100, 300))
        image.save(path)
        paths.append(path)
    monkeypatch.setattr(shot_assets, "get_shot_board_background_path", lambda *_: paths[0])
    monkeypatch.setattr(shot_assets, "get_shot_codex_layer_path", lambda *_: paths[1])
    monkeypatch.setattr(project_manager, "resolve_shot_preview_path", lambda *_: paths[2])
    image = Image.open(io.BytesIO(comic.render_page(client.app.state.project, "page")))
    assert image.getpixel((50, 150)) == (0, 128, 0)
    assert image.getpixel((170, 150)) == (127, 0, 128)


def test_export_missing_page_returns_validation_error(comic_client):
    client = comic_client()
    assert client.get("/api/project/comic/pages/missing/image").status_code == 400


def test_accepted_generation_result_preserves_panel_dimensions_and_pixels(comic_client, tmp_path):
    client = comic_client()
    doc = _compose(client)
    project = client.app.state.project
    shot = project.shots[0]
    request = generation_service.create_request(project, shot, "codex")
    art = Image.new("RGB", (200, 300), "red")
    art.paste("blue", (50, 50, 150, 250))
    source = tmp_path / "portrait-result.png"
    art.save(source)
    result = generation_service.submit_result(project, request["request_id"], [str(source)])
    artifact = result["artifacts"][0]
    accepted = generation_service.accept_candidate_as_codex_layer(
        project, shot, request["request_id"], result["result_id"], artifact["project_relative_path"],
    )
    with Image.open(accepted) as layer:
        assert layer.size == (200, 300)
        assert layer.getpixel((10, 150))[:3] == (255, 0, 0)
    exported = Image.open(io.BytesIO(comic.render_page(project, doc["pages"][0]["id"])))
    assert exported.getpixel((30, 170)) == (255, 0, 0)
    assert exported.getpixel((120, 170)) == (0, 0, 255)


def test_result_from_before_comic_edit_remains_stale(comic_client, tmp_path):
    client = comic_client()
    original = _compose(client)
    project = client.app.state.project
    shot = project.shots[0]
    generated = client.post(f"/api/shots/{shot.shot_id}/generation-requests", json={"destination": "codex"})
    assert generated.status_code == 200, generated.text
    request = generated.json()["request"]
    changed = copy.deepcopy(original)
    changed["style_prompt"] = "A completely different painting style"
    assert _put(client, changed).status_code == 200
    source = tmp_path / "old-style-result.png"
    Image.new("RGB", (200, 300), "red").save(source)
    generation_service.submit_result(project, request["request_id"], [str(source)])
    generation_service.reconcile_results(project)
    assert shot.generation_state["freshness_status"] == "stale"
    generation_service.pull_results(project)
    assert shot.generation_state["freshness_status"] == "stale"


@pytest.mark.parametrize("kind", ["folder", "document", "layout2"])
def test_desktop_png_and_chapter_zip_export_have_real_pixels_and_ordered_manifest(comic_client, kind):
    client = comic_client(kind)
    doc = _compose(client)
    doc["pages"] = list(reversed(doc["pages"]))
    assert _put(client, doc).status_code == 200
    project = client.app.state.project
    identity = str(project.reopen_path)
    response = client.post("/api/project/comic/export", json={"project_path": identity, "page_id": "spread"})
    assert response.status_code == 200, response.text
    target = Path(response.json()["path"])
    assert target.parent == project.exports_dir
    assert target.name == "Comic_spread.png"
    with Image.open(target) as image:
        assert image.size == (480, 360)
        assert image.getpixel((260, 20)) == (0, 0, 0)
    response = client.post("/api/project/comic/export", json={"project_path": identity, "chapter_id": "chapter_1"})
    assert response.status_code == 200, response.text
    target = Path(response.json()["path"])
    assert target.parent == project.exports_dir
    assert target.name == "Comic_chapter_1.zip"
    with zipfile.ZipFile(target) as archive:
        assert archive.namelist() == ["001_scroll.png", "002_spread.png", "003_page.png", "comic-prompts.json"]
        for filename, size in [("001_scroll.png", (240, 1200)), ("002_spread.png", (480, 360)), ("003_page.png", (240, 360))]:
            assert Image.open(io.BytesIO(archive.read(filename))).size == size
        manifest = json.loads(archive.read("comic-prompts.json"))
        assert manifest["comic_document"] == _document(client)
        assert manifest["exported_chapter_id"] == "chapter_1"
        assert {shot["shot_id"] for shot in manifest["boards"]} == {shot.shot_id for shot in project.shots}
        assert all("prompt_config" in shot for shot in manifest["boards"])


@pytest.mark.parametrize("scope", ["page", "chapter"])
def test_failed_atomic_export_preserves_old_file_and_cleans_temporary(comic_client, monkeypatch, scope):
    client = comic_client()
    _compose(client)
    project = client.app.state.project
    body = {"project_path": str(project.reopen_path), "page_id" if scope == "page" else "chapter_id": "page" if scope == "page" else "chapter_1"}
    response = client.post("/api/project/comic/export", json=body)
    assert response.status_code == 200, response.text
    target = Path(response.json()["path"])
    previous = target.read_bytes()
    files = set(project.exports_dir.iterdir())
    monkeypatch.setattr(comic.os, "replace", lambda *_: (_ for _ in ()).throw(OSError("injected publish failure")))
    failed = client.post("/api/project/comic/export", json=body)
    assert failed.status_code == 400, failed.text
    assert target.read_bytes() == previous
    assert set(project.exports_dir.iterdir()) == files


@pytest.mark.parametrize("body", [
    {"page_id": "../escaped"}, {"chapter_id": "../../escaped"}, {"page_id": "page", "chapter_id": "chapter_1"}, {},
])
def test_export_cannot_escape_exports_or_accept_ambiguous_scope(comic_client, body):
    client = comic_client()
    _compose(client)
    project = client.app.state.project
    body = {**body, "project_path": str(project.reopen_path)}
    assert client.post("/api/project/comic/export", json=body).status_code == 400
    assert not project.exports_dir.exists() or not list(project.exports_dir.iterdir())


def test_export_and_open_check_project_identity_and_open_does_not_regenerate(comic_client, monkeypatch):
    client = comic_client()
    _compose(client)
    project = client.app.state.project
    body = {"project_path": str(project.reopen_path), "page_id": "page"}
    assert client.post("/api/project/comic/export", json={**body, "project_path": "other"}).status_code == 409
    assert client.post("/api/project/comic/export/open", json={**body, "project_path": "other"}).status_code == 409
    assert client.post("/api/project/comic/export/open", json=body).status_code == 400
    response = client.post("/api/project/comic/export", json=body)
    assert response.status_code == 200, response.text
    target = Path(response.json()["path"])
    previous = target.read_bytes()
    opened = []
    monkeypatch.setattr("storyboard_tool.backend_service.os.startfile", lambda path: opened.append(Path(path)))
    monkeypatch.setattr(comic, "render_page", lambda *_: (_ for _ in ()).throw(AssertionError("Open must not regenerate")))
    result = client.post("/api/project/comic/export/open", json=body)
    assert result.status_code == 200, result.text
    assert opened == [target]
    assert target.read_bytes() == previous


@pytest.mark.parametrize("kind", ["folder", "document", "layout2"])
def test_prompt_preview_is_read_only_and_contains_manual_negative_and_geometry(comic_client, kind):
    client = comic_client(kind)
    _compose(client)
    project = client.app.state.project
    shot = project.shots[0]
    updated = client.patch(f"/api/shots/{shot.shot_id}", json={"prompt_config": {
        "mode": "manual", "manual_prompt": "Umbrella in the rain", "negative_prompt": "lettering",
    }})
    assert updated.status_code == 200, updated.text
    before = _disk(project)
    files = {path for path in project.metadata_root.rglob("*") if path.is_file()}
    state = [shot.to_dict() for shot in project.shots]
    dirty = client.app.state.dirty
    for _ in range(2):
        response = client.get(f"/api/project/comic/prompts/{shot.shot_id}")
        assert response.status_code == 200, response.text
        snapshot = response.json()
        assert snapshot["output_contract"]["kind"] == "comic-panel-image"
        assert snapshot["canvas"] == {"width": 200, "height": 300}
        assert "Umbrella in the rain" in snapshot["prompt"]["compiled_prompt"]
        assert snapshot["prompt"]["negative_prompt"] == "lettering"
    assert generation_service.list_requests(project) == []
    assert _disk(project) == before
    assert {path for path in project.metadata_root.rglob("*") if path.is_file()} == files
    assert [shot.to_dict() for shot in project.shots] == state
    assert client.app.state.dirty == dirty


@pytest.mark.parametrize("kind", ["folder", "document", "layout2"])
def test_prompt_preview_with_linked_scene_includes_context_without_changing_files(comic_client, kind):
    client = comic_client(kind)
    _compose(client)
    project = client.app.state.project
    scene, _ = scene2d.create_scene(project, title="Station", environment_prompt="Wet brick platform", consistency_anchors=["Clock above doorway"])
    shot = project.shots[0]
    shot.scene_id = scene["id"]
    project_manager.save_project(project)
    before = {path: path.read_bytes() for path in project.metadata_root.rglob("*") if path.is_file()}
    response = client.get(f"/api/project/comic/prompts/{shot.shot_id}")
    assert response.status_code == 200, response.text
    request = response.json()
    assert request["scene_context"]["id"] == scene["id"]
    assert "Wet brick platform" in request["prompt"]["compiled_prompt"]
    assert "Clock above doorway" in request["prompt"]["compiled_prompt"]
    assert {path: path.read_bytes() for path in project.metadata_root.rglob("*") if path.is_file()} == before
    assert generation_service.list_requests(project) == []


@pytest.mark.parametrize("kind", ["folder", "document", "layout2"])
def test_panel_psd_and_reference_background_use_panel_canvas(comic_client, tmp_path, kind):
    client = comic_client(kind)
    _compose(client)
    project = client.app.state.project
    shot = project.shots[0]
    psd = project_manager.create_canvas_for_shot(project, shot, width=900, height=600)
    with Image.open(psd) as image:
        assert image.size == (200, 300)
    source = project.project_root / "comic-reference.png"
    Image.new("RGB", (400, 200), "red").save(source)
    project.settings["ref_segments"] = [{
        "id": "comic_ref", "anchor_shot_id": shot.shot_id, "end_shot_id": shot.shot_id,
        "source_type": "image", "reference_path": project_relative_posix(project, source),
        "reference_id": "", "video_start": 0.0, "fit_mode": "fit",
    }]
    reference_segments.apply_ref_segment_image_to_boards(project, 0, 0, segment_id="comic_ref")
    background = shot_assets.get_shot_board_background_path(project, shot)
    assert background is not None
    with Image.open(background) as image:
        assert image.size == (200, 300)
        assert image.getpixel((100, 150))[:3] == (255, 0, 0)
    assert generation_service.build_request_snapshot(project, shot, "queue", read_only=True)["canvas"] == {"width": 200, "height": 300}


def test_export_fits_mixed_aspect_layers_independently(comic_client, tmp_path, monkeypatch):
    client = comic_client()
    doc = _compose(client)
    doc["pages"][0].update(width=120, height=120)
    doc["pages"][0]["panels"][0].update(x=10, y=10, width=100, height=100, fit="contain", border=0)
    assert _put(client, doc).status_code == 200
    background = tmp_path / "landscape-background.png"
    generated = tmp_path / "portrait-generated.png"
    drawing = tmp_path / "square-drawing.png"
    Image.new("RGBA", (200, 100), "red").save(background)
    Image.new("RGBA", (100, 200), "blue").save(generated)
    art = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
    art.paste("green", (160, 160, 190, 190))
    art.save(drawing)
    monkeypatch.setattr(shot_assets, "get_shot_board_background_path", lambda *_: background)
    monkeypatch.setattr(shot_assets, "get_shot_codex_layer_path", lambda *_: generated)
    monkeypatch.setattr(project_manager, "resolve_shot_preview_path", lambda *_: drawing)
    image = Image.open(io.BytesIO(comic.render_page(client.app.state.project, "page")))
    assert image.getpixel((15, 15)) == (255, 255, 255)
    assert image.getpixel((15, 60)) == (255, 0, 0)
    assert image.getpixel((60, 15)) == (0, 0, 255)
    assert image.getpixel((95, 95)) == (0, 128, 0)


def test_chapter_zip_contains_only_the_selected_chapter_and_boards(comic_client):
    client = comic_client(count=4)
    doc = _compose(client)
    project = client.app.state.project
    doc["chapters"].append({"id": "chapter_other", "title": "Other chapter", "prompt": "Other context"})
    doc["pages"].append({"id": "other_page", "chapter_id": "chapter_other", "title": "Other page", "mode": "page", "width": 240, "height": 360,
                         "panels": [{"id": "other_panel", "shot_id": project.shots[3].shot_id, "x": 20, "y": 20, "width": 200, "height": 300}]})
    assert _put(client, doc).status_code == 200
    result = client.post("/api/project/comic/export", json={"project_path": str(project.reopen_path), "chapter_id": "chapter_1"})
    assert result.status_code == 200, result.text
    with zipfile.ZipFile(result.json()["path"]) as archive:
        assert archive.namelist() == ["001_page.png", "002_spread.png", "003_scroll.png", "comic-prompts.json"]
        manifest = json.loads(archive.read("comic-prompts.json"))
        assert [chapter["id"] for chapter in manifest["comic_document"]["chapters"]] == ["chapter_1"]
        assert [page["id"] for page in manifest["comic_document"]["pages"]] == ["page", "spread", "scroll"]
        assert {board["shot_id"] for board in manifest["boards"]} == {shot.shot_id for shot in project.shots[:3]}


@pytest.mark.parametrize("kind", ["folder", "document", "layout2"])
def test_manual_shape_crop_lock_lettering_roundtrip(comic_client, kind):
    client = comic_client(kind)
    doc = _compose(client)
    doc["pages"][0].update(background="#abcdef", safe_margin=17, lettering=[_lettering(text="中文\nABC", vertical=True)])
    doc["pages"][0]["panels"][0].update(points=[[0, 0], [1, 0], [.6, 1], [0, 1]],
                                            locked=True, image_scale=1.75, image_x=-.25, image_y=.125)
    accepted = _put(client, doc)
    assert accepted.status_code == 200, accepted.text
    assert client.post("/api/project/save").status_code == 200
    project = client.app.state.project
    reopened = project_manager.open_project(project.reopen_path)
    try:
        assert json.loads(json.dumps(comic.get_document(reopened))) == accepted.json()["comic_document"]
    finally:
        if reopened.metadata_root != project.metadata_root:
            project_manager.cleanup_document_working_root(reopened)


@pytest.mark.parametrize("damage", ["outside-point", "concave", "crossing", "tiny-area", "too-many-points",
                                     "crop-scale", "crop-offset", "bad-background", "bad-lettering-color",
                                     "lettering-outside", "duplicate-lettering", "bad-tail", "safe-margin"])
def test_manual_invalid_geometry_never_writes(comic_client, damage):
    client = comic_client()
    original = _compose(client)
    changed = copy.deepcopy(original)
    page, panel = changed["pages"][0], changed["pages"][0]["panels"][0]
    page["lettering"] = [_lettering()]
    if damage == "outside-point": panel["points"] = [[0, 0], [1.1, 0], [0, 1]]
    elif damage == "concave": panel["points"] = [[0, 0], [1, 0], [.25, .25], [1, 1], [0, 1]]
    elif damage == "crossing": panel["points"] = [[0, 0], [1, 1], [1, 0], [0, 1]]
    elif damage == "tiny-area": panel["points"] = [[0, 0], [.1, 0], [0, .1]]
    elif damage == "too-many-points": panel["points"] = [[0, 0]] * 9
    elif damage == "crop-scale": panel["image_scale"] = 0
    elif damage == "crop-offset": panel["image_x"] = 2.01
    elif damage == "bad-background": page["background"] = "rgba(1,2,3,0)"
    elif damage == "bad-lettering-color": page["lettering"][0]["color"] = "red"
    elif damage == "lettering-outside": page["lettering"][0]["x"] = 200
    elif damage == "duplicate-lettering": page["lettering"].append(copy.deepcopy(page["lettering"][0]))
    elif damage == "bad-tail": page["lettering"][0]["tail"] = -1
    elif damage == "safe-margin": page["safe_margin"] = 513
    before, dirty = _disk(client.app.state.project), client.app.state.dirty
    response = _put(client, changed)
    assert response.status_code == 400, response.text
    assert _document(client) == original
    assert _disk(client.app.state.project) == before
    assert client.app.state.dirty == dirty


def test_polygon_mask_crop_and_lettering_stack_actual_pixels(comic_client, monkeypatch, tmp_path):
    client = comic_client()
    doc = _compose(client)
    page = doc["pages"][0]
    page.update(background="#123456", lettering=[_lettering(x=60, y=60, width=40, height=40)])
    panel = page["panels"][0]
    panel.update(x=20, y=20, width=200, height=200, border=0,
                 points=[[0, 0], [1, 0], [0, 1]], image_scale=1, image_x=0, image_y=0)
    assert _put(client, doc).status_code == 200
    source = tmp_path / "crop-source.png"
    artwork = Image.new("RGBA", (200, 200), "red")
    artwork.paste("blue", (100, 0, 200, 200))
    artwork.save(source)
    monkeypatch.setattr(shot_assets, "get_shot_board_background_path", lambda *_: None)
    monkeypatch.setattr(shot_assets, "get_shot_codex_layer_path", lambda *_: source)
    monkeypatch.setattr(project_manager, "resolve_shot_preview_path", lambda *_: None)
    image = Image.open(io.BytesIO(comic.render_page(client.app.state.project, "page")))
    assert image.getpixel((25, 25)) == (255, 0, 0)
    assert image.getpixel((150, 30)) == (0, 0, 255)
    assert image.getpixel((200, 200)) == (18, 52, 86), "outside polygon must preserve page color"
    assert image.getpixel((80, 80)) == (0, 255, 0), "lettering must composite above panel artwork"
    changed = _document(client)
    changed["pages"][0]["panels"][0].update(image_scale=2, image_x=.25)
    assert _put(client, changed).status_code == 200
    cropped = Image.open(io.BytesIO(comic.render_page(client.app.state.project, "page")))
    assert cropped.getpixel((150, 30)) == (255, 0, 0), "image crop translation must apply after fitting"
    assert cropped.getpixel((200, 200)) == (18, 52, 86)


@pytest.mark.parametrize("vertical,text", [(False, "站台对话ABC\n下一行"), (True, "竖排对话\n😀AB"), (False, "")])
def test_lettering_wrapping_and_rendering_do_not_overflow_comic_rect(vertical, text):
    from storyboard_tool.comic_lettering import lettering_lines, paint_lettering
    item = _lettering(text=text, vertical=vertical, x=10, y=10, width=80, height=96, kind="text")
    canvas = Image.new("RGB", (120, 140), "magenta")
    paint_lettering(canvas, item)
    for y in range(canvas.height):
        for x in range(canvas.width):
            if not (18 <= x < 82 and 18 <= y < 98):
                assert canvas.getpixel((x, y)) == (255, 0, 255)
    assert len(lettering_lines(item)) >= len(text.split("\n"))
    if text:
        assert any(canvas.getpixel((x, y)) != (255, 0, 255) for y in range(canvas.height) for x in range(canvas.width))


def test_speech_tail_and_caption_body_actual_pixels():
    from storyboard_tool.comic_lettering import paint_lettering
    canvas = Image.new("RGB", (240, 200), "magenta")
    paint_lettering(canvas, _lettering(kind="speech", x=10, y=10, width=100, height=100, tail=.25))
    assert canvas.getpixel((60, 40)) == (0, 255, 0)
    assert canvas.getpixel((39, 104)) == (0, 255, 0), "speech tail must be visible below body"
    assert canvas.getpixel((100, 104)) == (255, 0, 255)
    paint_lettering(canvas, _lettering(x=120, y=10, width=60, height=60))
    assert canvas.getpixel((120, 10)) == (0, 255, 0)
    assert canvas.getpixel((179, 69)) == (0, 255, 0)


@pytest.mark.parametrize("field", ["points", "image_scale", "image_x", "image_y"])
def test_nonfinite_comic_geometry_rejected_without_write(comic_client, field):
    client = comic_client()
    original = _compose(client)
    changed = copy.deepcopy(original)
    changed["pages"][0]["panels"][0][field] = [[0, 0], [float("nan"), 0], [0, 1]] if field == "points" else float("nan")
    before = _disk(client.app.state.project)
    body = {"document": changed, "project_path": str(client.app.state.project.reopen_path)}
    # Deliberately bypass HTTPX's strict JSON encoder to exercise server validation.
    result = client.put("/api/project/comic", content=json.dumps(body), headers={"Content-Type": "application/json"})
    assert result.status_code == 400, result.text
    assert _document(client) == original
    assert _disk(client.app.state.project) == before


@pytest.mark.parametrize("kind", ["speech", "caption", "text"])
def test_minimum_lettering_box_clips_large_font_without_render_error(kind):
    from storyboard_tool.comic_lettering import paint_lettering
    canvas = Image.new("RGB", (40, 40), "magenta")
    paint_lettering(canvas, _lettering(kind=kind, x=10, y=10, width=16, height=16, font_size=160, text="中文ABC"))
    assert canvas.getpixel((0, 0)) == (255, 0, 255)
    assert canvas.getpixel((26, 26)) == (255, 0, 255)


def _pdf_embedded_images(content):
    """Read ReportLab's lossless RGB image streams with only standard libraries."""
    import base64
    import re
    import zlib
    images = []
    for match in re.finditer(rb"\d+ 0 obj\s*(.*?)\s*endobj", content, re.S):
        body = match.group(1)
        if b"/Subtype /Image" not in body:
            continue
        header, stream = body.split(b"stream\n", 1)
        encoded = stream.rsplit(b"endstream", 1)[0].strip()
        assert b"/ASCII85Decode" in header and b"/FlateDecode" in header
        pixels = zlib.decompress(base64.a85decode(encoded, adobe=True))
        width = int(re.search(rb"/Width (\d+)", header).group(1))
        height = int(re.search(rb"/Height (\d+)", header).group(1))
        assert b"/DeviceRGB" in header
        images.append(Image.frombytes("RGB", (width, height), pixels))
    return images


def test_cbz_contains_only_sorted_png_with_exact_comic_pixels(comic_client):
    client = comic_client()
    doc = _compose(client)
    doc["pages"][0].update(background="#123456", lettering=[_lettering()])
    assert _put(client, doc).status_code == 200
    project = client.app.state.project
    result = client.post("/api/project/comic/export", json={"project_path": str(project.reopen_path), "chapter_id": "chapter_1", "format": "cbz"})
    assert result.status_code == 200, result.text
    assert Path(result.json()["path"]).suffix == ".cbz"
    with zipfile.ZipFile(result.json()["path"]) as archive:
        assert archive.namelist() == ["001_page.png", "002_spread.png", "003_scroll.png"]
        for name, page in zip(archive.namelist(), _document(client)["pages"]):
            assert archive.read(name) == comic.render_page(project, page["id"])
        image = Image.open(io.BytesIO(archive.read("001_page.png")))
        assert image.getpixel((0, 0)) == (18, 52, 86)
        assert image.getpixel((80, 80)) == (0, 255, 0)


def test_pdf_page_sizes_and_embedded_lossless_pixels(comic_client):
    import re
    client = comic_client()
    _compose(client)
    project = client.app.state.project
    result = client.post("/api/project/comic/export", json={"project_path": str(project.reopen_path), "chapter_id": "chapter_1", "format": "pdf"})
    assert result.status_code == 200, result.text
    content = Path(result.json()["path"]).read_bytes()
    assert content.startswith(b"%PDF-")
    assert len(re.findall(rb"/Type /Page\b", content)) == 3
    media = re.findall(rb"/MediaBox \[ ([^\]]+) \]", content)
    assert [[float(n) for n in box.split()] for box in media] == [[0, 0, 180, 270], [0, 0, 360, 270], [0, 0, 180, 900]]
    images = _pdf_embedded_images(content)
    assert len(images) == 3
    for image, page in zip(images, _document(client)["pages"]):
        expected = Image.open(io.BytesIO(comic.render_page(project, page["id"])))
        assert image.size == expected.size
        assert image.tobytes() == expected.tobytes(), "PDF must embed the exact composited page without aspect distortion"


def test_long_scroll_pdf_preserves_aspect_and_caps_page_points(comic_client):
    import re
    client = comic_client()
    doc = _compose(client)
    doc["pages"][2].update(width=64, height=32000, panels=[], background="#123456")
    assert _put(client, doc).status_code == 200
    project = client.app.state.project
    result = client.post("/api/project/comic/export", json={"project_path": str(project.reopen_path), "page_id": "scroll", "format": "pdf"})
    assert result.status_code == 200, result.text
    content = Path(result.json()["path"]).read_bytes()
    box = [float(n) for n in re.search(rb"/MediaBox \[ ([^\]]+) \]", content).group(1).split()]
    assert box == [0, 0, 28.8, 14400]
    assert box[2] / box[3] == pytest.approx(64 / 32000)
    assert _pdf_embedded_images(content)[0].size == (64, 32000)


@pytest.mark.parametrize("format", ["pdf", "cbz"])
def test_new_comic_export_atomic_failure_preserves_old_file(comic_client, monkeypatch, format):
    client = comic_client()
    _compose(client)
    project = client.app.state.project
    target = comic.export_comic(project, chapter_id="chapter_1", format=format)
    before = target.read_bytes()
    files = set(target.parent.iterdir())
    monkeypatch.setattr(comic.os, "replace", lambda *_: (_ for _ in ()).throw(OSError("injected final export failure")))
    with pytest.raises(OSError):
        comic.export_comic(project, chapter_id="chapter_1", format=format)
    assert target.read_bytes() == before
    assert set(target.parent.iterdir()) == files


@pytest.mark.parametrize("scope,format", [("page", "cbz"), ("page", "zip"), ("chapter", "png"), ("chapter", "../../outside"), ("chapter", "PDF")])
def test_invalid_comic_export_format_does_not_overwrite(comic_client, scope, format):
    client = comic_client()
    _compose(client)
    project = client.app.state.project
    target = comic.export_comic(project, chapter_id="chapter_1", format="cbz")
    before = target.read_bytes()
    files = set(target.parent.iterdir())
    result = client.post("/api/project/comic/export", json={"project_path": str(project.reopen_path),
        "page_id" if scope == "page" else "chapter_id": "page" if scope == "page" else "chapter_1", "format": format})
    assert result.status_code == 400, result.text
    assert target.read_bytes() == before
    assert set(target.parent.iterdir()) == files
