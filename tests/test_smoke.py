from __future__ import annotations

import contextlib
import io
import json
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
from storyboard_tool import backend_service as backend_service_module
from storyboard_tool import backups as backups_module
from storyboard_tool import video_utils
from storyboard_tool.models import Project, Shot

# 1x1 PNG for multipart upload smoke tests.
MINI_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000a49444154789c6300010000050001"
    "0d0a2db40000000049454e44ae426082"
)


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
            original_export = backend_service_module._export_storyboard_pdf

            def fake_export(_project, output_path, *, layout):
                self.assertEqual(layout, "two_per_page")
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(b"%PDF-1.4\n")

            backend_service_module._export_storyboard_pdf = fake_export
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
                backend_service_module._export_storyboard_pdf = original_export

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

    def test_project_canvas_size_create_and_update(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = api_module.create_app(Path(tmp))
            client = TestClient(app, raise_server_exceptions=False)
            with contextlib.redirect_stderr(io.StringIO()):
                created = client.post(
                    "/api/project/new",
                    json={"path": tmp, "canvas_width": 1600, "canvas_height": 900},
                )
            self.assertEqual(created.status_code, 200)
            payload = created.json()
            self.assertEqual(payload["settings"]["canvas_width"], 1600)
            self.assertEqual(payload["settings"]["canvas_height"], 900)

            with contextlib.redirect_stderr(io.StringIO()):
                updated = client.patch(
                    "/api/project/settings",
                    json={
                        "canvas_width": 1080,
                        "canvas_height": 1080,
                        "apply_canvas_size_to_blank_shots": False,
                    },
                )
            self.assertEqual(updated.status_code, 200)
            settings = updated.json()["settings"]
            self.assertEqual(settings["canvas_width"], 1080)
            self.assertEqual(settings["canvas_height"], 1080)


    def test_open_blender_scene_returns_project_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = api_module.create_app(Path(tmp))
            client = TestClient(app, raise_server_exceptions=False)
            with contextlib.redirect_stderr(io.StringIO()):
                created = client.post("/api/project/new", json={"path": tmp})
            self.assertEqual(created.status_code, 200)

            original_open = project_manager.open_blender_scene

            def fake_open_blender_scene(project):
                blend = project.root_path / "scene3d" / "scene.blend"
                blend.parent.mkdir(parents=True, exist_ok=True)
                blend.write_text("fake", encoding="utf-8")
                return blend

            project_manager.open_blender_scene = fake_open_blender_scene
            try:
                with contextlib.redirect_stderr(io.StringIO()):
                    response = client.post("/api/project/scene3d/open-blender")
            finally:
                project_manager.open_blender_scene = original_open

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertIn("path", payload)
            self.assertIn("relative_path", payload)
            self.assertIn("shots", payload)
            self.assertIsInstance(payload["dirty"], bool)
            self.assertIsInstance(payload["settings"], dict)

    def test_backend_dispatch_persists_canvas_size(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = api_module.create_app(Path(tmp))
            client = TestClient(app, raise_server_exceptions=False)
            with contextlib.redirect_stderr(io.StringIO()):
                created = client.post("/api/project/new", json={"path": tmp, "canvas_width": 1920, "canvas_height": 1080})
            self.assertEqual(created.status_code, 200)

            with contextlib.redirect_stderr(io.StringIO()):
                updated = client.post(
                    "/api",
                    json={
                        "method": "update_settings",
                        "args": [
                            {
                                "photoshop_path": "",
                                "blender_path": "",
                                "canvas_width": 1600,
                                "canvas_height": 900,
                                "apply_canvas_size_to_blank_shots": False,
                            }
                        ],
                    },
                )
            self.assertEqual(updated.status_code, 200)
            payload = updated.json()["result"]
            self.assertEqual(payload["settings"]["canvas_width"], 1600)
            self.assertEqual(payload["settings"]["canvas_height"], 900)


    def test_update_settings_rest_and_dispatch_share_backend_logic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = api_module.create_app(Path(tmp))
            client = TestClient(app, raise_server_exceptions=False)
            with contextlib.redirect_stderr(io.StringIO()):
                created = client.post("/api/project/new", json={"path": tmp})
            self.assertEqual(created.status_code, 200)
            settings_json = Path(tmp) / "Storyboard_Project" / "settings.json"

            def read_saved_mode() -> str:
                return json.loads(settings_json.read_text(encoding="utf-8")).get("reference_segment_mode", "")

            def assert_cleared_model_mode() -> None:
                self.assertEqual(read_saved_mode(), "video")

            with contextlib.redirect_stderr(io.StringIO()):
                client.patch("/api/project/settings", json={"reference_segment_mode": "model"})
                rest = client.patch("/api/project/settings", json={"reference_model_path": ""})
            self.assertEqual(rest.status_code, 200, rest.text)
            self.assertEqual(rest.json()["settings"]["reference_segment_mode"], "video")
            assert_cleared_model_mode()

            with contextlib.redirect_stderr(io.StringIO()):
                client.patch("/api/project/settings", json={"reference_segment_mode": "model"})
                dispatch = client.post(
                    "/api",
                    json={"method": "update_settings", "args": [{"reference_model_path": ""}]},
                )
            self.assertEqual(dispatch.status_code, 200, dispatch.text)
            dispatch_payload = dispatch.json()
            self.assertTrue(dispatch_payload["ok"], dispatch_payload.get("error"))
            self.assertEqual(
                dispatch_payload["result"]["settings"]["reference_segment_mode"],
                "video",
            )
            assert_cleared_model_mode()

    def test_project_lifecycle_rest_and_dispatch_share_backend_logic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = api_module.create_app(Path(tmp))
            client = TestClient(app, raise_server_exceptions=False)
            project_root = Path(tmp) / "Storyboard_Project"

            with contextlib.redirect_stderr(io.StringIO()):
                rest_created = client.post(
                    "/api/project/new",
                    json={"path": tmp, "canvas_width": 1280, "canvas_height": 720},
                )
            self.assertEqual(rest_created.status_code, 200)
            rest_payload = rest_created.json()
            self.assertEqual(rest_payload["settings"]["canvas_width"], 1280)
            self.assertTrue(project_root.exists())

            with contextlib.redirect_stderr(io.StringIO()):
                rest_saved = client.post("/api/project/save")
            self.assertEqual(rest_saved.status_code, 200)
            self.assertFalse(rest_saved.json()["dirty"])

            with contextlib.redirect_stderr(io.StringIO()):
                dispatch_created = client.post(
                    "/api",
                    json={
                        "method": "new_project",
                        "args": [str(Path(tmp) / "Dispatch_Project"), 1600, 900],
                    },
                )
            self.assertEqual(dispatch_created.status_code, 200)
            dispatch_payload = dispatch_created.json()
            self.assertTrue(dispatch_payload["ok"], dispatch_payload.get("error"))
            self.assertEqual(dispatch_payload["result"]["settings"]["canvas_width"], 1600)

            project_json = Path(tmp) / "Dispatch_Project" / "Storyboard_Project" / "project.json"
            with contextlib.redirect_stderr(io.StringIO()):
                dispatch_opened = client.post(
                    "/api",
                    json={"method": "open_project", "args": [str(project_json)]},
                )
            self.assertEqual(dispatch_opened.status_code, 200)
            opened_payload = dispatch_opened.json()
            self.assertTrue(opened_payload["ok"], opened_payload.get("error"))
            self.assertEqual(opened_payload["result"]["settings"]["canvas_width"], 1600)

    def test_comment_rest_and_dispatch_share_backend_logic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = api_module.create_app(Path(tmp))
            client = TestClient(app, raise_server_exceptions=False)
            with contextlib.redirect_stderr(io.StringIO()):
                created = client.post("/api/project/new", json={"path": tmp})
                shot_created = client.post("/api/shots", json={})
            self.assertEqual(created.status_code, 200)
            self.assertEqual(shot_created.status_code, 200)
            shot_id = shot_created.json()["shot"]["shot_id"]

            with contextlib.redirect_stderr(io.StringIO()):
                rest_comment = client.post(
                    f"/api/shots/{shot_id}/comments",
                    json={"text": "Needs wider framing"},
                )
            self.assertEqual(rest_comment.status_code, 200)
            rest_comments = rest_comment.json()["shots"][0]["comments"]
            self.assertEqual(len(rest_comments), 1)
            comment_id = rest_comments[0]["id"]

            with contextlib.redirect_stderr(io.StringIO()):
                rest_resolved = client.patch(
                    f"/api/shots/{shot_id}/comments/{comment_id}",
                    json={"resolved": True},
                )
            self.assertEqual(rest_resolved.status_code, 200)
            self.assertTrue(rest_resolved.json()["shots"][0]["comments"][0]["resolved"])

            with contextlib.redirect_stderr(io.StringIO()):
                dispatch_comment = client.post(
                    "/api",
                    json={"method": "add_comment", "args": [shot_id, "Check continuity"]},
                )
            self.assertEqual(dispatch_comment.status_code, 200)
            dispatch_payload = dispatch_comment.json()
            self.assertTrue(dispatch_payload["ok"], dispatch_payload.get("error"))
            dispatch_comments = dispatch_payload["result"]["shots"][0]["comments"]
            self.assertEqual(len(dispatch_comments), 2)
            second_id = max(item["id"] for item in dispatch_comments)

            with contextlib.redirect_stderr(io.StringIO()):
                dispatch_resolved = client.post(
                    "/api",
                    json={"method": "resolve_comment", "args": [shot_id, second_id, False]},
                )
            self.assertEqual(dispatch_resolved.status_code, 200)
            resolved_payload = dispatch_resolved.json()
            self.assertTrue(resolved_payload["ok"], resolved_payload.get("error"))
            resolved_comment = next(
                item for item in resolved_payload["result"]["shots"][0]["comments"] if item["id"] == second_id
            )
            self.assertFalse(resolved_comment["resolved"])

    def test_backup_retention_prunes_oldest_sets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Storyboard_Project"
            root.mkdir(parents=True)
            (root / "backups").mkdir()
            project = Project(root_path=root, settings=project_manager.DEFAULT_SETTINGS.copy())
            project.json_path.write_text("{}", encoding="utf-8")
            backups_dir = project.backups_dir
            for index in range(55):
                stamp = f"20260101_{index:06d}"
                (backups_dir / f"project_{stamp}.json").write_text("{}", encoding="utf-8")
                (backups_dir / f"shots_{stamp}.csv").write_text("id\n", encoding="utf-8")

            backups_module._prune_old_backups(project, keep=50)

            remaining = backups_module._backup_stamps(backups_dir)
            self.assertEqual(len(remaining), 50)
            self.assertEqual(remaining[0], "20260101_000054")
            self.assertEqual(remaining[-1], "20260101_000005")
            self.assertFalse((backups_dir / "project_20260101_000004.json").exists())

    @unittest.skipIf(find_spec("multipart") is None, "python-multipart is not installed")
    def test_upload_project_reference_rest_and_dispatch_share_backend_logic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = api_module.create_app(Path(tmp))
            client = TestClient(app, raise_server_exceptions=False)
            with contextlib.redirect_stderr(io.StringIO()):
                created = client.post("/api/project/new", json={"path": tmp})
            self.assertEqual(created.status_code, 200)

            with contextlib.redirect_stderr(io.StringIO()):
                rest = client.post(
                    "/api/project/references",
                    files={"file": ("ref.png", MINI_PNG, "image/png")},
                )
            self.assertEqual(rest.status_code, 200, rest.text)
            rest_links = rest.json()["settings"]["reference_links"]
            self.assertEqual(len(rest_links), 1)
            self.assertEqual(rest_links[0]["type"], "image")

            with contextlib.redirect_stderr(io.StringIO()):
                dispatch = client.post(
                    "/api",
                    json={
                        "method": "upload_project_reference",
                        "args": ["ref2.png", list(MINI_PNG)],
                    },
                )
            self.assertEqual(dispatch.status_code, 200, dispatch.text)
            dispatch_payload = dispatch.json()
            self.assertTrue(dispatch_payload["ok"], dispatch_payload.get("error"))
            dispatch_links = dispatch_payload["result"]["settings"]["reference_links"]
            self.assertEqual(len(dispatch_links), 2)

    @unittest.skipIf(find_spec("multipart") is None, "python-multipart is not installed")
    def test_import_shot_image_rest_and_dispatch_share_backend_logic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = api_module.create_app(Path(tmp))
            client = TestClient(app, raise_server_exceptions=False)
            with contextlib.redirect_stderr(io.StringIO()):
                created = client.post("/api/project/new", json={"path": tmp})
                shot_created = client.post("/api/shots", json={})
            self.assertEqual(created.status_code, 200)
            self.assertEqual(shot_created.status_code, 200)
            shot_id = shot_created.json()["shot"]["shot_id"]

            with contextlib.redirect_stderr(io.StringIO()):
                rest = client.post(
                    f"/api/shots/{shot_id}/image",
                    files={"file": ("board.png", MINI_PNG, "image/png")},
                )
            self.assertEqual(rest.status_code, 200, rest.text)
            rest_shot = rest.json()["shots"][0]
            self.assertTrue(rest_shot.get("preview_image_path") or rest_shot.get("image_path"))

            with contextlib.redirect_stderr(io.StringIO()):
                dispatch = client.post(
                    "/api",
                    json={
                        "method": "import_shot_image",
                        "args": [shot_id, "board2.png", list(MINI_PNG)],
                    },
                )
            self.assertEqual(dispatch.status_code, 200, dispatch.text)
            dispatch_payload = dispatch.json()
            self.assertTrue(dispatch_payload["ok"], dispatch_payload.get("error"))

    def test_canvas_color_rest_and_dispatch_share_backend_logic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = api_module.create_app(Path(tmp))
            client = TestClient(app, raise_server_exceptions=False)
            with contextlib.redirect_stderr(io.StringIO()):
                created = client.post("/api/project/new", json={"path": tmp})
            self.assertEqual(created.status_code, 200)

            with contextlib.redirect_stderr(io.StringIO()):
                rest_get = client.get("/api/project/canvas-color")
            self.assertEqual(rest_get.status_code, 200)
            self.assertEqual(rest_get.json()["color"], "#E8E8E8")

            with contextlib.redirect_stderr(io.StringIO()):
                rest_set = client.post("/api/project/canvas-color", json={"color": "#112233"})
            self.assertEqual(rest_set.status_code, 200)
            self.assertEqual(rest_set.json()["color"], "#112233")
            self.assertEqual(rest_set.json()["settings"]["canvas_background_color"], "#112233")

            with contextlib.redirect_stderr(io.StringIO()):
                dispatch_get = client.post("/api", json={"method": "get_canvas_color", "args": []})
            self.assertEqual(dispatch_get.status_code, 200)
            dispatch_get_payload = dispatch_get.json()
            self.assertTrue(dispatch_get_payload["ok"], dispatch_get_payload.get("error"))
            self.assertEqual(dispatch_get_payload["result"]["color"], "#112233")

            with contextlib.redirect_stderr(io.StringIO()):
                dispatch_set = client.post(
                    "/api",
                    json={"method": "set_canvas_color", "args": ["#AABBCC"]},
                )
            self.assertEqual(dispatch_set.status_code, 200)
            dispatch_set_payload = dispatch_set.json()
            self.assertTrue(dispatch_set_payload["ok"], dispatch_set_payload.get("error"))
            self.assertEqual(dispatch_set_payload["result"]["color"], "#AABBCC")

    def test_update_settings_rejects_invalid_photoshop_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = api_module.create_app(Path(tmp))
            client = TestClient(app, raise_server_exceptions=False)
            with contextlib.redirect_stderr(io.StringIO()):
                created = client.post("/api/project/new", json={"path": tmp})
            self.assertEqual(created.status_code, 200)

            with contextlib.redirect_stderr(io.StringIO()):
                rest = client.patch(
                    "/api/project/settings",
                    json={"photoshop_path": str(Path(tmp) / "missing-photoshop.exe")},
                )
            self.assertEqual(rest.status_code, 400)

            with contextlib.redirect_stderr(io.StringIO()):
                dispatch = client.post(
                    "/api",
                    json={
                        "method": "update_settings",
                        "args": [{"photoshop_path": str(Path(tmp) / "missing-photoshop.exe")}],
                    },
                )
            self.assertEqual(dispatch.status_code, 200)
            dispatch_payload = dispatch.json()
            self.assertFalse(dispatch_payload["ok"])
            self.assertIn("missing-photoshop.exe", dispatch_payload["error"])


if __name__ == "__main__":
    unittest.main()
