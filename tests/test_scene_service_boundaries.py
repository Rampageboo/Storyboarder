"""Facade contracts for scene adapters extracted into domain owners."""
from __future__ import annotations

import inspect
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from storyboard_tool import app_state, backend_service, blender_bridge, scene2d, scene3d, upload_payload
from storyboard_tool.backend_service import StoryboardBackendService
from storyboard_tool.models import Project
from storyboard_tool.service_exports import ExportServiceMixin
from storyboard_tool.service_scene3d import Scene3DServiceMixin


SIGNATURES = json.loads(
    (Path(__file__).parent / "fixtures/scene_service_signatures.json").read_text(encoding="utf-8")
)


def _service(project=None):
    app = SimpleNamespace(state=SimpleNamespace(project=project, dirty=False))
    return StoryboardBackendService(app)


@pytest.mark.parametrize("name,signature", SIGNATURES.items())
def test_scene_public_signatures_remain_compatible(name, signature):
    # Captured from the original facade before extraction; includes defaults,
    # positional/keyword shape and annotations used by API/bridge callers.
    assert str(inspect.signature(getattr(StoryboardBackendService, name))) == signature


def test_scene3d_file_has_one_owner():
    owners = [owner for owner in StoryboardBackendService.__mro__ if "method_get_scene3d_file" in vars(owner)]
    assert owners == [Scene3DServiceMixin]
    assert not hasattr(ExportServiceMixin, "method_get_scene3d_file")


@pytest.mark.parametrize("arguments,selected_id", [([], None), (["chosen-scene"], "chosen-scene")])
def test_facade_file_dispatch_preserves_optional_scene_selection(tmp_path, monkeypatch, arguments, selected_id):
    project = Project(root_path=tmp_path)
    service = _service(project)
    file_path = tmp_path / "selected.glb"
    seen = []

    def find_file(current_project, scene_id):
        seen.append((current_project, scene_id))
        return file_path

    monkeypatch.setattr(scene3d, "file_path", find_file)
    assert service.call("get_scene3d_file", arguments) == {
        "path": str(file_path), "media_type": "model/gltf-binary", "filename": "selected.glb",
    }
    assert seen == [(project, selected_id)]


@pytest.mark.parametrize("error,status", [(FileNotFoundError("missing"), 404), (ValueError("invalid"), 400)])
def test_facade_scene3d_file_errors_keep_status_and_detail(tmp_path, monkeypatch, error, status):
    def fail(*args):
        raise error

    monkeypatch.setattr(scene3d, "file_path", fail)
    with pytest.raises(HTTPException) as raised:
        _service(Project(root_path=tmp_path)).call("get_scene3d_file", ["scene-id"])
    assert raised.value.status_code == status
    assert raised.value.detail == str(error)


def test_facade_scene_lists_keep_distinct_payloads(tmp_path, monkeypatch):
    project = Project(root_path=tmp_path)
    service = _service(project)
    scenes2d = [{"id": "2d"}]
    scenes3d = {"scenes": [{"id": "3d"}], "active_scene_id": "3d"}
    monkeypatch.setattr(scene2d, "list_scenes", lambda current: scenes2d if current is project else None)
    monkeypatch.setattr(scene3d, "list_scenes", lambda current: scenes3d if current is project else None)
    assert service.call("list_scene2d") == {"scenes": scenes2d}
    assert service.call("list_scene3d") is scenes3d


@pytest.mark.parametrize("operation", ["scene2d_export_preview", "scene2d_psd_saved", "scene2d_next_perspective"])
def test_scene_plugin_dispatch_keeps_shared_factory_and_protocol(monkeypatch, operation):
    service = _service()
    protocol = {"project_session_id": "active", "context_revision": 3}
    expected = {"ok": True}
    calls = []

    def plugin_operation(*args):
        calls.append(args)
        return expected

    plugin = SimpleNamespace(**{operation: plugin_operation})
    monkeypatch.setattr(service, "_plugin_service", lambda: plugin)
    assert service.call(f"plugin_{operation}", ["scene", "perspective", protocol]) is expected
    assert calls == [("scene", "perspective", protocol)]


def test_facade_scene2d_import_keeps_upload_and_optional_arguments(tmp_path, monkeypatch):
    project = Project(root_path=tmp_path)
    service = _service(project)
    calls = []
    scene, perspective, scenes = {"id": "scene"}, {"id": "perspective"}, [{"id": "scene"}]

    def import_perspective(*args, **kwargs):
        calls.append((args, kwargs))
        return scene, perspective, scenes

    monkeypatch.setattr(scene2d, "import_perspective", import_perspective)
    monkeypatch.setattr(app_state, "persist_project_mutation", lambda app: calls.append(("persist", app)))
    result = service.call("import_scene2d_perspective", ["scene", "", [256, -1, "2"], "Title", "linked-3d"])
    assert result == {"scene": scene, "perspective": perspective, "scenes": scenes}
    assert calls == [
        ((project, "scene", "perspective", b"\x00\xff\x02"), {"title": "Title", "linked_scene3d_id": "linked-3d"}),
        ("persist", service.app),
    ]


def test_facade_active_scene3d_import_keeps_release_persist_and_bridge_order(tmp_path, monkeypatch):
    project = Project(root_path=tmp_path, settings={"scene3d": {"source": "active"}})
    service = _service(project)
    calls = []
    scene_payload = {"scenes": [{"id": "active"}]}

    def import_scene(*args):
        calls.append(("import", *args))
        return scene_payload

    monkeypatch.setattr(blender_bridge, "require_released", lambda app, action: calls.append(("release", app, action)))
    monkeypatch.setattr(scene3d, "import_active_scene_file", import_scene)
    monkeypatch.setattr(app_state, "persist_project_mutation", lambda app: calls.append(("persist", app)))
    monkeypatch.setattr(app_state, "_touch_live_bridge", lambda app: calls.append(("bridge", app)))
    monkeypatch.setattr(app_state, "_project_payload", lambda current, dirty: {"project_marker": "kept", "dirty": dirty})
    result = service.call("import_scene3d", ["", bytearray(b"glb")])
    assert result == {"scene3d": {"source": "active"}, "scenes3d": scene_payload, "project_marker": "kept", "dirty": False}
    assert calls == [
        ("release", service.app, "replacing the active Scene 3D asset"),
        ("import", project, "scene.glb", b"glb"),
        ("persist", service.app),
        ("bridge", service.app),
    ]


@pytest.mark.parametrize("payload,expected", [
    (b"bytes", b"bytes"),
    (bytearray(b"array"), b"array"),
    ([0, 255, 256, -1, "2"], b"\x00\xff\x00\xff\x02"),
])
def test_upload_helpers_preserve_conversion_and_historical_imports(payload, expected):
    assert backend_service._normalize_upload_bytes is upload_payload.normalize_upload_bytes
    assert backend_service._upload_stream is upload_payload.upload_stream
    assert backend_service._normalize_upload_bytes(payload) == expected
    stream = backend_service._upload_stream(payload)
    assert stream.read() == expected
    stream.seek(0)
    assert stream.read() == expected


@pytest.mark.parametrize("helper", [upload_payload.normalize_upload_bytes, upload_payload.upload_stream])
def test_upload_helpers_reject_unsupported_payloads_with_existing_error(helper):
    with pytest.raises(HTTPException) as raised:
        helper((1, 2))
    assert raised.value.status_code == 400
    assert raised.value.detail == "Upload payload must be bytes."
