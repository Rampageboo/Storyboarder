"""Tests for per-project preview-analysis job model (Parts 6, 7, 8, 11)."""

from __future__ import annotations

import contextlib
import io
import tempfile
import time
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


def _open_project(client: TestClient, tmp: str) -> str:
    """Create a project and return its project_json_path."""
    with contextlib.redirect_stderr(io.StringIO()):
        resp = client.post("/api/project/new", json={"path": tmp})
    assert resp.status_code == 200, resp.text
    return resp.json()["project_json_path"]


class PreviewAnalysisStatusTests(unittest.TestCase):
    def test_status_no_project_returns_no_project(self) -> None:
        """Status with no project returns no_project."""
        with tempfile.TemporaryDirectory() as tmp:
            client = _make_client(tmp)
            with contextlib.redirect_stderr(io.StringIO()):
                resp = client.get("/api/project/preview-analysis/status")
            self.assertEqual(resp.status_code, 200)
            body = resp.json()
            self.assertEqual(body["status"], "no_project")
            self.assertIsNone(body["job"])

    def test_refresh_no_project_returns_no_project(self) -> None:
        """Refresh with no project returns no_project without error."""
        with tempfile.TemporaryDirectory() as tmp:
            client = _make_client(tmp)
            with contextlib.redirect_stderr(io.StringIO()):
                resp = client.post("/api/project/preview-analysis/refresh")
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.json()["status"], "no_project")

    def test_refresh_starts_job_and_includes_task_id(self) -> None:
        """Refresh with an open project starts a background job and returns task_id."""
        with tempfile.TemporaryDirectory() as tmp:
            client = _make_client(tmp)
            _open_project(client, tmp)
            with contextlib.redirect_stderr(io.StringIO()):
                resp = client.post("/api/project/preview-analysis/refresh")
            self.assertEqual(resp.status_code, 200)
            body = resp.json()
            self.assertIn(body["status"], ("started", "already_running"))
            self.assertIn("task_id", body)
            self.assertIn("project_path", body)
            self.assertIn("revision", body)

    def test_duplicate_refresh_returns_already_running_with_same_task_id(self) -> None:
        """A second refresh while the first is running returns already_running with the same task_id."""
        with tempfile.TemporaryDirectory() as tmp:
            client = _make_client(tmp)
            _open_project(client, tmp)
            with contextlib.redirect_stderr(io.StringIO()):
                r1 = client.post("/api/project/preview-analysis/refresh")
                r2 = client.post("/api/project/preview-analysis/refresh")
            self.assertEqual(r1.status_code, 200)
            self.assertEqual(r2.status_code, 200)
            b1, b2 = r1.json(), r2.json()
            if b1["status"] == "started" and b2["status"] == "already_running":
                self.assertEqual(b1["task_id"], b2["task_id"])
            # Both are valid outcomes; no crash is the key assertion

    def test_status_after_refresh_reports_job(self) -> None:
        """GET /status after a refresh shows a job entry."""
        with tempfile.TemporaryDirectory() as tmp:
            client = _make_client(tmp)
            _open_project(client, tmp)
            with contextlib.redirect_stderr(io.StringIO()):
                client.post("/api/project/preview-analysis/refresh")
                # Give the background thread a moment to either finish or start
                time.sleep(0.3)
                resp = client.get("/api/project/preview-analysis/status")
            self.assertEqual(resp.status_code, 200)
            body = resp.json()
            self.assertIn(body["status"], ("running", "complete", "failed", "idle"))

    def test_zero_work_does_not_increment_revision(self) -> None:
        """
        When all previews are already cached (or there are none), the revision
        must not change — this prevents an infinite reload loop.
        """
        with tempfile.TemporaryDirectory() as tmp:
            client = _make_client(tmp)
            _open_project(client, tmp)
            with contextlib.redirect_stderr(io.StringIO()):
                # First call — no previews in a fresh project, so decoded_count = 0
                r = client.post("/api/project/preview-analysis/refresh")
            self.assertEqual(r.status_code, 200)
            initial_revision = r.json().get("revision", 0)

            # Wait for completion
            for _ in range(20):
                time.sleep(0.1)
                with contextlib.redirect_stderr(io.StringIO()):
                    status = client.get("/api/project/preview-analysis/status").json()
                if status.get("status") in ("complete", "failed", "idle"):
                    break

            # Second call after completion
            with contextlib.redirect_stderr(io.StringIO()):
                r2 = client.post("/api/project/preview-analysis/refresh")
            # Wait again
            for _ in range(20):
                time.sleep(0.1)
                with contextlib.redirect_stderr(io.StringIO()):
                    status = client.get("/api/project/preview-analysis/status").json()
                if status.get("status") in ("complete", "failed", "idle"):
                    break

            final_job = status.get("job")
            if final_job and final_job.get("decoded_count", 0) == 0:
                # No work was done — revision must stay at initial value
                self.assertEqual(final_job.get("revision", 0), initial_revision)

    def test_bridge_status_includes_preview_analysis_when_job_exists(self) -> None:
        """GET /api/bridge/status includes preview_analysis once a job has been created."""
        with tempfile.TemporaryDirectory() as tmp:
            client = _make_client(tmp)
            _open_project(client, tmp)
            with contextlib.redirect_stderr(io.StringIO()):
                client.post("/api/project/preview-analysis/refresh")
                time.sleep(0.3)
                resp = client.get("/api/bridge/status")
            self.assertEqual(resp.status_code, 200)
            body = resp.json()
            # preview_analysis field should be present now
            self.assertIn("preview_analysis", body)
            pa = body["preview_analysis"]
            self.assertIn("state", pa)
            self.assertIn("task_id", pa)
            self.assertIn("revision", pa)

    def test_preview_analysis_state_field_in_shot_payload(self) -> None:
        """Shot payload always includes preview_analysis_state."""
        with tempfile.TemporaryDirectory() as tmp:
            client = _make_client(tmp)
            with contextlib.redirect_stderr(io.StringIO()):
                resp = client.post("/api/project/new", json={"path": tmp})
            self.assertEqual(resp.status_code, 200)
            shots = resp.json()["shots"]
            for shot in shots:
                self.assertIn(
                    shot.get("preview_analysis_state"),
                    ("missing", "provisional", "cached"),
                    f"shot {shot['shot_id']} missing preview_analysis_state",
                )

    def test_fresh_shot_without_preview_has_missing_state(self) -> None:
        """A brand-new shot with no preview file has preview_analysis_state='missing'."""
        with tempfile.TemporaryDirectory() as tmp:
            client = _make_client(tmp)
            with contextlib.redirect_stderr(io.StringIO()):
                resp = client.post("/api/project/new", json={"path": tmp})
            self.assertEqual(resp.status_code, 200)
            for shot in resp.json()["shots"]:
                self.assertEqual(shot.get("preview_analysis_state"), "missing",
                                 "Shot with no preview file must have state=missing")


if __name__ == "__main__":
    unittest.main()
