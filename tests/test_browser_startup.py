"""Browser startup smoke via Playwright.

Requires dev dependencies::

    pip install -r requirements-dev.txt
    playwright install chromium

Skipped automatically when playwright is not installed.
"""

from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from importlib.util import find_spec
from pathlib import Path

from storyboard_tool import api as api_module
from storyboard_tool import desktop

PLAYWRIGHT_AVAILABLE = find_spec("playwright") is not None


@unittest.skipUnless(PLAYWRIGHT_AVAILABLE, "playwright is not installed")
class BrowserStartupTests(unittest.TestCase):
    def test_index_loads_and_new_project_path(self) -> None:
        from playwright.sync_api import sync_playwright

        with tempfile.TemporaryDirectory() as tmp:
            app = api_module.create_app(Path(tmp))
            with contextlib.redirect_stderr(io.StringIO()):
                _thread, port = desktop.start_server(app, host="127.0.0.1", port=0)

            base_url = f"http://127.0.0.1:{port}"
            console_errors: list[str] = []
            page_errors: list[str] = []

            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                page = browser.new_page()

                def on_console(msg) -> None:
                    if msg.type == "error":
                        console_errors.append(msg.text)

                def on_page_error(exc) -> None:
                    page_errors.append(str(exc))

                page.on("console", on_console)
                page.on("pageerror", on_page_error)

                page.goto(base_url, wait_until="domcontentloaded", timeout=60_000)
                page.wait_for_function(
                    """() => {
                      const overlay = document.getElementById('startupOverlay');
                      if (!overlay) return false;
                      if (overlay.classList.contains('has-error')) return false;
                      return overlay.classList.contains('is-done') || overlay.hidden;
                    }""",
                    timeout=45_000,
                )

                ready = page.evaluate(
                    """() => ({
                      bootstrap: window.__bootstrapModuleReady === true,
                      drawAnnotations: typeof drawAnnotations,
                      applyCanvasColor: typeof applyCanvasColor,
                      openScene3dModal: typeof openScene3dModal,
                      showDialog: typeof showDialog,
                    })"""
                )
                self.assertTrue(ready["bootstrap"], ready)
                for name in ("drawAnnotations", "applyCanvasColor", "openScene3dModal", "showDialog"):
                    self.assertEqual(ready[name], "function", f"{name} should be a global function")

                project_payload = page.evaluate(
                    """async (baseUrl) => {
                      const response = await fetch(baseUrl + '/api/project/new', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                          path: null,
                          canvas_width: 1920,
                          canvas_height: 1080,
                        }),
                      });
                      if (!response.ok) {
                        const detail = await response.text();
                        throw new Error('new project failed: ' + response.status + ' ' + detail);
                      }
                      return response.json();
                    }""",
                    base_url,
                )
                self.assertTrue(project_payload.get("name"))
                self.assertIn("shots", project_payload)

                browser.close()

            self.assertFalse(page_errors, page_errors)
            self.assertFalse(console_errors, console_errors)


class BrowserDevRequirementsTests(unittest.TestCase):
    def test_requirements_dev_lists_playwright(self) -> None:
        text = Path("requirements-dev.txt").read_text(encoding="utf-8")
        self.assertIn("playwright", text.lower())
