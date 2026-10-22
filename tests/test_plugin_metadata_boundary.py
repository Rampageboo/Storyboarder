"""Plugin metadata boundary tests.

These tests verify that the backend enforces ownership of project metadata:
- preview_image_path / image_path must never point to a background plate
- source_file_path must be a .psd file
- client-supplied paths (including traversal) are never authority
- Preview relink always goes through the backend write-intent path

The plugin is a client, not a metadata writer.  All path assignment is
decided by the backend (canonical role paths) and committed through a
single-use write intent.  These tests prevent regression of bugs where the
plugin could corrupt metadata by sending invalid paths.
"""
from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
import warnings
from pathlib import Path

with warnings.catch_warnings():
    warnings.filterwarnings("ignore", message="Using `httpx` with `starlette.testclient`")
    from fastapi.testclient import TestClient

from storyboard_tool import api as api_module
from storyboard_tool.plugin_service import (
    EXPLICIT_ASSET_PATHS_CAPABILITY,
    PLUGIN_PROTOCOL_VERSION,
)

MINI_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000a49444154789c6300010000050001"
    "0d0a2db40000000049454e44ae426082"
)
MINI_PSD = b"8BPS" + b"\0" * 32


def _quiet(fn):
    with contextlib.redirect_stderr(io.StringIO()):
        return fn()


class PluginMetadataBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.app = api_module.create_app(self.root)
        self.client = TestClient(self.app, raise_server_exceptions=False)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _open_project_with_shot(self) -> tuple[Path, str]:
        created = _quiet(
            lambda: self.client.post(
                "/api/project/new", json={"path": str(self.root / "Demo.sbd")}
            )
        )
        self.assertEqual(created.status_code, 200, created.text)
        project_root = Path(created.json()["project_path"]).parent
        added = _quiet(lambda: self.client.post("/api/shots", json={}))
        self.assertEqual(added.status_code, 200)
        return project_root, added.json()["shot"]["shot_id"]

    def _headers(self, *, work_key: str = "", asset_role: str = "", token: str = "") -> dict[str, str]:
        headers = {
            "x-storyboarder-protocol": str(PLUGIN_PROTOCOL_VERSION),
            "x-storyboarder-capabilities": EXPLICIT_ASSET_PATHS_CAPABILITY,
            "x-storyboarder-project-session": str(self.app.state.project_session_id),
            "x-storyboarder-context-revision": str(self.app.state.project.storage_revision),
        }
        if work_key:
            headers["x-storyboarder-work-key"] = work_key
        if asset_role:
            headers["x-storyboarder-asset-role"] = asset_role
        if token:
            headers["x-storyboarder-write-intent"] = token
        return headers

    def _intent(self, shot_id: str, role: str):
        return self.client.post(
            "/api/plugin/write-intents",
            headers=self._headers(),
            json={"work_key": f"shot:{shot_id}", "asset_role": role},
        )

    def _commit(self, shot_id: str, role: str, token: str, body: dict):
        endpoint = "export-preview" if role == "preview" else "psd-saved"
        return _quiet(lambda: self.client.post(
            f"/api/plugin/shots/{shot_id}/{endpoint}",
            headers=self._headers(work_key=f"shot:{shot_id}", asset_role=role, token=token),
            json=body,
        ))

    def _context_shot(self, shot_id: str) -> dict:
        context = _quiet(lambda: self.client.get("/api/plugin/context", headers=self._headers()))
        self.assertEqual(context.status_code, 200, context.text)
        shot = next((s for s in context.json().get("shots", []) if s["shot_id"] == shot_id), None)
        self.assertIsNotNone(shot)
        return shot

    # ------------------------------------------------------------------
    # Background plate must never become preview metadata
    # ------------------------------------------------------------------

    def test_export_preview_without_write_intent_rejects_background_path(self) -> None:
        """A client-supplied background path without a write intent is rejected."""
        project_root, shot_id = self._open_project_with_shot()
        background = project_root / "Images" / "Shots" / f"{shot_id}_background.png"
        background.parent.mkdir(parents=True, exist_ok=True)
        background.write_bytes(MINI_PNG)

        response = self.client.post(
            f"/api/plugin/shots/{shot_id}/export-preview",
            headers=self._headers(work_key=f"shot:{shot_id}", asset_role="preview"),
            json={"preview_image_path": f"Images/Shots/{shot_id}_background.png"},
        )
        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(response.json()["code"], "PLUGIN_WRITE_INTENT_REJECTED")

    def test_background_not_written_into_preview_metadata_after_rejection(self) -> None:
        """After a rejected export-preview, shot metadata is unchanged."""
        project_root, shot_id = self._open_project_with_shot()
        background = project_root / "Images" / "Shots" / f"{shot_id}_background.png"
        background.parent.mkdir(parents=True, exist_ok=True)
        background.write_bytes(MINI_PNG)

        response = self.client.post(
            f"/api/plugin/shots/{shot_id}/export-preview",
            headers=self._headers(work_key=f"shot:{shot_id}", asset_role="preview"),
            json={"preview_image_path": f"Images/Shots/{shot_id}_background.png"},
        )
        self.assertNotEqual(response.status_code, 200)

        shot = self._context_shot(shot_id)
        self.assertNotIn("_background", shot.get("preview_image_path", ""))
        self.assertNotIn("_background", shot.get("image_path", ""))

    def test_board_background_role_is_not_writable(self) -> None:
        """The plugin cannot obtain a write intent for the board background plate."""
        _project_root, shot_id = self._open_project_with_shot()
        response = self._intent(shot_id, "board_background")
        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(response.json()["code"], "PLUGIN_WRITE_INTENT_REJECTED")

    # ------------------------------------------------------------------
    # Client-supplied paths (including traversal) are never authority
    # ------------------------------------------------------------------

    def test_export_preview_ignores_path_traversal_in_preview_path(self) -> None:
        """A traversal preview_image_path is ignored; the canonical preview is committed."""
        project_root, shot_id = self._open_project_with_shot()
        issued = self._intent(shot_id, "preview").json()
        Path(issued["write_path"]).write_bytes(MINI_PNG)

        response = self._commit(
            shot_id, "preview", issued["token"], {"preview_image_path": "../../../etc/passwd"}
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            response.json()["shot"]["preview_image_path"],
            f"Images/Shots/{shot_id}_preview.png",
        )
        self.assertEqual(
            (project_root / "Images" / "Shots" / f"{shot_id}_preview.png").read_bytes(),
            MINI_PNG,
        )

    def test_psd_saved_ignores_path_traversal_in_source_path(self) -> None:
        """A traversal source_file_path is ignored; the canonical PSD is recorded."""
        project_root, shot_id = self._open_project_with_shot()
        issued = self._intent(shot_id, "source_psd").json()
        Path(issued["canonical_path"]).write_bytes(MINI_PSD)

        response = self._commit(
            shot_id, "source_psd", issued["token"], {"source_file_path": "../../outside_project.psd"}
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["shot"]["source_file_path"], f"PSD/Shots/{shot_id}.psd")
        self.assertFalse((project_root.parent / "outside_project.psd").exists())

    # ------------------------------------------------------------------
    # source_file_path must be a .psd file; previews must be PNGs
    # ------------------------------------------------------------------

    def test_export_preview_rejects_non_png_inbox_file(self) -> None:
        """export-preview must reject an inbox file that is not a PNG."""
        _project_root, shot_id = self._open_project_with_shot()
        issued = self._intent(shot_id, "preview").json()
        Path(issued["write_path"]).write_bytes(MINI_PSD)

        response = self._commit(shot_id, "preview", issued["token"], {})
        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(self._context_shot(shot_id).get("preview_image_path", ""), "")

    def test_psd_saved_rejects_non_psd_source_file(self) -> None:
        """psd-saved must reject a canonical source file that is not a PSD."""
        _project_root, shot_id = self._open_project_with_shot()
        issued = self._intent(shot_id, "source_psd").json()
        Path(issued["canonical_path"]).write_bytes(MINI_PNG)

        response = self._commit(shot_id, "source_psd", issued["token"], {})
        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(self._context_shot(shot_id).get("source_file_path", ""), "")

    # ------------------------------------------------------------------
    # Preview relink goes through backend validation
    # ------------------------------------------------------------------

    def test_preview_relink_goes_through_backend(self) -> None:
        """Valid export-preview sets preview_image_path via the backend's canonical path."""
        _project_root, shot_id = self._open_project_with_shot()
        issued = self._intent(shot_id, "preview").json()
        Path(issued["write_path"]).write_bytes(MINI_PNG)

        response = self._commit(
            shot_id, "preview", issued["token"], {"preview_image_path": "elsewhere/x.png"}
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["shot"]["preview_image_path"], f"Images/Shots/{shot_id}_preview.png")
        self.assertEqual(body["shot"]["image_path"], f"Images/Shots/{shot_id}_preview.png")

    def test_source_file_path_is_psd_only_after_valid_save(self) -> None:
        """source_file_path in metadata must always point to the .psd, never a PNG."""
        _project_root, shot_id = self._open_project_with_shot()
        issued = self._intent(shot_id, "source_psd").json()
        Path(issued["canonical_path"]).write_bytes(MINI_PSD)
        response = self._commit(shot_id, "source_psd", issued["token"], {})
        self.assertEqual(response.status_code, 200, response.text)

        src = self._context_shot(shot_id).get("source_file_path", "")
        self.assertTrue(src.endswith(".psd"), f"source_file_path must end with .psd, got: {src}")

    # ------------------------------------------------------------------
    # Fallback write isolation: no direct endpoint exposes metadata writes
    # ------------------------------------------------------------------

    def test_no_direct_shots_json_write_endpoint_exists(self) -> None:
        """There must be no backend route that lets the plugin write shots.json directly."""
        _project_root, _shot_id = self._open_project_with_shot()
        # If such an endpoint existed, the plugin could bypass the ownership boundary.
        response = self.client.post("/api/plugin/write-shots-json", json={})
        self.assertIn(response.status_code, (404, 405, 422))

    def test_no_direct_project_json_write_endpoint_exists(self) -> None:
        """There must be no backend route that lets the plugin write project.json directly."""
        _project_root, _shot_id = self._open_project_with_shot()
        response = self.client.post("/api/plugin/write-project-json", json={})
        self.assertIn(response.status_code, (404, 405, 422))


if __name__ == "__main__":
    unittest.main()
