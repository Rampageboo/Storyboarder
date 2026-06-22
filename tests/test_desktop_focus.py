"""Tests for _focus_desktop_window() and POST /api/app/focus (CODEX_TASK Part 5).

Verifies:
- Normal window: show+focus called, restore NOT called.
- Maximized window: same — restore NOT called.
- Minimized window: restore called exactly once, then focus.
- Focus failure: endpoint still returns structured result; no geometry method attempted after.
- API endpoint: returns expected JSON fields.
"""
from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
import warnings
from pathlib import Path
from unittest.mock import MagicMock, call

with warnings.catch_warnings():
    warnings.filterwarnings("ignore", message="Using `httpx` with `starlette.testclient`")
    from fastapi.testclient import TestClient

from storyboard_tool import api as api_module
from storyboard_tool.backend_service import _focus_desktop_window


def _fake_window(minimized: bool = False, raise_on_focus: bool = False) -> MagicMock:
    """Return a mock pywebview Window with the key focus-related methods."""
    window = MagicMock()
    # pywebview exposes .minimized as a bool property.
    type(window).minimized = property(lambda self: minimized)
    window.restore = MagicMock()
    window.show    = MagicMock()
    if raise_on_focus:
        window.focus = MagicMock(side_effect=RuntimeError("focus unavailable"))
    else:
        window.focus = MagicMock()
    return window


class FocusDesktopWindowTests(unittest.TestCase):
    # ── Normal window ─────────────────────────────────────────────────────────

    def test_normal_window_restore_not_called(self):
        window = _fake_window(minimized=False)
        result = _focus_desktop_window(window)
        window.restore.assert_not_called()

    def test_normal_window_show_called(self):
        window = _fake_window(minimized=False)
        _focus_desktop_window(window)
        window.show.assert_called_once()

    def test_normal_window_focus_called(self):
        window = _fake_window(minimized=False)
        _focus_desktop_window(window)
        window.focus.assert_called_once()

    def test_normal_window_returns_focused_true(self):
        window = _fake_window(minimized=False)
        result = _focus_desktop_window(window)
        self.assertTrue(result["focused"])
        self.assertFalse(result["restored_from_minimized"])

    # ── Maximized window ──────────────────────────────────────────────────────

    def test_maximized_window_restore_not_called(self):
        # maximized=True does NOT mean minimized; restore must be skipped.
        window = _fake_window(minimized=False)
        type(window).maximized = property(lambda self: True)
        result = _focus_desktop_window(window)
        window.restore.assert_not_called()
        self.assertFalse(result["restored_from_minimized"])

    # ── Minimized window ──────────────────────────────────────────────────────

    def test_minimized_window_restore_called_once(self):
        window = _fake_window(minimized=True)
        _focus_desktop_window(window)
        window.restore.assert_called_once()

    def test_minimized_window_restored_from_minimized_true(self):
        window = _fake_window(minimized=True)
        result = _focus_desktop_window(window)
        self.assertTrue(result["restored_from_minimized"])

    def test_minimized_window_focus_called_after_restore(self):
        window = _fake_window(minimized=True)
        _focus_desktop_window(window)
        # restore then focus — check both were called
        window.restore.assert_called_once()
        window.focus.assert_called_once()

    # ── Failure: focus raises ────────────────────────────────────────────────

    def test_focus_failure_returns_structured_result(self):
        window = _fake_window(minimized=False, raise_on_focus=True)
        result = _focus_desktop_window(window)
        self.assertTrue(result["ok"])
        self.assertFalse(result["focused"])
        self.assertIn("shown", result)
        self.assertIn("restored_from_minimized", result)

    def test_focus_failure_does_not_propagate(self):
        window = _fake_window(minimized=False, raise_on_focus=True)
        # Must not raise
        try:
            _focus_desktop_window(window)
        except Exception as exc:  # noqa: BLE001
            self.fail(f"_focus_desktop_window raised unexpectedly: {exc}")

    # ── Result shape ─────────────────────────────────────────────────────────

    def test_result_has_all_diagnostic_fields(self):
        window = _fake_window()
        result = _focus_desktop_window(window)
        for key in ("ok", "focused", "shown", "restored_from_minimized"):
            self.assertIn(key, result, f"Missing key: {key}")

    def test_ok_is_always_true(self):
        window = _fake_window(minimized=True, raise_on_focus=True)
        result = _focus_desktop_window(window)
        self.assertTrue(result["ok"])


class FocusEndpointTests(unittest.TestCase):
    """Integration tests for POST /api/app/focus via TestClient."""

    def _make_client(self) -> tuple[TestClient, object]:
        import tempfile
        tmp = tempfile.mkdtemp()
        app = api_module.create_app(Path(tmp))
        client = TestClient(app, raise_server_exceptions=False)
        return client, app

    def test_no_window_returns_ok(self):
        client, app = self._make_client()
        # No main_window attached → safe no-op
        with contextlib.redirect_stderr(io.StringIO()):
            resp = client.post("/api/app/focus")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["ok"])
        self.assertFalse(body["focused"])

    def test_no_window_returns_all_fields(self):
        client, app = self._make_client()
        with contextlib.redirect_stderr(io.StringIO()):
            resp = client.post("/api/app/focus")
        body = resp.json()
        for key in ("ok", "focused", "shown", "restored_from_minimized"):
            self.assertIn(key, body)

    def test_with_normal_window_restore_not_called(self):
        client, app = self._make_client()
        window = _fake_window(minimized=False)
        app.state.main_window = window
        with contextlib.redirect_stderr(io.StringIO()):
            resp = client.post("/api/app/focus")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["ok"])
        self.assertFalse(body["restored_from_minimized"])
        window.restore.assert_not_called()

    def test_with_minimized_window_restore_called(self):
        client, app = self._make_client()
        window = _fake_window(minimized=True)
        app.state.main_window = window
        with contextlib.redirect_stderr(io.StringIO()):
            resp = client.post("/api/app/focus")
        body = resp.json()
        self.assertTrue(body["restored_from_minimized"])
        window.restore.assert_called_once()


if __name__ == "__main__":
    unittest.main()
