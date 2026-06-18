from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
import warnings
from pathlib import Path
from unittest.mock import patch

with warnings.catch_warnings():
    warnings.filterwarnings("ignore", message="Using `httpx` with `starlette.testclient` is deprecated")
    from fastapi.testclient import TestClient

from storyboard_tool import api as api_module


def _make_client(tmp: str) -> TestClient:
    return TestClient(api_module.create_app(Path(tmp)), raise_server_exceptions=False)


def _quiet(fn):
    with contextlib.redirect_stderr(io.StringIO()):
        return fn()


class TestNoProjectError(unittest.TestCase):
    def test_get_project_without_open_project_returns_code(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _make_client(tmp)
            response = _quiet(lambda: client.get("/api/project"))
            self.assertEqual(response.status_code, 400)
            body = response.json()
            self.assertEqual(body.get("code"), "PROJECT_NOT_OPEN")
            self.assertIn("detail", body)

    def test_save_project_without_open_project_returns_code(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _make_client(tmp)
            response = _quiet(lambda: client.post("/api/project/save"))
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json().get("code"), "PROJECT_NOT_OPEN")

    def test_error_body_has_both_detail_and_code(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = _make_client(tmp)
            response = _quiet(lambda: client.get("/api/project/missing-files"))
            self.assertEqual(response.status_code, 400)
            body = response.json()
            self.assertIn("detail", body)
            self.assertIn("code", body)
            self.assertIsInstance(body["detail"], str)


class TestShotNotFoundError(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.client = _make_client(self._tmp.name)
        response = _quiet(lambda: self.client.post("/api/project/new", json={"path": self._tmp.name}))
        self.assertEqual(response.status_code, 200)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_delete_nonexistent_shot(self) -> None:
        response = _quiet(lambda: self.client.delete("/api/shots/no_such_shot"))
        self.assertEqual(response.status_code, 404)
        body = response.json()
        self.assertEqual(body.get("code"), "SHOT_NOT_FOUND")
        self.assertIn("detail", body)

    def test_patch_nonexistent_shot(self) -> None:
        response = _quiet(lambda: self.client.patch("/api/shots/no_such_shot", json={"title": "X"}))
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json().get("code"), "SHOT_NOT_FOUND")

    def test_duplicate_nonexistent_shot(self) -> None:
        response = _quiet(lambda: self.client.post("/api/shots/no_such_shot/duplicate"))
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json().get("code"), "SHOT_NOT_FOUND")

    def test_apply_ref_segment_unknown_shots(self) -> None:
        response = _quiet(lambda: self.client.post(
            "/api/project/ref-segment/apply",
            json={"anchor_shot_id": "bad_a", "end_shot_id": "bad_b"},
        ))
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json().get("code"), "SHOT_NOT_FOUND")


class TestInvalidProjectOperation(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.client = _make_client(self._tmp.name)
        response = _quiet(lambda: self.client.post("/api/project/new", json={"path": self._tmp.name}))
        self.assertEqual(response.status_code, 200)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_reorder_with_unknown_ids_returns_invalid_request(self) -> None:
        with patch(
            "storyboard_tool.project_manager.reorder_shots",
            side_effect=ValueError("Unknown shot ID: fake_id"),
        ):
            response = _quiet(lambda: self.client.post("/api/shots/reorder", json={"shot_ids": ["fake_id"]}))
        self.assertEqual(response.status_code, 400)
        body = response.json()
        self.assertEqual(body.get("code"), "INVALID_REQUEST")
        self.assertIn("detail", body)

    def test_restore_shot_failure_returns_invalid_request(self) -> None:
        with patch(
            "storyboard_tool.project_manager.restore_shot",
            side_effect=ValueError("Invalid shot data"),
        ):
            response = _quiet(lambda: self.client.post(
                "/api/shots/restore",
                json={"shot": {"shot_id": "fake"}, "index": 0},
            ))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json().get("code"), "INVALID_REQUEST")


class TestMediaNotFoundError(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.client = _make_client(self._tmp.name)
        response = _quiet(lambda: self.client.post("/api/project/new", json={"path": self._tmp.name}))
        self.assertEqual(response.status_code, 200)
        # Add a shot to the project for these tests.
        add = _quiet(lambda: self.client.post("/api/shots", json={}))
        self.assertEqual(add.status_code, 200)
        self.shot_id = add.json()["shot"]["shot_id"]

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_open_source_no_source_file(self) -> None:
        # add_shot always creates a canvas (source_file_path is set), so mock _find_shot
        # to return a bare shot with no source_file_path to exercise the MEDIA_NOT_FOUND path.
        from storyboard_tool.models import Shot
        bare = Shot(shot_id=self.shot_id)
        with patch("storyboard_tool.app_state._find_shot", return_value=bare):
            response = _quiet(lambda: self.client.post(f"/api/shots/{self.shot_id}/open-source"))
        self.assertEqual(response.status_code, 400)
        body = response.json()
        self.assertEqual(body.get("code"), "MEDIA_NOT_FOUND")
        self.assertIn("source file", body.get("detail", "").lower())

    def test_open_preview_no_preview_image(self) -> None:
        response = _quiet(lambda: self.client.post(f"/api/shots/{self.shot_id}/open-preview"))
        self.assertEqual(response.status_code, 400)
        body = response.json()
        self.assertEqual(body.get("code"), "MEDIA_NOT_FOUND")

    def test_get_shot_image_no_image(self) -> None:
        response = _quiet(lambda: self.client.get(f"/api/shots/{self.shot_id}/image"))
        self.assertEqual(response.status_code, 404)
        body = response.json()
        self.assertEqual(body.get("code"), "MEDIA_NOT_FOUND")


class TestExportError(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.client = _make_client(self._tmp.name)
        response = _quiet(lambda: self.client.post("/api/project/new", json={"path": self._tmp.name}))
        self.assertEqual(response.status_code, 200)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_export_shot_list_failure_returns_export_failed(self) -> None:
        with patch(
            "storyboard_tool.service_exports.export_shot_list_csv",
            side_effect=RuntimeError("disk full"),
        ):
            response = _quiet(lambda: self.client.post("/api/export/shot-list"))
        self.assertEqual(response.status_code, 500)
        body = response.json()
        self.assertEqual(body.get("code"), "EXPORT_FAILED")
        self.assertIn("detail", body)

    def test_export_timing_failure_returns_export_failed(self) -> None:
        with patch(
            "storyboard_tool.service_exports.export_timing_json",
            side_effect=OSError("permission denied"),
        ):
            response = _quiet(lambda: self.client.post("/api/export/timing"))
        self.assertEqual(response.status_code, 500)
        body = response.json()
        self.assertEqual(body.get("code"), "EXPORT_FAILED")


if __name__ == "__main__":
    unittest.main()
