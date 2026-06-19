"""Plugin metadata boundary tests.

These tests verify that the backend enforces ownership of project metadata:
- preview_image_path / image_path must never point to a background plate
- source_file_path must be a .psd file
- Path traversal in plugin-supplied paths is rejected
- Preview relink always goes through the backend API validation path

The plugin is a client, not a metadata writer.  All path assignment must be
validated and committed by the backend.  These tests prevent regression of
bugs where the plugin could corrupt metadata by sending invalid paths.
"""
from __future__ import annotations

import tempfile
import unittest
import warnings
from pathlib import Path

with warnings.catch_warnings():
    warnings.filterwarnings("ignore", message="Using `httpx` with `starlette.testclient`")
    from fastapi.testclient import TestClient

from storyboard_tool import api as api_module

MINI_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000a49444154789c6300010000050001"
    "0d0a2db40000000049454e44ae426082"
)


class PluginMetadataBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.app = api_module.create_app(self.root)
        self.client = TestClient(self.app, raise_server_exceptions=False)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _open_project_with_shot(self) -> tuple[Path, str]:
        import contextlib
        import io

        def quiet(fn):
            with contextlib.redirect_stderr(io.StringIO()):
                return fn()

        created = quiet(lambda: self.client.post("/api/project/new", json={"path": self._tmp.name}))
        self.assertEqual(created.status_code, 200)
        project_root = Path(created.json()["project_path"])
        added = quiet(lambda: self.client.post("/api/shots", json={}))
        self.assertEqual(added.status_code, 200)
        return project_root, added.json()["shot"]["shot_id"]

    # ------------------------------------------------------------------
    # Background plate must never become preview metadata
    # ------------------------------------------------------------------

    def test_export_preview_rejects_background_path_as_preview(self) -> None:
        """plugin export-preview with _background.png as preview must return 400."""
        project_root, shot_id = self._open_project_with_shot()
        shot_dir = project_root / "shots" / shot_id
        shot_dir.mkdir(parents=True, exist_ok=True)

        background_rel = f"shots/{shot_id}/{shot_id}_background.png"
        (shot_dir / f"{shot_id}_background.png").write_bytes(MINI_PNG)

        response = self.client.post(
            f"/api/plugin/shots/{shot_id}/export-preview",
            json={"preview_image_path": background_rel},
        )
        self.assertEqual(response.status_code, 400, response.text)
        self.assertIn("background", response.json().get("detail", "").lower())

    def test_background_not_written_into_preview_metadata_after_rejection(self) -> None:
        """After a rejected export-preview, shot metadata is unchanged."""
        import contextlib
        import io

        project_root, shot_id = self._open_project_with_shot()
        shot_dir = project_root / "shots" / shot_id
        shot_dir.mkdir(parents=True, exist_ok=True)

        background_rel = f"shots/{shot_id}/{shot_id}_background.png"
        (shot_dir / f"{shot_id}_background.png").write_bytes(MINI_PNG)

        # Attempt to set background as preview (must fail).
        response = self.client.post(
            f"/api/plugin/shots/{shot_id}/export-preview",
            json={"preview_image_path": background_rel},
        )
        self.assertEqual(response.status_code, 400)

        # Check that shot metadata was NOT mutated.
        with contextlib.redirect_stderr(io.StringIO()):
            context = self.client.get("/api/plugin/context")
        self.assertEqual(context.status_code, 200)
        shots = context.json().get("shots", [])
        shot = next((s for s in shots if s["shot_id"] == shot_id), None)
        self.assertIsNotNone(shot)
        # preview_image_path must not point to the background file.
        self.assertNotIn("_background", shot.get("preview_image_path", ""))
        self.assertNotIn("_background", shot.get("image_path", ""))

    # ------------------------------------------------------------------
    # Path traversal rejection
    # ------------------------------------------------------------------

    def test_export_preview_rejects_path_traversal_in_preview_path(self) -> None:
        """plugin export-preview with path-traversal preview_image_path must return 400."""
        _project_root, shot_id = self._open_project_with_shot()

        response = self.client.post(
            f"/api/plugin/shots/{shot_id}/export-preview",
            json={"preview_image_path": "../../../etc/passwd"},
        )
        self.assertEqual(response.status_code, 400, response.text)

    def test_export_preview_rejects_path_traversal_in_source_path(self) -> None:
        """plugin export-preview with path-traversal source_file_path must return 400."""
        _project_root, shot_id = self._open_project_with_shot()

        response = self.client.post(
            f"/api/plugin/shots/{shot_id}/export-preview",
            json={"source_file_path": "../../outside_project.psd"},
        )
        self.assertEqual(response.status_code, 400, response.text)

    # ------------------------------------------------------------------
    # source_file_path must be a .psd file
    # ------------------------------------------------------------------

    def test_export_preview_rejects_non_psd_source_path(self) -> None:
        """plugin export-preview must reject a source_file_path that is not a .psd."""
        project_root, shot_id = self._open_project_with_shot()
        shot_dir = project_root / "shots" / shot_id
        shot_dir.mkdir(parents=True, exist_ok=True)
        (shot_dir / f"{shot_id}_preview.png").write_bytes(MINI_PNG)
        # Source is a .png, not a .psd — must be rejected.
        (shot_dir / f"{shot_id}_source.png").write_bytes(MINI_PNG)

        response = self.client.post(
            f"/api/plugin/shots/{shot_id}/export-preview",
            json={
                "preview_image_path": f"shots/{shot_id}/{shot_id}_preview.png",
                "source_file_path": f"shots/{shot_id}/{shot_id}_source.png",
            },
        )
        self.assertEqual(response.status_code, 400, response.text)

    def test_psd_saved_rejects_non_psd_source_path(self) -> None:
        """plugin psd-saved must reject a source_file_path that is not a .psd."""
        project_root, shot_id = self._open_project_with_shot()
        shot_dir = project_root / "shots" / shot_id
        shot_dir.mkdir(parents=True, exist_ok=True)
        (shot_dir / f"{shot_id}_preview.png").write_bytes(MINI_PNG)

        response = self.client.post(
            f"/api/plugin/shots/{shot_id}/psd-saved",
            json={"source_file_path": f"shots/{shot_id}/{shot_id}_preview.png"},
        )
        self.assertEqual(response.status_code, 400, response.text)

    # ------------------------------------------------------------------
    # Preview relink goes through backend validation
    # ------------------------------------------------------------------

    def test_preview_relink_in_linked_mode_goes_through_backend(self) -> None:
        """Valid export-preview sets preview_image_path via backend validation."""
        project_root, shot_id = self._open_project_with_shot()
        shot_dir = project_root / "shots" / shot_id
        shot_dir.mkdir(parents=True, exist_ok=True)
        preview_rel = f"shots/{shot_id}/{shot_id}_preview.png"
        source_rel = f"shots/{shot_id}/{shot_id}.psd"
        (shot_dir / f"{shot_id}_preview.png").write_bytes(MINI_PNG)
        (shot_dir / f"{shot_id}.psd").write_bytes(b"8BPS" + b"\0" * 32)

        response = self.client.post(
            f"/api/plugin/shots/{shot_id}/export-preview",
            json={"preview_image_path": preview_rel, "source_file_path": source_rel},
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        # Backend assigned the preview path — plugin did not write it locally.
        self.assertEqual(body["shot"]["preview_image_path"], preview_rel)
        self.assertEqual(body["shot"]["source_file_path"], source_rel)

    def test_source_file_path_is_psd_only_after_valid_export(self) -> None:
        """source_file_path in metadata must always point to the .psd, never a PNG."""
        project_root, shot_id = self._open_project_with_shot()
        shot_dir = project_root / "shots" / shot_id
        shot_dir.mkdir(parents=True, exist_ok=True)
        (shot_dir / f"{shot_id}_preview.png").write_bytes(MINI_PNG)
        (shot_dir / f"{shot_id}.psd").write_bytes(b"8BPS" + b"\0" * 32)

        self.client.post(
            f"/api/plugin/shots/{shot_id}/export-preview",
            json={
                "preview_image_path": f"shots/{shot_id}/{shot_id}_preview.png",
                "source_file_path": f"shots/{shot_id}/{shot_id}.psd",
            },
        )
        import contextlib
        import io

        with contextlib.redirect_stderr(io.StringIO()):
            context = self.client.get("/api/plugin/context")
        shot = next(
            (s for s in context.json().get("shots", []) if s["shot_id"] == shot_id), None
        )
        self.assertIsNotNone(shot)
        src = shot.get("source_file_path", "")
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
