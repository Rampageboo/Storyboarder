"""Tests for project asset lifecycle: creation, import, deletion, and missing-file reporting."""
from __future__ import annotations

import io
import tempfile
from pathlib import Path

import pytest

from storyboard_tool import project_manager, reference_segments, shot_service
from storyboard_tool.export_utils import missing_files
from storyboard_tool.image_utils import board_background_filename


def _make_project(tmp_path: Path):
    return project_manager.create_project(tmp_path)


def _make_png_bytes(width: int = 4, height: int = 4) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (width, height), color=(80, 120, 200)).save(buf, "PNG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# create_project
# ---------------------------------------------------------------------------


class TestCreateProject:
    def setup_method(self):
        self._tmp = Path(tempfile.mkdtemp())

    def test_creates_expected_subdirectories(self):
        project = _make_project(self._tmp)
        root = project.root_path
        for dirname in ("shots", "references", "exports", "backups", "scene3d", "scenes2d", "scenes3d"):
            assert (root / dirname).is_dir(), f"expected {dirname}/ directory"

    def test_creates_project_json(self):
        project = _make_project(self._tmp)
        assert project.json_path.is_file()

    def test_creates_settings_json(self):
        project = _make_project(self._tmp)
        assert project.settings_path.is_file()

    def test_starts_with_zero_shots(self):
        project = _make_project(self._tmp)
        assert project.shots == []


# ---------------------------------------------------------------------------
# add_shot
# ---------------------------------------------------------------------------


class TestAddShot:
    def setup_method(self):
        self._tmp = Path(tempfile.mkdtemp())

    def test_shot_appears_in_project_shots(self):
        project = _make_project(self._tmp)
        shot = project_manager.add_shot(project)
        assert shot in project.shots

    def test_creates_shot_directory(self):
        project = _make_project(self._tmp)
        shot = project_manager.add_shot(project)
        assert project_manager.get_shot_dir(project, shot).is_dir()

    def test_after_index_inserts_at_correct_position(self):
        project = _make_project(self._tmp)
        s0 = project_manager.add_shot(project)
        s2 = project_manager.add_shot(project)
        # Insert after index 0 (s0) → should appear between s0 and s2
        s1 = project_manager.add_shot(project, after_index=0)
        ids = [s.shot_id for s in project.shots]
        assert ids.index(s1.shot_id) == 1
        assert ids.index(s2.shot_id) == 2


# ---------------------------------------------------------------------------
# delete_shot
# ---------------------------------------------------------------------------


class TestDeleteShot:
    def setup_method(self):
        self._tmp = Path(tempfile.mkdtemp())

    def test_removes_shot_from_project(self):
        project = _make_project(self._tmp)
        shot = project_manager.add_shot(project)
        shot_id = shot.shot_id
        shot_service.delete_shot(project, shot_id)
        assert all(s.shot_id != shot_id for s in project.shots)

    def test_unknown_shot_id_raises_value_error(self):
        project = _make_project(self._tmp)
        with pytest.raises(ValueError):
            shot_service.delete_shot(project, "nonexistent-shot-id")


# ---------------------------------------------------------------------------
# import_image_for_shot
# ---------------------------------------------------------------------------


class TestImportImageForShot:
    def setup_method(self):
        self._tmp = Path(tempfile.mkdtemp())

    def test_updates_shot_preview_fields(self):
        project = _make_project(self._tmp)
        shot = project_manager.add_shot(project)
        png_path = self._tmp / "source.png"
        png_path.write_bytes(_make_png_bytes())
        project_manager.import_image_for_shot(project, shot, png_path)
        assert shot.preview_image_path or shot.image_path

    def test_creates_preview_file_on_disk(self):
        project = _make_project(self._tmp)
        shot = project_manager.add_shot(project)
        png_path = self._tmp / "source.png"
        png_path.write_bytes(_make_png_bytes())
        project_manager.import_image_for_shot(project, shot, png_path)
        rel = shot.preview_image_path or shot.image_path
        assert rel and (project.root_path / rel).is_file()

    def test_creates_board_background_copy(self):
        project = _make_project(self._tmp)
        shot = project_manager.add_shot(project)
        png_path = self._tmp / "source.png"
        png_path.write_bytes(_make_png_bytes())
        project_manager.import_image_for_shot(project, shot, png_path)
        shot_dir = project_manager.get_shot_dir(project, shot)
        bg = shot_dir / board_background_filename(shot.shot_id)
        assert bg.is_file()

    def test_missing_source_file_raises(self):
        project = _make_project(self._tmp)
        shot = project_manager.add_shot(project)
        with pytest.raises(Exception):
            project_manager.import_image_for_shot(project, shot, self._tmp / "nonexistent.png")


# ---------------------------------------------------------------------------
# import_project_reference_stream
# ---------------------------------------------------------------------------


class TestImportProjectReferenceStream:
    def setup_method(self):
        self._tmp = Path(tempfile.mkdtemp())

    def test_adds_entry_to_reference_links(self):
        project = _make_project(self._tmp)
        entry = reference_segments.import_project_reference_stream(
            project, io.BytesIO(_make_png_bytes()), "ref.png"
        )
        links = project_manager.normalize_reference_links(project.settings.get("reference_links"))
        assert any(link["id"] == entry["id"] for link in links)

    def test_creates_file_inside_references_dir(self):
        project = _make_project(self._tmp)
        entry = reference_segments.import_project_reference_stream(
            project, io.BytesIO(_make_png_bytes()), "ref.png"
        )
        dest = project.root_path / entry["path"]
        assert dest.is_file()
        assert dest.is_relative_to(project.root_path / "references")

    def test_returns_entry_with_id_title_type_path(self):
        project = _make_project(self._tmp)
        entry = reference_segments.import_project_reference_stream(
            project, io.BytesIO(b""), "clip.mp4"
        )
        for key in ("id", "title", "type", "path"):
            assert key in entry

    def test_unsupported_extension_raises_value_error(self):
        project = _make_project(self._tmp)
        with pytest.raises(ValueError, match="(?i)supported"):
            reference_segments.import_project_reference_stream(
                project, io.BytesIO(b"bad"), "file.xyz"
            )

    def test_unsupported_extension_leaves_reference_links_unchanged(self):
        project = _make_project(self._tmp)
        before = list(project.settings.get("reference_links") or [])
        try:
            reference_segments.import_project_reference_stream(
                project, io.BytesIO(b""), "file.xyz"
            )
        except ValueError:
            pass
        after = list(project.settings.get("reference_links") or [])
        assert after == before

    def test_duplicate_filenames_produce_separate_entries(self):
        project = _make_project(self._tmp)
        e1 = reference_segments.import_project_reference_stream(
            project, io.BytesIO(_make_png_bytes()), "ref.png"
        )
        e2 = reference_segments.import_project_reference_stream(
            project, io.BytesIO(_make_png_bytes()), "ref.png"
        )
        assert e1["id"] != e2["id"]
        assert e1["path"] != e2["path"]


# ---------------------------------------------------------------------------
# remove_project_reference
# ---------------------------------------------------------------------------


class TestRemoveProjectReference:
    def setup_method(self):
        self._tmp = Path(tempfile.mkdtemp())

    def _import_image_ref(self, project):
        return reference_segments.import_project_reference_stream(
            project, io.BytesIO(_make_png_bytes()), "img.png"
        )

    def test_deletes_file_on_disk(self):
        project = _make_project(self._tmp)
        entry = self._import_image_ref(project)
        file_path = project.root_path / entry["path"]
        assert file_path.is_file()
        reference_segments.remove_project_reference(project, entry["id"])
        assert not file_path.exists()

    def test_removes_entry_from_reference_links(self):
        project = _make_project(self._tmp)
        entry = self._import_image_ref(project)
        reference_segments.remove_project_reference(project, entry["id"])
        links = project_manager.normalize_reference_links(project.settings.get("reference_links"))
        assert not any(link["id"] == entry["id"] for link in links)

    def test_unknown_ref_id_raises_value_error(self):
        project = _make_project(self._tmp)
        with pytest.raises(ValueError, match="(?i)not found"):
            reference_segments.remove_project_reference(project, "nonexistent-id")

    def test_clears_segment_source_that_referenced_deleted_file(self):
        project = _make_project(self._tmp)
        entry = reference_segments.import_project_reference_stream(
            project, io.BytesIO(b""), "clip.mp4"
        )
        project.settings["ref_segments"] = [
            {
                "id": "seg_test",
                "anchor_shot_id": "s0",
                "end_shot_id": "s0",
                "source_type": "video",
                "reference_id": entry["id"],
                "reference_path": entry["path"],
                "video_start": 0.0,
                "fit_mode": "fit",
            }
        ]
        reference_segments.remove_project_reference(project, entry["id"])
        segments = project_manager.normalize_reference_links(
            {"reference_links": project.settings.get("ref_segments") or []}
        )
        # After removal, the segment's reference_id and reference_path should be cleared
        raw_segments = project.settings.get("ref_segments") or []
        for seg in raw_segments:
            if seg.get("id") == "seg_test":
                assert not seg.get("reference_id")
                assert not seg.get("reference_path")


# ---------------------------------------------------------------------------
# missing_files
# ---------------------------------------------------------------------------


class TestMissingFiles:
    def setup_method(self):
        self._tmp = Path(tempfile.mkdtemp())

    def test_empty_project_has_no_missing_files(self):
        project = _make_project(self._tmp)
        assert missing_files(project) == []

    def test_reports_deleted_preview_file(self):
        project = _make_project(self._tmp)
        shot = project_manager.add_shot(project)
        png_path = self._tmp / "src.png"
        png_path.write_bytes(_make_png_bytes())
        project_manager.import_image_for_shot(project, shot, png_path)
        rel = shot.preview_image_path or shot.image_path
        assert rel
        (project.root_path / rel).unlink()
        found = missing_files(project)
        assert any(m["shot_id"] == shot.shot_id for m in found)

    def test_missing_source_file_is_reported(self):
        project = _make_project(self._tmp)
        shot = project_manager.add_shot(project)
        # Manually inject a stale source_file_path
        shot.source_file_path = "shots/nonexistent/nonexistent.psd"
        found = missing_files(project)
        assert any(
            m["shot_id"] == shot.shot_id and m["field"] == "source_file_path" for m in found
        )


# ---------------------------------------------------------------------------
# snapshot + restore undo
# ---------------------------------------------------------------------------


class TestSnapshotRestoreUndo:
    def setup_method(self):
        self._tmp = Path(tempfile.mkdtemp())

    def test_restore_recovers_shot_fields(self):
        project = _make_project(self._tmp)
        for _ in range(2):
            project_manager.add_shot(project)
        shots = project.shots
        original_titles = [s.title for s in shots]
        token = project_manager.snapshot_boards_for_undo(project, 0, len(shots) - 1)
        # Mutate shot titles
        for shot in shots:
            shot.title = "MUTATED"
        # Restore
        project_manager.restore_boards_from_undo(project, token)
        for i, shot in enumerate(project.shots):
            assert shot.title == original_titles[i]

    def test_invalid_token_raises(self):
        project = _make_project(self._tmp)
        with pytest.raises((FileNotFoundError, ValueError, KeyError, Exception)):
            project_manager.restore_boards_from_undo(project, "nonexistent-token-xyz")
