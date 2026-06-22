"""Tests for _focus_desktop_window(), state helpers, and POST /api/app/focus.

Matches the real pywebview surface: window.restore(), window.show() only.
There is no callable window.focus() — pywebview uses 'focus' as a config value.
"""
from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
import warnings
from pathlib import Path
from unittest.mock import MagicMock

with warnings.catch_warnings():
    warnings.filterwarnings("ignore", message="Using `httpx` with `starlette.testclient`")
    from fastapi.testclient import TestClient

from storyboard_tool import api as api_module
from storyboard_tool.backend_service import (
    _focus_desktop_window,
    _get_main_window_state,
    _set_main_window_state,
)


def _fake_window(raise_on_restore: bool = False, raise_on_show: bool = False) -> MagicMock:
    """Return a mock matching the real pywebview Window focus surface.

    Real pywebview Window exposes restore(), show(), resize(), move(), maximize()
    as methods. 'focus' is a configuration attribute, not a callable method.
    """
    window = MagicMock(spec=["restore", "show", "resize", "move", "maximize"])
    if raise_on_restore:
        window.restore = MagicMock(side_effect=RuntimeError("restore unavailable"))
    else:
        window.restore = MagicMock()
    if raise_on_show:
        window.show = MagicMock(side_effect=RuntimeError("show unavailable"))
    else:
        window.show = MagicMock()
    window.resize = MagicMock()
    window.move = MagicMock()
    window.maximize = MagicMock()
    return window


class FocusDesktopWindowNormalTests(unittest.TestCase):
    """Normal window state: restore must not be called."""

    def test_restore_not_called(self):
        window = _fake_window()
        _focus_desktop_window(window, window_state="normal")
        window.restore.assert_not_called()

    def test_show_called_once(self):
        window = _fake_window()
        _focus_desktop_window(window, window_state="normal")
        window.show.assert_called_once()

    def test_resize_not_called(self):
        window = _fake_window()
        _focus_desktop_window(window, window_state="normal")
        window.resize.assert_not_called()

    def test_move_not_called(self):
        window = _fake_window()
        _focus_desktop_window(window, window_state="normal")
        window.move.assert_not_called()

    def test_maximize_not_called(self):
        window = _fake_window()
        _focus_desktop_window(window, window_state="normal")
        window.maximize.assert_not_called()

    def test_restored_from_minimized_false(self):
        window = _fake_window()
        result = _focus_desktop_window(window, window_state="normal")
        self.assertFalse(result["restored_from_minimized"])

    def test_window_state_after_remains_normal(self):
        window = _fake_window()
        result = _focus_desktop_window(window, window_state="normal")
        self.assertEqual(result["window_state_after"], "normal")

    def test_activation_requested_true(self):
        window = _fake_window()
        result = _focus_desktop_window(window, window_state="normal")
        self.assertTrue(result["activation_requested"])


class FocusDesktopWindowMaximizedTests(unittest.TestCase):
    """Maximized window state: restore must not be called."""

    def test_restore_not_called(self):
        window = _fake_window()
        _focus_desktop_window(window, window_state="maximized")
        window.restore.assert_not_called()

    def test_show_called_once(self):
        window = _fake_window()
        _focus_desktop_window(window, window_state="maximized")
        window.show.assert_called_once()

    def test_restored_from_minimized_false(self):
        window = _fake_window()
        result = _focus_desktop_window(window, window_state="maximized")
        self.assertFalse(result["restored_from_minimized"])

    def test_window_state_after_remains_maximized(self):
        window = _fake_window()
        result = _focus_desktop_window(window, window_state="maximized")
        self.assertEqual(result["window_state_after"], "maximized")


class FocusDesktopWindowMinimizedTests(unittest.TestCase):
    """Minimized window state: restore then show."""

    def test_restore_called_once(self):
        window = _fake_window()
        _focus_desktop_window(window, window_state="minimized")
        window.restore.assert_called_once()

    def test_show_called_once(self):
        window = _fake_window()
        _focus_desktop_window(window, window_state="minimized")
        window.show.assert_called_once()

    def test_restored_from_minimized_true(self):
        window = _fake_window()
        result = _focus_desktop_window(window, window_state="minimized")
        self.assertTrue(result["restored_from_minimized"])

    def test_window_state_after_is_normal(self):
        window = _fake_window()
        result = _focus_desktop_window(window, window_state="minimized")
        self.assertEqual(result["window_state_after"], "normal")

    def test_activation_requested_true(self):
        window = _fake_window()
        result = _focus_desktop_window(window, window_state="minimized")
        self.assertTrue(result["activation_requested"])


class FocusDesktopWindowRestoreFailureTests(unittest.TestCase):
    """Restore raises: show is still attempted, state does not falsely become normal."""

    def test_show_still_called_after_restore_failure(self):
        window = _fake_window(raise_on_restore=True)
        _focus_desktop_window(window, window_state="minimized")
        window.show.assert_called_once()

    def test_restored_from_minimized_false_on_restore_failure(self):
        window = _fake_window(raise_on_restore=True)
        result = _focus_desktop_window(window, window_state="minimized")
        self.assertFalse(result["restored_from_minimized"])

    def test_window_state_after_stays_minimized_on_restore_failure(self):
        window = _fake_window(raise_on_restore=True)
        result = _focus_desktop_window(window, window_state="minimized")
        self.assertEqual(result["window_state_after"], "minimized")

    def test_structured_result_returned(self):
        window = _fake_window(raise_on_restore=True)
        result = _focus_desktop_window(window, window_state="minimized")
        self.assertTrue(result["ok"])
        self.assertIn("shown", result)
        self.assertIn("restored_from_minimized", result)

    def test_no_exception_escapes(self):
        window = _fake_window(raise_on_restore=True)
        try:
            _focus_desktop_window(window, window_state="minimized")
        except Exception as exc:
            self.fail(f"_focus_desktop_window raised unexpectedly: {exc}")


class FocusDesktopWindowShowFailureTests(unittest.TestCase):
    """Show raises: no exception escapes, activation_requested is false."""

    def test_no_exception_escapes(self):
        window = _fake_window(raise_on_show=True)
        try:
            _focus_desktop_window(window, window_state="normal")
        except Exception as exc:
            self.fail(f"_focus_desktop_window raised unexpectedly: {exc}")

    def test_activation_requested_false(self):
        window = _fake_window(raise_on_show=True)
        result = _focus_desktop_window(window, window_state="normal")
        self.assertFalse(result["activation_requested"])

    def test_geometry_methods_untouched(self):
        window = _fake_window(raise_on_show=True)
        _focus_desktop_window(window, window_state="normal")
        window.resize.assert_not_called()
        window.move.assert_not_called()
        window.maximize.assert_not_called()

    def test_ok_still_true(self):
        window = _fake_window(raise_on_show=True)
        result = _focus_desktop_window(window, window_state="normal")
        self.assertTrue(result["ok"])


class FocusDesktopWindowResultShapeTests(unittest.TestCase):
    """Result always has the full diagnostic shape."""

    def test_all_diagnostic_fields_present(self):
        window = _fake_window()
        result = _focus_desktop_window(window, window_state="normal")
        for key in ("ok", "shown", "activation_requested", "focused",
                    "restored_from_minimized", "window_state_before", "window_state_after"):
            self.assertIn(key, result, f"Missing key: {key}")

    def test_ok_always_true(self):
        window = _fake_window(raise_on_restore=True, raise_on_show=True)
        result = _focus_desktop_window(window, window_state="minimized")
        self.assertTrue(result["ok"])

    def test_window_state_before_recorded(self):
        window = _fake_window()
        result = _focus_desktop_window(window, window_state="maximized")
        self.assertEqual(result["window_state_before"], "maximized")


class WindowStateHelpersTests(unittest.TestCase):
    """_set_main_window_state / _get_main_window_state helper tests (Part 6)."""

    def _make_app(self):
        tmp = tempfile.mkdtemp()
        return api_module.create_app(Path(tmp))

    def test_default_state_is_normal(self):
        app = self._make_app()
        self.assertEqual(_get_main_window_state(app), "normal")

    def test_set_minimized(self):
        app = self._make_app()
        _set_main_window_state(app, "minimized")
        self.assertEqual(_get_main_window_state(app), "minimized")

    def test_set_maximized(self):
        app = self._make_app()
        _set_main_window_state(app, "maximized")
        self.assertEqual(_get_main_window_state(app), "maximized")

    def test_set_restored_to_normal(self):
        app = self._make_app()
        _set_main_window_state(app, "minimized")
        _set_main_window_state(app, "normal")
        self.assertEqual(_get_main_window_state(app), "normal")

    def test_shown_does_not_replace_maximized(self):
        app = self._make_app()
        _set_main_window_state(app, "maximized")
        # Simulate _mark_shown logic: only update if not maximized or minimized
        state = _get_main_window_state(app)
        if state not in {"maximized", "minimized"}:
            _set_main_window_state(app, "normal")
        self.assertEqual(_get_main_window_state(app), "maximized")

    def test_invalid_state_ignored(self):
        app = self._make_app()
        _set_main_window_state(app, "normal")
        _set_main_window_state(app, "flying")
        self.assertEqual(_get_main_window_state(app), "normal")


class FocusEndpointTests(unittest.TestCase):
    """Integration tests for POST /api/app/focus via TestClient."""

    def _make_client(self) -> tuple[TestClient, object]:
        tmp = tempfile.mkdtemp()
        app = api_module.create_app(Path(tmp))
        client = TestClient(app, raise_server_exceptions=False)
        return client, app

    def test_no_window_returns_ok(self):
        client, app = self._make_client()
        with contextlib.redirect_stderr(io.StringIO()):
            resp = client.post("/api/app/focus")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["ok"])

    def test_no_window_returns_all_fields(self):
        client, app = self._make_client()
        with contextlib.redirect_stderr(io.StringIO()):
            resp = client.post("/api/app/focus")
        body = resp.json()
        for key in ("ok", "shown", "activation_requested", "focused",
                    "restored_from_minimized", "window_state_before", "window_state_after"):
            self.assertIn(key, body)

    def test_no_window_not_focused(self):
        client, app = self._make_client()
        with contextlib.redirect_stderr(io.StringIO()):
            resp = client.post("/api/app/focus")
        self.assertFalse(resp.json()["focused"])

    def test_normal_window_restore_not_called(self):
        client, app = self._make_client()
        window = _fake_window()
        app.state.main_window = window
        app.state.main_window_state = "normal"
        with contextlib.redirect_stderr(io.StringIO()):
            resp = client.post("/api/app/focus")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["ok"])
        self.assertFalse(body["restored_from_minimized"])
        window.restore.assert_not_called()

    def test_maximized_window_restore_not_called(self):
        client, app = self._make_client()
        window = _fake_window()
        app.state.main_window = window
        app.state.main_window_state = "maximized"
        with contextlib.redirect_stderr(io.StringIO()):
            resp = client.post("/api/app/focus")
        body = resp.json()
        self.assertFalse(body["restored_from_minimized"])
        self.assertEqual(body["window_state_after"], "maximized")
        window.restore.assert_not_called()

    def test_minimized_window_restore_called(self):
        client, app = self._make_client()
        window = _fake_window()
        app.state.main_window = window
        app.state.main_window_state = "minimized"
        with contextlib.redirect_stderr(io.StringIO()):
            resp = client.post("/api/app/focus")
        body = resp.json()
        self.assertTrue(body["restored_from_minimized"])
        self.assertEqual(body["window_state_after"], "normal")
        window.restore.assert_called_once()

    def test_minimized_restore_updates_app_state(self):
        client, app = self._make_client()
        window = _fake_window()
        app.state.main_window = window
        app.state.main_window_state = "minimized"
        with contextlib.redirect_stderr(io.StringIO()):
            client.post("/api/app/focus")
        self.assertEqual(_get_main_window_state(app), "normal")


if __name__ == "__main__":
    unittest.main()
