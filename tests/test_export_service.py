from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from storyboard_tool import export_service
from storyboard_tool.models import Project, Shot


def _make_project(tmp: str) -> Project:
    root = Path(tmp)
    project = Project(root_path=root)
    project.exports_dir.mkdir(parents=True, exist_ok=True)
    return project


def _add_shot(project: Project, shot_id: str) -> Shot:
    shot = Shot(shot_id=shot_id)
    project.shots.append(shot)
    return shot


class TestResolveOutputPath(unittest.TestCase):
    def test_known_types_return_exports_dir_relative_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _make_project(tmp)
            cases = {
                "pdf": "storyboard.pdf",
                "shot_list": "shot_list.csv",
                "timing": "timing.json",
                "contact_sheet": "contact_sheet.png",
                "image_sequence": "image_sequence",
            }
            for export_type, filename in cases.items():
                with self.subTest(export_type=export_type):
                    path = export_service.resolve_output_path(project, export_type)
                    self.assertEqual(path, project.exports_dir / filename)

    def test_unknown_type_raises_value_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _make_project(tmp)
            with self.assertRaises(ValueError):
                export_service.resolve_output_path(project, "nonexistent")


class TestCheckExportExists(unittest.TestCase):
    def test_missing_file_raises_file_not_found(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _make_project(tmp)
            with self.assertRaises(FileNotFoundError):
                export_service.check_export_exists(project, "pdf")

    def test_existing_file_returns_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _make_project(tmp)
            output_path = export_service.resolve_output_path(project, "timing")
            output_path.write_text("{}", encoding="utf-8")
            result = export_service.check_export_exists(project, "timing")
            self.assertEqual(result, output_path)


class TestGetMissingMedia(unittest.TestCase):
    def test_no_shots_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _make_project(tmp)
            self.assertEqual(export_service.get_missing_media(project), [])

    def test_shot_with_missing_preview_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _make_project(tmp)
            shot = _add_shot(project, "shot_001")
            shot.preview_image_path = "shots/shot_001/shot_001_preview.png"
            result = export_service.get_missing_media(project)
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]["shot_id"], "shot_001")
            self.assertEqual(result[0]["field"], "preview_image_path")

    def test_existing_file_not_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _make_project(tmp)
            shot = _add_shot(project, "shot_001")
            preview_dir = project.root_path / "shots" / "shot_001"
            preview_dir.mkdir(parents=True)
            preview = preview_dir / "shot_001_preview.png"
            preview.write_bytes(b"")
            shot.preview_image_path = "shots/shot_001/shot_001_preview.png"
            result = export_service.get_missing_media(project)
            self.assertEqual(result, [])


class TestExportShotList(unittest.TestCase):
    def test_creates_csv_with_header(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _make_project(tmp)
            _add_shot(project, "shot_001")
            output_path = export_service.export_shot_list(project)
            self.assertTrue(output_path.exists())
            content = output_path.read_text(encoding="utf-8")
            self.assertIn("shot_id", content)
            self.assertIn("shot_001", content)


class TestExportTiming(unittest.TestCase):
    def test_creates_json_with_total_seconds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _make_project(tmp)
            shot = _add_shot(project, "shot_001")
            shot.duration_seconds = 3.5
            output_path = export_service.export_timing(project)
            self.assertTrue(output_path.exists())
            data = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertIn("total_seconds", data)
            self.assertIn("shots", data)
            self.assertEqual(len(data["shots"]), 1)
            self.assertAlmostEqual(data["total_seconds"], 3.5, places=2)

    def test_empty_project_produces_zero_total(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _make_project(tmp)
            output_path = export_service.export_timing(project)
            data = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(data["total_seconds"], 0.0)
            self.assertEqual(data["shots"], [])


class TestExportPdf(unittest.TestCase):
    def test_invalid_layout_falls_back_to_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _make_project(tmp)
            captured = {}

            def fake_pdf(proj, out, *, layout):
                captured["layout"] = layout
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(b"%PDF")

            with patch("storyboard_tool.pdf_exporter.export_storyboard_pdf", fake_pdf):
                export_service.export_pdf(project, "bogus_layout")

            self.assertEqual(captured["layout"], export_service.DEFAULT_PDF_LAYOUT)

    def test_valid_layout_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _make_project(tmp)
            captured = {}

            def fake_pdf(proj, out, *, layout):
                captured["layout"] = layout
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(b"%PDF")

            with patch("storyboard_tool.pdf_exporter.export_storyboard_pdf", fake_pdf):
                export_service.export_pdf(project, "one_per_page")

            self.assertEqual(captured["layout"], "one_per_page")

    def test_export_with_missing_media_still_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _make_project(tmp)
            shot = _add_shot(project, "shot_001")
            shot.preview_image_path = "shots/shot_001/shot_001_preview.png"

            def fake_pdf(proj, out, *, layout):
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(b"%PDF")

            with patch("storyboard_tool.pdf_exporter.export_storyboard_pdf", fake_pdf):
                output = export_service.export_pdf(project)

            self.assertTrue(output.exists())


if __name__ == "__main__":
    unittest.main()
