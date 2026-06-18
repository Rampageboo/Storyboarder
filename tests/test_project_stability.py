"""Project stability tests — Core Stability Pass.

Covers:
- validate_project_integrity: duplicate IDs, missing dirs, bad paths,
  background-filename in artwork metadata, source link validation
- Shot lifecycle: add, duplicate, reorder, delete, restore, move up/down
- Save/reload: all mutations persist correctly through a full project cycle
- Atomic source import: failed stream copy leaves no partial file at destination
"""
from __future__ import annotations

import io
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from storyboard_tool import project_manager
from storyboard_tool.image_utils import board_background_filename
from storyboard_tool.models import Project


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_png(color: tuple = (100, 150, 200)) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), color).save(buf, "PNG")
    return buf.getvalue()


MINI_PNG = _make_png()


def _make_project(tmp: str) -> Project:
    return project_manager.create_project(Path(tmp))


def _reload(project: Project) -> Project:
    return project_manager.open_project(project.json_path)


# ---------------------------------------------------------------------------
# validate_project_integrity
# ---------------------------------------------------------------------------

class TestValidateProjectIntegrity(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_clean_project_no_issues(self):
        project = _make_project(self._tmp)
        project_manager.add_shot(project)
        self.assertEqual(project_manager.validate_project_integrity(project), [])

    def test_duplicate_shot_id_detected(self):
        project = _make_project(self._tmp)
        a = project_manager.add_shot(project)
        b = project_manager.add_shot(project)
        b.shot_id = a.shot_id  # force duplicate
        kinds = {i["kind"] for i in project_manager.validate_project_integrity(project)}
        self.assertIn("duplicate_shot_id", kinds)

    def test_missing_shot_dir_detected(self):
        project = _make_project(self._tmp)
        shot = project_manager.add_shot(project)
        shutil.rmtree(project_manager.get_shot_dir(project, shot))
        kinds = {i["kind"] for i in project_manager.validate_project_integrity(project)}
        self.assertIn("missing_shot_dir", kinds)

    def test_image_path_pointing_to_background_detected(self):
        project = _make_project(self._tmp)
        shot = project_manager.add_shot(project)
        bg = board_background_filename(shot.shot_id)
        shot.image_path = f"shots/{shot.shot_id}/{bg}"
        kinds = {i["kind"] for i in project_manager.validate_project_integrity(project)}
        self.assertIn("metadata_points_to_background", kinds)

    def test_preview_path_pointing_to_background_detected(self):
        project = _make_project(self._tmp)
        shot = project_manager.add_shot(project)
        bg = board_background_filename(shot.shot_id)
        shot.preview_image_path = f"shots/{shot.shot_id}/{bg}"
        kinds = {i["kind"] for i in project_manager.validate_project_integrity(project)}
        self.assertIn("metadata_points_to_background", kinds)

    def test_path_traversal_in_image_path_detected(self):
        project = _make_project(self._tmp)
        shot = project_manager.add_shot(project)
        shot.image_path = "../../etc/passwd"
        kinds = {i["kind"] for i in project_manager.validate_project_integrity(project)}
        self.assertIn("path_traversal", kinds)

    def test_path_traversal_in_source_file_path_detected(self):
        project = _make_project(self._tmp)
        shot = project_manager.add_shot(project)
        shot.source_file_path = "../../evil.psd"
        kinds = {i["kind"] for i in project_manager.validate_project_integrity(project)}
        self.assertIn("path_traversal", kinds)

    def test_missing_source_file_reported(self):
        project = _make_project(self._tmp)
        shot = project_manager.add_shot(project)
        shot.source_file_path = "shots/nonexistent/nonexistent.psd"
        kinds = {i["kind"] for i in project_manager.validate_project_integrity(project)}
        self.assertIn("missing_source_file", kinds)

    def test_never_raises(self):
        project = _make_project(self._tmp)
        shot = project_manager.add_shot(project)
        shot.source_file_path = "shots/nonexistent/nonexistent.psd"
        shot.image_path = "../../outside"
        try:
            project_manager.validate_project_integrity(project)
        except Exception as exc:
            self.fail(f"validate_project_integrity raised unexpectedly: {exc}")

    def test_existing_source_file_not_flagged(self):
        project = _make_project(self._tmp)
        shot = project_manager.add_shot(project)
        shot_dir = project_manager.get_shot_dir(project, shot)
        psd = shot_dir / f"{shot.shot_id}.psd"
        psd.write_bytes(b"PSD")
        shot.source_file_path = psd.relative_to(project.root_path).as_posix()
        issues = project_manager.validate_project_integrity(project)
        kinds = {i["kind"] for i in issues}
        self.assertNotIn("missing_source_file", kinds)


# ---------------------------------------------------------------------------
# Shot lifecycle
# ---------------------------------------------------------------------------

class TestShotLifecycle(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_add_shot_creates_shot_dir(self):
        project = _make_project(self._tmp)
        shot = project_manager.add_shot(project)
        self.assertTrue(project_manager.get_shot_dir(project, shot).is_dir())

    def test_add_shot_creates_annotation_file(self):
        project = _make_project(self._tmp)
        shot = project_manager.add_shot(project)
        self.assertTrue(shot.annotation_path)
        self.assertTrue((project.root_path / shot.annotation_path).is_file())

    def test_add_shot_creates_references_dir(self):
        project = _make_project(self._tmp)
        shot = project_manager.add_shot(project)
        self.assertTrue((project_manager.get_shot_dir(project, shot) / "references").is_dir())

    def test_add_shot_appends_to_list(self):
        project = _make_project(self._tmp)
        before = len(project.shots)
        project_manager.add_shot(project)
        self.assertEqual(len(project.shots), before + 1)

    def test_add_shot_after_index_inserts_between(self):
        project = _make_project(self._tmp)
        a = project_manager.add_shot(project)
        b = project_manager.add_shot(project)
        c = project_manager.add_shot(project, after_index=0)
        self.assertEqual(project.shots[0].shot_id, a.shot_id)
        self.assertEqual(project.shots[1].shot_id, c.shot_id)
        self.assertEqual(project.shots[2].shot_id, b.shot_id)

    def test_add_shot_unique_ids(self):
        project = _make_project(self._tmp)
        ids = {project_manager.add_shot(project).shot_id for _ in range(5)}
        self.assertEqual(len(ids), 5)

    def test_duplicate_shot_has_new_id(self):
        project = _make_project(self._tmp)
        orig = project_manager.add_shot(project)
        dup = project_manager.duplicate_shot(project, 0)
        self.assertNotEqual(dup.shot_id, orig.shot_id)

    def test_duplicate_shot_clears_artwork_paths(self):
        project = _make_project(self._tmp)
        shot = project_manager.add_shot(project)
        shot.image_path = "shots/fake/fake_preview.png"
        shot.preview_image_path = "shots/fake/fake_preview.png"
        dup = project_manager.duplicate_shot(project, 0)
        self.assertEqual(dup.image_path, "")
        self.assertEqual(dup.preview_image_path, "")

    def test_duplicate_shot_does_not_inherit_original_source_file_path(self):
        """Duplicate must not share the original shot's PSD path.
        (add_shot always creates a fresh blank canvas, so source_file_path
        is expected to be set — but to a NEW path, not the original's.)"""
        project = _make_project(self._tmp)
        orig = project_manager.add_shot(project)
        orig_source = orig.source_file_path  # blank canvas created by add_shot
        dup = project_manager.duplicate_shot(project, 0)
        # The duplicate gets its own blank canvas; it must not share the original's path.
        self.assertNotEqual(dup.source_file_path, orig_source)

    def test_duplicate_shot_inserted_after_source(self):
        project = _make_project(self._tmp)
        a = project_manager.add_shot(project)
        b = project_manager.add_shot(project)
        dup = project_manager.duplicate_shot(project, 0)
        self.assertEqual(project.shots[1].shot_id, dup.shot_id)
        self.assertEqual(project.shots[2].shot_id, b.shot_id)

    def test_reorder_shots_changes_order(self):
        project = _make_project(self._tmp)
        a = project_manager.add_shot(project)
        b = project_manager.add_shot(project)
        project_manager.reorder_shots(project, [b.shot_id, a.shot_id])
        self.assertEqual(project.shots[0].shot_id, b.shot_id)
        self.assertEqual(project.shots[1].shot_id, a.shot_id)

    def test_reorder_shots_raises_on_wrong_count(self):
        project = _make_project(self._tmp)
        project_manager.add_shot(project)
        with self.assertRaises(ValueError):
            project_manager.reorder_shots(project, ["nonexistent_id"])

    def test_reorder_shots_raises_on_unknown_id(self):
        project = _make_project(self._tmp)
        a = project_manager.add_shot(project)
        with self.assertRaises(ValueError):
            project_manager.reorder_shots(project, ["bad_id"])

    def test_delete_shot_removes_from_list(self):
        project = _make_project(self._tmp)
        shot = project_manager.add_shot(project)
        before = len(project.shots)
        deleted = project_manager.delete_shot(project, 0)
        self.assertEqual(deleted.shot_id, shot.shot_id)
        self.assertEqual(len(project.shots), before - 1)

    def test_delete_shot_does_not_delete_files(self):
        """delete_shot is metadata-only — it must NOT remove the shot directory."""
        project = _make_project(self._tmp)
        shot = project_manager.add_shot(project)
        shot_dir = project_manager.get_shot_dir(project, shot)
        project_manager.delete_shot(project, 0)
        self.assertTrue(shot_dir.is_dir())

    def test_restore_shot_reinserts_at_index(self):
        project = _make_project(self._tmp)
        shot = project_manager.add_shot(project)
        data = shot.to_dict()
        project_manager.delete_shot(project, 0)
        project_manager.restore_shot(project, data, 0)
        self.assertEqual(project.shots[0].shot_id, shot.shot_id)

    def test_restore_shot_raises_on_duplicate_id(self):
        project = _make_project(self._tmp)
        shot = project_manager.add_shot(project)
        with self.assertRaises(ValueError):
            project_manager.restore_shot(project, shot.to_dict(), 0)

    def test_move_shot_up(self):
        project = _make_project(self._tmp)
        a = project_manager.add_shot(project)
        b = project_manager.add_shot(project)
        new_idx = project_manager.move_shot_up(project, 1)
        self.assertEqual(new_idx, 0)
        self.assertEqual(project.shots[0].shot_id, b.shot_id)
        self.assertEqual(project.shots[1].shot_id, a.shot_id)

    def test_move_shot_down(self):
        project = _make_project(self._tmp)
        a = project_manager.add_shot(project)
        b = project_manager.add_shot(project)
        new_idx = project_manager.move_shot_down(project, 0)
        self.assertEqual(new_idx, 1)
        self.assertEqual(project.shots[1].shot_id, a.shot_id)
        self.assertEqual(project.shots[0].shot_id, b.shot_id)

    def test_move_shot_up_at_zero_is_noop(self):
        project = _make_project(self._tmp)
        a = project_manager.add_shot(project)
        new_idx = project_manager.move_shot_up(project, 0)
        self.assertEqual(new_idx, 0)
        self.assertEqual(project.shots[0].shot_id, a.shot_id)

    def test_integrity_passes_after_full_lifecycle(self):
        """Integrity check must pass after add → reorder → delete → restore."""
        project = _make_project(self._tmp)
        a = project_manager.add_shot(project)
        b = project_manager.add_shot(project)
        project_manager.reorder_shots(project, [b.shot_id, a.shot_id])
        data = project.shots[0].to_dict()
        project_manager.delete_shot(project, 0)
        project_manager.restore_shot(project, data, 0)
        self.assertEqual(project_manager.validate_project_integrity(project), [])


# ---------------------------------------------------------------------------
# Save/reload persistence
# ---------------------------------------------------------------------------

class TestSaveReloadPersistence(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_shot_count_persists(self):
        project = _make_project(self._tmp)
        project_manager.add_shot(project)
        project_manager.add_shot(project)
        project_manager.save_project(project)
        self.assertEqual(len(_reload(project).shots), 2)

    def test_reorder_persists(self):
        project = _make_project(self._tmp)
        a = project_manager.add_shot(project)
        b = project_manager.add_shot(project)
        project_manager.reorder_shots(project, [b.shot_id, a.shot_id])
        project_manager.save_project(project)
        reloaded = _reload(project)
        self.assertEqual(reloaded.shots[0].shot_id, b.shot_id)
        self.assertEqual(reloaded.shots[1].shot_id, a.shot_id)

    def test_delete_persists(self):
        project = _make_project(self._tmp)
        a = project_manager.add_shot(project)
        project_manager.add_shot(project)
        project_manager.delete_shot(project, 0)
        project_manager.save_project(project)
        reloaded = _reload(project)
        self.assertEqual(len(reloaded.shots), 1)
        self.assertNotEqual(reloaded.shots[0].shot_id, a.shot_id)

    def test_source_file_path_persists(self):
        project = _make_project(self._tmp)
        shot = project_manager.add_shot(project)
        psd = project_manager.get_shot_dir(project, shot) / f"{shot.shot_id}.psd"
        psd.write_bytes(b"PSD")
        shot.source_file_path = psd.relative_to(project.root_path).as_posix()
        project_manager.save_project(project)
        self.assertEqual(_reload(project).shots[0].source_file_path, shot.source_file_path)

    def test_preview_image_path_persists(self):
        project = _make_project(self._tmp)
        shot = project_manager.add_shot(project)
        preview = project_manager.get_shot_dir(project, shot) / f"{shot.shot_id}_preview.png"
        preview.write_bytes(MINI_PNG)
        shot.image_path = preview.relative_to(project.root_path).as_posix()
        shot.preview_image_path = shot.image_path
        project_manager.save_project(project)
        reloaded = _reload(project).shots[0]
        self.assertEqual(reloaded.image_path, shot.image_path)
        self.assertEqual(reloaded.preview_image_path, shot.preview_image_path)

    def test_background_file_persists_independently_of_image_path(self):
        """Background file survives save/reload; image_path must NOT point to it."""
        project = _make_project(self._tmp)
        shot = project_manager.add_shot(project)
        shot_dir = project_manager.get_shot_dir(project, shot)
        bg_path = shot_dir / board_background_filename(shot.shot_id)
        bg_path.write_bytes(MINI_PNG)
        project_manager.save_project(project)
        reloaded = _reload(project).shots[0]
        bg_rel = bg_path.relative_to(project.root_path).as_posix()
        self.assertTrue(bg_path.is_file(), "background file must survive save/reload")
        self.assertNotEqual(reloaded.image_path, bg_rel)
        self.assertNotEqual(reloaded.preview_image_path, bg_rel)

    def test_integrity_passes_after_save_reload(self):
        project = _make_project(self._tmp)
        project_manager.add_shot(project)
        project_manager.save_project(project)
        reloaded = _reload(project)
        self.assertEqual(project_manager.validate_project_integrity(reloaded), [])


# ---------------------------------------------------------------------------
# Atomic source file import
# ---------------------------------------------------------------------------

class TestAtomicSourceImport(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_failed_stream_leaves_existing_file_intact(self):
        """If the stream copy raises mid-write, the pre-existing file must be
        left intact (no truncation) and no .tmp file must linger."""
        project = _make_project(self._tmp)
        shot = project_manager.add_shot(project)
        shot_dir = project_manager.get_shot_dir(project, shot)
        # add_shot creates a blank canvas; capture its content before the failed import.
        destination = shot_dir / f"{shot.shot_id}.psd"
        original_bytes = destination.read_bytes() if destination.is_file() else None

        class ErrorStream:
            def read(self, n=-1):
                raise OSError("simulated disk full")

        with self.assertRaises(OSError):
            project_manager.import_source_file_stream(project, shot, ErrorStream(), "test.psd")

        # No .tmp file must remain.
        tmp = destination.with_suffix(".psd.tmp")
        self.assertFalse(tmp.is_file(), "temp file must be cleaned up on failure")
        # If a file existed before, it must be intact (not truncated).
        if original_bytes is not None:
            self.assertEqual(destination.read_bytes(), original_bytes,
                             "pre-existing file must not be truncated by a failed import")

    def test_successful_import_creates_destination(self):
        """A successful import writes the file; use a non-PSD suffix to skip PSD parsing."""
        project = _make_project(self._tmp)
        shot = project_manager.add_shot(project)
        # Use .txt suffix so import_source_file_stream skips the PSD export step.
        stream = io.BytesIO(b"fake source bytes")
        result = project_manager.import_source_file_stream(project, shot, stream, "canvas.txt")
        self.assertTrue(result.is_file())
        self.assertEqual(shot.source_file_path, result.relative_to(project.root_path).as_posix())
