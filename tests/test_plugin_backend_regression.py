"""Plugin/backend integration regression tests.

Covers the boundary between the Photoshop UXP plugin and the backend service:

  Shot asset flags (project shot payload):
  - shot payloads include has_board_background and has_artwork_preview
  - has_artwork_preview is False when only a background plate or solid fill exists
  - has_artwork_preview is True only when real (non-solid) artwork PNG exists

  Plugin context contract:
  - image_path / preview_image_path never carry _background.png after any operation
  - work-item asset paths keep board_background separate from preview

  Plugin focus contract:
  - focusing a shot updates selected_shot_id in the returned context
  - focusing a shot does NOT touch image/preview/background asset metadata

  SB bg ownership no-op:
  - sync_psd_board_background always returns False (backend is a no-op)
  - sync_psd_board_background does not create or modify PSD files on disk
  - this is intentional: Photoshop plugin owns the in-PSD linked SB bg layer

  Source PSD / preview path separation:
  - source_file_path is always .psd after psd-saved
  - image_path / preview_image_path never become .psd paths

  Shots.json canonicality:
  - shots.json remains the canonical store after plugin-facing endpoint calls

Tests that already exist (not duplicated here):
  test_plugin_metadata_boundary.py:
    export_preview_without_write_intent_rejects_background_path
    background_not_written_into_preview_metadata_after_rejection
    board_background_role_is_not_writable
    export_preview_ignores_path_traversal_in_preview_path
    psd_saved_ignores_path_traversal_in_source_path
    export_preview_rejects_non_png_inbox_file
    psd_saved_rejects_non_psd_source_file
    preview_relink_goes_through_backend
    source_file_path_is_psd_only_after_valid_save
    no_direct_shots_json_write_endpoint_exists
    no_direct_project_json_write_endpoint_exists
  test_photoshop_bridge.py:
    test_plugin_heartbeat_updates_bridge_status
    test_plugin_context_includes_project_shot_and_bridge_contract
    test_plugin_export_preview_and_psd_saved_increment_project_revision
    test_plugin_context_without_project_uses_structured_no_project_error
"""
from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
import warnings
from pathlib import Path

with warnings.catch_warnings():
    warnings.filterwarnings("ignore", message="Using `httpx` with `starlette.testclient`")
    from fastapi.testclient import TestClient

from conftest import make_project
from storyboard_tool import api as api_module
from storyboard_tool import project_manager
from storyboard_tool.image_utils import board_background_filename
from storyboard_tool.plugin_service import (
    EXPLICIT_ASSET_PATHS_CAPABILITY,
    PLUGIN_PROTOCOL_VERSION,
)

# Minimal valid 1x1 transparent PNG for use as a test file.
MINI_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000a49444154789c6300010000050001"
    "0d0a2db40000000049454e44ae426082"
)
MINI_PSD = b"8BPS" + b"\x00" * 32


def _quiet(fn):
    with contextlib.redirect_stderr(io.StringIO()):
        return fn()


class _ProjectFixture(unittest.TestCase):
    """Base class providing a project + shot and a test client."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.app = api_module.create_app(self.root)
        self.client = TestClient(self.app, raise_server_exceptions=False)
        self.project_root, self.shot_id = self._open_project_with_shot()
        self.shot_images_dir = self.project_root / "Images" / "Shots"

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

    def _write_background_plate(self) -> Path:
        bg = self.shot_images_dir / board_background_filename(self.shot_id)
        bg.parent.mkdir(parents=True, exist_ok=True)
        bg.write_bytes(MINI_PNG)
        return bg

    def _commit_preview(self, png: bytes = MINI_PNG):
        """Write a preview through the plugin write-intent flow."""
        key = f"shot:{self.shot_id}"
        issued = self.client.post(
            "/api/plugin/write-intents",
            headers=self._headers(),
            json={"work_key": key, "asset_role": "preview"},
        )
        self.assertEqual(issued.status_code, 200, issued.text)
        Path(issued.json()["write_path"]).write_bytes(png)
        return _quiet(lambda: self.client.post(
            f"/api/plugin/shots/{self.shot_id}/export-preview",
            headers=self._headers(
                work_key=key, asset_role="preview", token=issued.json()["token"]
            ),
            json={},
        ))

    def _commit_psd(self, raw: bytes = MINI_PSD):
        """Save the source PSD through the plugin write-intent flow."""
        key = f"shot:{self.shot_id}"
        issued = self.client.post(
            "/api/plugin/write-intents",
            headers=self._headers(),
            json={"work_key": key, "asset_role": "source_psd"},
        )
        self.assertEqual(issued.status_code, 200, issued.text)
        Path(issued.json()["canonical_path"]).write_bytes(raw)
        return _quiet(lambda: self.client.post(
            f"/api/plugin/shots/{self.shot_id}/psd-saved",
            headers=self._headers(
                work_key=key, asset_role="source_psd", token=issued.json()["token"]
            ),
            json={},
        ))

    def _get_context(self) -> dict:
        resp = _quiet(lambda: self.client.get("/api/plugin/context", headers=self._headers()))
        self.assertEqual(resp.status_code, 200, resp.text)
        return resp.json()

    def _get_shot_from_context(self, shot_id: str) -> dict:
        ctx = self._get_context()
        shot = next((s for s in ctx["shots"] if s["shot_id"] == shot_id), None)
        self.assertIsNotNone(shot, f"Shot {shot_id} not found in context")
        return shot

    def _get_project_shot(self, shot_id: str) -> dict:
        resp = _quiet(lambda: self.client.get("/api/project"))
        self.assertEqual(resp.status_code, 200, resp.text)
        shot = next((s for s in resp.json()["shots"] if s["shot_id"] == shot_id), None)
        self.assertIsNotNone(shot, f"Shot {shot_id} not found in project payload")
        return shot


# ---------------------------------------------------------------------------
# 1. Shot payload — has_board_background / has_artwork_preview flags
# ---------------------------------------------------------------------------

class TestShotPayloadAssetFlags(_ProjectFixture):

    def test_fresh_shot_has_no_board_background(self):
        """A newly created shot has no board background plate on disk."""
        shot = self._get_project_shot(self.shot_id)
        self.assertFalse(shot.get("has_board_background"),
                         "Fresh shot must report has_board_background=False")

    def test_fresh_shot_has_no_artwork_preview(self):
        """A newly created shot has no real artwork preview."""
        shot = self._get_project_shot(self.shot_id)
        self.assertFalse(shot.get("has_artwork_preview"),
                         "Fresh shot must report has_artwork_preview=False")

    def test_has_board_background_true_when_background_file_exists(self):
        """has_board_background is True once the _background.png plate is on disk."""
        self._write_background_plate()

        shot = self._get_project_shot(self.shot_id)
        self.assertTrue(shot.get("has_board_background"),
                        "has_board_background must be True when _background.png exists")

    def test_background_plate_alone_does_not_set_has_artwork_preview(self):
        """has_artwork_preview must be False when only the background plate exists (no drawing)."""
        self._write_background_plate()
        # Ensure no preview PNG exists (fresh shot)
        (self.shot_images_dir / f"{self.shot_id}_preview.png").unlink(missing_ok=True)

        shot = self._get_project_shot(self.shot_id)
        self.assertFalse(shot.get("has_artwork_preview"),
                         "Background plate alone must NOT set has_artwork_preview")

    def test_real_artwork_preview_sets_has_artwork_preview(self):
        """has_artwork_preview is True when a non-solid-color _preview.png exists."""
        # MINI_PNG is a transparent 1x1 — not solid. Commit via the backend so
        # metadata is set correctly.
        resp = self._commit_preview(MINI_PNG)
        self.assertEqual(resp.status_code, 200, resp.text)

        shot = self._get_project_shot(self.shot_id)
        self.assertTrue(shot.get("has_artwork_preview"),
                        "has_artwork_preview must be True when real artwork preview exists")

    def test_project_shots_include_has_board_background_key(self):
        """Every shot in the project payload must have a has_board_background key."""
        resp = _quiet(lambda: self.client.get("/api/project"))
        for shot in resp.json().get("shots", []):
            self.assertIn("has_board_background", shot,
                          f"Shot {shot.get('shot_id')} missing has_board_background key")

    def test_project_shots_include_has_artwork_preview_key(self):
        """Every shot in the project payload must have a has_artwork_preview key."""
        resp = _quiet(lambda: self.client.get("/api/project"))
        for shot in resp.json().get("shots", []):
            self.assertIn("has_artwork_preview", shot,
                          f"Shot {shot.get('shot_id')} missing has_artwork_preview key")


# ---------------------------------------------------------------------------
# 2. Plugin context — _background.png never in preview metadata fields
# ---------------------------------------------------------------------------

class TestContextNeverExposesBackgroundAsPreview(_ProjectFixture):

    def test_image_path_never_contains_background_in_fresh_shot(self):
        """image_path must not reference _background.png in a fresh shot."""
        shot = self._get_shot_from_context(self.shot_id)
        self.assertNotIn("_background", shot.get("image_path", ""),
                         "image_path must not reference _background.png")

    def test_preview_image_path_never_contains_background_in_fresh_shot(self):
        """preview_image_path must not reference _background.png in a fresh shot."""
        shot = self._get_shot_from_context(self.shot_id)
        self.assertNotIn("_background", shot.get("preview_image_path", ""),
                         "preview_image_path must not reference _background.png")

    def test_image_path_clean_after_background_plate_written(self):
        """Writing a background plate file must not pollute image_path with _background."""
        self._write_background_plate()

        shot = self._get_shot_from_context(self.shot_id)
        self.assertNotIn("_background", shot.get("image_path", ""),
                         "image_path must not become _background.png after background plate write")

    def test_preview_image_path_clean_after_background_plate_written(self):
        """Writing a background plate must not pollute preview_image_path."""
        self._write_background_plate()

        shot = self._get_shot_from_context(self.shot_id)
        self.assertNotIn("_background", shot.get("preview_image_path", ""),
                         "preview_image_path must not reference _background.png")

    def test_work_item_background_path_is_separate_from_preview(self):
        """Work-item asset paths expose board_background as a dedicated role, not preview."""
        self._write_background_plate()
        ctx = self._get_context()
        item = next(
            (i for i in ctx.get("work_items", []) if i.get("key") == f"shot:{self.shot_id}"),
            None,
        )
        self.assertIsNotNone(item, "Shot must appear in context work items")
        paths = item["asset_paths"]
        self.assertIn("_background", paths["board_background"]["project_relative_path"],
                      "board_background role must reference the _background.png file")
        self.assertNotIn("_background", paths["preview"]["project_relative_path"],
                         "preview role must NOT reference _background.png")
        self.assertNotIn("_background", item.get("preview_image_path", ""))


# ---------------------------------------------------------------------------
# 3. Plugin focus contract
# ---------------------------------------------------------------------------

class TestPluginFocusShot(_ProjectFixture):

    def _add_shot(self) -> str:
        resp = _quiet(lambda: self.client.post("/api/shots", json={}))
        self.assertEqual(resp.status_code, 200)
        return resp.json()["shot"]["shot_id"]

    def _focus(self, shot_id: str):
        return _quiet(lambda: self.client.post(
            f"/api/plugin/shots/{shot_id}/focus", headers=self._headers()
        ))

    def test_focus_shot_updates_live_selected_shot_state(self):
        """POST /api/plugin/shots/<id>/focus must set live_selected_shot_id in app state.

        Note: context['selected_shot_id'] derives from the plugin heartbeat file,
        which in CI / dev environments can reflect a real connected plugin instance.
        We verify the authoritative backend state directly instead.
        """
        second_id = self._add_shot()
        resp = self._focus(second_id)
        self.assertEqual(resp.status_code, 200, resp.text)
        # The backend state (live_selected_shot_id) must reflect the focused shot.
        live_sel = str(getattr(self.app.state, "live_selected_shot_id", "") or "")
        self.assertEqual(live_sel, second_id,
                         "app.state.live_selected_shot_id must be the focused shot after focus call")

    def test_focus_shot_returns_full_context_shape(self):
        """focus endpoint must return a full context object with shots, canvas, bridge."""
        resp = self._focus(self.shot_id)
        self.assertEqual(resp.status_code, 200, resp.text)
        ctx = resp.json()
        self.assertIn("shots", ctx, "context must include shots list")
        self.assertIn("canvas", ctx, "context must include canvas info")
        self.assertIn("bridge", ctx, "context must include bridge info")
        self.assertIn("project_root", ctx, "context must include project_root")

    def test_focus_shot_does_not_mutate_image_path(self):
        """Focusing a shot must not change image_path / preview_image_path."""
        shot = self._get_shot_from_context(self.shot_id)
        original_image = shot.get("image_path", "")
        original_preview = shot.get("preview_image_path", "")

        self._focus(self.shot_id)

        shot_after = self._get_shot_from_context(self.shot_id)
        self.assertEqual(shot_after.get("image_path", ""), original_image,
                         "focus must not mutate image_path")
        self.assertEqual(shot_after.get("preview_image_path", ""), original_preview,
                         "focus must not mutate preview_image_path")

    def test_focus_shot_does_not_mutate_background_metadata(self):
        """Focusing a shot must not change has_board_background or background paths."""
        shot_before = self._get_project_shot(self.shot_id)
        bg_before = shot_before.get("has_board_background", False)

        self._focus(self.shot_id)

        shot_after = self._get_project_shot(self.shot_id)
        self.assertEqual(shot_after.get("has_board_background", False), bg_before,
                         "focus must not mutate has_board_background")

    def test_focus_unknown_shot_returns_error(self):
        """Focusing a non-existent shot_id must return an error, not 200."""
        resp = self._focus("ghost_shot_id")
        self.assertNotEqual(resp.status_code, 200,
                            "Focusing a non-existent shot must not return 200")


# ---------------------------------------------------------------------------
# 4. SB bg ownership — sync_psd_board_background is a documented no-op
# ---------------------------------------------------------------------------

class TestSyncPsdBoardBackgroundNoOp(unittest.TestCase):
    """Verify that the backend never modifies the in-PSD SB bg layer.

    The Photoshop plugin owns the in-PSD linked SB bg layer as a linked
    smart object pointing at <shot>_background.png.  The backend must not
    rasterize or overwrite it via psd_tools, because doing so would:
      1. Destroy the linked smart object and replace it with a flat layer.
      2. Corrupt the PSD (psd_tools round-trip bakes linked layers).
    sync_psd_board_background is therefore intentionally a no-op that
    returns False to signal that no PSD was modified.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _make_project_and_shot(self):
        project = make_project(self.root)
        shot = project_manager.add_shot(project)
        return project, shot

    def _psd_path(self, project, shot) -> Path:
        psd_path = project_manager.resolve_shot_asset(project, shot.shot_id, "source_psd")
        psd_path.parent.mkdir(parents=True, exist_ok=True)
        return psd_path

    def test_sync_psd_board_background_returns_false(self):
        """sync_psd_board_background must return False — it is a deliberate no-op.

        The plugin owns the in-PSD linked SB bg layer; the backend must not
        touch it.
        """
        project, shot = self._make_project_and_shot()
        psd_path = self._psd_path(project, shot)
        psd_path.write_bytes(b"8BPS" + b"\x00" * 64)

        result = project_manager.sync_psd_board_background(project, shot, psd_path)
        self.assertFalse(result, "sync_psd_board_background must return False (no-op)")

    def test_sync_psd_board_background_does_not_modify_psd(self):
        """sync_psd_board_background must not modify the PSD file on disk.

        The plugin owns the linked SB bg layer; any backend write would
        corrupt the linked smart object.
        """
        project, shot = self._make_project_and_shot()
        psd_path = self._psd_path(project, shot)
        original_bytes = b"8BPS" + b"\x00" * 64
        psd_path.write_bytes(original_bytes)
        original_mtime = psd_path.stat().st_mtime

        project_manager.sync_psd_board_background(project, shot, psd_path)

        self.assertEqual(psd_path.read_bytes(), original_bytes,
                         "sync_psd_board_background must not alter PSD file contents")
        self.assertEqual(psd_path.stat().st_mtime, original_mtime,
                         "sync_psd_board_background must not touch PSD mtime")

    def test_sync_psd_board_background_does_not_create_psd(self):
        """sync_psd_board_background must not create a PSD when none exists."""
        project, shot = self._make_project_and_shot()
        fake_path = self._psd_path(project, shot).with_name(f"{shot.shot_id}_never_created.psd")
        self.assertFalse(fake_path.exists(), "Test setup: PSD must not exist before call")

        project_manager.sync_psd_board_background(project, shot, fake_path)

        self.assertFalse(fake_path.exists(),
                         "sync_psd_board_background must not create a new PSD file")

    def test_sync_psd_board_background_does_not_mutate_shot_metadata(self):
        """sync_psd_board_background must not change any Shot metadata fields."""
        project, shot = self._make_project_and_shot()
        psd_path = self._psd_path(project, shot)
        psd_path.write_bytes(b"8BPS" + b"\x00" * 64)

        original_data = shot.to_dict()
        project_manager.sync_psd_board_background(project, shot, psd_path)
        after_data = shot.to_dict()

        self.assertEqual(original_data, after_data,
                         "sync_psd_board_background must not change any Shot metadata")


# ---------------------------------------------------------------------------
# 5. Source PSD / preview path separation
# ---------------------------------------------------------------------------

class TestSourcePsdPreviewSeparation(_ProjectFixture):

    def test_source_file_path_ends_with_psd_after_psd_saved(self):
        """source_file_path must always end with .psd after psd-saved."""
        resp = self._commit_psd()
        self.assertEqual(resp.status_code, 200, resp.text)
        src = resp.json()["shot"].get("source_file_path", "")
        self.assertTrue(src.endswith(".psd"), f"source_file_path must end with .psd, got: {src!r}")

    def test_image_path_never_becomes_psd_path(self):
        """image_path must never point to a .psd file after any plugin operation."""
        self.assertEqual(self._commit_psd().status_code, 200)
        self.assertEqual(self._commit_preview().status_code, 200)
        shot = self._get_shot_from_context(self.shot_id)
        image_path = shot.get("image_path", "")
        self.assertFalse(image_path.endswith(".psd"),
                         f"image_path must never be a .psd path, got: {image_path!r}")

    def test_preview_image_path_never_becomes_psd_path(self):
        """preview_image_path must never point to a .psd file after any plugin operation."""
        self.assertEqual(self._commit_psd().status_code, 200)
        self.assertEqual(self._commit_preview().status_code, 200)
        shot = self._get_shot_from_context(self.shot_id)
        preview_path = shot.get("preview_image_path", "")
        self.assertFalse(preview_path.endswith(".psd"),
                         f"preview_image_path must never be a .psd path, got: {preview_path!r}")

    def test_image_path_and_preview_image_path_never_contain_psd_extension(self):
        """image_path and preview_image_path must never be assigned .psd paths.

        After a PSD save and a preview export, image_path and preview_image_path
        end in .png (not .psd). The source PSD file is set on source_file_path only.
        """
        self.assertEqual(self._commit_psd().status_code, 200)
        resp = self._commit_preview()
        self.assertEqual(resp.status_code, 200, resp.text)
        shot = resp.json()["shot"]
        # The assigned preview paths must point to PNG artwork, never the PSD source.
        self.assertTrue(shot.get("image_path", "").endswith(".png"),
                        "image_path must be a .png path after export-preview")
        self.assertTrue(shot.get("preview_image_path", "").endswith(".png"),
                        "preview_image_path must be a .png path after export-preview")
        # The PSD IS correctly set on source_file_path.
        self.assertTrue(shot.get("source_file_path", "").endswith(".psd"),
                        "source_file_path must point to the .psd")


# ---------------------------------------------------------------------------
# 6. Plugin metadata ownership — shots.json canonical after plugin operations
# ---------------------------------------------------------------------------

class TestShotsJsonCanonicalAfterPluginOps(_ProjectFixture):

    def _metadata_root(self) -> Path:
        return self.project_root / ".storyboarder" / "data"

    def _shots_on_disk(self) -> list[dict]:
        from storyboard_tool.shot_store import load_shots_json, shots_json_path

        path = shots_json_path(self._metadata_root())
        self.assertTrue(path.is_file(), "shots.json must exist")
        shots = load_shots_json(path)
        self.assertIsNotNone(shots)
        return [shot.to_dict() for shot in shots]

    def test_shots_json_records_export_preview(self):
        """shots.json is the canonical store after a plugin export-preview call."""
        self.assertEqual(self._commit_preview().status_code, 200)

        shot = next(s for s in self._shots_on_disk() if s["shot_id"] == self.shot_id)
        self.assertEqual(shot["preview_image_path"], f"Images/Shots/{self.shot_id}_preview.png")

    def test_shots_json_records_psd_saved(self):
        """shots.json is the canonical store after a plugin psd-saved call."""
        self.assertEqual(self._commit_psd().status_code, 200)

        shot = next(s for s in self._shots_on_disk() if s["shot_id"] == self.shot_id)
        self.assertEqual(shot["source_file_path"], f"PSD/Shots/{self.shot_id}.psd")

    def test_project_json_has_no_inline_shots_after_plugin_operations(self):
        """project.json must never have an inline shots key after plugin ops."""
        self.assertEqual(self._commit_psd().status_code, 200)
        self.assertEqual(self._commit_preview().status_code, 200)

        manifest = json.loads((self._metadata_root() / "project.json").read_text(encoding="utf-8"))
        self.assertNotIn("shots", manifest,
                         "project.json must not contain an inline 'shots' key after plugin ops")


if __name__ == "__main__":
    unittest.main()
