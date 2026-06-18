"""Tests for shot_service: create, duplicate, delete, reorder, find, update."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from storyboard_tool import project_manager, shot_service
from storyboard_tool.models import Project, Shot


def _project_with_shots(*shot_ids: str) -> Project:
    """In-memory project — no filesystem, for lookup-only tests."""
    project = Project(root_path=Path("/fake"))
    project.shots = [Shot(shot_id=sid) for sid in shot_ids]
    return project


class TestFindShot(unittest.TestCase):
    def test_find_shot_index_returns_correct_index(self) -> None:
        project = _project_with_shots("a", "b", "c")
        self.assertEqual(shot_service.find_shot_index(project, "b"), 1)

    def test_find_shot_index_first_and_last(self) -> None:
        project = _project_with_shots("x", "y", "z")
        self.assertEqual(shot_service.find_shot_index(project, "x"), 0)
        self.assertEqual(shot_service.find_shot_index(project, "z"), 2)

    def test_find_shot_index_raises_value_error_when_missing(self) -> None:
        project = _project_with_shots("a", "b")
        with self.assertRaises(ValueError):
            shot_service.find_shot_index(project, "not_here")

    def test_find_shot_returns_correct_shot(self) -> None:
        project = _project_with_shots("a", "b", "c")
        shot = shot_service.find_shot(project, "c")
        self.assertEqual(shot.shot_id, "c")

    def test_find_shot_raises_value_error_when_missing(self) -> None:
        project = _project_with_shots("a")
        with self.assertRaises(ValueError):
            shot_service.find_shot(project, "z")

    def test_find_shot_error_message_contains_shot_id(self) -> None:
        project = _project_with_shots("a")
        with self.assertRaises(ValueError, msg="error should name the missing id") as ctx:
            shot_service.find_shot_index(project, "missing_id")
        self.assertIn("missing_id", str(ctx.exception))


class TestCreateShot(unittest.TestCase):
    def test_create_shot_appends_to_empty_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = project_manager.create_project(Path(tmp))
            shot = shot_service.create_shot(project)
            self.assertEqual(len(project.shots), 1)
            self.assertEqual(project.shots[0].shot_id, shot.shot_id)

    def test_create_shot_appends_when_no_after_given(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = project_manager.create_project(Path(tmp))
            first = shot_service.create_shot(project)
            second = shot_service.create_shot(project)
            self.assertEqual(project.shots[-1].shot_id, second.shot_id)

    def test_create_shot_after_specific_shot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = project_manager.create_project(Path(tmp))
            a = shot_service.create_shot(project)
            c = shot_service.create_shot(project)
            b = shot_service.create_shot(project, after_shot_id=a.shot_id)
            ids = [s.shot_id for s in project.shots]
            self.assertEqual(ids, [a.shot_id, b.shot_id, c.shot_id])

    def test_create_shot_raises_when_after_shot_not_found(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = project_manager.create_project(Path(tmp))
            with self.assertRaises(ValueError):
                shot_service.create_shot(project, after_shot_id="nonexistent")

    def test_create_shot_returns_shot_with_unique_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = project_manager.create_project(Path(tmp))
            a = shot_service.create_shot(project)
            b = shot_service.create_shot(project)
            self.assertNotEqual(a.shot_id, b.shot_id)


class TestDuplicateShot(unittest.TestCase):
    def test_duplicate_shot_inserts_after_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = project_manager.create_project(Path(tmp))
            original = shot_service.create_shot(project)
            duplicate = shot_service.duplicate_shot(project, original.shot_id)
            ids = [s.shot_id for s in project.shots]
            self.assertEqual(ids, [original.shot_id, duplicate.shot_id])

    def test_duplicate_shot_gets_new_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = project_manager.create_project(Path(tmp))
            original = shot_service.create_shot(project)
            duplicate = shot_service.duplicate_shot(project, original.shot_id)
            self.assertNotEqual(duplicate.shot_id, original.shot_id)

    def test_duplicate_shot_preserves_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = project_manager.create_project(Path(tmp))
            original = shot_service.create_shot(project)
            original.scene = "INT. LAB"
            original.duration_seconds = 5.0
            duplicate = shot_service.duplicate_shot(project, original.shot_id)
            self.assertEqual(duplicate.scene, "INT. LAB")
            self.assertAlmostEqual(duplicate.duration_seconds, 5.0)

    def test_duplicate_shot_does_not_inherit_original_media_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = project_manager.create_project(Path(tmp))
            original = shot_service.create_shot(project)
            original.ref_video_path = "references/clip.mp4"
            original.ref_video_time = 12.5
            duplicate = shot_service.duplicate_shot(project, original.shot_id)
            # duplicate_shot clears the reference-video fields from the copy
            self.assertEqual(duplicate.ref_video_path, "")
            self.assertAlmostEqual(duplicate.ref_video_time, 0.0)
            # duplicate gets its own canvas PSD, not the original's
            self.assertNotEqual(duplicate.source_file_path, original.source_file_path)

    def test_duplicate_shot_raises_when_not_found(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = project_manager.create_project(Path(tmp))
            with self.assertRaises(ValueError):
                shot_service.duplicate_shot(project, "missing")


class TestDeleteShot(unittest.TestCase):
    def test_delete_shot_removes_from_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = project_manager.create_project(Path(tmp))
            shot = shot_service.create_shot(project)
            shot_service.delete_shot(project, shot.shot_id)
            self.assertEqual(len(project.shots), 0)

    def test_delete_shot_returns_removed_shot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = project_manager.create_project(Path(tmp))
            shot = shot_service.create_shot(project)
            removed = shot_service.delete_shot(project, shot.shot_id)
            self.assertEqual(removed.shot_id, shot.shot_id)

    def test_delete_shot_leaves_other_shots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = project_manager.create_project(Path(tmp))
            a = shot_service.create_shot(project)
            b = shot_service.create_shot(project)
            c = shot_service.create_shot(project)
            shot_service.delete_shot(project, b.shot_id)
            ids = [s.shot_id for s in project.shots]
            self.assertEqual(ids, [a.shot_id, c.shot_id])

    def test_delete_shot_raises_when_not_found(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = project_manager.create_project(Path(tmp))
            with self.assertRaises(ValueError):
                shot_service.delete_shot(project, "nonexistent")


class TestReorderShots(unittest.TestCase):
    def test_reorder_shots_changes_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = project_manager.create_project(Path(tmp))
            a = shot_service.create_shot(project)
            b = shot_service.create_shot(project)
            c = shot_service.create_shot(project)
            shot_service.reorder_shots(project, [c.shot_id, a.shot_id, b.shot_id])
            self.assertEqual(
                [s.shot_id for s in project.shots],
                [c.shot_id, a.shot_id, b.shot_id],
            )

    def test_reorder_shots_same_order_is_noop(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = project_manager.create_project(Path(tmp))
            a = shot_service.create_shot(project)
            b = shot_service.create_shot(project)
            shot_service.reorder_shots(project, [a.shot_id, b.shot_id])
            self.assertEqual([s.shot_id for s in project.shots], [a.shot_id, b.shot_id])

    def test_reorder_shots_raises_on_missing_shot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = project_manager.create_project(Path(tmp))
            a = shot_service.create_shot(project)
            b = shot_service.create_shot(project)
            with self.assertRaises(ValueError):
                shot_service.reorder_shots(project, [a.shot_id])

    def test_reorder_shots_raises_on_unknown_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = project_manager.create_project(Path(tmp))
            a = shot_service.create_shot(project)
            with self.assertRaises(ValueError):
                shot_service.reorder_shots(project, [a.shot_id, "unknown"])


class TestUpdateShot(unittest.TestCase):
    def _shot(self) -> Shot:
        return Shot(shot_id="test_shot", title="Original", status="Draft", duration_seconds=3.0)

    def test_update_shot_applies_text_fields(self) -> None:
        shot = self._shot()
        shot_service.update_shot(shot, {
            "title": "New Title",
            "scene": "INT. OFFICE",
            "description": "Wide shot",
            "dialogue": "Hello",
        })
        self.assertEqual(shot.title, "New Title")
        self.assertEqual(shot.scene, "INT. OFFICE")
        self.assertEqual(shot.description, "Wide shot")
        self.assertEqual(shot.dialogue, "Hello")

    def test_update_shot_partial_preserves_unchanged_fields(self) -> None:
        shot = self._shot()
        shot.scene = "EXT. PARK"
        shot_service.update_shot(shot, {"title": "Changed"})
        self.assertEqual(shot.title, "Changed")
        self.assertEqual(shot.scene, "EXT. PARK")

    def test_update_shot_valid_status_applied(self) -> None:
        shot = self._shot()
        shot_service.update_shot(shot, {"status": "Approved"})
        self.assertEqual(shot.status, "Approved")

    def test_update_shot_invalid_status_defaults_to_draft(self) -> None:
        shot = self._shot()
        shot.status = "Approved"
        shot_service.update_shot(shot, {"status": "BadStatus"})
        self.assertEqual(shot.status, "Draft")

    def test_update_shot_duration_applied(self) -> None:
        shot = self._shot()
        shot_service.update_shot(shot, {"duration_seconds": 5.5})
        self.assertAlmostEqual(shot.duration_seconds, 5.5)

    def test_update_shot_duration_clamped_to_minimum(self) -> None:
        shot = self._shot()
        shot_service.update_shot(shot, {"duration_seconds": 0.0})
        self.assertGreaterEqual(shot.duration_seconds, 0.1)

    def test_update_shot_negative_duration_clamped(self) -> None:
        shot = self._shot()
        shot_service.update_shot(shot, {"duration_seconds": -10.0})
        self.assertAlmostEqual(shot.duration_seconds, 0.1)

    def test_update_shot_with_non_dict_is_noop(self) -> None:
        shot = self._shot()
        original_title = shot.title
        shot_service.update_shot(shot, None)  # type: ignore[arg-type]
        self.assertEqual(shot.title, original_title)

    def test_update_shot_tags_strips_blank_entries(self) -> None:
        shot = self._shot()
        shot_service.update_shot(shot, {"tags": ["action", "", "wide", "  "]})
        self.assertEqual(shot.tags, ["action", "wide"])

    def test_update_shot_camera_data_applied(self) -> None:
        shot = self._shot()
        shot_service.update_shot(shot, {"camera_data": {"fov": 35}})
        self.assertEqual(shot.camera_data, {"fov": 35})

    def test_update_shot_camera_data_non_dict_preserves_existing(self) -> None:
        shot = self._shot()
        shot.camera_data = {"fov": 50}
        shot_service.update_shot(shot, {"camera_data": "not-a-dict"})
        self.assertEqual(shot.camera_data, {"fov": 50})

    def test_update_shot_all_text_note_fields(self) -> None:
        shot = self._shot()
        shot_service.update_shot(shot, {
            "action_note": "pan left",
            "camera_note": "crane",
            "character_note": "hero only",
            "lighting_note": "overcast",
            "transition_note": "cut",
            "sequence": "seq_01",
        })
        self.assertEqual(shot.action_note, "pan left")
        self.assertEqual(shot.camera_note, "crane")
        self.assertEqual(shot.character_note, "hero only")
        self.assertEqual(shot.lighting_note, "overcast")
        self.assertEqual(shot.transition_note, "cut")
        self.assertEqual(shot.sequence, "seq_01")

    def test_update_shot_duration_standalone_helper(self) -> None:
        shot = self._shot()
        shot_service.update_shot_duration(shot, 7.0)
        self.assertAlmostEqual(shot.duration_seconds, 7.0)

    def test_update_shot_duration_clamps_negative_standalone(self) -> None:
        shot = self._shot()
        shot_service.update_shot_duration(shot, -1.0)
        self.assertAlmostEqual(shot.duration_seconds, 0.1)

    def test_normalize_shot_payload_is_alias_for_update(self) -> None:
        shot = self._shot()
        shot_service.normalize_shot_payload(shot, {"title": "via alias"})
        self.assertEqual(shot.title, "via alias")


if __name__ == "__main__":
    unittest.main()
