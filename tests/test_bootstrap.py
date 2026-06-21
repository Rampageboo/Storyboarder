"""Tests for GET /api/app/bootstrap."""

from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
import warnings
from pathlib import Path

with warnings.catch_warnings():
    warnings.filterwarnings("ignore", message="Using `httpx` with `starlette.testclient` is deprecated")
    from fastapi.testclient import TestClient

from storyboard_tool import api as api_module


def _make_client(tmp: str) -> TestClient:
    app = api_module.create_app(Path(tmp))
    return TestClient(app, raise_server_exceptions=False)


class BootstrapTests(unittest.TestCase):
    def test_no_project_no_session_returns_null_project(self) -> None:
        """Bootstrap with no open project and no session path returns project: null."""
        with tempfile.TemporaryDirectory() as tmp:
            client = _make_client(tmp)
            with contextlib.redirect_stderr(io.StringIO()):
                resp = client.get("/api/app/bootstrap")
            self.assertEqual(resp.status_code, 200)
            body = resp.json()
            self.assertIsNone(body["project"])
            self.assertFalse(body["opened_last_project"])
            self.assertIsInstance(body["session"], dict)
            self.assertIsInstance(body["startup_timings"], dict)

    def test_existing_open_project_returned_without_reopening(self) -> None:
        """If a project is already open, bootstrap returns it without re-opening."""
        with tempfile.TemporaryDirectory() as tmp:
            client = _make_client(tmp)
            with contextlib.redirect_stderr(io.StringIO()):
                created = client.post("/api/project/new", json={"path": tmp})
            self.assertEqual(created.status_code, 200)
            project_json = created.json()["project_json_path"]

            with contextlib.redirect_stderr(io.StringIO()):
                resp = client.get("/api/app/bootstrap")
            self.assertEqual(resp.status_code, 200)
            body = resp.json()
            self.assertIsNotNone(body["project"])
            self.assertEqual(body["project"]["project_json_path"], project_json)
            self.assertFalse(body["opened_last_project"])

    def test_valid_last_project_path_opens_project(self) -> None:
        """Bootstrap opens the project at last_project_json_path when no project is loaded."""
        with tempfile.TemporaryDirectory() as tmp:
            # First client: create project and record session
            client1 = _make_client(tmp)
            with contextlib.redirect_stderr(io.StringIO()):
                created = client1.post("/api/project/new", json={"path": tmp})
            self.assertEqual(created.status_code, 200)
            project_json = created.json()["project_json_path"]

            # Persist the path to session manually
            with contextlib.redirect_stderr(io.StringIO()):
                client1.put("/api/app/session", json={"last_project_json_path": project_json})

            # Second client: no project in memory but session has last path
            client2 = _make_client(tmp)
            with contextlib.redirect_stderr(io.StringIO()):
                resp = client2.get("/api/app/bootstrap")
            self.assertEqual(resp.status_code, 200)
            body = resp.json()
            self.assertIsNotNone(body["project"])
            self.assertEqual(body["project"]["project_json_path"], project_json)
            self.assertTrue(body["opened_last_project"])

    def test_missing_last_project_path_returns_null_with_warning(self) -> None:
        """Bootstrap with a missing/invalid last project path returns project: null non-fatally."""
        with tempfile.TemporaryDirectory() as tmp:
            client = _make_client(tmp)
            # Write a last path that doesn't exist
            with contextlib.redirect_stderr(io.StringIO()):
                client.put("/api/app/session", json={"last_project_json_path": "/nonexistent/project.json"})

            client2 = _make_client(tmp)
            with contextlib.redirect_stderr(io.StringIO()):
                resp = client2.get("/api/app/bootstrap")
            self.assertEqual(resp.status_code, 200)
            body = resp.json()
            self.assertIsNone(body["project"])
            self.assertFalse(body["opened_last_project"])
            # A non-fatal warning should be present
            self.assertIn("warning", body)

    def test_startup_timings_present(self) -> None:
        """Bootstrap always includes startup_timings with timing keys."""
        with tempfile.TemporaryDirectory() as tmp:
            client = _make_client(tmp)
            with contextlib.redirect_stderr(io.StringIO()):
                resp = client.get("/api/app/bootstrap")
            self.assertEqual(resp.status_code, 200)
            timings = resp.json()["startup_timings"]
            self.assertIn("total_ms", timings)
            self.assertIn("session_load_ms", timings)
            self.assertIn("project_load_ms", timings)
            self.assertGreaterEqual(timings["total_ms"], 0)


if __name__ == "__main__":
    unittest.main()
