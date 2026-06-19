"""Plugin/backend integration regression tests.

Covers the boundary between the Photoshop UXP plugin and the backend service:

  Plugin context contract:
  - shot payloads include has_board_background and has_artwork_preview
  - has_artwork_preview is False when only a background plate or solid fill exists
  - has_artwork_preview is True only when real (non-solid) artwork PNG exists
  - image_path / preview_image_path never carry _background.png after any operation
  - context shot list does not leak _background.png into preview metadata fields

  Plugin focus contract:
  - focusing a shot updates selected_shot_id in the returned context
  - focusing a shot does NOT touch image/preview/background asset metadata

  SB bg ownership no-op:
  - sync_psd_board_background always returns False (backend is a no-op)
  - sync_psd_board_background does not create or modify PSD files on disk
  - this is intentional: Photoshop plugin owns the in-PSD linked SB bg layer

  Source PSD / preview path separation:
  - source_file_path is always .psd after export-preview
  - image_path / preview_image_path never become .psd paths
  - _background.png is separate from preview paths in _plugin_shot_paths

  Shots.json canonicality:
  - shots.json remains the canonical store after plugin-facing endpoint calls

Tests that already exist (not duplicated here):
  test_plugin_metadata_boundary.py:
    export_preview_rejects_background_path_as_preview
    background_not_written_into_preview_metadata_after_rejection
    export_preview_rejects_path_traversal_in_preview_path
    export_preview_rejects_path_traversal_in_source_path
    export_preview_rejects_non_psd_source_path
    psd_saved_rejects_non_psd_source_path
    preview_relink_in_linked_mode_goes_through_backend
    source_file_path_is_psd_only_after_valid_export
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
import tempfile
import unittest
import warnings
from pathlib import Path

with warnings.catch_warnings():
    warnings.filterwarnings("ignore", message="Using `httpx` with `starlette.testclient`")
    from fastapi.testclient import TestClient

from storyboard_tool import api as api_module
from storyboard_tool import project_manager
from storyboard_tool.image_utils import board_background_filename

# Minimal valid 1x1 transparent PNG for use as a test file.
MINI_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000a49444154789c6300010000050001"
    "0d0a2db40000000049454e44ae426082"
)


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
        self.shot_dir = self.project_root / "shots" / self.shot_id

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _open_project_with_shot(self) -> tuple[Path, str]:
        created = _quiet(lambda: self.client.post("/api/project/new", json={"path": self._tmp.name}))
        self.assertEqual(created.status_code, 200)
        project_root = Path(created.json()["project_path"])
        added = _quiet(lambda: self.client.post("/api/shots", json={}))
        self.assertEqual(added.status_code, 200)
        return project_root, added.json()["shot"]["shot_id"]

    def _get_context(self) -> dict:
        resp = _quiet(lambda: self.client.get("/api/plugin/context"))
        self.assertEqual(resp.status_code, 200)
        return resp.json()

    def _get_shot_from_context(self, shot_id: str) -> dict:
        ctx = self._get_context()
        shot = next((s for s in ctx["shots"] if s["shot_id"] == shot_id), None)
        self.assertIsNotNone(shot, f"Shot {shot_id} not found in context")
        return shot


# ---------------------------------------------------------------------------
# 1. Plugin context — has_board_background / has_artwork_preview flags
# ---------------------------------------------------------------------------

class TestPluginContextAssetFlags(_ProjectFixture):

    def test_fresh_shot_has_no_board_background(self):
        """A newly created shot has no board background plate on disk."""
        shot = self._get_shot_from_context(self.shot_id)
        self.assertFalse(shot.get("has_board_background"),
                         "Fresh shot must report has_board_background=False")

    def test_fresh_shot_has_no_artwork_preview(self):
        """A newly created shot has no real artwork preview."""
        shot = self._get_shot_from_context(self.shot_id)
        self.assertFalse(shot.get("has_artwork_preview"),
                         "Fresh shot must report has_artwork_preview=False")

    def test_has_board_background_true_when_background_file_exists(self):
        """has_board_background is True once the _background.png plate is on disk."""
        bg = self.shot_dir / board_background_filename(self.shot_id)
        bg.parent.mkdir(parents=True, exist_ok=True)
        bg.write_bytes(MINI_PNG)

        shot = self._get_shot_from_context(self.shot_id)
        self.assertTrue(shot.get("has_board_background"),
                        "has_board_background must be True when _background.png exists")

    def test_background_plate_alone_does_not_set_has_artwork_preview(self):
        """has_artwork_preview must be False when only the background plate exists (no drawing)."""
        bg = self.shot_dir / board_background_filename(self.shot_id)
        bg.parent.mkdir(parents=True, exist_ok=True)
        bg.write_bytes(MINI_PNG)
        # Ensure no preview PNG exists (fresh shot)
        preview = self.shot_dir / f"{self.shot_id}_preview.png"
        preview.unlink(missing_ok=True)

        shot = self._get_shot_from_context(self.shot_id)
        self.assertFalse(shot.get("has_artwork_preview"),
                         "Background plate alone must NOT set has_artwork_preview")

    def test_real_artwork_preview_sets_has_artwork_preview(self):
        """has_artwork_preview is True when a non-solid-color _preview.png exists."""
        # Write a transparent (non-solid) PNG as the artwork preview.
        preview = self.shot_dir / f"{self.shot_id}_preview.png"
        preview.parent.mkdir(parents=True, exist_ok=True)
        preview.write_bytes(MINI_PNG)  # MINI_PNG is a transparent 1x1 — not solid
        # Relink preview via backend so metadata is set correctly.
        preview_rel = f"shots/{self.shot_id}/{self.shot_id}_preview.png"
        _quiet(lambda: self.client.post(
            f"/api/plugin/shots/{self.shot_id}/export-preview",
            json={"preview_image_path": preview_rel},
        ))

        shot = self._get_shot_from_context(self.shot_id)
        self.assertTrue(shot.get("has_artwork_preview"),
                        "has_artwork_preview must be True when real artwork preview exists")

    def test_context_shots_include_has_board_background_key(self):
        """Every shot in the context must have a has_board_background key."""
        ctx = self._get_context()
        for shot in ctx.get("shots", []):
            self.assertIn("has_board_background", shot,
                          f"Shot {shot.get('shot_id')} missing has_board_background key")

    def test_context_shots_include_has_artwork_preview_key(self):
        """Every shot in the context must have a has_artwork_preview key."""
        ctx = self._get_context()
        for shot in ctx.get("shots", []):
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
        bg = self.shot_dir / board_background_filename(self.shot_id)
        bg.parent.mkdir(parents=True, exist_ok=True)
        bg.write_bytes(MINI_PNG)

        shot = self._get_shot_from_context(self.shot_id)
        self.assertNotIn("_background", shot.get("image_path", ""),
                         "image_path must not become _background.png after background plate write")

    def test_preview_image_path_clean_after_background_plate_written(self):
        """Writing a background plate must not pollute preview_image_path."""
        bg = self.shot_dir / board_background_filename(self.shot_id)
        bg.parent.mkdir(parents=True, exist_ok=True)
        bg.write_bytes(MINI_PNG)

        shot = self._get_shot_from_context(self.shot_id)
        self.assertNotIn("_background", shot.get("preview_image_path", ""),
                         "preview_image_path must not reference _background.png")

    def test_plugin_shot_paths_background_key_is_separate_from_preview(self):
        """_plugin_shot_paths must expose board_background as a dedicated field, not preview.

        Each shot payload in the context includes a per-shot 'paths' dict from
        _plugin_shot_health. We use that to avoid dependency on which shot is
        currently heartbeat-selected (which can reflect a live plugin session).
        """
        bg = self.shot_dir / board_background_filename(self.shot_id)
        bg.parent.mkdir(parents=True, exist_ok=True)
        bg.write_bytes(MINI_PNG)
        ctx = self._get_context()
        shot = next((s for s in ctx.get("shots", []) if s["shot_id"] == self.shot_id), None)
        self.assertIsNotNone(shot, "Shot must appear in context")
        paths = shot.get("paths", {})
        board_background = paths.get("board_background", "")
        preview = paths.get("preview", "")
        self.assertIn("_background", board_background,
                      "per-shot paths.board_background must reference the _background.png file")
        self.assertNotIn("_background", preview,
                         "per-shot paths.preview must NOT reference _background.png")


# ---------------------------------------------------------------------------
# 3. Plugin focus contract
# ---------------------------------------------------------------------------

class TestPluginFocusShot(_ProjectFixture):

    def _add_shot(self) -> str:
        resp = _quiet(lambda: self.client.post("/api/shots", json={}))
        self.assertEqual(resp.status_code, 200)
        return resp.json()["shot"]["shot_id"]

    def test_focus_shot_updates_live_selected_shot_state(self):
        """POST /api/plugin/shots/<id>/focus must set live_selected_shot_id in app state.

        Note: context['selected_shot_id'] derives from the plugin heartbeat file,
        which in CI / dev environments can reflect a real connected plugin instance.
        We verify the authoritative backend state directly instead.
        """
        second_id = self._add_shot()
        resp = _quiet(lambda: self.client.post(f"/api/plugin/shots/{second_id}/focus"))
        self.assertEqual(resp.status_code, 200)
        # The backend state (live_selected_shot_id) must reflect the focused shot.
        live_sel = str(getattr(self.app.state, "live_selected_shot_id", "") or "")
        self.assertEqual(live_sel, second_id,
                         "app.state.live_selected_shot_id must be the focused shot after focus call")

    def test_focus_shot_returns_full_context_shape(self):
        """focus endpoint must return a full context object with shots, canvas, bridge."""
        resp = _quiet(lambda: self.client.post(f"/api/plugin/shots/{self.shot_id}/focus"))
        self.assertEqual(resp.status_code, 200)
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

        _quiet(lambda: self.client.post(f"/api/plugin/shots/{self.shot_id}/focus"))

        shot_after = self._get_shot_from_context(self.shot_id)
        self.assertEqual(shot_after.get("image_path", ""), original_image,
                         "focus must not mutate image_path")
        self.assertEqual(shot_after.get("preview_image_path", ""), original_preview,
                         "focus must not mutate preview_image_path")

    def test_focus_shot_does_not_mutate_background_metadata(self):
        """Focusing a shot must not change has_board_background or background paths."""
        shot_before = self._get_shot_from_context(self.shot_id)
        bg_before = shot_before.get("has_board_background", False)

        _quiet(lambda: self.client.post(f"/api/plugin/shots/{self.shot_id}/focus"))

        shot_after = self._get_shot_from_context(self.shot_id)
        self.assertEqual(shot_after.get("has_board_background", False), bg_before,
                         "focus must not mutate has_board_background")

    def test_focus_unknown_shot_returns_error(self):
        """Focusing a non-existent shot_id must return an error, not 200."""
        resp = _quiet(lambda: self.client.post("/api/plugin/shots/ghost_shot_id/focus"))
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
        project = project_manager.create_project(self.root)
        shot = project_manager.add_shot(project)
        return project, shot

    def test_sync_psd_board_background_returns_false(self):
        """sync_psd_board_background must return False — it is a deliberate no-op.

        The plugin owns the in-PSD linked SB bg layer; the backend must not
        touch it.
        """
        project, shot = self._make_project_and_shot()
        shot_dir = project_manager.get_shot_dir(project, shot)
        psd_path = shot_dir / f"{shot.shot_id}.psd"
        psd_path.write_bytes(b"8BPS" + b"\x00" * 64)

        result = project_manager.sync_psd_board_background(project, shot, psd_path)
        self.assertFalse(result, "sync_psd_board_background must return False (no-op)")

    def test_sync_psd_board_background_does_not_modify_psd(self):
        """sync_psd_board_background must not modify the PSD file on disk.

        The plugin owns the linked SB bg layer; any backend write would
        corrupt the linked smart object.
        """
        project, shot = self._make_project_and_shot()
        shot_dir = project_manager.get_shot_dir(project, shot)
        psd_path = shot_dir / f"{shot.shot_id}.psd"
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
        shot_dir = project_manager.get_shot_dir(project, shot)
        fake_path = shot_dir / f"{shot.shot_id}_never_created.psd"
        self.assertFalse(fake_path.exists(), "Test setup: PSD must not exist before call")

        project_manager.sync_psd_board_background(project, shot, fake_path)

        self.assertFalse(fake_path.exists(),
                         "sync_psd_board_background must not create a new PSD file")

    def test_sync_psd_board_background_does_not_mutate_shot_metadata(self):
        """sync_psd_board_background must not change any Shot metadata fields."""
        project, shot = self._make_project_and_shot()
        shot_dir = project_manager.get_shot_dir(project, shot)
        psd_path = shot_dir / f"{shot.shot_id}.psd"
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

    def test_source_file_path_ends_with_psd_after_export_preview(self):
        """source_file_path must always end with .psd after export-preview."""
        preview_rel = f"shots/{self.shot_id}/{self.shot_id}_preview.png"
        source_rel = f"shots/{self.shot_id}/{self.shot_id}.psd"
        self.shot_dir.mkdir(parents=True, exist_ok=True)
        (self.shot_dir / f"{self.shot_id}_preview.png").write_bytes(MINI_PNG)
        (self.shot_dir / f"{self.shot_id}.psd").write_bytes(b"8BPS" + b"\x00" * 32)

        resp = _quiet(lambda: self.client.post(
            f"/api/plugin/shots/{self.shot_id}/export-preview",
            json={"preview_image_path": preview_rel, "source_file_path": source_rel},
        ))
        self.assertEqual(resp.status_code, 200)
        shot = resp.json()["shot"]
        src = shot.get("source_file_path", "")
        self.assertTrue(src.endswith(".psd"), f"source_file_path must end with .psd, got: {src!r}")

    def test_image_path_never_becomes_psd_path(self):
        """image_path must never point to a .psd file after any plugin operation."""
        preview_rel = f"shots/{self.shot_id}/{self.shot_id}_preview.png"
        source_rel = f"shots/{self.shot_id}/{self.shot_id}.psd"
        self.shot_dir.mkdir(parents=True, exist_ok=True)
        (self.shot_dir / f"{self.shot_id}_preview.png").write_bytes(MINI_PNG)
        (self.shot_dir / f"{self.shot_id}.psd").write_bytes(b"8BPS" + b"\x00" * 32)

        _quiet(lambda: self.client.post(
            f"/api/plugin/shots/{self.shot_id}/export-preview",
            json={"preview_image_path": preview_rel, "source_file_path": source_rel},
        ))
        shot = self._get_shot_from_context(self.shot_id)
        image_path = shot.get("image_path", "")
        self.assertFalse(image_path.endswith(".psd"),
                         f"image_path must never be a .psd path, got: {image_path!r}")

    def test_preview_image_path_never_becomes_psd_path(self):
        """preview_image_path must never point to a .psd file after any plugin operation."""
        preview_rel = f"shots/{self.shot_id}/{self.shot_id}_preview.png"
        source_rel = f"shots/{self.shot_id}/{self.shot_id}.psd"
        self.shot_dir.mkdir(parents=True, exist_ok=True)
        (self.shot_dir / f"{self.shot_id}_preview.png").write_bytes(MINI_PNG)
        (self.shot_dir / f"{self.shot_id}.psd").write_bytes(b"8BPS" + b"\x00" * 32)

        _quiet(lambda: self.client.post(
            f"/api/plugin/shots/{self.shot_id}/export-preview",
            json={"preview_image_path": preview_rel, "source_file_path": source_rel},
        ))
        shot = self._get_shot_from_context(self.shot_id)
        preview_path = shot.get("preview_image_path", "")
        self.assertFalse(preview_path.endswith(".psd"),
                         f"preview_image_path must never be a .psd path, got: {preview_path!r}")

    def test_image_path_and_preview_image_path_never_contain_psd_extension(self):
        """image_path and preview_image_path must never be assigned .psd paths.

        The backend validates and assigns preview metadata from what the plugin
        sends.  We verify that after any valid export-preview call, the resulting
        image_path and preview_image_path end in .png (not .psd), regardless of
        what source_file_path was set to.  The source PSD file is set on
        source_file_path only.
        """
        preview_rel = f"shots/{self.shot_id}/{self.shot_id}_preview.png"
        source_rel = f"shots/{self.shot_id}/{self.shot_id}.psd"
        self.shot_dir.mkdir(parents=True, exist_ok=True)
        (self.shot_dir / f"{self.shot_id}_preview.png").write_bytes(MINI_PNG)
        (self.shot_dir / f"{self.shot_id}.psd").write_bytes(b"8BPS" + b"\x00" * 32)

        resp = _quiet(lambda: self.client.post(
            f"/api/plugin/shots/{self.shot_id}/export-preview",
            json={"preview_image_path": preview_rel, "source_file_path": source_rel},
        ))
        self.assertEqual(resp.status_code, 200)
        shot = resp.json()["shot"]
        # The assigned preview paths must point to PNG artwork, never the PSD source.
        self.assertFalse(shot.get("image_path", "").endswith(".psd"),
                         "image_path must not be a .psd path after export-preview")
        self.assertFalse(shot.get("preview_image_path", "").endswith(".psd"),
                         "preview_image_path must not be a .psd path after export-preview")
        # The PSD IS correctly set on source_file_path.
        self.assertTrue(shot.get("source_file_path", "").endswith(".psd"),
                        "source_file_path must point to the .psd")


# ---------------------------------------------------------------------------
# 6. Plugin metadata ownership — shots.json canonical after plugin operations
# ---------------------------------------------------------------------------

class TestShotsJsonCanonicalAfterPluginOps(_ProjectFixture):

    def test_shots_json_exists_after_export_preview(self):
        """shots.json must be present (canonical) after a plugin export-preview call."""
        from storyboard_tool.shot_store import shots_json_path

        preview_rel = f"shots/{self.shot_id}/{self.shot_id}_preview.png"
        self.shot_dir.mkdir(parents=True, exist_ok=True)
        (self.shot_dir / f"{self.shot_id}_preview.png").write_bytes(MINI_PNG)

        _quiet(lambda: self.client.post(
            f"/api/plugin/shots/{self.shot_id}/export-preview",
            json={"preview_image_path": preview_rel},
        ))
        _quiet(lambda: self.client.post("/api/project/save"))

        self.assertTrue(
            shots_json_path(self.project_root).is_file(),
            "shots.json must exist after plugin export-preview + save",
        )

    def test_shots_json_exists_after_psd_saved(self):
        """shots.json must be present after a plugin psd-saved call."""
        from storyboard_tool.shot_store import shots_json_path

        source_rel = f"shots/{self.shot_id}/{self.shot_id}.psd"
        self.shot_dir.mkdir(parents=True, exist_ok=True)
        (self.shot_dir / f"{self.shot_id}.psd").write_bytes(b"8BPS" + b"\x00" * 32)

        _quiet(lambda: self.client.post(
            f"/api/plugin/shots/{self.shot_id}/psd-saved",
            json={"source_file_path": source_rel},
        ))
        _quiet(lambda: self.client.post("/api/project/save"))

        self.assertTrue(
            shots_json_path(self.project_root).is_file(),
            "shots.json must exist after plugin psd-saved + save",
        )

    def test_plugin_context_does_not_require_shots_csv_to_be_accurate(self):
        """Plugin context reads from in-memory state, not from shots.csv on disk.

        This verifies the plugin does not need to write shots.csv to affect
        the backend's view of the project — shots.json is the canonical store.
        """
        from storyboard_tool.shot_store import shots_csv_path
        import json as _json

        # Corrupt the CSV to verify it does not affect the in-memory state.
        csv_path = shots_csv_path(self.project_root)
        if csv_path.is_file():
            csv_path.write_text("shot_id\nFAKE_CSV_GHOST_SHOT\n", encoding="utf-8")

        ctx = self._get_context()
        shot_ids = {s["shot_id"] for s in ctx.get("shots", [])}
        self.assertIn(self.shot_id, shot_ids,
                      "In-memory project must retain the real shot despite corrupt CSV")
        self.assertNotIn("FAKE_CSV_GHOST_SHOT", shot_ids,
                         "Ghost shot from CSV must not appear in plugin context")

    def test_project_json_has_no_inline_shots_after_plugin_operations(self):
        """project.json must never have an inline shots key after plugin operations."""
        import json as _json

        source_rel = f"shots/{self.shot_id}/{self.shot_id}.psd"
        self.shot_dir.mkdir(parents=True, exist_ok=True)
        (self.shot_dir / f"{self.shot_id}.psd").write_bytes(b"8BPS" + b"\x00" * 32)

        _quiet(lambda: self.client.post(
            f"/api/plugin/shots/{self.shot_id}/psd-saved",
            json={"source_file_path": source_rel},
        ))
        _quiet(lambda: self.client.post("/api/project/save"))

        manifest = _json.loads((self.project_root / "project.json").read_text(encoding="utf-8"))
        self.assertNotIn("shots", manifest,
                         "project.json must not contain an inline 'shots' key after plugin ops")


if __name__ == "__main__":
    unittest.main()
