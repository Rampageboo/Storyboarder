"""Regression test coverage for core professional stability workflows.

Tests are grouped by concern and use the REST API via TestClient.
Lower-level helpers (project_manager, atomic write) are tested directly
where the API is not the right boundary.
"""
from __future__ import annotations

import contextlib
import inspect
import io
import json
import shutil
import tempfile
import unittest
import warnings
from pathlib import Path

with warnings.catch_warnings():
    warnings.filterwarnings("ignore", message="Using `httpx` with `starlette.testclient`")
    from fastapi.testclient import TestClient

from storyboard_tool import api as api_module
from storyboard_tool import desktop as desktop_module
from storyboard_tool import main as main_module
from storyboard_tool import project_manager
from storyboard_tool.models import Project, Shot

REPO_ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = REPO_ROOT / "storyboard_tool" / "web" / "static"


def _quiet(fn):
    with contextlib.redirect_stderr(io.StringIO()):
        return fn()


class _ProjectFixture(unittest.TestCase):
    """Base: creates a temp dir + TestClient with a project containing two shots."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()
        self._app = api_module.create_app(Path(self._tmp))
        self._client = TestClient(self._app, raise_server_exceptions=False)
        resp = _quiet(lambda: self._client.post("/api/project/new", json={"path": self._tmp}))
        self.assertEqual(resp.status_code, 200, f"Project creation failed: {resp.text}")
        self._project_data = resp.json()
        # Seed with two shots so lifecycle tests have a realistic starting point.
        for _ in range(2):
            _quiet(lambda: self._client.post("/api/shots", json={}))

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _add_shot(self, after_shot_id: str | None = None) -> dict:
        body = {}
        if after_shot_id:
            body["after_shot_id"] = after_shot_id
        resp = _quiet(lambda: self._client.post("/api/shots", json=body))
        self.assertEqual(resp.status_code, 200)
        return resp.json()

    def _shot_ids(self) -> list[str]:
        resp = _quiet(lambda: self._client.get("/api/project"))
        return [s["shot_id"] for s in resp.json().get("shots", [])]


# ---------------------------------------------------------------------------
# Shot lifecycle
# ---------------------------------------------------------------------------

class TestShotLifecycle(_ProjectFixture):
    def test_add_shot_returns_new_shot(self) -> None:
        before = self._shot_ids()
        data = self._add_shot()
        new_ids = [s["shot_id"] for s in data.get("shots", [])]
        self.assertEqual(len(new_ids), len(before) + 1, "Expected one more shot after add")

    def test_add_shot_after_specific_shot(self) -> None:
        initial_ids = self._shot_ids()
        self.assertGreaterEqual(len(initial_ids), 2, "Fixture should seed at least 2 shots")
        anchor_id = initial_ids[0]
        second_id = initial_ids[1]
        self._add_shot(after_shot_id=anchor_id)
        new_ids = self._shot_ids()
        self.assertEqual(len(new_ids), len(initial_ids) + 1)
        # anchor, NEW, second, ... ? second should have moved one position right
        anchor_pos = new_ids.index(anchor_id)
        self.assertNotEqual(new_ids[anchor_pos + 1], second_id, "New shot should sit between anchor and second")

    def test_duplicate_shot_increases_count(self) -> None:
        before = self._shot_ids()
        shot_id = before[0]
        resp = _quiet(lambda: self._client.post(f"/api/shots/{shot_id}/duplicate"))
        self.assertEqual(resp.status_code, 200)
        after = self._shot_ids()
        self.assertEqual(len(after), len(before) + 1)

    def test_delete_shot_decreases_count(self) -> None:
        self._add_shot()
        before = self._shot_ids()
        shot_id = before[0]
        resp = _quiet(lambda: self._client.delete(f"/api/shots/{shot_id}"))
        self.assertEqual(resp.status_code, 200)
        after = self._shot_ids()
        self.assertEqual(len(after), len(before) - 1)
        self.assertNotIn(shot_id, after)

    def test_delete_nonexistent_shot_returns_404(self) -> None:
        resp = _quiet(lambda: self._client.delete("/api/shots/does_not_exist"))
        self.assertEqual(resp.status_code, 404)

    def test_reorder_shots_changes_order(self) -> None:
        # Add a second shot so we have two to reorder
        self._add_shot()
        ids = self._shot_ids()
        self.assertGreaterEqual(len(ids), 2)
        reversed_ids = list(reversed(ids))
        resp = _quiet(
            lambda: self._client.post("/api/shots/reorder", json={"shot_ids": reversed_ids})
        )
        self.assertEqual(resp.status_code, 200)
        new_order = self._shot_ids()
        self.assertEqual(new_order, reversed_ids)

    def test_reorder_with_unknown_ids_returns_error(self) -> None:
        resp = _quiet(
            lambda: self._client.post(
                "/api/shots/reorder", json={"shot_ids": ["ghost_001", "ghost_002"]}
            )
        )
        self.assertIn(resp.status_code, (400, 422))


# ---------------------------------------------------------------------------
# Project save / load roundtrip
# ---------------------------------------------------------------------------

class TestProjectRoundtrip(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_save_and_reload_preserves_shots(self) -> None:
        root = Path(self._tmp) / "MyProject"
        project = project_manager.create_project(root)
        with contextlib.suppress(Exception):
            # add_shot might fail if Photoshop is not configured; we test the data layer
            project_manager.add_shot(project)
            project_manager.add_shot(project)
        project_manager.save_project(project)

        reloaded = project_manager.open_project(project.json_path)
        self.assertEqual(len(reloaded.shots), len(project.shots))
        for orig, relo in zip(project.shots, reloaded.shots):
            self.assertEqual(orig.shot_id, relo.shot_id)

    def test_save_and_reload_preserves_settings(self) -> None:
        root = Path(self._tmp) / "SettingsProject"
        project = project_manager.create_project(root)
        project.settings["pdf_layout"] = "one_per_page"
        project.settings["canvas_background_color"] = "#123456"
        project_manager.save_settings(project)

        reloaded = project_manager.open_project(project.json_path)
        self.assertEqual(reloaded.settings.get("pdf_layout"), "one_per_page")
        self.assertEqual(reloaded.settings.get("canvas_background_color"), "#123456")

    def test_project_json_is_valid_after_save(self) -> None:
        root = Path(self._tmp) / "JsonProject"
        project = project_manager.create_project(root)
        project_manager.save_project(project)

        content = project.json_path.read_text(encoding="utf-8")
        parsed = json.loads(content)
        self.assertIn("version", parsed)


# ---------------------------------------------------------------------------
# Atomic save
# ---------------------------------------------------------------------------

class TestAtomicSave(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_atomic_write_creates_valid_json(self) -> None:
        target = Path(self._tmp) / "output.json"
        data = {"key": "value", "number": 42}
        project_manager._atomic_write_json(target, data)
        self.assertTrue(target.exists())
        parsed = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(parsed, data)

    def test_atomic_write_overwrites_existing_file(self) -> None:
        target = Path(self._tmp) / "existing.json"
        target.write_text('{"old": true}', encoding="utf-8")
        project_manager._atomic_write_json(target, {"new": True})
        self.assertEqual(json.loads(target.read_text(encoding="utf-8")), {"new": True})

    def test_atomic_write_leaves_no_temp_file_on_success(self) -> None:
        target = Path(self._tmp) / "clean.json"
        project_manager._atomic_write_json(target, {"clean": True})
        tmp_files = list(Path(self._tmp).glob("*.tmp"))
        self.assertEqual(tmp_files, [], "Stale .tmp file left after successful atomic write")


# ---------------------------------------------------------------------------
# Ref-apply snapshot + undo
# ---------------------------------------------------------------------------

class TestRefApplyUndo(_ProjectFixture):
    def _ensure_two_shots(self) -> tuple[str, str]:
        ids = self._shot_ids()
        if len(ids) < 2:
            self._add_shot()
            ids = self._shot_ids()
        return ids[0], ids[-1]

    def test_snapshot_returns_undo_token(self) -> None:
        anchor, end = self._ensure_two_shots()
        resp = _quiet(
            lambda: self._client.post(
                "/api/project/ref-segments/snapshot",
                json={"anchor_shot_id": anchor, "end_shot_id": end},
            )
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("undo_token", resp.json())
        self.assertTrue(resp.json()["undo_token"])

    def test_restore_from_undo_token_succeeds(self) -> None:
        anchor, end = self._ensure_two_shots()
        snap = _quiet(
            lambda: self._client.post(
                "/api/project/ref-segments/snapshot",
                json={"anchor_shot_id": anchor, "end_shot_id": end},
            )
        )
        token = snap.json()["undo_token"]

        restore = _quiet(
            lambda: self._client.post("/api/project/ref-apply/undo", json={"token": token})
        )
        self.assertEqual(restore.status_code, 200)

    def test_invalid_undo_token_returns_error(self) -> None:
        resp = _quiet(
            lambda: self._client.post(
                "/api/project/ref-apply/undo", json={"token": "notarealtoken"}
            )
        )
        self.assertIn(resp.status_code, (400, 404))


# ---------------------------------------------------------------------------
# Missing media
# ---------------------------------------------------------------------------

class TestMissingMediaOnOpen(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_project_opens_with_shots_that_have_missing_preview(self) -> None:
        root = Path(self._tmp) / "MissingProject"
        project = project_manager.create_project(root)
        shot = project.shots[0] if project.shots else Shot(shot_id="shot_missing")
        shot.preview_image_path = "shots/shot_missing/shot_missing_preview.png"
        if shot not in project.shots:
            project.shots.append(shot)
        project_manager.save_project(project)

        # Must not raise; loads even when preview file is absent
        reloaded = project_manager.open_project(project.json_path)
        self.assertIsNotNone(reloaded)

    def test_missing_files_endpoint_reports_missing_preview(self) -> None:
        app = api_module.create_app(Path(self._tmp))
        client = TestClient(app, raise_server_exceptions=False)
        resp = _quiet(lambda: client.post("/api/project/new", json={"path": self._tmp}))
        self.assertEqual(resp.status_code, 200)

        # Add a shot first (new projects start with 0 shots)
        _quiet(lambda: client.post("/api/shots", json={}))

        # Inject a nonexistent preview path onto the first shot
        project = app.state.project
        self.assertGreater(len(project.shots), 0, "Expected at least one shot after add")
        shot = project.shots[0]
        shot.preview_image_path = "shots/ghost/ghost_preview.png"

        resp = _quiet(lambda: client.get("/api/project/missing-files"))
        self.assertEqual(resp.status_code, 200)
        missing = resp.json().get("missing_files", [])
        ids = [m["shot_id"] for m in missing]
        self.assertIn(shot.shot_id, ids)


# ---------------------------------------------------------------------------
# Export with missing media
# ---------------------------------------------------------------------------

class TestExportWithMissingMedia(_ProjectFixture):
    def test_shot_list_export_succeeds_with_no_preview(self) -> None:
        # Shot list is CSV metadata ? does not require image files
        resp = _quiet(lambda: self._client.post("/api/export/shot-list"))
        self.assertEqual(resp.status_code, 200)
        self.assertIn("path", resp.json())

    def test_timing_export_succeeds_with_no_images(self) -> None:
        resp = _quiet(lambda: self._client.post("/api/export/timing"))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("path", data)


# ---------------------------------------------------------------------------
# Desktop-only CLI ? no --browser / --host / --port flags
# ---------------------------------------------------------------------------

class TestDesktopOnlyCLI(unittest.TestCase):
    def test_desktop_module_has_no_browser_flag(self) -> None:
        src = inspect.getsource(desktop_module)
        self.assertNotIn("--browser", src)

    def test_desktop_module_has_no_host_flag(self) -> None:
        src = inspect.getsource(desktop_module)
        self.assertNotIn('"--host"', src)
        self.assertNotIn("'--host'", src)

    def test_desktop_module_has_no_port_flag(self) -> None:
        src = inspect.getsource(desktop_module)
        self.assertNotIn('"--port"', src)
        self.assertNotIn("'--port'", src)

    def test_main_module_has_no_argparse(self) -> None:
        src = inspect.getsource(main_module)
        self.assertNotIn("argparse", src)
        self.assertNotIn("ArgumentParser", src)

    def test_open_desktop_window_accepts_no_cli_args(self) -> None:
        sig = inspect.signature(desktop_module.open_desktop_window)
        param_names = list(sig.parameters.keys())
        # Only app and optional title ? no host, port, browser
        for forbidden in ("host", "port", "browser"):
            self.assertNotIn(forbidden, param_names)


# ---------------------------------------------------------------------------
# Forbidden legacy files (file-system checks)
# ---------------------------------------------------------------------------

class TestForbiddenLegacyFiles(unittest.TestCase):
    def test_no_previewStyleBridge_anywhere(self) -> None:
        matches = list(REPO_ROOT.rglob("previewStyleBridge*"))
        # Exclude dist/build artefacts
        real = [p for p in matches if ".git" not in p.parts and "node_modules" not in p.parts]
        self.assertEqual(real, [], f"Legacy previewStyleBridge file found: {real}")

    def test_no_scene3d_js_shim_in_static(self) -> None:
        self.assertFalse(
            (STATIC_DIR / "scene3d.js").exists(),
            "Legacy storyboard_tool/web/static/scene3d.js should be removed",
        )

    def test_no_scene3d_preview_style_shim_in_runtime(self) -> None:
        self.assertFalse(
            (STATIC_DIR / "runtime" / "scene3d_preview_style.js").exists(),
            "Legacy scene3d_preview_style.js shim should be removed",
        )

    def test_no_legacy_app_js_in_static(self) -> None:
        self.assertFalse(
            (STATIC_DIR / "app.js").exists(),
            "Legacy web/static/app.js (old JS frontend) should be removed",
        )

    def test_no_legacy_index_html_in_static(self) -> None:
        self.assertFalse(
            (STATIC_DIR / "index.html").exists(),
            "Legacy web/static/index.html should be removed",
        )


# ---------------------------------------------------------------------------
# Forbidden legacy API routes
# ---------------------------------------------------------------------------

class TestForbiddenLegacyRoutes(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp()
        app = api_module.create_app(Path(self._tmp))
        self._client = TestClient(app, raise_server_exceptions=False)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_ref_segment_route_returns_404(self) -> None:
        resp = _quiet(lambda: self._client.get("/ref-segment"))
        self.assertEqual(resp.status_code, 404)

    def test_ref_scene3d_route_returns_404(self) -> None:
        resp = _quiet(lambda: self._client.get("/ref-scene3d"))
        self.assertEqual(resp.status_code, 404)

    def test_legacy_window_route_returns_404(self) -> None:
        resp = _quiet(lambda: self._client.get("/legacy"))
        self.assertEqual(resp.status_code, 404)


if __name__ == "__main__":
    unittest.main()
