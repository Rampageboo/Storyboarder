from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
import warnings
from pathlib import Path
from unittest import mock

with warnings.catch_warnings():
    warnings.filterwarnings("ignore", message="Using `httpx` with `starlette.testclient`")
    from fastapi.testclient import TestClient

from storyboard_tool import api as api_module
from storyboard_tool import backend_service as backend_service_module
from storyboard_tool import live_bridge
from storyboard_tool.schemas import BridgeStatusResponse, PluginContextResponse


MINI_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000a49444154789c6300010000050001"
    "0d0a2db40000000049454e44ae426082"
)


def _quiet(fn):
    with contextlib.redirect_stderr(io.StringIO()):
        return fn()


class PhotoshopBridgeContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        # Isolate the machine-global bridge dir to a temp path. Otherwise this test
        # reads C:/Users/Public/StoryboardTool/storyboard_plugin_heartbeat.json — a
        # file a real running app instance keeps fresh — making plugin_linked flap
        # True and the no-project contract assertion fail. See live_bridge dir helpers.
        bridge_dir = self.root / "_bridge"
        bridge_dir.mkdir(parents=True, exist_ok=True)
        for name in ("global_bridge_dir", "shared_bridge_dir"):
            patcher = mock.patch.object(live_bridge, name, return_value=bridge_dir)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.app = api_module.create_app(self.root)
        self.client = TestClient(self.app, raise_server_exceptions=False)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _open_project_with_shot(self) -> tuple[Path, str]:
        created = _quiet(lambda: self.client.post("/api/project/new", json={"path": self._tmp.name}))
        self.assertEqual(created.status_code, 200)
        project_root = Path(created.json()["project_path"])
        added = _quiet(lambda: self.client.post("/api/shots", json={}))
        self.assertEqual(added.status_code, 200)
        return project_root, added.json()["shot"]["shot_id"]

    def test_bridge_status_no_project_has_stable_contract(self) -> None:
        response = self.client.get("/api/bridge/status")
        self.assertEqual(response.status_code, 200)
        status = BridgeStatusResponse.model_validate(response.json())
        self.assertTrue(status.app_running)
        self.assertFalse(status.project_open)
        self.assertFalse(status.plugin_linked)
        self.assertEqual(status.plugin_selected_shot_id, "")
        self.assertEqual(status.plugin_open_shot_ids, [])
        self.assertEqual(status.plugin_project_revision, 0)
        self.assertIn("/api/bridge/live", status.bridge_url)

    def test_plugin_heartbeat_updates_bridge_status(self) -> None:
        _project_root, shot_id = self._open_project_with_shot()
        response = self.client.post(
            "/api/plugin/heartbeat",
            json={"selected_shot_id": shot_id, "open_shot_ids": [shot_id, ""]},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": "true"})

        status = BridgeStatusResponse.model_validate(self.client.get("/api/bridge/status").json())
        self.assertTrue(status.plugin_linked)
        self.assertEqual(status.plugin_selected_shot_id, shot_id)
        self.assertEqual(status.plugin_open_shot_ids, [shot_id])

    def test_file_heartbeat_updates_validated_work_key_status(self) -> None:
        _project_root, shot_id = self._open_project_with_shot()
        stale = self.client.post(
            "/api/plugin/heartbeat",
            json={"selected_shot_id": shot_id, "open_shot_ids": [shot_id]},
        )
        self.assertEqual(stale.status_code, 200)

        active_key = f"shot:{shot_id}"
        live_bridge.plugin_heartbeat_file_path().write_text(
            json.dumps(
                {
                    "selected_shot_id": "",
                    "open_shot_ids": [],
                    "active_work_key": active_key,
                    "open_work_keys": [active_key, "shot:missing"],
                }
            ),
            encoding="utf-8",
        )

        status = self.client.get("/api/bridge/status").json()
        self.assertTrue(status["plugin_linked"])
        self.assertEqual(status["plugin_selected_shot_id"], "")
        self.assertEqual(status["plugin_open_shot_ids"], [])
        self.assertEqual(status["plugin_active_work_key"], active_key)
        self.assertEqual(status["plugin_open_work_keys"], [active_key])

    def test_plugin_context_includes_project_shot_and_bridge_contract(self) -> None:
        _project_root, shot_id = self._open_project_with_shot()
        self.client.post("/api/plugin/heartbeat", json={"selected_shot_id": shot_id, "open_shot_ids": [shot_id]})

        response = self.client.get("/api/plugin/context")
        self.assertEqual(response.status_code, 200)
        context = PluginContextResponse.model_validate(response.json())
        self.assertEqual(context.selected_shot_id, shot_id)
        self.assertTrue(context.project_root)
        self.assertTrue(context.project_json_path.endswith("project.json"))
        self.assertGreaterEqual(len(context.shots), 1)
        self.assertIn("width", context.canvas)
        self.assertIn("background_color", context.canvas)
        self.assertIn("plugin_project_revision", context.bridge)

    def test_plugin_export_preview_and_psd_saved_increment_project_revision(self) -> None:
        project_root, shot_id = self._open_project_with_shot()
        shot_dir = project_root / "shots" / shot_id
        shot_dir.mkdir(parents=True, exist_ok=True)
        preview_rel = f"shots/{shot_id}/{shot_id}_preview.png"
        source_rel = f"shots/{shot_id}/{shot_id}.psd"
        (shot_dir / f"{shot_id}_preview.png").write_bytes(MINI_PNG)
        (shot_dir / f"{shot_id}.psd").write_bytes(b"8BPS" + b"\0" * 32)

        exported = self.client.post(
            f"/api/plugin/shots/{shot_id}/export-preview",
            json={"preview_image_path": preview_rel, "source_file_path": source_rel},
        )
        self.assertEqual(exported.status_code, 200)
        exported_body = exported.json()
        self.assertEqual(exported_body["shot"]["preview_image_path"], preview_rel)
        self.assertIn("context", exported_body)
        revision_after_export = self.client.get("/api/bridge/status").json()["plugin_project_revision"]
        self.assertGreaterEqual(revision_after_export, 1)

        saved = self.client.post(f"/api/plugin/shots/{shot_id}/psd-saved", json={"source_file_path": source_rel})
        self.assertEqual(saved.status_code, 200)
        saved_body = saved.json()
        self.assertEqual(saved_body["shot"]["source_file_path"], source_rel)
        self.assertIn("context", saved_body)
        revision_after_save = self.client.get("/api/bridge/status").json()["plugin_project_revision"]
        self.assertGreater(revision_after_save, revision_after_export)

    def test_plugin_context_without_project_uses_structured_no_project_error(self) -> None:
        response = _quiet(lambda: self.client.get("/api/plugin/context"))
        self.assertEqual(response.status_code, 400)
        body = response.json()
        self.assertEqual(body.get("code"), "PROJECT_NOT_OPEN")
        self.assertIn("detail", body)

    def test_app_focus_no_window_is_clean_noop(self) -> None:
        response = self.client.post("/api/app/focus")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertFalse(body["focused"])
        # Diagnostic fields returned even with no window.
        self.assertIn("shown", body)
        self.assertIn("restored_from_minimized", body)

    def test_app_focus_uses_desktop_window_when_available(self) -> None:
        calls: list[str] = []

        class Window:
            # No .minimized attribute → window is not minimized; restore must not be called.
            def restore(self) -> None:
                calls.append("restore")

            def show(self) -> None:
                calls.append("show")

            def focus(self) -> None:
                calls.append("focus")

        self.app.state.main_window = Window()
        response = self.client.post("/api/app/focus")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertTrue(body["focused"])
        # restore must NOT be called for a non-minimized window.
        self.assertNotIn("restore", calls)
        self.assertIn("show", calls)
        self.assertIn("focus", calls)
        self.assertFalse(body["restored_from_minimized"])

    def test_preheat_photoshop_missing_path_is_clean_noop(self) -> None:
        with mock.patch.object(backend_service_module, "preheat_photoshop") as preheat:
            preheat.return_value = {
                "ok": True,
                "attempted": False,
                "launched": False,
                "message": "Photoshop path is not configured.",
            }
            response = self.client.post("/api/app/preheat-photoshop")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "ok": True,
                "attempted": False,
                "launched": False,
                "message": "Photoshop path is not configured.",
            },
        )
        preheat.assert_called_once_with("")


if __name__ == "__main__":
    unittest.main()
