"""Focused tests for reference_segments domain module.

Covers:
- _segment_board_range validation
- normalize_ref_segments (modern list, legacy single, empty)
- find_ref_segment (by id, active id, first fallback)
- clear_active_reference_model / clear_active_reference_image
- delete_ref_segment clears provenance only for affected shots
- snapshot_boards_for_undo + restore_boards_from_undo round-trip
- apply_ref_segment_image_to_boards affects only the specified range
- deleting an unrelated reference does not clear unrelated shot metadata
"""

from __future__ import annotations

import io
import shutil
import tempfile
import unittest
from pathlib import Path

from storyboard_tool import project_manager, reference_segments
from storyboard_tool.models import Project, Shot


def _make_png(width: int = 4, height: int = 4) -> bytes:
    """Return the bytes of a valid PNG image (uses PIL)."""
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color=(100, 150, 200)).save(buf, "PNG")
    return buf.getvalue()


# Minimal valid 1×1 PNG (used only for file-existence checks, not PIL decoding).
MINI_PNG = _make_png(1, 1)


def _make_project(tmp_dir: str) -> Project:
    return project_manager.create_project(Path(tmp_dir))


# ---------------------------------------------------------------------------
# _segment_board_range
# ---------------------------------------------------------------------------

class TestSegmentBoardRange(unittest.TestCase):
    def _shots(self, n: int) -> list[Shot]:
        return [Shot(shot_id=f"s{i}") for i in range(n)]

    def test_normal_range_returns_min_max(self) -> None:
        lo, hi = reference_segments._segment_board_range(self._shots(5), 1, 3)
        self.assertEqual((lo, hi), (1, 3))

    def test_inverted_indices_are_normalized(self) -> None:
        lo, hi = reference_segments._segment_board_range(self._shots(5), 4, 1)
        self.assertEqual((lo, hi), (1, 4))

    def test_out_of_bounds_indices_are_clamped(self) -> None:
        lo, hi = reference_segments._segment_board_range(self._shots(3), -5, 99)
        self.assertEqual((lo, hi), (0, 2))

    def test_empty_shots_raises(self) -> None:
        with self.assertRaises(ValueError):
            reference_segments._segment_board_range([], 0, 0)

    def test_single_board_range_ok(self) -> None:
        lo, hi = reference_segments._segment_board_range(self._shots(1), 0, 0)
        self.assertEqual((lo, hi), (0, 0))


# ---------------------------------------------------------------------------
# normalize_ref_segments
# ---------------------------------------------------------------------------

class TestNormalizeRefSegments(unittest.TestCase):
    def test_modern_list_is_normalised(self) -> None:
        settings = {
            "ref_segments": [
                {
                    "id": "seg_a",
                    "anchor_shot_id": "s0",
                    "end_shot_id": "s2",
                    "source_type": "video",
                }
            ]
        }
        result = reference_segments.normalize_ref_segments(settings)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], "seg_a")
        self.assertEqual(result[0]["source_type"], "video")

    def test_segment_without_id_gets_one_assigned(self) -> None:
        settings = {
            "ref_segments": [
                {"anchor_shot_id": "s0", "end_shot_id": "s1", "source_type": "image"}
            ]
        }
        result = reference_segments.normalize_ref_segments(settings)
        self.assertTrue(result[0]["id"].startswith("seg_"))

    def test_segment_missing_anchor_or_end_is_dropped(self) -> None:
        settings = {
            "ref_segments": [
                {"id": "bad", "anchor_shot_id": "", "end_shot_id": "s1"},
                {"id": "good", "anchor_shot_id": "s0", "end_shot_id": "s1"},
            ]
        }
        result = reference_segments.normalize_ref_segments(settings)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], "good")

    def test_empty_ref_segments_list_returns_empty(self) -> None:
        result = reference_segments.normalize_ref_segments({"ref_segments": []})
        self.assertEqual(result, [])

    def test_no_ref_segments_key_returns_empty(self) -> None:
        result = reference_segments.normalize_ref_segments({})
        self.assertEqual(result, [])

    def test_invalid_source_type_becomes_none(self) -> None:
        settings = {
            "ref_segments": [
                {
                    "id": "seg_a",
                    "anchor_shot_id": "s0",
                    "end_shot_id": "s1",
                    "source_type": "banana",
                }
            ]
        }
        result = reference_segments.normalize_ref_segments(settings)
        self.assertEqual(result[0]["source_type"], "none")


# ---------------------------------------------------------------------------
# find_ref_segment
# ---------------------------------------------------------------------------

class TestFindRefSegment(unittest.TestCase):
    def _project_with_segments(self) -> Project:
        project = Project(root_path=Path("/fake"))
        project.settings = {
            "ref_segments": [
                {
                    "id": "seg_a",
                    "anchor_shot_id": "s0",
                    "end_shot_id": "s1",
                    "source_type": "video",
                },
                {
                    "id": "seg_b",
                    "anchor_shot_id": "s2",
                    "end_shot_id": "s3",
                    "source_type": "image",
                },
            ],
            "active_ref_segment_id": "seg_b",
        }
        return project

    def test_finds_by_explicit_id(self) -> None:
        project = self._project_with_segments()
        seg = reference_segments.find_ref_segment(project, "seg_a")
        self.assertIsNotNone(seg)
        self.assertEqual(seg["id"], "seg_a")

    def test_falls_back_to_active_when_id_none(self) -> None:
        project = self._project_with_segments()
        seg = reference_segments.find_ref_segment(project, None)
        self.assertEqual(seg["id"], "seg_b")

    def test_falls_back_to_first_when_no_active(self) -> None:
        project = self._project_with_segments()
        project.settings["active_ref_segment_id"] = ""
        seg = reference_segments.find_ref_segment(project, None)
        self.assertEqual(seg["id"], "seg_a")

    def test_returns_none_when_no_segments(self) -> None:
        project = Project(root_path=Path("/fake"))
        project.settings = {"ref_segments": []}
        self.assertIsNone(reference_segments.find_ref_segment(project, None))


# ---------------------------------------------------------------------------
# clear_active_reference_model / clear_active_reference_image
# ---------------------------------------------------------------------------

class TestClearActiveReference(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_clear_model_resets_path_and_mode(self) -> None:
        project = _make_project(self._tmp)
        project.settings["reference_model_path"] = "references/model.glb"
        project.settings["reference_segment_mode"] = "model"

        reference_segments.clear_active_reference_model(project)

        self.assertEqual(project.settings["reference_model_path"], "")
        self.assertEqual(project.settings["reference_segment_mode"], "video")

    def test_clear_model_does_not_touch_other_modes(self) -> None:
        project = _make_project(self._tmp)
        project.settings["reference_model_path"] = "references/model.glb"
        project.settings["reference_segment_mode"] = "video"

        reference_segments.clear_active_reference_model(project)

        self.assertEqual(project.settings["reference_segment_mode"], "video")

    def test_clear_image_resets_path_and_mode(self) -> None:
        project = _make_project(self._tmp)
        project.settings["reference_image_path"] = "references/ref.png"
        project.settings["reference_segment_mode"] = "image"

        reference_segments.clear_active_reference_image(project)

        self.assertEqual(project.settings["reference_image_path"], "")
        self.assertEqual(project.settings["reference_segment_mode"], "video")

    def test_clear_image_does_not_touch_other_modes(self) -> None:
        project = _make_project(self._tmp)
        project.settings["reference_image_path"] = "references/ref.png"
        project.settings["reference_segment_mode"] = "video"

        reference_segments.clear_active_reference_image(project)

        self.assertEqual(project.settings["reference_segment_mode"], "video")


# ---------------------------------------------------------------------------
# delete_ref_segment — provenance clearing
# ---------------------------------------------------------------------------

class TestDeleteRefSegment(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _make_shot_with_provenance(self, shot_id: str, seg_id: str) -> Shot:
        shot = Shot(shot_id=shot_id)
        shot.camera_data = {"ref_segment_id": seg_id, "ref_source_type": "image"}
        shot.ref_video_path = "references/ref.png"
        return shot

    def test_delete_clears_provenance_for_range_shots(self) -> None:
        project = _make_project(self._tmp)
        shot_a = self._make_shot_with_provenance("s0", "seg_a")
        shot_b = self._make_shot_with_provenance("s1", "seg_a")
        project.shots = [shot_a, shot_b]
        project.settings["ref_segments"] = [
            {
                "id": "seg_a",
                "anchor_shot_id": "s0",
                "end_shot_id": "s1",
                "source_type": "image",
                "reference_path": "references/ref.png",
            }
        ]

        reference_segments.delete_ref_segment(project, "seg_a")

        for shot in project.shots:
            cam = shot.camera_data or {}
            self.assertNotIn("ref_segment_id", cam, f"provenance not cleared for {shot.shot_id}")
            self.assertEqual(shot.ref_video_path, "", f"ref_video_path not cleared for {shot.shot_id}")

    def test_delete_does_not_clear_unrelated_shot(self) -> None:
        project = _make_project(self._tmp)
        target_shot = self._make_shot_with_provenance("s0", "seg_a")
        unrelated_shot = self._make_shot_with_provenance("s1", "seg_other")
        project.shots = [target_shot, unrelated_shot]
        project.settings["ref_segments"] = [
            {
                "id": "seg_a",
                "anchor_shot_id": "s0",
                "end_shot_id": "s0",
                "source_type": "image",
                "reference_path": "references/ref.png",
            }
        ]

        reference_segments.delete_ref_segment(project, "seg_a")

        cam_unrelated = unrelated_shot.camera_data or {}
        self.assertEqual(
            cam_unrelated.get("ref_segment_id"),
            "seg_other",
            "unrelated shot provenance must not be cleared",
        )

    def test_delete_removes_segment_from_settings(self) -> None:
        project = _make_project(self._tmp)
        project.shots = [Shot(shot_id="s0"), Shot(shot_id="s1")]
        project.settings["ref_segments"] = [
            {
                "id": "seg_a",
                "anchor_shot_id": "s0",
                "end_shot_id": "s1",
                "source_type": "none",
            }
        ]

        reference_segments.delete_ref_segment(project, "seg_a")

        remaining = reference_segments.normalize_ref_segments(project.settings)
        self.assertFalse(any(s["id"] == "seg_a" for s in remaining))

    def test_delete_nonexistent_segment_raises(self) -> None:
        project = _make_project(self._tmp)
        project.settings["ref_segments"] = []
        with self.assertRaises(ValueError):
            reference_segments.delete_ref_segment(project, "no_such_seg")


# ---------------------------------------------------------------------------
# snapshot_boards_for_undo + restore_boards_from_undo round-trip
# ---------------------------------------------------------------------------

class TestSnapshotAndRestore(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_snapshot_and_restore_round_trip(self) -> None:
        project = _make_project(self._tmp)
        # Add a second shot so we have index 0 and 1.
        project_manager.add_shot(project)
        shot = project.shots[0]
        shot_dir = project_manager.get_shot_dir(project, shot)
        shot_dir.mkdir(parents=True, exist_ok=True)
        preview_path = shot_dir / f"{shot.shot_id}_preview.png"
        preview_path.write_bytes(MINI_PNG)
        shot.preview_image_path = preview_path.relative_to(project.root_path).as_posix()

        token = reference_segments.snapshot_boards_for_undo(project, 0, 0)
        self.assertTrue(token)

        # Simulate a destructive change.
        preview_path.unlink()
        shot.preview_image_path = ""

        result = reference_segments.restore_boards_from_undo(project, token)
        self.assertEqual(result["restored"], 1)
        self.assertTrue(preview_path.is_file())

    def test_snapshot_retention_is_capped(self) -> None:
        project = _make_project(self._tmp)
        project_manager.add_shot(project)
        shot = project.shots[0]
        shot_dir = project_manager.get_shot_dir(project, shot)
        shot_dir.mkdir(parents=True, exist_ok=True)
        (shot_dir / f"{shot.shot_id}_preview.png").write_bytes(MINI_PNG)

        cap = reference_segments.MAX_REF_UNDO_SNAPSHOTS
        tokens = [reference_segments.snapshot_boards_for_undo(project, 0, 0) for _ in range(cap + 5)]

        undo_root = project.root_path / "backups" / "ref_undo"
        kept = [child for child in undo_root.iterdir() if child.is_dir()]
        self.assertLessEqual(len(kept), cap + 1)  # at most the cap (+1 protected current)
        # The most recent snapshot must survive and still be restorable.
        newest_token = tokens[-1]
        self.assertTrue((undo_root / newest_token).is_dir())
        result = reference_segments.restore_boards_from_undo(project, newest_token)
        self.assertEqual(result["restored"], 1)

    def test_restore_with_invalid_token_raises(self) -> None:
        project = _make_project(self._tmp)
        with self.assertRaises(ValueError):
            reference_segments.restore_boards_from_undo(project, "notavalidtoken")

    def test_restore_cleans_up_snapshot_dir(self) -> None:
        project = _make_project(self._tmp)
        project_manager.add_shot(project)
        shot = project.shots[0]
        shot_dir = project_manager.get_shot_dir(project, shot)
        shot_dir.mkdir(parents=True, exist_ok=True)

        token = reference_segments.snapshot_boards_for_undo(project, 0, 0)
        undo_root = project.root_path / "backups" / "ref_undo" / token
        self.assertTrue(undo_root.is_dir())

        reference_segments.restore_boards_from_undo(project, token)
        self.assertFalse(undo_root.exists(), "snapshot dir should be removed after restore")


# ---------------------------------------------------------------------------
# apply_ref_segment_image_to_boards affects only the specified shot range
# ---------------------------------------------------------------------------

class TestApplyImageSegment(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_apply_image_stamps_provenance_on_range_only(self) -> None:
        project = _make_project(self._tmp)
        # Need at least 3 shots: apply to [0..1], leave [2] untouched.
        for _ in range(3):
            project_manager.add_shot(project)
        self.assertGreaterEqual(len(project.shots), 3)

        ref_dir = project.root_path / "references"
        ref_dir.mkdir(parents=True, exist_ok=True)
        ref_image = ref_dir / "ref_test.png"
        ref_image.write_bytes(MINI_PNG)
        rel_path = ref_image.relative_to(project.root_path).as_posix()

        project.settings["ref_segments"] = [
            {
                "id": "seg_img",
                "anchor_shot_id": project.shots[0].shot_id,
                "end_shot_id": project.shots[1].shot_id,
                "source_type": "image",
                "reference_path": rel_path,
            }
        ]
        project.settings["active_ref_segment_id"] = "seg_img"

        reference_segments.apply_ref_segment_image_to_boards(
            project, 0, 1, segment_id="seg_img"
        )

        for i in range(2):
            cam = project.shots[i].camera_data or {}
            self.assertEqual(
                cam.get("ref_segment_id"),
                "seg_img",
                f"shot[{i}] should have seg_img provenance",
            )

        outside_cam = project.shots[2].camera_data or {}
        self.assertNotEqual(
            outside_cam.get("ref_segment_id"),
            "seg_img",
            "shot outside the range must not receive provenance",
        )

    def test_apply_image_with_invalid_range_raises(self) -> None:
        project = _make_project(self._tmp)
        project_manager.add_shot(project)
        project.settings["ref_segments"] = [
            {
                "id": "seg_img",
                "anchor_shot_id": project.shots[0].shot_id,
                "end_shot_id": project.shots[0].shot_id,
                "source_type": "image",
                "reference_path": "references/missing.png",
            }
        ]
        project.settings["active_ref_segment_id"] = "seg_img"
        with self.assertRaises((ValueError, FileNotFoundError)):
            reference_segments.apply_ref_segment_image_to_boards(
                project, 0, 0, segment_id="seg_img"
            )


# ---------------------------------------------------------------------------
# Deleting a reference does not clear unrelated shot metadata
# ---------------------------------------------------------------------------

class TestDeleteProjectReference(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_removing_ref_b_does_not_clear_ref_a_provenance(self) -> None:
        project = _make_project(self._tmp)
        project_manager.add_shot(project)
        ref_dir = project.root_path / "references"
        ref_dir.mkdir(parents=True, exist_ok=True)
        ref_a = ref_dir / "ref_a.png"
        ref_b = ref_dir / "ref_b.png"
        ref_a.write_bytes(MINI_PNG)
        ref_b.write_bytes(MINI_PNG)

        project.settings["reference_links"] = [
            {"id": "id_a", "title": "A", "type": "image", "path": "references/ref_a.png"},
            {"id": "id_b", "title": "B", "type": "image", "path": "references/ref_b.png"},
        ]
        project.shots[0].camera_data = {"ref_segment_id": "seg_a", "ref_source_type": "image"}
        project.shots[0].ref_video_path = "references/ref_a.png"
        project.settings["ref_segments"] = [
            {
                "id": "seg_a",
                "anchor_shot_id": project.shots[0].shot_id,
                "end_shot_id": project.shots[0].shot_id,
                "source_type": "image",
                "reference_id": "id_a",
                "reference_path": "references/ref_a.png",
            }
        ]

        reference_segments.remove_project_reference(project, "id_b")

        cam = project.shots[0].camera_data or {}
        self.assertEqual(cam.get("ref_segment_id"), "seg_a", "seg_a provenance should be intact")
        self.assertEqual(project.shots[0].ref_video_path, "references/ref_a.png")


if __name__ == "__main__":
    unittest.main()
