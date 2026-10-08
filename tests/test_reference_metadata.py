"""Reference-library compatibility and the storage/workflow import boundary."""
from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from storyboard_tool import reference_metadata


def test_normalization_preserves_local_links_and_scene_provenance():
    raw = [
        None,
        {"id": "remote", "url": "HTTPS://example.com/reference.png"},
        {"id": "empty", "path": "  "},
        {"id": "image", "path": " Images\\ref.png ", "title": " Ref "},
        {"id": "image", "path": "Images/model.GLB", "type": "unknown"},
        {"id": "scene", "path": "Images/scene.png", "type": "scene2d",
         "source_scene2d_id": " scene-a ", "source_scene2d_perspective_id": " view-a "},
        {"id": "video", "url": "Images/ref.MP4"},
    ]
    before = copy.deepcopy(raw)
    links = reference_metadata.normalize_reference_links(raw)
    assert raw == before
    assert links[0] == {"id": "image", "title": "Ref", "type": "image", "path": "Images/ref.png"}
    assert links[1]["type"] == "model"
    assert links[1]["title"] == "model.GLB"
    assert links[1]["id"] != "image"
    assert links[2] == {
        "id": "scene", "title": "scene.png", "type": "scene2d", "path": "Images/scene.png",
        "source_scene2d_id": "scene-a", "source_scene2d_perspective_id": "view-a",
    }
    assert links[3] == {"id": "video", "title": "ref.MP4", "type": "video", "path": "Images/ref.MP4"}
    assert len({link["id"] for link in links}) == len(links)
    assert reference_metadata.normalize_reference_links(links) == links


def test_legacy_library_migration_is_idempotent_and_keeps_authored_data():
    settings = {
        "reference_links": [{"id": "existing", "path": "Images/model.glb", "type": "image"}],
        "reference_video_path": "Images\\video.mp4",
        "reference_model_path": "Images/model.glb",
        "reference_image_path": "Images/picture.png",
        "scene3d": {"file_path": "Blender/scene.glb"},
        "story_graph": {"revision": 8, "routes": [{"id": "route"}]},
        "comic_document": {"revision": 3, "pages": [{"id": "page"}]},
    }
    before = copy.deepcopy(settings)
    reference_metadata.ensure_reference_library(settings)
    links = settings["reference_links"]
    assert [(link["path"], link["type"]) for link in links] == [
        ("Images/picture.png", "image"), ("Images/video.mp4", "video"),
        ("Images/model.glb", "model"), ("Blender/scene.glb", "model"),
    ]
    assert links[2]["id"] == "existing"
    assert settings["story_graph"] == before["story_graph"]
    assert settings["comic_document"] == before["comic_document"]
    normalized = copy.deepcopy(settings)
    reference_metadata.ensure_reference_library(settings)
    assert settings == normalized


def test_settings_load_normalizes_without_rewriting_file(tmp_path):
    from storyboard_tool.project_storage import load_settings

    path = tmp_path / "settings.json"
    stored = {"reference_links": [{"id": "a", "path": "Images\\a.png"}],
              "character_bible_prompt": "Keep this prompt", "custom_setting": {"keep": True}}
    text = json.dumps(stored)
    path.write_text(text, encoding="utf-8")
    result = load_settings(SimpleNamespace(settings_path=path))
    assert result["reference_links"] == [
        {"id": "a", "path": "Images/a.png", "title": "a.png", "type": "image"},
    ]
    assert result["character_bible_prompt"] == stored["character_bible_prompt"]
    assert result["custom_setting"] == stored["custom_setting"]
    assert result["canvas_width"] == 1920
    assert path.read_text(encoding="utf-8") == text


def test_storage_load_does_not_import_workflow_modules(tmp_path):
    """A fresh interpreter must load real settings without the former cycle."""
    path = tmp_path / "settings.json"
    path.write_text('{"reference_video_path": "Images/video.mp4"}', encoding="utf-8")
    script = """
import importlib.abc
import sys
from pathlib import Path
from types import SimpleNamespace

class RejectWorkflowImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in {
            'storyboard_tool.project_manager', 'storyboard_tool.reference_segments',
            'storyboard_tool.backend_service', 'storyboard_tool.scene2d',
            'storyboard_tool.scene3d', 'storyboard_tool.image_utils',
        }:
            raise AssertionError('Storage imported workflow: ' + fullname)

sys.meta_path.insert(0, RejectWorkflowImports())
from storyboard_tool.project_storage import load_settings
settings = load_settings(SimpleNamespace(settings_path=Path(sys.argv[1])))
assert settings['reference_links'][0]['path'] == 'Images/video.mp4'
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(path)],
        cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_existing_reference_facades_keep_the_same_functions():
    from storyboard_tool import project_manager, reference_segments

    for name in ("normalize_reference_links", "ensure_reference_library", "reference_media_type"):
        assert getattr(project_manager, name) is getattr(reference_metadata, name)
        assert getattr(reference_segments, name) is getattr(reference_metadata, name)
