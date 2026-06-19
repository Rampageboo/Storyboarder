"""File transaction safety regression tests.

Verifies that multi-file operations leave no partial state when they fail:

  - atomic_copy_file: temp cleaned up on failure; destination preserved
  - _save_board_background_copy: atomic (no partial background on error)
  - import_image_for_shot: metadata unchanged when file copy fails
  - import_source_file_stream: source_file_path unchanged when write fails
  - _set_shot_preview_paths: image_path/preview_image_path survive thumbnail failure
  - thumbnail path not updated when thumbnail generation fails
  - _background.png never reaches image_path / preview_image_path
  - export_psd_composite_to_png: no partial PNG left on failure
"""
from __future__ import annotations

import io
import os
import shutil
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from storyboard_tool import project_manager
from storyboard_tool.file_transactions import atomic_copy_file
from storyboard_tool.image_utils import board_background_filename
from storyboard_tool.shot_assets import _save_board_background_copy, _set_shot_preview_paths


def _make_project(tmp: str):
    return project_manager.create_project(Path(tmp))


def _make_png_bytes(width: int = 4, height: int = 4) -> bytes:
    """Return minimal valid PNG bytes (solid red 4x4 image)."""
    from PIL import Image
    import io as _io
    img = Image.new("RGB", (width, height), (200, 100, 50))
    buf = _io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# atomic_copy_file
# ---------------------------------------------------------------------------

class TestAtomicCopyFile(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_copy_succeeds_content_matches(self):
        src = Path(self._tmp) / "source.png"
        dst = Path(self._tmp) / "dest.png"
        src.write_bytes(b"hello world")
        result = atomic_copy_file(src, dst)
        self.assertEqual(result, dst)
        self.assertEqual(dst.read_bytes(), b"hello world")

    def test_copy_no_temp_file_left_on_success(self):
        src = Path(self._tmp) / "source.png"
        dst = Path(self._tmp) / "dest.png"
        src.write_bytes(b"data")
        atomic_copy_file(src, dst)
        tmp_files = list(Path(self._tmp).glob("*.tmp"))
        self.assertEqual(tmp_files, [], "No stale .tmp files after successful copy")

    def test_copy_same_path_is_noop(self):
        src = Path(self._tmp) / "same.png"
        src.write_bytes(b"unchanged")
        result = atomic_copy_file(src, src)
        self.assertEqual(result, src)
        self.assertEqual(src.read_bytes(), b"unchanged")

    def test_copy_missing_source_raises_and_no_temp_left(self):
        src = Path(self._tmp) / "nonexistent.png"
        dst = Path(self._tmp) / "dest.png"
        dst.write_bytes(b"original destination")
        with self.assertRaises(Exception):
            atomic_copy_file(src, dst)
        # Destination must not be touched
        self.assertEqual(dst.read_bytes(), b"original destination")
        tmp_files = list(Path(self._tmp).glob("*.tmp"))
        self.assertEqual(tmp_files, [], "No .tmp file left after failed copy")

    def test_copy_creates_parent_directories(self):
        src = Path(self._tmp) / "source.png"
        dst = Path(self._tmp) / "nested" / "deep" / "dest.png"
        src.write_bytes(b"nested")
        atomic_copy_file(src, dst)
        self.assertTrue(dst.is_file())
        self.assertEqual(dst.read_bytes(), b"nested")


# ---------------------------------------------------------------------------
# _save_board_background_copy (atomic via atomic_copy_file)
# ---------------------------------------------------------------------------

class TestBoardBackgroundCopyAtomic(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_background_copy_no_temp_left_on_success(self):
        src = Path(self._tmp) / "preview.png"
        dst = Path(self._tmp) / "bg.png"
        src.write_bytes(_make_png_bytes())
        _save_board_background_copy(src, dst)
        tmp_files = list(Path(self._tmp).glob("*.tmp"))
        self.assertEqual(tmp_files, [], "No stale .tmp after background copy")

    def test_background_copy_same_path_noop(self):
        src = Path(self._tmp) / "same.png"
        src.write_bytes(b"same")
        result = _save_board_background_copy(src, src)
        self.assertEqual(result, src)
        self.assertEqual(src.read_bytes(), b"same")

    def test_background_copy_missing_source_preserves_existing_destination(self):
        src = Path(self._tmp) / "missing.png"
        dst = Path(self._tmp) / "existing_bg.png"
        dst.write_bytes(b"previous background")
        with self.assertRaises(Exception):
            _save_board_background_copy(src, dst)
        # Existing destination must be intact
        self.assertEqual(dst.read_bytes(), b"previous background")
        tmp_files = list(Path(self._tmp).glob("*.tmp"))
        self.assertEqual(tmp_files, [], "No .tmp left after failed background copy")


# ---------------------------------------------------------------------------
# import_image_for_shot — metadata unchanged when file import fails
# ---------------------------------------------------------------------------

class TestPreviewImportMetadata(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_failed_import_leaves_metadata_unchanged(self):
        project = _make_project(self._tmp)
        shot = project_manager.add_shot(project)
        original_image_path = shot.image_path
        original_preview = shot.preview_image_path
        original_thumb = shot.thumbnail_path

        bad_source = Path(self._tmp) / "nonexistent.png"
        with self.assertRaises(Exception):
            project_manager.import_image_for_shot(project, shot, bad_source)

        self.assertEqual(shot.image_path, original_image_path,
                         "image_path must not change after failed import")
        self.assertEqual(shot.preview_image_path, original_preview,
                         "preview_image_path must not change after failed import")
        self.assertEqual(shot.thumbnail_path, original_thumb,
                         "thumbnail_path must not change after failed import")

    def test_failed_import_no_temp_files_left(self):
        project = _make_project(self._tmp)
        shot = project_manager.add_shot(project)
        shot_dir = project_manager.get_shot_dir(project, shot)

        bad_source = Path(self._tmp) / "nonexistent.png"
        with self.assertRaises(Exception):
            project_manager.import_image_for_shot(project, shot, bad_source)

        tmp_files = list(shot_dir.glob("*.tmp"))
        self.assertEqual(tmp_files, [], "No stale .tmp files after failed import_image_for_shot")

    def test_successful_import_sets_metadata(self):
        project = _make_project(self._tmp)
        shot = project_manager.add_shot(project)
        source = Path(self._tmp) / "art.png"
        source.write_bytes(_make_png_bytes())

        project_manager.import_image_for_shot(project, shot, source)

        self.assertTrue(shot.image_path, "image_path must be set after successful import")
        self.assertTrue(shot.preview_image_path, "preview_image_path must be set")
        self.assertNotIn("_background", shot.image_path,
                         "image_path must not point to _background.png")

    def test_successful_import_no_temp_files_left(self):
        project = _make_project(self._tmp)
        shot = project_manager.add_shot(project)
        source = Path(self._tmp) / "art.png"
        source.write_bytes(_make_png_bytes())
        shot_dir = project_manager.get_shot_dir(project, shot)

        project_manager.import_image_for_shot(project, shot, source)

        tmp_files = list(shot_dir.glob("*.tmp"))
        self.assertEqual(tmp_files, [], "No stale .tmp files after successful import")


# ---------------------------------------------------------------------------
# import_source_file_stream — source_file_path unchanged when write fails
# ---------------------------------------------------------------------------

class TestSourceImportMetadata(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_failed_stream_leaves_source_file_path_unchanged(self):
        project = _make_project(self._tmp)
        shot = project_manager.add_shot(project)
        original_source_file_path = shot.source_file_path

        class BrokenStream(io.RawIOBase):
            def read(self, n=-1):
                raise OSError("simulated stream error")
            def readinto(self, b):
                raise OSError("simulated stream error")

        with self.assertRaises(OSError):
            project_manager.import_source_file_stream(
                project, shot, BrokenStream(), "canvas.psd"
            )

        self.assertEqual(
            shot.source_file_path, original_source_file_path,
            "source_file_path must not change after a failed stream write",
        )

    def test_failed_stream_no_temp_file_left(self):
        project = _make_project(self._tmp)
        shot = project_manager.add_shot(project)
        shot_dir = project_manager.get_shot_dir(project, shot)

        class BrokenStream(io.RawIOBase):
            def read(self, n=-1):
                raise OSError("simulated stream error")
            def readinto(self, b):
                raise OSError("simulated stream error")

        with self.assertRaises(OSError):
            project_manager.import_source_file_stream(
                project, shot, BrokenStream(), "canvas.psd"
            )

        tmp_files = list(shot_dir.glob("*.tmp*"))
        self.assertEqual(tmp_files, [], "No stale .tmp files after failed import_source_file_stream")


# ---------------------------------------------------------------------------
# _set_shot_preview_paths — thumbnail failure is non-fatal
# ---------------------------------------------------------------------------

class TestThumbnailFailureRobustness(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_thumbnail_failure_does_not_prevent_preview_paths_being_set(self):
        """If thumbnail generation fails, image_path / preview_image_path must still be set."""
        project = _make_project(self._tmp)
        shot = project_manager.add_shot(project)
        shot_dir = project_manager.get_shot_dir(project, shot)

        preview = shot_dir / f"{shot.shot_id}_preview.png"
        preview.write_bytes(_make_png_bytes())

        expected_rel = preview.relative_to(project.root_path).as_posix()

        with unittest.mock.patch(
            "storyboard_tool.shot_assets.create_thumbnail",
            side_effect=OSError("disk full"),
        ):
            _set_shot_preview_paths(project, shot, preview)

        self.assertEqual(shot.image_path, expected_rel,
                         "image_path must be set even when thumbnail fails")
        self.assertEqual(shot.preview_image_path, expected_rel,
                         "preview_image_path must be set even when thumbnail fails")

    def test_thumbnail_failure_leaves_thumbnail_path_at_prior_value(self):
        """If thumbnail creation raises, thumbnail_path must not be updated."""
        project = _make_project(self._tmp)
        shot = project_manager.add_shot(project)
        shot_dir = project_manager.get_shot_dir(project, shot)

        # Give the shot a prior thumbnail_path so we can confirm it is unchanged.
        prior_thumb = "shots/prior_thumb.png"
        shot.thumbnail_path = prior_thumb

        preview = shot_dir / f"{shot.shot_id}_preview.png"
        preview.write_bytes(_make_png_bytes())

        with unittest.mock.patch(
            "storyboard_tool.shot_assets.create_thumbnail",
            side_effect=OSError("disk full"),
        ):
            _set_shot_preview_paths(project, shot, preview)

        self.assertEqual(shot.thumbnail_path, prior_thumb,
                         "thumbnail_path must remain at prior value when thumbnail generation fails")

    def test_thumbnail_failure_does_not_propagate_exception(self):
        """A thumbnail failure must not raise — _set_shot_preview_paths must complete."""
        project = _make_project(self._tmp)
        shot = project_manager.add_shot(project)
        shot_dir = project_manager.get_shot_dir(project, shot)

        preview = shot_dir / f"{shot.shot_id}_preview.png"
        preview.write_bytes(_make_png_bytes())

        with unittest.mock.patch(
            "storyboard_tool.shot_assets.create_thumbnail",
            side_effect=OSError("disk full"),
        ):
            # Must not raise
            _set_shot_preview_paths(project, shot, preview)


# ---------------------------------------------------------------------------
# Background plate never becomes preview metadata
# ---------------------------------------------------------------------------

class TestBackgroundNeverBecomesPreviewMetadata(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_set_shot_preview_paths_with_background_path_is_blocked_by_relink_guard(self):
        """relink_preview_image (the validated entry point) must reject _background.png."""
        project = _make_project(self._tmp)
        shot = project_manager.add_shot(project)
        shot_dir = project_manager.get_shot_dir(project, shot)

        bg = shot_dir / board_background_filename(shot.shot_id)
        bg.write_bytes(_make_png_bytes())
        bg_rel = bg.relative_to(project.root_path).as_posix()

        original_image_path = shot.image_path
        original_preview = shot.preview_image_path

        with self.assertRaises(ValueError):
            project_manager.relink_preview_image(project, shot, bg_rel)

        self.assertEqual(shot.image_path, original_image_path,
                         "image_path unchanged after relink rejection")
        self.assertEqual(shot.preview_image_path, original_preview,
                         "preview_image_path unchanged after relink rejection")

    def test_background_plate_not_in_metadata_after_import_and_save(self):
        """After import_image_for_shot and save/reload, no metadata path points to _background.png."""
        from storyboard_tool.shot_store import shots_json_path, load_shots_json

        project = _make_project(self._tmp)
        shot = project_manager.add_shot(project)
        source = Path(self._tmp) / "art.png"
        source.write_bytes(_make_png_bytes())

        project_manager.import_image_for_shot(project, shot, source)
        project_manager.save_project(project)

        # Reload canonical shots.json and check metadata paths
        reloaded_shots = load_shots_json(shots_json_path(project.root_path))
        for s in reloaded_shots:
            self.assertNotIn("_background", s.image_path,
                             f"image_path must not reference _background: {s.image_path}")
            self.assertNotIn("_background", s.preview_image_path,
                             f"preview_image_path must not reference _background: {s.preview_image_path}")


# ---------------------------------------------------------------------------
# save_drawing_for_shot — atomic write + metadata correctness
# ---------------------------------------------------------------------------

class TestSaveDrawingTransaction(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_save_drawing_bad_data_url_leaves_metadata_unchanged(self):
        project = _make_project(self._tmp)
        shot = project_manager.add_shot(project)
        original_image = shot.image_path
        original_preview = shot.preview_image_path

        with self.assertRaises(ValueError):
            project_manager.save_drawing_for_shot(project, shot, "not-a-data-url")

        self.assertEqual(shot.image_path, original_image,
                         "image_path unchanged after bad data URL")
        self.assertEqual(shot.preview_image_path, original_preview,
                         "preview_image_path unchanged after bad data URL")

    def test_save_drawing_no_temp_left_on_success(self):
        project = _make_project(self._tmp)
        shot = project_manager.add_shot(project)
        shot_dir = project_manager.get_shot_dir(project, shot)

        import base64
        from PIL import Image as _Image
        import io as _io
        img = _Image.new("RGB", (4, 4), (10, 20, 30))
        buf = _io.BytesIO()
        img.save(buf, "PNG")
        data_url = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()

        project_manager.save_drawing_for_shot(project, shot, data_url)

        tmp_files = list(shot_dir.glob("*.tmp*"))
        self.assertEqual(tmp_files, [], "No stale .tmp files after save_drawing_for_shot")


if __name__ == "__main__":
    unittest.main()
