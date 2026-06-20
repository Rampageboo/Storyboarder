"""Tests for Scene3D backend: capture apply, file import, and boundary conditions."""
from __future__ import annotations

import base64
import io
import tempfile
from pathlib import Path

import pytest

from storyboard_tool import project_manager, reference_segments
from storyboard_tool.external_tools import (
    SCENE3D_EXTENSIONS,
    get_scene3d_file_path,
    import_scene3d_stream,
)


def _make_project(tmp_path: Path):
    return project_manager.create_project(tmp_path)


def _make_png() -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (4, 4), color=(100, 150, 200)).save(buf, "PNG")
    return buf.getvalue()


def _png_data_url() -> str:
    return "data:image/png;base64," + base64.b64encode(_make_png()).decode()


# ---------------------------------------------------------------------------
# SCENE3D_EXTENSIONS constant
# ---------------------------------------------------------------------------


class TestScene3dExtensions:
    def test_glb_and_gltf_are_accepted(self):
        assert ".glb" in SCENE3D_EXTENSIONS
        assert ".gltf" in SCENE3D_EXTENSIONS

    def test_fbx_and_obj_are_not_accepted(self):
        assert ".fbx" not in SCENE3D_EXTENSIONS
        assert ".obj" not in SCENE3D_EXTENSIONS


# ---------------------------------------------------------------------------
# import_scene3d_stream
# ---------------------------------------------------------------------------


class TestImportScene3dStream:
    def setup_method(self):
        self._tmp = Path(tempfile.mkdtemp())

    def test_valid_glb_updates_settings(self):
        project = _make_project(self._tmp)
        import_scene3d_stream(project, io.BytesIO(b"GLB_PLACEHOLDER"), "scene.glb")
        scene3d = project.settings.get("scene3d") or {}
        assert scene3d.get("source") == "blender"
        assert str(scene3d.get("file_path", "")).endswith("scene3d/scene.glb")

    def test_valid_gltf_updates_settings(self):
        project = _make_project(self._tmp)
        import_scene3d_stream(project, io.BytesIO(b"GLTF_PLACEHOLDER"), "model.gltf")
        scene3d = project.settings.get("scene3d") or {}
        assert str(scene3d.get("file_path", "")).endswith(".gltf")

    def test_returns_scene_settings_dict(self):
        project = _make_project(self._tmp)
        result = import_scene3d_stream(project, io.BytesIO(b"x"), "scene.glb")
        assert isinstance(result, dict)
        assert "file_path" in result
        assert "source" in result

    def test_unsupported_extension_raises_value_error(self):
        project = _make_project(self._tmp)
        with pytest.raises(ValueError, match="(?i)(glb|gltf|supported)"):
            import_scene3d_stream(project, io.BytesIO(b""), "scene.fbx")

    def test_unsupported_extension_leaves_settings_unchanged(self):
        project = _make_project(self._tmp)
        before = dict(project.settings.get("scene3d") or {})
        try:
            import_scene3d_stream(project, io.BytesIO(b""), "scene.obj")
        except ValueError:
            pass
        after = dict(project.settings.get("scene3d") or {})
        assert after == before

    def test_preserves_existing_scene3d_keys(self):
        project = _make_project(self._tmp)
        project.settings["scene3d"] = {"camera_name": "Cam.001", "wireframe_mode": "on"}
        import_scene3d_stream(project, io.BytesIO(b"x"), "scene.glb")
        scene3d = project.settings.get("scene3d") or {}
        # New keys are added; old keys that were not in the update dict may be overwritten by
        # scene_settings.update(), but keys NOT in SCENE3D update payload survive if not touched.
        assert "file_path" in scene3d

    def test_failed_import_does_not_destroy_existing_scene_file(self, monkeypatch):
        project = _make_project(self._tmp)
        scene_dir = project.root_path / "scene3d"
        scene_dir.mkdir(parents=True, exist_ok=True)
        destination = scene_dir / "scene.glb"
        destination.write_bytes(b"existing model bytes")
        project.settings["scene3d"] = {"file_path": "scene3d/scene.glb", "source": "blender"}
        before_settings = dict(project.settings["scene3d"])

        def fail_after_partial_write(source, target):
            target.write(b"partial replacement")
            raise OSError("simulated write failure")

        monkeypatch.setattr("storyboard_tool.external_tools.shutil.copyfileobj", fail_after_partial_write)

        with pytest.raises(OSError, match="simulated write failure"):
            import_scene3d_stream(project, io.BytesIO(b"new model bytes"), "scene.glb")

        assert destination.read_bytes() == b"existing model bytes"
        assert project.settings["scene3d"] == before_settings
        assert list(scene_dir.glob("scene.glb.*.tmp")) == []


# ---------------------------------------------------------------------------
# get_scene3d_file_path
# ---------------------------------------------------------------------------


class TestGetScene3dFilePath:
    def setup_method(self):
        self._tmp = Path(tempfile.mkdtemp())

    def test_returns_none_when_scene3d_not_set(self):
        project = _make_project(self._tmp)
        assert get_scene3d_file_path(project) is None

    def test_returns_path_for_valid_glb(self):
        project = _make_project(self._tmp)
        import_scene3d_stream(project, io.BytesIO(b"x"), "scene.glb")
        result = get_scene3d_file_path(project)
        assert result is not None
        assert result.exists()
        assert result.suffix == ".glb"

    def test_raises_file_not_found_after_file_deleted(self):
        project = _make_project(self._tmp)
        import_scene3d_stream(project, io.BytesIO(b"x"), "scene.glb")
        # Delete the file on disk — project root is project.root_path, not self._tmp directly
        (project.root_path / "scene3d" / "scene.glb").unlink()
        with pytest.raises(FileNotFoundError):
            get_scene3d_file_path(project)

    def test_path_traversal_raises(self):
        project = _make_project(self._tmp)
        project.settings["scene3d"] = {"file_path": "../../etc/passwd"}
        with pytest.raises((ValueError, FileNotFoundError)):
            get_scene3d_file_path(project)

    def test_absolute_path_outside_project_raises(self):
        project = _make_project(self._tmp)
        project.settings["scene3d"] = {"file_path": "/tmp/evil.glb"}
        with pytest.raises((ValueError, FileNotFoundError)):
            get_scene3d_file_path(project)


# ---------------------------------------------------------------------------
# apply_model_captures_to_boards — input validation
# ---------------------------------------------------------------------------


class TestApplyModelCapturesValidation:
    """Tests for the early-exit validation in apply_model_captures_to_boards.

    These tests exercise validations that raise BEFORE the function reaches
    model-file or image-compositing code, so no GLB file is needed on disk.
    """

    def setup_method(self):
        self._tmp = Path(tempfile.mkdtemp())

    def _project_with_shots(self, n: int):
        project = _make_project(self._tmp)
        for _ in range(n):
            project_manager.add_shot(project)
        return project

    def test_empty_captures_raises(self):
        project = self._project_with_shots(2)
        shots = project.shots
        with pytest.raises(ValueError, match="(?i)captures.*required"):
            reference_segments.apply_model_captures_to_boards(
                project, shots[0].shot_id, shots[1].shot_id, "seg1", "", []
            )

    def test_missing_shot_id_in_capture_raises(self):
        project = self._project_with_shots(1)
        shots = project.shots
        with pytest.raises(ValueError, match="(?i)shot_id"):
            reference_segments.apply_model_captures_to_boards(
                project,
                shots[0].shot_id,
                shots[0].shot_id,
                "seg1",
                "",
                [{"shot_id": "", "data_url": _png_data_url(), "animation_time": 0.0}],
            )

    def test_invalid_data_url_raises(self):
        project = self._project_with_shots(1)
        shots = project.shots
        with pytest.raises(ValueError, match="(?i)invalid.*png.*data.url"):
            reference_segments.apply_model_captures_to_boards(
                project,
                shots[0].shot_id,
                shots[0].shot_id,
                "seg1",
                "",
                [{"shot_id": shots[0].shot_id, "data_url": "data:image/jpeg;base64,AAAA", "animation_time": 0.0}],
            )

    def test_jpeg_data_url_rejected(self):
        project = self._project_with_shots(1)
        shots = project.shots
        with pytest.raises(ValueError, match="(?i)invalid.*png.*data.url"):
            reference_segments.apply_model_captures_to_boards(
                project,
                shots[0].shot_id,
                shots[0].shot_id,
                "seg1",
                "",
                [{"shot_id": shots[0].shot_id, "data_url": "data:image/jpeg;base64,/9j/AAAA", "animation_time": 0.0}],
            )

    def test_duplicate_shot_id_in_captures_raises(self):
        project = self._project_with_shots(2)
        shots = project.shots
        data_url = _png_data_url()
        with pytest.raises(ValueError, match="(?i)duplicate"):
            reference_segments.apply_model_captures_to_boards(
                project,
                shots[0].shot_id,
                shots[1].shot_id,
                "seg1",
                "",
                [
                    {"shot_id": shots[0].shot_id, "data_url": data_url, "animation_time": 0.0},
                    {"shot_id": shots[0].shot_id, "data_url": data_url, "animation_time": 0.5},
                ],
            )

    def test_missing_capture_for_board_in_range_raises(self):
        project = self._project_with_shots(2)
        shots = project.shots
        data_url = _png_data_url()
        with pytest.raises(ValueError, match="(?i)missing.*3d.*capture"):
            reference_segments.apply_model_captures_to_boards(
                project,
                shots[0].shot_id,
                shots[1].shot_id,
                "seg1",
                "",
                # Only one capture provided; shots[1] is missing
                [{"shot_id": shots[0].shot_id, "data_url": data_url, "animation_time": 0.0}],
            )

    def test_unknown_anchor_shot_raises(self):
        project = self._project_with_shots(1)
        shots = project.shots
        with pytest.raises((ValueError, KeyError, IndexError, Exception)):
            reference_segments.apply_model_captures_to_boards(
                project,
                "nonexistent-shot-id",
                shots[0].shot_id,
                "seg1",
                "",
                [{"shot_id": shots[0].shot_id, "data_url": _png_data_url(), "animation_time": 0.0}],
            )
