from __future__ import annotations

import contextlib
import io
import re
import socket
import sys
import tempfile
import types
import unittest
import warnings
from importlib.util import find_spec
from pathlib import Path

with warnings.catch_warnings():
    warnings.filterwarnings("ignore", message="Using `httpx` with `starlette.testclient` is deprecated")
    from fastapi.testclient import TestClient

from storyboard_tool.bridge import DesktopBridge
from storyboard_tool import desktop, live_bridge, project_manager
from storyboard_tool import api as api_module
from storyboard_tool import video_utils
from storyboard_tool.models import Project, Shot


class StoryboardSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        live_bridge._BRIDGE_WRITE_WARNED_PATHS.clear()

    def tearDown(self) -> None:
        live_bridge._BRIDGE_WRITE_WARNED_PATHS.clear()

    def test_public_window_routes_and_bridge_status_load(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = api_module.create_app(Path(tmp))
            client = TestClient(app, raise_server_exceptions=False)

            with contextlib.redirect_stderr(io.StringIO()):
                for route in ("/", "/ref-segment", "/ref-scene3d", "/ref-video", "/api/bridge/status"):
                    with self.subTest(route=route):
                        response = client.get(route)
                        self.assertEqual(response.status_code, 200)

    @unittest.skipIf(find_spec("multipart") is None, "python-multipart is not installed")
    def test_rest_pdf_export_route_reaches_exporter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            original_export = api_module._export_storyboard_pdf

            def fake_export(_project, output_path, *, layout):
                self.assertEqual(layout, "two_per_page")
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(b"%PDF-1.4\n")

            api_module._export_storyboard_pdf = fake_export
            app = api_module.create_app(Path(tmp))
            client = TestClient(app, raise_server_exceptions=False)
            try:
                with contextlib.redirect_stderr(io.StringIO()):
                    project = client.post("/api/project/new", json={"path": tmp})
                    self.assertEqual(project.status_code, 200)

                    response = client.post("/api/export/pdf", json={"layout": "two_per_page"})

                self.assertEqual(response.status_code, 200)
                payload = response.json()
                self.assertTrue(payload["path"].endswith("storyboard.pdf"))
                self.assertEqual(payload["download_url"], "/api/export/pdf")
            finally:
                api_module._export_storyboard_pdf = original_export

    def test_shutdown_reference_cleanup_removes_unreferenced_reference_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Storyboard_Project"
            (root / "shots").mkdir(parents=True)
            (root / "references").mkdir()
            (root / "exports").mkdir()
            (root / "scripts").mkdir()
            (root / "backups").mkdir()
            project = Project(root_path=root, settings=project_manager.DEFAULT_SETTINGS.copy())
            shot = Shot(shot_id="shot_001")
            project.shots.append(shot)
            shot_dir = project_manager.get_shot_dir(project, shot)
            shot_dir.mkdir(parents=True)
            ref_dir = shot_dir / "references"
            ref_dir.mkdir()
            orphan = ref_dir / "orphan.png"
            orphan.write_bytes(b"orphan")
            kept = ref_dir / "kept.png"
            kept.write_bytes(b"kept")
            shot.reference_image_paths = [kept.relative_to(project.root_path).as_posix()]

            deleted = project_manager.shutdown_reference_cleanup(project, save_if_dirty=False)

            self.assertIn(orphan.relative_to(project.root_path).as_posix(), deleted)
            self.assertFalse(orphan.exists())
            self.assertTrue(kept.exists())

    def test_api_shutdown_reference_cleanup_logs_and_continues(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = api_module.create_app(Path(tmp))
            original_cleanup = project_manager.shutdown_reference_cleanup

            def failing_cleanup(*_args, **_kwargs):
                raise RuntimeError("cleanup failed")

            project_manager.shutdown_reference_cleanup = failing_cleanup
            stderr = io.StringIO()
            try:
                with contextlib.redirect_stderr(stderr):
                    api_module._shutdown_reference_cleanup(app)
            finally:
                project_manager.shutdown_reference_cleanup = original_cleanup

            self.assertIn("Reference cleanup failed: cleanup failed", stderr.getvalue())

    def test_dispatch_knows_reference_segment_apply_methods(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = api_module.create_app(Path(tmp))
            client = TestClient(app, raise_server_exceptions=False)
            calls = [
                ("apply_ref_segment", ["shot_a", "shot_b", ""]),
                ("apply_ref_segment_image", ["shot_a", "shot_b", ""]),
                ("apply_ref_segment_3d", ["shot_a", "shot_b", "", "Camera"]),
            ]

            for method, args in calls:
                with self.subTest(method=method):
                    response = client.post("/api", json={"method": method, "args": args})
                    self.assertEqual(response.status_code, 200)
                    payload = response.json()
                    self.assertFalse(payload["ok"])
                    self.assertNotIn("Unknown API method", payload["error"])

    def test_frontend_dispatch_entries_have_backend_methods(self) -> None:
        dispatch_js = Path("storyboard_tool/web/static/core/dispatch.js").read_text(encoding="utf-8")
        backend_py = Path("storyboard_tool/backend_service.py").read_text(encoding="utf-8")
        dispatch_methods = set(re.findall(r'dispatch:\s*"([a-zA-Z0-9_]+)"', dispatch_js))
        backend_methods = set(re.findall(r"def method_([a-zA-Z0-9_]+)\(", backend_py))

        self.assertTrue(dispatch_methods)
        self.assertFalse(dispatch_methods - backend_methods)

    def test_desktop_bridge_exposes_snake_and_camel_case_methods(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bridge = DesktopBridge(api_module.create_app(Path(tmp)))

            self.assertEqual(bridge.api_call("ping"), "python-backend-ready")
            self.assertEqual(bridge.apiCall("ping"), "python-backend-ready")
            self.assertTrue(callable(bridge.upload_multipart))
            self.assertTrue(callable(bridge.uploadMultipart))
            self.assertTrue(callable(bridge.open_ref_video_window))
            self.assertTrue(callable(bridge.openRefVideoWindow))

    def test_desktop_bridge_request_and_error_paths_are_stable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bridge = DesktopBridge(api_module.create_app(Path(tmp)))

            with contextlib.redirect_stderr(io.StringIO()):
                status = bridge.request("GET", "/api/bridge/status")
            self.assertIsInstance(status, dict)
            self.assertIn("live", status)
            self.assertFalse(status["project_open"])

            with self.assertRaisesRegex(RuntimeError, "Args must be a JSON array"):
                bridge.api_call("ping", "{}")

            with self.assertRaisesRegex(RuntimeError, "No project opened"):
                bridge.uploadMultipart("/api/project/references", "ref.png", "image/png", [137, 80, 78, 71])

    def test_webview_storage_path_falls_back_when_global_dir_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            blocker = Path(tmp) / "not_a_directory"
            blocker.write_text("blocked", encoding="utf-8")
            original_global_bridge_dir = desktop.global_bridge_dir
            original_warned = set(desktop._WEBVIEW_STORAGE_WARNED_PATHS)
            desktop.global_bridge_dir = lambda: blocker
            desktop._WEBVIEW_STORAGE_WARNED_PATHS.clear()
            stderr = io.StringIO()
            try:
                with contextlib.redirect_stderr(stderr):
                    path = desktop.webview_storage_path()
                    second_path = desktop.webview_storage_path()
            finally:
                desktop.global_bridge_dir = original_global_bridge_dir
                desktop._WEBVIEW_STORAGE_WARNED_PATHS.clear()
                desktop._WEBVIEW_STORAGE_WARNED_PATHS.update(original_warned)

            self.assertTrue(path.is_dir())
            self.assertEqual(path, second_path)
            self.assertNotEqual(path, blocker / "webview")
            self.assertEqual(stderr.getvalue().count("Webview storage path unavailable"), 1)

    def test_start_server_accepts_ephemeral_port(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = api_module.create_app(Path(tmp))
            with contextlib.redirect_stderr(io.StringIO()):
                thread, port = desktop.start_server(app, port=0)

            self.assertGreater(port, 0)
            self.assertTrue(thread.is_alive())
            self.assertEqual(app.state.bridge_port, port)

    def test_resolve_server_port_accepts_ephemeral_port(self) -> None:
        port = live_bridge.resolve_server_port("127.0.0.1", 0)

        self.assertGreater(port, 0)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", port))

    def test_startup_overlay_timeout_reports_issue_not_ready(self) -> None:
        main_js = Path("storyboard_tool/web/static/main.js").read_text(encoding="utf-8")
        app_js = Path("storyboard_tool/web/static/app.js").read_text(encoding="utf-8")
        styles = Path("storyboard_tool/web/static/styles.css").read_text(encoding="utf-8")

        self.assertIn('failStartupOverlay("Initialization timed out")', main_js)
        self.assertIn('failStartupOverlay(`Could not load ${APP_SCRIPTS[index]}`)', main_js)
        self.assertIn('window.failStartupOverlay?.("Startup failed")', app_js)
        self.assertIn(".startup-overlay.has-error", styles)
        self.assertIn("--startup-accent: #ff6b5a", styles)
        self.assertNotIn('if (!startupUi.hidden) finishStartupOverlay("Ready");', main_js)

    def test_core_api_serializes_object_body_on_all_fetch_paths(self) -> None:
        api_js = Path("storyboard_tool/web/static/core/api.js").read_text(encoding="utf-8")

        self.assertGreaterEqual(api_js.count("JSON.stringify(fetchOptions.body)"), 2)
        self.assertIn("bridge.upload_multipart || bridge.uploadMultipart", api_js)

    def test_bridge_write_warning_is_emitted_once_per_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            blocker = Path(tmp) / "blocked"
            blocker.write_text("blocked", encoding="utf-8")
            target = blocker / "storyboard_live_bridge.json"
            original_warned = set(live_bridge._BRIDGE_WRITE_WARNED_PATHS)
            live_bridge._BRIDGE_WRITE_WARNED_PATHS.clear()
            stderr = io.StringIO()
            try:
                with contextlib.redirect_stderr(stderr):
                    self.assertFalse(live_bridge._try_write_bridge_file(target, "{}"))
                    self.assertFalse(live_bridge._try_write_bridge_file(target, "{}"))
            finally:
                live_bridge._BRIDGE_WRITE_WARNED_PATHS.clear()
                live_bridge._BRIDGE_WRITE_WARNED_PATHS.update(original_warned)

            self.assertEqual(stderr.getvalue().count("bridge file write skipped"), 1)

    def test_plugin_heartbeat_mtime_falls_back_to_file_mtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            heartbeat = Path(tmp) / live_bridge.PLUGIN_HEARTBEAT_FILENAME
            heartbeat.write_text("{not json", encoding="utf-8")
            original_shared_bridge_dir = live_bridge.shared_bridge_dir
            live_bridge.shared_bridge_dir = lambda: Path(tmp)
            try:
                mtime = live_bridge.read_plugin_heartbeat_mtime()
            finally:
                live_bridge.shared_bridge_dir = original_shared_bridge_dir

            self.assertGreater(mtime, 0.0)

    def test_video_duration_releases_cv2_capture_when_open_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "clip.mp4"
            source.write_bytes(b"video")
            released = []

            class FakeCapture:
                def __init__(self, _path: str) -> None:
                    pass

                def isOpened(self) -> bool:
                    return False

                def release(self) -> None:
                    released.append(True)

            fake_cv2 = types.SimpleNamespace(
                VideoCapture=FakeCapture,
                CAP_PROP_FPS=5,
                CAP_PROP_FRAME_COUNT=7,
            )
            original_cv2 = sys.modules.get("cv2")
            sys.modules["cv2"] = fake_cv2
            try:
                with self.assertRaisesRegex(ValueError, "Cannot open video"):
                    video_utils.get_video_duration(source)
            finally:
                if original_cv2 is None:
                    sys.modules.pop("cv2", None)
                else:
                    sys.modules["cv2"] = original_cv2

            self.assertEqual(released, [True])


if __name__ == "__main__":
    unittest.main()
