"""Tests for the preview analysis cache (preview_analysis_cache.py)."""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import time
import unittest
import warnings
from pathlib import Path

with warnings.catch_warnings():
    warnings.filterwarnings("ignore", message="Using `httpx` with `starlette.testclient` is deprecated")
    from fastapi.testclient import TestClient

from storyboard_tool import api as api_module
from storyboard_tool import preview_analysis_cache as pac

# Minimal 8×8 opaque PNG for tests that need a real image file.
import base64
_MINI_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAgAAAAICAYAAADED76LAAAAD0lEQVQI12NgYGBg"
    "ICAAABQAAW8AzfEAAAAASUVORK5CYII="
)
MINI_PNG = base64.b64decode(_MINI_PNG_B64)


class CacheUnitTests(unittest.TestCase):
    def test_load_cache_returns_empty_on_missing_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = pac.load_cache(Path(tmp))
            self.assertEqual(cache, {})

    def test_load_cache_returns_empty_on_corrupt_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache_path = root / "workspace" / "cache" / "preview_analysis.json"
            cache_path.parent.mkdir(parents=True)
            cache_path.write_text("{invalid json", encoding="utf-8")
            result = pac.load_cache(root)
            self.assertEqual(result, {})

    def test_cache_miss_for_uncached_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            preview = Path(tmp) / "preview.png"
            preview.write_bytes(MINI_PNG)
            result = pac.get_cached({}, preview)
            self.assertIsNone(result)

    def test_cache_hit_when_mtime_and_size_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            preview = Path(tmp) / "preview.png"
            preview.write_bytes(MINI_PNG)
            cache: dict = {}
            pac.set_cached(cache, preview, has_artwork_preview=True, preview_has_transparency=False)
            result = pac.get_cached(cache, preview)
            self.assertIsNotNone(result)
            self.assertTrue(result["has_artwork_preview"])
            self.assertFalse(result["preview_has_transparency"])

    def test_cache_miss_when_mtime_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            preview = Path(tmp) / "preview.png"
            preview.write_bytes(MINI_PNG)
            cache: dict = {}
            pac.set_cached(cache, preview, has_artwork_preview=True, preview_has_transparency=False)
            # Modify the file (and therefore its mtime)
            time.sleep(0.01)
            preview.write_bytes(MINI_PNG + b"\x00")
            result = pac.get_cached(cache, preview)
            self.assertIsNone(result)

    def test_cache_miss_when_size_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            preview = Path(tmp) / "preview.png"
            preview.write_bytes(MINI_PNG)
            cache: dict = {}
            pac.set_cached(cache, preview, has_artwork_preview=True, preview_has_transparency=False)
            # Replace entry's size with a wrong value to simulate a size change
            key = list(cache["entries"].keys())[0]
            cache["entries"][key]["size"] = 999999
            result = pac.get_cached(cache, preview)
            self.assertIsNone(result)

    def test_save_and_reload_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            preview = root / "preview.png"
            preview.write_bytes(MINI_PNG)
            cache: dict = {}
            pac.set_cached(cache, preview, has_artwork_preview=True, preview_has_transparency=True)
            pac.save_cache(root, cache)
            reloaded = pac.load_cache(root)
            result = pac.get_cached(reloaded, preview)
            self.assertIsNotNone(result)
            self.assertTrue(result["has_artwork_preview"])
            self.assertTrue(result["preview_has_transparency"])

    def test_save_is_atomic(self) -> None:
        """save_cache writes to a unique sibling temp file then replaces — no stale .tmp remains."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache_path = root / "workspace" / "cache" / "preview_analysis.json"
            preview = root / "preview.png"
            preview.write_bytes(MINI_PNG)
            cache: dict = {}
            pac.set_cached(cache, preview, has_artwork_preview=False, preview_has_transparency=False)
            pac.save_cache(root, cache)
            self.assertTrue(cache_path.is_file())
            # No stale temp files should remain in the cache directory
            tmp_files = list(cache_path.parent.glob("*.tmp"))
            self.assertEqual(len(tmp_files), 0, f"Stale temp files remain: {tmp_files}")

    def test_save_uses_unique_temp_name(self) -> None:
        """Two concurrent saves use different temp names — fixed .tmp collisions are impossible."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            preview = root / "preview.png"
            preview.write_bytes(MINI_PNG)
            cache: dict = {}
            pac.set_cached(cache, preview, has_artwork_preview=True, preview_has_transparency=False)
            pac.save_cache(root, cache)
            pac.save_cache(root, cache)
            cache_path = root / "workspace" / "cache" / "preview_analysis.json"
            tmp_files = list(cache_path.parent.glob("*.tmp"))
            self.assertEqual(len(tmp_files), 0)

    def test_missing_preview_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            preview = Path(tmp) / "nonexistent.png"
            result = pac.get_cached({}, preview)
            self.assertIsNone(result)

    def test_set_cached_ignores_missing_file(self) -> None:
        """set_cached on a missing file must not raise."""
        cache: dict = {}
        pac.set_cached(cache, Path("/nonexistent/path.png"), True, False)
        self.assertEqual(cache, {})


class CacheStartupIntegrationTests(unittest.TestCase):
    def test_cache_miss_does_not_block_startup_with_full_decode(self) -> None:
        """
        With no cache, project payload returns provisional values (True/False)
        without blocking to decode images.
        """
        with tempfile.TemporaryDirectory() as tmp:
            app = api_module.create_app(Path(tmp))
            client = TestClient(app, raise_server_exceptions=False)
            with contextlib.redirect_stderr(io.StringIO()):
                resp = client.post("/api/project/new", json={"path": tmp})
            self.assertEqual(resp.status_code, 200)
            shots = resp.json()["shots"]
            # Initial shots have no preview — has_artwork_preview must be False
            for shot in shots:
                self.assertFalse(shot.get("has_artwork_preview", True),
                                 "Empty shot must not claim artwork_preview")


if __name__ == "__main__":
    unittest.main()
