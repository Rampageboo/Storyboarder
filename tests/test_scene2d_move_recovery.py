from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from storyboard_tool import project_manager, scene2d


MINI_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000011f15c489"
    "0000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082"
)


class Scene2DMoveRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.project = project_manager.create_project(Path(self._tmp.name))
        self.source_scene, _ = scene2d.create_scene(self.project, "Source")
        self.target_scene, _ = scene2d.create_scene(self.project, "Target")
        self.source_scene, self.perspective, _ = scene2d.create_perspective(
            self.project,
            self.source_scene["id"],
            title="Move me",
        )
        (self.project.root_path / self.perspective["preview_image_path"]).write_bytes(MINI_PNG)
        self.reference, _ = scene2d.add_perspective_to_references(
            self.project,
            self.source_scene["id"],
            self.perspective["id"],
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _tx_dir(self) -> Path:
        return self.project.scenes2d_dir / scene2d.PERSPECTIVE_MOVE_ROOT / scene2d.new_uuid()

    def _base_journal(self, tx_dir: Path) -> dict:
        source_dir = (self.project.root_path / self.perspective["source_file_path"]).parent
        target_dir = (
            self.project.scenes2d_dir
            / self.target_scene["id"]
            / "perspectives"
            / self.perspective["id"]
        )
        expected_source = scene2d._source_rel(self.target_scene["id"], self.perspective["id"])
        expected_preview = scene2d._preview_rel(self.target_scene["id"], self.perspective["id"])
        original_files = scene2d._backup_move_metadata(
            self.project,
            tx_dir,
            self.source_scene["id"],
            self.target_scene["id"],
        )
        return {
            "operation_id": tx_dir.name,
            "source_scene_id": self.source_scene["id"],
            "target_scene_id": self.target_scene["id"],
            "perspective_id": self.perspective["id"],
            "source_dir": scene2d._project_rel(self.project, source_dir),
            "target_dir": scene2d._project_rel(self.project, target_dir),
            "target_preexisted": False,
            "source_existed_before": True,
            "preview_existed_before": True,
            "original_source_file_path": self.perspective["source_file_path"],
            "original_preview_image_path": self.perspective["preview_image_path"],
            "expected_source_file_path": expected_source,
            "expected_preview_image_path": expected_preview,
            "original_reference_links": [
                {
                    "id": self.reference["id"],
                    "source_scene2d_id": self.source_scene["id"],
                    "source_scene2d_perspective_id": self.perspective["id"],
                    "path": self.perspective["preview_image_path"],
                }
            ],
            "expected_reference_links": [{"id": self.reference["id"]}],
            "original_files": original_files,
            "started_at": scene2d._now_iso(),
        }

    def _move_files_only(self, journal: dict) -> None:
        source = self.project.root_path / journal["source_dir"]
        target = self.project.root_path / journal["target_dir"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(target))

    def _commit_metadata(self, journal: dict) -> None:
        scenes = scene2d.list_scenes(self.project)
        source = next(item for item in scenes if item["id"] == self.source_scene["id"])
        target = next(item for item in scenes if item["id"] == self.target_scene["id"])
        perspective = scene2d._find_perspective(source, self.perspective["id"])
        source["perspectives"] = [item for item in source["perspectives"] if item["id"] != perspective["id"]]
        target["perspectives"].append(perspective)
        perspective["source_file_path"] = journal["expected_source_file_path"]
        perspective["preview_image_path"] = journal["expected_preview_image_path"]
        if source["primary_perspective_id"] == perspective["id"]:
            source["primary_perspective_id"] = source["perspectives"][0]["id"]
        links = project_manager.normalize_reference_links(self.project.settings.get("reference_links"))
        for link in links:
            if link["id"] == self.reference["id"]:
                link["source_scene2d_id"] = self.target_scene["id"]
                link["source_scene2d_perspective_id"] = self.perspective["id"]
                link["path"] = journal["expected_preview_image_path"]
        self.project.settings["reference_links"] = links
        project_manager.save_settings(self.project)
        scene2d._save_scenes(self.project, scenes)

    def _assert_rolled_back(self, tx_dir: Path) -> None:
        self.assertFalse(tx_dir.exists())
        self.assertTrue((self.project.root_path / self.perspective["source_file_path"]).is_file())
        self.assertFalse((self.project.root_path / scene2d._source_rel(self.target_scene["id"], self.perspective["id"])).exists())
        scenes = scene2d.list_scenes(self.project)
        source = next(item for item in scenes if item["id"] == self.source_scene["id"])
        target = next(item for item in scenes if item["id"] == self.target_scene["id"])
        self.assertIn(self.perspective["id"], [item["id"] for item in source["perspectives"]])
        self.assertNotIn(self.perspective["id"], [item["id"] for item in target["perspectives"]])
        link = next(item for item in self.project.settings["reference_links"] if item["id"] == self.reference["id"])
        self.assertEqual(link["source_scene2d_id"], self.source_scene["id"])
        self.assertEqual(link["path"], self.perspective["preview_image_path"])

    def test_files_moved_restart_recovery_rolls_back_and_is_idempotent(self) -> None:
        tx_dir = self._tx_dir()
        journal = self._base_journal(tx_dir)
        self._move_files_only(journal)
        scene2d._write_move_journal(tx_dir, {**journal, "state": "files_moved"})

        scene2d.list_scenes(self.project)
        self._assert_rolled_back(tx_dir)
        scene2d.list_scenes(self.project)
        self._assert_rolled_back(tx_dir)

    def test_metadata_committing_complete_commit_rolls_forward_and_cleans(self) -> None:
        tx_dir = self._tx_dir()
        journal = self._base_journal(tx_dir)
        self._move_files_only(journal)
        self._commit_metadata(journal)
        scene2d._write_move_journal(tx_dir, {**journal, "state": "metadata_committing"})

        scene2d.list_scenes(self.project)

        self.assertFalse(tx_dir.exists())
        self.assertTrue((self.project.root_path / journal["expected_source_file_path"]).is_file())
        scenes = scene2d.list_scenes(self.project)
        occurrences = [
            scene["id"]
            for scene in scenes
            for perspective in scene["perspectives"]
            if perspective["id"] == self.perspective["id"]
        ]
        self.assertEqual(occurrences, [self.target_scene["id"]])

    def test_rollback_failure_preserves_journal_and_backups(self) -> None:
        tx_dir = self._tx_dir()
        journal = self._base_journal(tx_dir)
        self._move_files_only(journal)
        scene2d._write_move_journal(tx_dir, {**journal, "state": "files_moved"})

        real_move = shutil.move

        def fail_reverse_move(src: str, dst: str):
            if Path(src).resolve() == (self.project.root_path / journal["target_dir"]).resolve():
                raise OSError("forced reverse move failure")
            return real_move(src, dst)

        with mock.patch("storyboard_tool.scene2d.shutil.move", side_effect=fail_reverse_move):
            with self.assertRaises(RuntimeError):
                scene2d.list_scenes(self.project)

        self.assertTrue(tx_dir.is_dir())
        journal_path = tx_dir / scene2d.PERSPECTIVE_MOVE_JOURNAL
        self.assertTrue(journal_path.is_file())
        saved = json.loads(journal_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["state"], "rollback_failed")
        for entry in saved["original_files"]:
            if entry["existed"]:
                self.assertTrue((self.project.root_path / entry["backup_path"]).is_file())


if __name__ == "__main__":
    unittest.main()
