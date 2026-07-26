from __future__ import annotations

import contextlib
import io
import json
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

from storyboard_tool import desktop, live_bridge, project_manager
from storyboard_tool import api as api_module
from storyboard_tool import backend_service as backend_service_module
from storyboard_tool import export_service as export_service_module
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
        react_index = Path("storyboard_tool/web/dist/index.html")
        with tempfile.TemporaryDirectory() as tmp:
            app = api_module.create_app(Path(tmp))
            client = TestClient(app, raise_server_exceptions=False)

            with contextlib.redirect_stderr(io.StringIO()):
                response = client.get("/api/bridge/status")
                self.assertEqual(response.status_code, 200)

            with contextlib.redirect_stderr(io.StringIO()):
                response = client.get("/legacy")
                self.assertEqual(response.status_code, 404)

            # /ref-video redirects to / so bridge.py can open a second pywebview window.
            with contextlib.redirect_stderr(io.StringIO()):
                response = client.get("/ref-video", follow_redirects=False)
                self.assertEqual(response.status_code, 302)
                self.assertEqual(response.headers.get("location"), "/")

            # /ref-segment and /ref-scene3d were removed (dead standalone window routes).
            with contextlib.redirect_stderr(io.StringIO()):
                for route in ("/ref-segment", "/ref-scene3d"):
                    with self.subTest(route=route):
                        response = client.get(route, follow_redirects=False)
                        self.assertEqual(response.status_code, 404)

            if react_index.is_file():
                with contextlib.redirect_stderr(io.StringIO()):
                    for route in ("/", "/react"):
                        with self.subTest(route=route):
                            response = client.get(route)
                            self.assertEqual(response.status_code, 200)
            else:
                with contextlib.redirect_stderr(io.StringIO()):
                    for route in ("/", "/react"):
                        with self.subTest(route=route):
                            response = client.get(route)
                            self.assertEqual(response.status_code, 404)

    def test_runtime_modules_served(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = api_module.create_app(Path(tmp))
            client = TestClient(app, raise_server_exceptions=False)
            for route in (
                "/static/runtime/scene3d_workspace.js",
            ):
                with self.subTest(route=route):
                    response = client.get(route)
                    self.assertEqual(response.status_code, 200)

    def test_deleted_runtime_files_return_404(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = api_module.create_app(Path(tmp))
            client = TestClient(app, raise_server_exceptions=False)
            for route in (
                "/static/runtime/scene3d.js",
                "/static/runtime/scene3d_preview_style.js",
                "/static/runtime/favicon.svg",
                "/static/runtime/icons.svg",
            ):
                with self.subTest(route=route):
                    response = client.get(route)
                    self.assertEqual(response.status_code, 404)

    @unittest.skipIf(find_spec("multipart") is None, "python-multipart is not installed")
    def test_rest_pdf_export_route_reaches_exporter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            original_export = export_service_module.export_pdf

            def fake_export(project, layout="two_per_page", suffix=""):
                self.assertEqual(layout, "two_per_page")
                self.assertEqual(suffix, "")
                output_path = project.exports_dir / "storyboard.pdf"
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(b"%PDF-1.4\n")
                return output_path

            export_service_module.export_pdf = fake_export
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

                with contextlib.redirect_stderr(io.StringIO()):
                    download = client.get("/api/export/pdf")
                self.assertEqual(download.status_code, 200)
                self.assertIn("application/pdf", download.headers.get("content-type", ""))
                self.assertEqual(download.content, b"%PDF-1.4\n")
            finally:
                export_service_module.export_pdf = original_export

    def test_export_download_returns_404_before_export(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = api_module.create_app(Path(tmp))
            client = TestClient(app, raise_server_exceptions=False)
            with contextlib.redirect_stderr(io.StringIO()):
                created = client.post("/api/project/new", json={"path": tmp})
            self.assertEqual(created.status_code, 200)

            with contextlib.redirect_stderr(io.StringIO()):
                response = client.get("/api/export/shot-list")
            self.assertEqual(response.status_code, 404)

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

    def test_reference_segment_apply_routes_reach_backend(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = api_module.create_app(Path(tmp))
            client = TestClient(app, raise_server_exceptions=False)
            with contextlib.redirect_stderr(io.StringIO()):
                client.post("/api/project/new", json={"path": tmp})
            calls = [
                ("/api/project/ref-segment/apply", {"anchor_shot_id": "shot_a", "end_shot_id": "shot_b"}),
                ("/api/project/ref-segment/apply-image", {"anchor_shot_id": "shot_a", "end_shot_id": "shot_b"}),
                (
                    "/api/project/ref-segment/apply-3d",
                    {"anchor_shot_id": "shot_a", "end_shot_id": "shot_b", "camera_name": "Camera"},
                ),
            ]

            for path, body in calls:
                with self.subTest(path=path):
                    with contextlib.redirect_stderr(io.StringIO()):
                        response = client.post(path, json=body)
                    # Route is registered and reaches the service: the only failure is
                    # the missing shot, not an unregistered endpoint.
                    self.assertEqual(response.status_code, 404)
                    self.assertIn("Shot not found", response.json()["detail"])

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

    def test_start_internal_server_accepts_ephemeral_port(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = api_module.create_app(Path(tmp))
            with contextlib.redirect_stderr(io.StringIO()):
                thread, port = desktop.start_internal_server(app, port=0)

            self.assertGreater(port, 0)
            self.assertTrue(thread.is_alive())
            self.assertEqual(app.state.bridge_port, port)

    def test_resolve_server_port_accepts_ephemeral_port(self) -> None:
        port = live_bridge.resolve_server_port("127.0.0.1", 0)

        self.assertGreater(port, 0)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", port))

    def test_requirements_dev_lists_playwright(self) -> None:
        text = Path("requirements-dev.txt").read_text(encoding="utf-8")
        self.assertIn("playwright", text.lower())

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
            self.assertFalse(payload["settings"]["preheat_photoshop_on_open"])

            with contextlib.redirect_stderr(io.StringIO()):
                updated = client.patch(
                    "/api/project/settings",
                    json={
                        "canvas_width": 1080,
                        "canvas_height": 1080,
                        "apply_canvas_size_to_blank_shots": False,
                        "preheat_photoshop_on_open": True,
                    },
                )
            self.assertEqual(updated.status_code, 200)
            settings = updated.json()["settings"]
            self.assertEqual(settings["canvas_width"], 1080)
            self.assertEqual(settings["canvas_height"], 1080)
            self.assertTrue(settings["preheat_photoshop_on_open"])


    def test_open_blender_scene_returns_project_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = api_module.create_app(Path(tmp))
            client = TestClient(app, raise_server_exceptions=False)
            with contextlib.redirect_stderr(io.StringIO()):
                created = client.post("/api/project/new", json={"path": tmp})
            self.assertEqual(created.status_code, 200)

            original_open = project_manager.open_blender_scene

            def fake_open_blender_scene(project, relative_path=""):
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

    def test_update_settings_clears_reference_model_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = api_module.create_app(Path(tmp))
            client = TestClient(app, raise_server_exceptions=False)
            with contextlib.redirect_stderr(io.StringIO()):
                created = client.post("/api/project/new", json={"path": tmp})
            self.assertEqual(created.status_code, 200)
            settings_json = Path(tmp) / "Storyboard_Project" / "settings.json"

            def read_saved_mode() -> str:
                return json.loads(settings_json.read_text(encoding="utf-8")).get("reference_segment_mode", "")

            with contextlib.redirect_stderr(io.StringIO()):
                client.patch("/api/project/settings", json={"reference_segment_mode": "model"})
                rest = client.patch("/api/project/settings", json={"reference_model_path": ""})
            self.assertEqual(rest.status_code, 200, rest.text)
            self.assertEqual(rest.json()["settings"]["reference_segment_mode"], "video")
            self.assertEqual(read_saved_mode(), "video")

    def test_update_settings_persists_canvas_color_and_scene3d_together(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = api_module.create_app(Path(tmp))
            client = TestClient(app, raise_server_exceptions=False)
            with contextlib.redirect_stderr(io.StringIO()):
                created = client.post("/api/project/new", json={"path": tmp})
            self.assertEqual(created.status_code, 200)

            scene3d = {"file_path": "scene3d/scene.glb", "camera_name": "Camera_A"}
            with contextlib.redirect_stderr(io.StringIO()):
                rest = client.patch(
                    "/api/project/settings",
                    json={
                        "canvas_background_color": "#112233",
                        "preheat_photoshop_on_open": True,
                        "scene3d": scene3d,
                    },
                )
            self.assertEqual(rest.status_code, 200, rest.text)
            settings = rest.json()["settings"]
            self.assertEqual(settings["canvas_background_color"], "#112233")
            self.assertTrue(settings["preheat_photoshop_on_open"])
            self.assertEqual(settings["scene3d"], scene3d)

            settings_json = Path(tmp) / "Storyboard_Project" / "settings.json"
            saved = json.loads(settings_json.read_text(encoding="utf-8"))
            self.assertEqual(saved["canvas_background_color"], "#112233")
            self.assertTrue(saved["preheat_photoshop_on_open"])
            self.assertEqual(saved["scene3d"], scene3d)

    def test_project_lifecycle_new_save_open(self) -> None:
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
                second_created = client.post(
                    "/api/project/new",
                    json={
                        "path": str(Path(tmp) / "Second_Project"),
                        "canvas_width": 1600,
                        "canvas_height": 900,
                    },
                )
            self.assertEqual(second_created.status_code, 200)
            self.assertEqual(second_created.json()["settings"]["canvas_width"], 1600)

            project_json = Path(tmp) / "Second_Project" / "Storyboard_Project" / "project.json"
            with contextlib.redirect_stderr(io.StringIO()):
                opened = client.post("/api/project/open", json={"project_json_path": str(project_json)})
            self.assertEqual(opened.status_code, 200)
            self.assertEqual(opened.json()["settings"]["canvas_width"], 1600)

    def test_comment_add_and_resolve(self) -> None:
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
                second_comment = client.post(
                    f"/api/shots/{shot_id}/comments",
                    json={"text": "Check continuity"},
                )
            self.assertEqual(second_comment.status_code, 200)
            second_comments = second_comment.json()["shots"][0]["comments"]
            self.assertEqual(len(second_comments), 2)
            second_id = max(item["id"] for item in second_comments)

            with contextlib.redirect_stderr(io.StringIO()):
                reopened = client.patch(
                    f"/api/shots/{shot_id}/comments/{second_id}",
                    json={"resolved": False},
                )
            self.assertEqual(reopened.status_code, 200)
            reopened_comment = next(
                item for item in reopened.json()["shots"][0]["comments"] if item["id"] == second_id
            )
            self.assertFalse(reopened_comment["resolved"])

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
    def test_upload_project_reference_rest(self) -> None:
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
                second = client.post(
                    "/api/project/references",
                    files={"file": ("ref2.png", MINI_PNG, "image/png")},
                )
            self.assertEqual(second.status_code, 200, second.text)
            second_links = second.json()["settings"]["reference_links"]
            self.assertEqual(len(second_links), 2)

    @unittest.skipIf(find_spec("multipart") is None, "python-multipart is not installed")
    def test_import_shot_image_rest(self) -> None:
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
                second = client.post(
                    f"/api/shots/{shot_id}/image",
                    files={"file": ("board2.png", MINI_PNG, "image/png")},
                )
            self.assertEqual(second.status_code, 200, second.text)
            second_shot = second.json()["shots"][0]
            self.assertTrue(second_shot.get("preview_image_path") or second_shot.get("image_path"))

    def test_canvas_color_rest(self) -> None:
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
                reget = client.get("/api/project/canvas-color")
            self.assertEqual(reget.status_code, 200)
            self.assertEqual(reget.json()["color"], "#112233")

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
            self.assertIn("missing-photoshop.exe", rest.json()["detail"])

    def test_sync_prefers_fresh_preview_over_psd_recomposite(self) -> None:
        from PIL import Image

        from storyboard_tool import linked_sync
        from storyboard_tool.image_utils import create_blank_psd

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shot_dir = root / "shots" / "shot_001"
            shot_dir.mkdir(parents=True)
            preview_path = shot_dir / "shot_001_preview.png"
            psd_path = shot_dir / "shot_001.psd"
            Image.new("RGB", (20, 20), (255, 0, 0)).save(preview_path, "PNG")
            create_blank_psd(psd_path, 100, 100, background_color="#E8E8E8")
            psd_path.touch()

            shot = Shot(
                shot_id="shot_001",
                preview_image_path="shots/shot_001/shot_001_preview.png",
                image_path="shots/shot_001/shot_001_preview.png",
                source_file_path="shots/shot_001/shot_001.psd",
            )
            project = Project(root_path=root, shots=[shot])

            result = linked_sync.sync_shot_from_linked_files(project, shot, force=True)
            self.assertTrue(result.get("synced"))

            with Image.open(preview_path) as synced:
                self.assertEqual(synced.getpixel((10, 10)), (255, 0, 0))

    def test_preview_export_layer_filter_drops_canvas_background(self) -> None:
        from storyboard_tool.image_utils import preview_export_layer_filter

        class Layer:
            def __init__(self, name: str):
                self.name = name

        self.assertFalse(preview_export_layer_filter(Layer("Background")))
        self.assertFalse(preview_export_layer_filter(Layer("SB bg")))
        self.assertFalse(preview_export_layer_filter(Layer("SB ref: shot_001")))
        self.assertTrue(preview_export_layer_filter(Layer("Layer 1")))

    def test_transparent_preview_is_not_solid_color_plate(self) -> None:
        from PIL import Image

        from storyboard_tool.image_utils import is_solid_color_image

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "preview.png"
            image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
            for x in range(20, 40):
                image.putpixel((x, 32), (255, 0, 0, 255))
            image.save(path, "PNG")
            self.assertFalse(is_solid_color_image(path))

    def test_canvas_color_sync_skips_psd_backed_shots(self) -> None:
        from storyboard_tool import canvas_settings
        from storyboard_tool.image_utils import create_blank_psd

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shot_dir = root / "shots" / "shot_001"
            shot_dir.mkdir(parents=True)
            preview_path = shot_dir / "shot_001_preview.png"
            preview_path.write_bytes(MINI_PNG)
            create_blank_psd(shot_dir / "shot_001.psd", 100, 100)
            shot = Shot(
                shot_id="shot_001",
                preview_image_path="",
                image_path="",
                source_file_path="shots/shot_001/shot_001.psd",
            )
            project = Project(root_path=root, shots=[shot])
            changed = canvas_settings._sync_shot_canvas_color_assets(project, shot, "#AABBCC")
            self.assertFalse(changed)
            self.assertFalse(shot.preview_image_path)
            self.assertTrue(preview_path.is_file())

    def test_resolve_shot_preview_path_falls_back_to_disk(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shot_dir = root / "shots" / "shot_025"
            shot_dir.mkdir(parents=True)
            preview_path = shot_dir / "shot_025_preview.png"
            preview_path.write_bytes(MINI_PNG)
            shot = Shot(shot_id="shot_025")
            project = Project(root_path=root, shots=[shot])
            resolved = project_manager.resolve_shot_preview_path(project, shot)
            self.assertEqual(resolved, preview_path)

    def test_plugin_export_preview_validates_project_relative_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = api_module.create_app(root)
            client = TestClient(app, raise_server_exceptions=False)

            with contextlib.redirect_stderr(io.StringIO()):
                created = client.post("/api/project/new", json={"path": tmp})
            self.assertEqual(created.status_code, 200)
            root = Path(created.json()["project_path"])
            with contextlib.redirect_stderr(io.StringIO()):
                added = client.post("/api/shots", json={})
            self.assertEqual(added.status_code, 200)
            shot_id = added.json()["shot"]["shot_id"]
            shot_dir = root / "shots" / shot_id
            shot_dir.mkdir(parents=True, exist_ok=True)
            preview_rel = f"shots/{shot_id}/{shot_id}_preview.png"
            source_rel = f"shots/{shot_id}/{shot_id}.psd"
            (shot_dir / f"{shot_id}_preview.png").write_bytes(MINI_PNG)
            (shot_dir / f"{shot_id}.psd").write_bytes(b"8BPS" + b"\0" * 32)

            with contextlib.redirect_stderr(io.StringIO()):
                valid = client.post(
                    f"/api/plugin/shots/{shot_id}/export-preview",
                    json={"preview_image_path": preview_rel, "source_file_path": source_rel},
                )
            self.assertEqual(valid.status_code, 200)
            payload = valid.json()
            self.assertEqual(payload["shot"]["source_file_path"], source_rel)
            self.assertEqual(payload["shot"]["preview_image_path"], preview_rel)
            self.assertIn("context", payload)
            status = client.get("/api/bridge/status")
            self.assertEqual(status.status_code, 200)
            self.assertGreaterEqual(status.json()["plugin_project_revision"], 1)

            with contextlib.redirect_stderr(io.StringIO()):
                bad_preview = client.post(
                    f"/api/plugin/shots/{shot_id}/export-preview",
                    json={"preview_image_path": "../../outside.png", "source_file_path": source_rel},
                )
            self.assertEqual(bad_preview.status_code, 400)

            with contextlib.redirect_stderr(io.StringIO()):
                bad_source = client.post(
                    f"/api/plugin/shots/{shot_id}/export-preview",
                    json={"preview_image_path": preview_rel, "source_file_path": "../../outside.psd"},
                )
            self.assertEqual(bad_source.status_code, 400)

            text_source = shot_dir / "not-a-psd.txt"
            text_source.write_text("not psd", encoding="utf-8")
            with contextlib.redirect_stderr(io.StringIO()):
                non_psd = client.post(
                    f"/api/plugin/shots/{shot_id}/export-preview",
                    json={"preview_image_path": preview_rel, "source_file_path": f"shots/{shot_id}/not-a-psd.txt"},
                )
            self.assertEqual(non_psd.status_code, 400)

    def test_delete_ref_segment_keeps_drawing_when_psd_exists_without_link(self) -> None:
        from storyboard_tool import reference_segments
        from storyboard_tool.image_utils import board_background_filename, create_blank_psd

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shot_dir = root / "shots" / "shot_001"
            shot_dir.mkdir(parents=True)
            create_blank_psd(shot_dir / "shot_001.psd", 100, 100)
            preview_path = shot_dir / "shot_001_preview.png"
            preview_path.write_bytes(MINI_PNG)
            background_path = shot_dir / board_background_filename("shot_001")
            background_path.write_bytes(MINI_PNG)

            shot = Shot(
                shot_id="shot_001",
                preview_image_path="shots/shot_001/shot_001_preview.png",
                image_path="shots/shot_001/shot_001_preview.png",
                ref_video_path="references/ref.mp4",
            )
            project = Project(
                root_path=root,
                shots=[shot],
                settings={
                    "ref_segments": [
                        {
                            "id": "seg_test",
                            "anchor_shot_id": "shot_001",
                            "end_shot_id": "shot_001",
                            "source_type": "video",
                        }
                    ]
                },
            )

            reference_segments.delete_ref_segment(project, "seg_test")

            self.assertTrue(shot.preview_image_path)
            self.assertTrue(shot.image_path)
            self.assertFalse(background_path.is_file())

    def test_psd_recovery_skips_plugin_managed_layers(self) -> None:
        from storyboard_tool import psd_recovery

        self.assertTrue(psd_recovery._is_plugin_managed_layer_name("Background"))
        self.assertTrue(psd_recovery._is_plugin_managed_layer_name("SB bg"))
        self.assertTrue(psd_recovery._is_plugin_managed_layer_name("SB ref: shot_001"))
        self.assertFalse(psd_recovery._is_plugin_managed_layer_name("Layer 1"))


if __name__ == "__main__":
    unittest.main()
