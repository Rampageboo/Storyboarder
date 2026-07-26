from __future__ import annotations

import contextlib
import csv
import inspect
import io
import json
import tempfile
import unittest
import warnings
from pathlib import Path
from unittest.mock import patch

with warnings.catch_warnings():
    warnings.filterwarnings("ignore", message="Using `httpx` with `starlette.testclient` is deprecated")
    from fastapi.testclient import TestClient

from storyboard_tool import api as api_module, export_service, export_utils
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

    def test_suffix_is_inserted_before_the_extension(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _make_project(tmp)
            self.assertEqual(
                export_service.resolve_output_path(project, "pdf", "_board-003"),
                project.exports_dir / "storyboard_board-003.pdf",
            )
            # Extensionless outputs (a directory) still get the suffix.
            self.assertEqual(
                export_service.resolve_output_path(project, "image_sequence", "_board-003"),
                project.exports_dir / "image_sequence_board-003",
            )


class TestScopeToBoards(unittest.TestCase):
    def _project(self, tmp: str, count: int) -> Project:
        project = _make_project(tmp)
        for index in range(count):
            _add_shot(project, chr(ord("a") + index))
        return project

    def test_empty_spec_keeps_the_whole_storyboard(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = self._project(tmp, 2)
            scoped, suffix = export_service.scope_to_boards(project, "")
            self.assertIs(scoped, project)
            self.assertEqual(suffix, "")

    def test_single_board_keeps_only_that_board_and_names_it_by_position(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = self._project(tmp, 3)
            scoped, suffix = export_service.scope_to_boards(project, "3")
            self.assertEqual([shot.shot_id for shot in scoped.shots], ["c"])
            self.assertEqual(suffix, "_board-003")
            # A view, not a copy: paths and settings still point at the real project.
            self.assertEqual(scoped.root_path, project.root_path)
            self.assertEqual(scoped.exports_dir, project.exports_dir)
            # The real project keeps every board.
            self.assertEqual(len(project.shots), 3)

    def test_range_keeps_those_boards_in_storyboard_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = self._project(tmp, 6)
            scoped, suffix = export_service.scope_to_boards(project, "2-4")
            self.assertEqual([shot.shot_id for shot in scoped.shots], ["b", "c", "d"])
            self.assertEqual(suffix, "_boards-002-004")

    def test_gappy_spec_is_ordered_by_position_not_by_how_it_was_typed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = self._project(tmp, 6)
            scoped, _ = export_service.scope_to_boards(project, "5, 1-2")
            self.assertEqual([shot.shot_id for shot in scoped.shots], ["a", "b", "e"])

    def test_selecting_every_board_keeps_the_plain_filename(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = self._project(tmp, 3)
            scoped, suffix = export_service.scope_to_boards(project, "1-3")
            self.assertEqual(len(scoped.shots), 3)
            self.assertEqual(suffix, "")

    def test_out_of_range_spec_raises_value_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = self._project(tmp, 2)
            with self.assertRaises(ValueError):
                export_service.scope_to_boards(project, "9")


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


class TestExportScopeIsWiredEverywhere(unittest.TestCase):
    """Every export the modal offers must accept a board range.

    A generating export method that silently lacks `boards` shows up only when
    the route is called, so pin the whole set here.
    """

    SCOPED_METHODS = (
        "method_export_pdf",
        "method_export_shot_list",
        "method_export_timing",
        "method_export_contact_sheet",
        "method_export_animatic",
        "method_export_image_sequence",
        "method_open_export",
        "method_resolve_board_range",
    )

    def test_every_export_method_accepts_a_board_range(self) -> None:
        from storyboard_tool.service_exports import ExportServiceMixin

        for name in self.SCOPED_METHODS:
            with self.subTest(method=name):
                parameters = inspect.signature(getattr(ExportServiceMixin, name)).parameters
                self.assertIn("boards", parameters)
                self.assertEqual(parameters["boards"].default, "")

    def _client_with_boards(self, tmp: str, count: int) -> TestClient:
        client = TestClient(api_module.create_app(Path(tmp)), raise_server_exceptions=False)
        with contextlib.redirect_stderr(io.StringIO()):
            created = client.post("/api/project/new", json={"path": str(Path(tmp) / "Scoped.sbd")})
            self.assertEqual(created.status_code, 200)
            for _ in range(count):
                client.post("/api/shots", json={})
        return client

    def test_scoped_routes_write_range_suffixed_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = self._client_with_boards(tmp, 4)
            with contextlib.redirect_stderr(io.StringIO()):
                for spec, route, expected in (
                    ("2", "/api/export/shot-list", "shot_list_board-002.csv"),
                    ("2-3", "/api/export/shot-list", "shot_list_boards-002-003.csv"),
                    ("1,4", "/api/export/timing", "timing_boards-001+004.json"),
                    ("2-3", "/api/export/image-sequence", "image_sequence_boards-002-003"),
                    ("", "/api/export/shot-list", "shot_list.csv"),
                ):
                    with self.subTest(spec=spec, route=route):
                        response = client.post(route, json={"boards": spec})
                        self.assertEqual(response.status_code, 200, response.text)
                        self.assertEqual(Path(response.json()["path"]).name, expected)

    def test_range_export_contains_only_those_boards(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = self._client_with_boards(tmp, 5)
            with contextlib.redirect_stderr(io.StringIO()):
                response = client.post("/api/export/shot-list", json={"boards": "2-4"})
            self.assertEqual(response.status_code, 200, response.text)
            rows = Path(response.json()["path"]).read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(rows) - 1, 3)  # header + three boards

    def test_bad_range_is_rejected_with_a_readable_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = self._client_with_boards(tmp, 2)
            with contextlib.redirect_stderr(io.StringIO()):
                response = client.post("/api/export/shot-list", json={"boards": "9"})
            self.assertEqual(response.status_code, 400)
            self.assertIn("this storyboard has 2", response.json()["detail"])

    def test_resolve_range_reports_selection_without_exporting(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = self._client_with_boards(tmp, 5)
            with contextlib.redirect_stderr(io.StringIO()):
                ok = client.post("/api/export/resolve-range", json={"boards": "2-4"}).json()
                everything = client.post("/api/export/resolve-range", json={"boards": ""}).json()
                bad = client.post("/api/export/resolve-range", json={"boards": "nope"}).json()

            self.assertEqual(ok["boards"], [2, 3, 4])
            self.assertEqual(ok["count"], 3)
            self.assertEqual(ok["suffix"], "_boards-002-004")
            self.assertEqual(ok["error"], "")

            self.assertEqual(everything["count"], 5)
            self.assertEqual(everything["suffix"], "")

            self.assertEqual(bad["count"], 0)
            self.assertIn("not a board number", bad["error"])
            # A bad range is reported, not raised: the dialog validates as you type.
            self.assertFalse((Path(tmp) / "exports").exists())


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


class TestBoardNumbersNotUuids(unittest.TestCase):
    """Exports identify a board by its position in the strip, never by its UUID.

    The numbers must also be the ones the user sees: a range export narrows the
    shot list, so counting that list would renumber boards 3-5 as 1-3.
    """

    def _client_with_boards(self, tmp: str, count: int) -> TestClient:
        client = TestClient(api_module.create_app(Path(tmp)), raise_server_exceptions=False)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(client.post("/api/project/new", json={"path": str(Path(tmp) / "Numbered.sbd")}).status_code, 200)
            for _ in range(count):
                client.post("/api/shots", json={})
        return client

    def test_shot_list_leads_with_the_board_number(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = self._client_with_boards(tmp, 3)
            with contextlib.redirect_stderr(io.StringIO()):
                path = Path(client.post("/api/export/shot-list", json={}).json()["path"])
            rows = list(csv.reader(path.read_text(encoding="utf-8").splitlines()))
            self.assertEqual(rows[0][0], "board")
            self.assertEqual([row[0] for row in rows[1:]], ["1", "2", "3"])

    def test_range_export_keeps_the_real_board_numbers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = self._client_with_boards(tmp, 6)
            with contextlib.redirect_stderr(io.StringIO()):
                path = Path(client.post("/api/export/shot-list", json={"boards": "3-5"}).json()["path"])
            rows = list(csv.reader(path.read_text(encoding="utf-8").splitlines()))
            # Not 1, 2, 3 — these are boards 3, 4, 5 of the storyboard.
            self.assertEqual([row[0] for row in rows[1:]], ["3", "4", "5"])

    def test_timing_json_is_keyed_by_board_number(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = self._client_with_boards(tmp, 4)
            with contextlib.redirect_stderr(io.StringIO()):
                path = Path(client.post("/api/export/timing", json={"boards": "2-3"}).json()["path"])
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual([row["board"] for row in data["shots"]], [2, 3])

    def test_image_sequence_filenames_use_board_numbers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = self._client_with_boards(tmp, 5)
            with contextlib.redirect_stderr(io.StringIO()):
                whole = Path(client.post("/api/export/image-sequence", json={}).json()["path"])
                partial = Path(client.post("/api/export/image-sequence", json={"boards": "4-5"}).json()["path"])
            self.assertEqual(
                sorted(p.name for p in whole.iterdir()),
                ["board_0001.png", "board_0002.png", "board_0003.png", "board_0004.png", "board_0005.png"],
            )
            self.assertEqual(sorted(p.name for p in partial.iterdir()), ["board_0004.png", "board_0005.png"])

    def test_no_uuid_appears_in_a_generated_filename(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = self._client_with_boards(tmp, 2)
            with contextlib.redirect_stderr(io.StringIO()):
                shot_ids = [shot["shot_id"] for shot in client.get("/api/project").json()["shots"]]
                directory = Path(client.post("/api/export/image-sequence", json={}).json()["path"])
            names = " ".join(p.name for p in directory.iterdir())
            for shot_id in shot_ids:
                self.assertNotIn(shot_id, names)


class TestNumberedShots(unittest.TestCase):
    def test_whole_project_numbers_from_one(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _make_project(tmp)
            _add_shot(project, "a")
            _add_shot(project, "b")
            self.assertEqual([number for number, _ in export_utils.numbered_shots(project)], [1, 2])

    def test_scoped_view_uses_its_recorded_positions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _make_project(tmp)
            for name in "abcdef":
                _add_shot(project, name)
            scoped, _ = export_service.scope_to_boards(project, "2, 5-6")
            self.assertEqual(
                [(number, shot.shot_id) for number, shot in export_utils.numbered_shots(scoped)],
                [(2, "b"), (5, "e"), (6, "f")],
            )

    def test_mismatched_numbering_falls_back_to_counting(self) -> None:
        # Defensive: a hand-built view must never crash an export.
        with tempfile.TemporaryDirectory() as tmp:
            project = _make_project(tmp)
            _add_shot(project, "a")
            _add_shot(project, "b")
            project.board_numbers = [7]  # too short to describe both shots
            self.assertEqual([number for number, _ in export_utils.numbered_shots(project)], [1, 2])
