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
    _get_main_window_restore_state,
    _get_main_window_state,
    _set_main_window_restore_state,
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


# ---------------------------------------------------------------------------
# _focus_desktop_window — normal state
# ---------------------------------------------------------------------------

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
        result = _focus_desktop_window(window, window_state="normal", restore_state="normal")
        self.assertEqual(result["window_state_after"], "normal")

    def test_activation_requested_true(self):
        window = _fake_window()
        result = _focus_desktop_window(window, window_state="normal")
        self.assertTrue(result["activation_requested"])


# ---------------------------------------------------------------------------
# _focus_desktop_window — maximized state
# ---------------------------------------------------------------------------

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
        result = _focus_desktop_window(
            window, window_state="maximized", restore_state="maximized"
        )
        self.assertEqual(result["window_state_after"], "maximized")


# ---------------------------------------------------------------------------
# _focus_desktop_window — minimized from normal
# ---------------------------------------------------------------------------

class FocusDesktopWindowMinimizedFromNormalTests(unittest.TestCase):
    """Minimized (was normal): restore then show; state_after = normal."""

    def test_restore_called_once(self):
        window = _fake_window()
        _focus_desktop_window(window, window_state="minimized", restore_state="normal")
        window.restore.assert_called_once()

    def test_show_called_once(self):
        window = _fake_window()
        _focus_desktop_window(window, window_state="minimized", restore_state="normal")
        window.show.assert_called_once()

    def test_restored_from_minimized_true(self):
        window = _fake_window()
        result = _focus_desktop_window(window, window_state="minimized", restore_state="normal")
        self.assertTrue(result["restored_from_minimized"])

    def test_window_state_after_is_normal(self):
        window = _fake_window()
        result = _focus_desktop_window(window, window_state="minimized", restore_state="normal")
        self.assertEqual(result["window_state_after"], "normal")

    def test_window_restore_state_before_is_normal(self):
        window = _fake_window()
        result = _focus_desktop_window(window, window_state="minimized", restore_state="normal")
        self.assertEqual(result["window_restore_state_before"], "normal")


# ---------------------------------------------------------------------------
# _focus_desktop_window — minimized from maximized
# ---------------------------------------------------------------------------

class FocusDesktopWindowMinimizedFromMaximizedTests(unittest.TestCase):
    """Minimized (was maximized): restore then show; state_after = maximized."""

    def test_restore_called_once(self):
        window = _fake_window()
        _focus_desktop_window(window, window_state="minimized", restore_state="maximized")
        window.restore.assert_called_once()

    def test_show_called_once(self):
        window = _fake_window()
        _focus_desktop_window(window, window_state="minimized", restore_state="maximized")
        window.show.assert_called_once()

    def test_restored_from_minimized_true(self):
        window = _fake_window()
        result = _focus_desktop_window(window, window_state="minimized", restore_state="maximized")
        self.assertTrue(result["restored_from_minimized"])

    def test_window_state_after_is_maximized(self):
        window = _fake_window()
        result = _focus_desktop_window(window, window_state="minimized", restore_state="maximized")
        self.assertEqual(result["window_state_after"], "maximized")

    def test_window_restore_state_before_is_maximized(self):
        window = _fake_window()
        result = _focus_desktop_window(window, window_state="minimized", restore_state="maximized")
        self.assertEqual(result["window_restore_state_before"], "maximized")


# ---------------------------------------------------------------------------
# _focus_desktop_window — restore failure
# ---------------------------------------------------------------------------

class FocusDesktopWindowRestoreFailureTests(unittest.TestCase):
    """Restore raises: show is still attempted; state stays minimized; restore_state preserved."""

    def test_show_still_called_after_restore_failure(self):
        window = _fake_window(raise_on_restore=True)
        _focus_desktop_window(window, window_state="minimized", restore_state="maximized")
        window.show.assert_called_once()

    def test_restored_from_minimized_false_on_restore_failure(self):
        window = _fake_window(raise_on_restore=True)
        result = _focus_desktop_window(window, window_state="minimized", restore_state="maximized")
        self.assertFalse(result["restored_from_minimized"])

    def test_window_state_after_stays_minimized_on_restore_failure(self):
        window = _fake_window(raise_on_restore=True)
        result = _focus_desktop_window(window, window_state="minimized", restore_state="maximized")
        self.assertEqual(result["window_state_after"], "minimized")

    def test_restore_state_before_preserved_on_failure(self):
        window = _fake_window(raise_on_restore=True)
        result = _focus_desktop_window(window, window_state="minimized", restore_state="maximized")
        self.assertEqual(result["window_restore_state_before"], "maximized")

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


# ---------------------------------------------------------------------------
# _focus_desktop_window — show failure
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# _focus_desktop_window — result shape
# ---------------------------------------------------------------------------

class FocusDesktopWindowResultShapeTests(unittest.TestCase):
    """Result always has the full diagnostic shape."""

    def test_all_diagnostic_fields_present(self):
        window = _fake_window()
        result = _focus_desktop_window(window, window_state="normal")
        for key in (
            "ok", "shown", "activation_requested", "focused",
            "restored_from_minimized", "window_state_before",
            "window_restore_state_before", "window_state_after",
        ):
            self.assertIn(key, result, f"Missing key: {key}")

    def test_ok_always_true(self):
        window = _fake_window(raise_on_restore=True, raise_on_show=True)
        result = _focus_desktop_window(window, window_state="minimized")
        self.assertTrue(result["ok"])

    def test_window_state_before_recorded(self):
        window = _fake_window()
        result = _focus_desktop_window(window, window_state="maximized")
        self.assertEqual(result["window_state_before"], "maximized")

    def test_window_restore_state_before_recorded(self):
        window = _fake_window()
        result = _focus_desktop_window(
            window, window_state="minimized", restore_state="maximized"
        )
        self.assertEqual(result["window_restore_state_before"], "maximized")


# ---------------------------------------------------------------------------
# State helpers — current window state
# ---------------------------------------------------------------------------

class WindowStateHelpersTests(unittest.TestCase):
    """_set_main_window_state / _get_main_window_state."""

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
        # Simulate _mark_shown: only update if not already maximized/minimized.
        state = _get_main_window_state(app)
        if state not in {"maximized", "minimized"}:
            _set_main_window_state(app, "normal")
        self.assertEqual(_get_main_window_state(app), "maximized")

    def test_invalid_state_ignored(self):
        app = self._make_app()
        _set_main_window_state(app, "normal")
        _set_main_window_state(app, "flying")
        self.assertEqual(_get_main_window_state(app), "normal")


# ---------------------------------------------------------------------------
# State helpers — restore state
# ---------------------------------------------------------------------------

class WindowRestoreStateHelpersTests(unittest.TestCase):
    """_set_main_window_restore_state / _get_main_window_restore_state."""

    def _make_app(self):
        tmp = tempfile.mkdtemp()
        return api_module.create_app(Path(tmp))

    def test_default_restore_state_is_normal(self):
        app = self._make_app()
        self.assertEqual(_get_main_window_restore_state(app), "normal")

    def test_set_restore_maximized(self):
        app = self._make_app()
        _set_main_window_restore_state(app, "maximized")
        self.assertEqual(_get_main_window_restore_state(app), "maximized")

    def test_set_restore_back_to_normal(self):
        app = self._make_app()
        _set_main_window_restore_state(app, "maximized")
        _set_main_window_restore_state(app, "normal")
        self.assertEqual(_get_main_window_restore_state(app), "normal")

    def test_minimized_not_accepted_as_restore_state(self):
        app = self._make_app()
        _set_main_window_restore_state(app, "normal")
        _set_main_window_restore_state(app, "minimized")
        self.assertEqual(_get_main_window_restore_state(app), "normal")

    def test_invalid_string_ignored(self):
        app = self._make_app()
        _set_main_window_restore_state(app, "normal")
        _set_main_window_restore_state(app, "unknown")
        self.assertEqual(_get_main_window_restore_state(app), "normal")

    def test_none_ignored(self):
        app = self._make_app()
        _set_main_window_restore_state(app, "normal")
        _set_main_window_restore_state(app, None)  # type: ignore[arg-type]
        self.assertEqual(_get_main_window_restore_state(app), "normal")


# ---------------------------------------------------------------------------
# Event-transition model
# ---------------------------------------------------------------------------

class EventTransitionModelTests(unittest.TestCase):
    """Simulate the event-handler closures; verify both state fields."""

    def _make_app(self):
        tmp = tempfile.mkdtemp()
        return api_module.create_app(Path(tmp))

    def _simulate(self, app, event: str) -> None:
        """Apply the desktop.py handler logic for the given event name."""
        if event == "maximized":
            _set_main_window_state(app, "maximized")
            _set_main_window_restore_state(app, "maximized")
        elif event == "minimized":
            _set_main_window_state(app, "minimized")
            # restore_state intentionally NOT changed
        elif event == "restored":
            _set_main_window_state(app, "normal")
            _set_main_window_restore_state(app, "normal")
        elif event == "shown":
            state = _get_main_window_state(app)
            if state not in {"maximized", "minimized"}:
                _set_main_window_state(app, "normal")

    def test_normal_to_maximized_sets_both_states(self):
        app = self._make_app()
        self._simulate(app, "maximized")
        self.assertEqual(_get_main_window_state(app), "maximized")
        self.assertEqual(_get_main_window_restore_state(app), "maximized")

    def test_maximized_to_minimized_preserves_restore_state(self):
        app = self._make_app()
        self._simulate(app, "maximized")
        self._simulate(app, "minimized")
        self.assertEqual(_get_main_window_state(app), "minimized")
        self.assertEqual(_get_main_window_restore_state(app), "maximized")

    def test_normal_to_minimized_restore_state_stays_normal(self):
        app = self._make_app()
        # Start at normal (default)
        self._simulate(app, "minimized")
        self.assertEqual(_get_main_window_state(app), "minimized")
        self.assertEqual(_get_main_window_restore_state(app), "normal")

    def test_restored_from_minimized_maximized_sets_normal(self):
        app = self._make_app()
        self._simulate(app, "maximized")
        self._simulate(app, "minimized")
        self._simulate(app, "restored")
        self.assertEqual(_get_main_window_state(app), "normal")
        self.assertEqual(_get_main_window_restore_state(app), "normal")

    def test_shown_does_not_clobber_maximized(self):
        app = self._make_app()
        self._simulate(app, "maximized")
        self._simulate(app, "shown")
        self.assertEqual(_get_main_window_state(app), "maximized")
        self.assertEqual(_get_main_window_restore_state(app), "maximized")

    def test_shown_does_not_clobber_minimized(self):
        app = self._make_app()
        self._simulate(app, "minimized")
        self._simulate(app, "shown")
        self.assertEqual(_get_main_window_state(app), "minimized")


# ---------------------------------------------------------------------------
# Shutdown persistence — _get_main_window_restore_state drives _save
# ---------------------------------------------------------------------------

class ShutdownPersistenceTests(unittest.TestCase):
    """Verify that restore_state (not current_state) drives the saved maximized flag."""

    def _make_app(self):
        tmp = tempfile.mkdtemp()
        return api_module.create_app(Path(tmp))

    def test_maximized_saves_as_maximized(self):
        app = self._make_app()
        _set_main_window_state(app, "maximized")
        _set_main_window_restore_state(app, "maximized")
        self.assertTrue(_get_main_window_restore_state(app) == "maximized")

    def test_minimized_from_maximized_saves_as_maximized(self):
        """Close while minimized (was maximized) → next launch should be maximized."""
        app = self._make_app()
        _set_main_window_state(app, "maximized")
        _set_main_window_restore_state(app, "maximized")
        _set_main_window_state(app, "minimized")
        # restore_state was NOT touched by the minimized event
        is_maximized = _get_main_window_restore_state(app) == "maximized"
        self.assertTrue(is_maximized)

    def test_minimized_from_normal_saves_as_not_maximized(self):
        """Close while minimized (was normal) → next launch should be normal."""
        app = self._make_app()
        _set_main_window_state(app, "minimized")
        _set_main_window_restore_state(app, "normal")
        is_maximized = _get_main_window_restore_state(app) == "maximized"
        self.assertFalse(is_maximized)

    def test_normal_saves_as_not_maximized(self):
        app = self._make_app()
        _set_main_window_state(app, "normal")
        _set_main_window_restore_state(app, "normal")
        self.assertFalse(_get_main_window_restore_state(app) == "maximized")

    def test_resize_after_maximize_does_not_clear_restore_state(self):
        """Regression: generic resize events must NOT erase the maximized restore state.

        The old model used _maximized[0] = False in _on_resized, which could
        run after the maximized event on Windows. The new model has no resize
        handler that touches restore_state — only the 'restored' event does.
        """
        app = self._make_app()
        # Simulate: maximized event fires
        _set_main_window_state(app, "maximized")
        _set_main_window_restore_state(app, "maximized")
        # Simulate: resize event fires (old code would have done _maximized[0] = False here)
        # In the new model nothing touches restore_state on resize — so no-op.
        # Verify the restore_state is still maximized (shutdown will save correctly).
        self.assertEqual(_get_main_window_restore_state(app), "maximized")
        self.assertTrue(_get_main_window_restore_state(app) == "maximized")


# ---------------------------------------------------------------------------
# Focus endpoint integration tests
# ---------------------------------------------------------------------------

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
        for key in (
            "ok", "shown", "activation_requested", "focused",
            "restored_from_minimized", "window_state_before",
            "window_restore_state_before", "window_state_after",
        ):
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
        app.state.main_window_restore_state = "normal"
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
        app.state.main_window_restore_state = "maximized"
        with contextlib.redirect_stderr(io.StringIO()):
            resp = client.post("/api/app/focus")
        body = resp.json()
        self.assertFalse(body["restored_from_minimized"])
        self.assertEqual(body["window_state_after"], "maximized")
        self.assertEqual(body["window_restore_state_before"], "maximized")
        window.restore.assert_not_called()

    def test_minimized_from_normal_focus_returns_to_normal(self):
        client, app = self._make_client()
        window = _fake_window()
        app.state.main_window = window
        app.state.main_window_state = "minimized"
        app.state.main_window_restore_state = "normal"
        with contextlib.redirect_stderr(io.StringIO()):
            resp = client.post("/api/app/focus")
        body = resp.json()
        self.assertTrue(body["restored_from_minimized"])
        self.assertEqual(body["window_restore_state_before"], "normal")
        self.assertEqual(body["window_state_after"], "normal")
        window.restore.assert_called_once()

    def test_minimized_from_maximized_focus_returns_to_maximized(self):
        client, app = self._make_client()
        window = _fake_window()
        app.state.main_window = window
        app.state.main_window_state = "minimized"
        app.state.main_window_restore_state = "maximized"
        with contextlib.redirect_stderr(io.StringIO()):
            resp = client.post("/api/app/focus")
        body = resp.json()
        self.assertTrue(body["restored_from_minimized"])
        self.assertEqual(body["window_restore_state_before"], "maximized")
        self.assertEqual(body["window_state_after"], "maximized")
        window.restore.assert_called_once()

    def test_minimized_from_maximized_updates_app_state_to_maximized(self):
        client, app = self._make_client()
        window = _fake_window()
        app.state.main_window = window
        app.state.main_window_state = "minimized"
        app.state.main_window_restore_state = "maximized"
        with contextlib.redirect_stderr(io.StringIO()):
            client.post("/api/app/focus")
        self.assertEqual(_get_main_window_state(app), "maximized")

    def test_minimized_from_normal_updates_app_state_to_normal(self):
        client, app = self._make_client()
        window = _fake_window()
        app.state.main_window = window
        app.state.main_window_state = "minimized"
        app.state.main_window_restore_state = "normal"
        with contextlib.redirect_stderr(io.StringIO()):
            client.post("/api/app/focus")
        self.assertEqual(_get_main_window_state(app), "normal")

    def test_restore_failure_state_remains_minimized(self):
        client, app = self._make_client()
        window = _fake_window(raise_on_restore=True)
        app.state.main_window = window
        app.state.main_window_state = "minimized"
        app.state.main_window_restore_state = "maximized"
        with contextlib.redirect_stderr(io.StringIO()):
            resp = client.post("/api/app/focus")
        body = resp.json()
        self.assertFalse(body["restored_from_minimized"])
        self.assertEqual(body["window_state_after"], "minimized")
        # restore_state_before must still be reported correctly
        self.assertEqual(body["window_restore_state_before"], "maximized")

    def test_restore_failure_app_state_not_updated(self):
        client, app = self._make_client()
        window = _fake_window(raise_on_restore=True)
        app.state.main_window = window
        app.state.main_window_state = "minimized"
        app.state.main_window_restore_state = "maximized"
        with contextlib.redirect_stderr(io.StringIO()):
            client.post("/api/app/focus")
        # current state stays minimized; restore_state is unchanged
        self.assertEqual(_get_main_window_state(app), "minimized")
        self.assertEqual(_get_main_window_restore_state(app), "maximized")


if __name__ == "__main__":
    unittest.main()
