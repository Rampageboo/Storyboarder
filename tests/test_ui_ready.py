"""Tests for POST /api/app/ui-ready."""

from __future__ import annotations

import contextlib
import io
import os
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


class UiReadyTests(unittest.TestCase):
    def setUp(self) -> None:
        # Save original env so we can restore it after each test.
        self._original_token = os.environ.pop("STORYBOARDER_LAUNCH_TOKEN", None)

    def tearDown(self) -> None:
        os.environ.pop("STORYBOARDER_LAUNCH_TOKEN", None)
        if self._original_token is not None:
            os.environ["STORYBOARDER_LAUNCH_TOKEN"] = self._original_token

    def test_no_token_is_safe_noop(self) -> None:
        """Without a token the endpoint returns ok and marker_written=False."""
        with tempfile.TemporaryDirectory() as tmp:
            client = _make_client(tmp)
            with contextlib.redirect_stderr(io.StringIO()):
                resp = client.post("/api/app/ui-ready")
            self.assertEqual(resp.status_code, 200)
            body = resp.json()
            self.assertTrue(body["ok"])
            self.assertFalse(body["marker_written"])

    def test_valid_token_writes_marker(self) -> None:
        """A valid UUID token causes the ready marker to be written."""
        token = "abc123testtoken4567890"
        os.environ["STORYBOARDER_LAUNCH_TOKEN"] = token
        with tempfile.TemporaryDirectory() as tmp:
            client = _make_client(tmp)
            with contextlib.redirect_stderr(io.StringIO()):
                # A valid token now also gates state-changing /api calls, so the
                # (SPA-simulating) request must echo it.
                resp = client.post("/api/app/ui-ready", headers={"X-Storyboarder-Token": token})
            self.assertEqual(resp.status_code, 200)
            body = resp.json()
            self.assertTrue(body["ok"])
            self.assertTrue(body["marker_written"])
            marker = Path(tempfile.gettempdir()) / f"storyboarder-launch-{token}.ready"
            self.assertTrue(marker.is_file(), f"Expected marker at {marker}")
            # Clean up
            try:
                marker.unlink()
            except OSError:
                pass

    def test_invalid_token_characters_rejected(self) -> None:
        """A token with path-traversal or unusual characters is rejected gracefully."""
        os.environ["STORYBOARDER_LAUNCH_TOKEN"] = "../../etc/passwd"
        with tempfile.TemporaryDirectory() as tmp:
            client = _make_client(tmp)
            with contextlib.redirect_stderr(io.StringIO()):
                resp = client.post("/api/app/ui-ready")
            self.assertEqual(resp.status_code, 200)
            body = resp.json()
            self.assertTrue(body["ok"])
            self.assertFalse(body["marker_written"])

    def test_client_cannot_supply_arbitrary_path(self) -> None:
        """The endpoint accepts no request body; the path comes from the env var only."""
        os.environ["STORYBOARDER_LAUNCH_TOKEN"] = "validtoken123"
        with tempfile.TemporaryDirectory() as tmp:
            client = _make_client(tmp)
            # Sending a body with a path must be ignored (endpoint takes no body)
            with contextlib.redirect_stderr(io.StringIO()):
                resp = client.post(
                    "/api/app/ui-ready",
                    json={"path": "/tmp/evil"},
                    headers={"X-Storyboarder-Token": "validtoken123"},
                )
            self.assertEqual(resp.status_code, 200)
            # Only the env-var-based marker should be written, not /tmp/evil
            evil = Path("/tmp/evil")
            self.assertFalse(evil.exists())
            # Clean up the real marker
            marker = Path(tempfile.gettempdir()) / "storyboarder-launch-validtoken123.ready"
            try:
                marker.unlink()
            except OSError:
                pass

    def test_long_token_rejected(self) -> None:
        """Token over 64 characters is rejected."""
        os.environ["STORYBOARDER_LAUNCH_TOKEN"] = "a" * 65
        with tempfile.TemporaryDirectory() as tmp:
            client = _make_client(tmp)
            with contextlib.redirect_stderr(io.StringIO()):
                resp = client.post("/api/app/ui-ready")
            self.assertEqual(resp.status_code, 200)
            body = resp.json()
            self.assertFalse(body["marker_written"])


if __name__ == "__main__":
    unittest.main()
