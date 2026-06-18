"""Tests for project_transaction and atomic save in project_manager."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from storyboard_tool import project_manager, project_transaction, shot_service
from storyboard_tool.models import Project, Shot


def _make_project(tmp_dir: str) -> Project:
    return project_manager.create_project(Path(tmp_dir))


class TestMutateProjectRollback(unittest.TestCase):
    def test_exception_restores_shots(self) -> None:
        project = Project(root_path=Path("/fake"))
        project.shots = [Shot(shot_id="a"), Shot(shot_id="b")]

        with self.assertRaises(RuntimeError):
            with project_transaction.mutate_project(project):
                project.shots.pop()
                raise RuntimeError("boom")

        self.assertEqual(len(project.shots), 2)
        self.assertEqual(project.shots[0].shot_id, "a")
        self.assertEqual(project.shots[1].shot_id, "b")

    def test_exception_restores_settings(self) -> None:
        project = Project(root_path=Path("/fake"))
        project.settings = {"key": "original"}

        with self.assertRaises(ValueError):
            with project_transaction.mutate_project(project):
                project.settings["key"] = "mutated"
                raise ValueError("failed")

        self.assertEqual(project.settings["key"], "original")

    def test_success_keeps_shots_changes(self) -> None:
        project = Project(root_path=Path("/fake"))
        project.shots = [Shot(shot_id="a")]

        with project_transaction.mutate_project(project):
            project.shots.append(Shot(shot_id="b"))

        self.assertEqual(len(project.shots), 2)

    def test_success_keeps_settings_changes(self) -> None:
        project = Project(root_path=Path("/fake"))
        project.settings = {"key": "original"}

        with project_transaction.mutate_project(project):
            project.settings["key"] = "updated"

        self.assertEqual(project.settings["key"], "updated")

    def test_rollback_is_independent_deep_copy(self) -> None:
        """Mutating a shot's field inside the block, then rolling back, restores that field."""
        project = Project(root_path=Path("/fake"))
        shot = Shot(shot_id="x")
        shot.title = "before"
        project.shots = [shot]

        with self.assertRaises(RuntimeError):
            with project_transaction.mutate_project(project):
                project.shots[0].title = "during"
                raise RuntimeError("abort")

        self.assertEqual(project.shots[0].title, "before")

    def test_reraises_original_exception(self) -> None:
        project = Project(root_path=Path("/fake"))
        project.shots = []

        class _CustomError(Exception):
            pass

        with self.assertRaises(_CustomError):
            with project_transaction.mutate_project(project):
                raise _CustomError("specific")

    def test_nested_mutations_outer_rollback(self) -> None:
        """Outer rollback works even if inner block succeeded."""
        project = Project(root_path=Path("/fake"))
        project.shots = [Shot(shot_id="a")]

        with self.assertRaises(RuntimeError):
            with project_transaction.mutate_project(project):
                project.shots.append(Shot(shot_id="b"))
                # simulated second operation that fails
                raise RuntimeError("second op failed")

        self.assertEqual(len(project.shots), 1)


class TestMutateProjectWithShotService(unittest.TestCase):
    def test_delete_shot_rolls_back_on_unexpected_error(self) -> None:
        project = Project(root_path=Path("/fake"))
        project.shots = [Shot(shot_id="x"), Shot(shot_id="y")]

        with self.assertRaises(RuntimeError):
            with project_transaction.mutate_project(project):
                project.shots.pop(0)
                raise RuntimeError("filesystem failed")

        self.assertEqual(len(project.shots), 2)

    def test_reorder_shots_rolls_back_on_error(self) -> None:
        project = Project(root_path=Path("/fake"))
        project.shots = [Shot(shot_id="a"), Shot(shot_id="b"), Shot(shot_id="c")]
        original_ids = [s.shot_id for s in project.shots]

        with self.assertRaises(ValueError):
            with project_transaction.mutate_project(project):
                project_manager.reorder_shots(project, ["c", "a", "b"])
                raise ValueError("save failed")

        self.assertEqual([s.shot_id for s in project.shots], original_ids)


class TestAtomicWriteJson(unittest.TestCase):
    def test_save_project_creates_json_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _make_project(tmp)
            self.assertTrue(project.json_path.is_file())

    def test_save_settings_creates_settings_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _make_project(tmp)
            self.assertTrue(project.settings_path.is_file())

    def test_save_project_json_is_valid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _make_project(tmp)
            data = json.loads(project.json_path.read_text(encoding="utf-8"))
            self.assertIn("version", data)

    def test_save_settings_json_is_valid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _make_project(tmp)
            data = json.loads(project.settings_path.read_text(encoding="utf-8"))
            self.assertIsInstance(data, dict)

    def test_atomic_write_leaves_original_unchanged_on_os_replace_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "test.json"
            path.write_text('{"original": true}', encoding="utf-8")

            with patch("os.replace", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    project_manager._atomic_write_json(path, {"new": True})

            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertTrue(data.get("original"))

    def test_atomic_write_no_temp_file_left_on_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "target.json"

            with patch("os.replace", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    project_manager._atomic_write_json(path, {"x": 1})

            leftover_tmps = list(Path(tmp).glob("*.tmp"))
            self.assertEqual(leftover_tmps, [], "temp file should be cleaned up on failure")

    def test_save_round_trip_preserves_settings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _make_project(tmp)
            project.settings["canvas_width"] = 1280
            project.settings["canvas_height"] = 720
            project_manager.save_settings(project)

            reloaded = project_manager.open_project(project.json_path)
            self.assertEqual(reloaded.settings.get("canvas_width"), 1280)
            self.assertEqual(reloaded.settings.get("canvas_height"), 720)


class TestRefApplyUndo(unittest.TestCase):
    def test_mutate_project_restores_camera_data_on_failure(self) -> None:
        """Simulates a ref-apply partial mutation followed by rollback."""
        project = Project(root_path=Path("/fake"))
        shot_a = Shot(shot_id="a")
        shot_b = Shot(shot_id="b")
        shot_a.camera_data = {"fov": 50}
        shot_b.camera_data = {"fov": 50}
        project.shots = [shot_a, shot_b]

        with self.assertRaises(RuntimeError):
            with project_transaction.mutate_project(project):
                # simulate partial apply: first shot updated, second fails
                project.shots[0].camera_data = {"fov": 35, "applied": True}
                raise RuntimeError("apply failed on shot 2")

        self.assertEqual(project.shots[0].camera_data, {"fov": 50})
        self.assertEqual(project.shots[1].camera_data, {"fov": 50})

    def test_mutate_project_commits_camera_data_on_success(self) -> None:
        project = Project(root_path=Path("/fake"))
        shot = Shot(shot_id="x")
        shot.camera_data = {"fov": 50}
        project.shots = [shot]

        with project_transaction.mutate_project(project):
            project.shots[0].camera_data = {"fov": 35, "applied": True}

        self.assertEqual(project.shots[0].camera_data["fov"], 35)
        self.assertTrue(project.shots[0].camera_data.get("applied"))


if __name__ == "__main__":
    unittest.main()
