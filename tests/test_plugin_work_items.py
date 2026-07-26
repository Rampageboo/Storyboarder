"""Backend tests for shot work-item schema (CODEX_TASK Part 16).

Verifies that PluginBridgeService.work_items() returns shot entries with:
  shot_title, index, count, previous_key, next_key
Covers: first shot, middle shot, last shot, empty title, non-empty title.
"""
from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
import warnings
from pathlib import Path
from unittest import mock

with warnings.catch_warnings():
    warnings.filterwarnings("ignore", message="Using `httpx` with `starlette.testclient`")
    from fastapi.testclient import TestClient

from storyboard_tool import api as api_module
from storyboard_tool import live_bridge


def _quiet(fn):
    with contextlib.redirect_stderr(io.StringIO()):
        return fn()


class ShotWorkItemsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
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

    def _new_project(self) -> Path:
        r = _quiet(lambda: self.client.post("/api/project/new", json={"path": self._tmp.name}))
        self.assertEqual(r.status_code, 200)
        return Path(r.json()["project_path"])

    def _add_shot(self, title: str = "") -> str:
        r = _quiet(lambda: self.client.post("/api/shots", json={}))
        self.assertEqual(r.status_code, 200, r.text)
        shot_id = r.json()["shot"]["shot_id"]
        if title:
            r2 = _quiet(lambda: self.client.patch(f"/api/shots/{shot_id}", json={"title": title}))
            self.assertEqual(r2.status_code, 200, r2.text)
        return shot_id

    def _work_items(self) -> list[dict]:
        r = self.client.get("/api/plugin/context")
        self.assertEqual(r.status_code, 200, r.text)
        return r.json().get("work_items", [])

    def _shot_items(self) -> list[dict]:
        return [item for item in self._work_items() if item.get("kind") == "shot"]

    # ── required fields present ───────────────────────────────────────────────

    def test_shot_item_has_shot_title_field(self):
        self._new_project()
        self._add_shot("Opening")
        items = self._shot_items()
        self.assertEqual(len(items), 1)
        self.assertIn("shot_title", items[0])

    def test_shot_item_has_index_field(self):
        self._new_project()
        self._add_shot()
        items = self._shot_items()
        self.assertIn("index", items[0])

    def test_shot_item_has_count_field(self):
        self._new_project()
        self._add_shot()
        items = self._shot_items()
        self.assertIn("count", items[0])

    def test_shot_item_has_previous_key_field(self):
        self._new_project()
        self._add_shot()
        items = self._shot_items()
        self.assertIn("previous_key", items[0])

    def test_shot_item_has_next_key_field(self):
        self._new_project()
        self._add_shot()
        items = self._shot_items()
        self.assertIn("next_key", items[0])

    # ── title values ──────────────────────────────────────────────────────────

    def test_shot_title_non_empty(self):
        self._new_project()
        self._add_shot("Close up")
        items = self._shot_items()
        self.assertEqual(items[0]["shot_title"], "Close up")

    def test_shot_title_empty_when_no_title(self):
        self._new_project()
        self._add_shot("")
        items = self._shot_items()
        self.assertEqual(items[0]["shot_title"], "")

    # ── index / count ─────────────────────────────────────────────────────────

    def test_index_is_one_based(self):
        self._new_project()
        self._add_shot()
        items = self._shot_items()
        self.assertEqual(items[0]["index"], 1)

    def test_count_equals_total_shots(self):
        self._new_project()
        self._add_shot()
        self._add_shot()
        self._add_shot()
        items = self._shot_items()
        for item in items:
            self.assertEqual(item["count"], 3)

    def test_index_order_matches_shot_order(self):
        self._new_project()
        self._add_shot("A")
        self._add_shot("B")
        self._add_shot("C")
        items = self._shot_items()
        indices = [item["index"] for item in items]
        self.assertEqual(indices, [1, 2, 3])

    # ── previous_key / next_key ───────────────────────────────────────────────

    def test_first_shot_has_empty_previous_key(self):
        self._new_project()
        sid1 = self._add_shot("A")
        self._add_shot("B")
        items = self._shot_items()
        first = next(i for i in items if i["shot_id"] == sid1)
        self.assertEqual(first["previous_key"], "")

    def test_last_shot_has_empty_next_key(self):
        self._new_project()
        self._add_shot("A")
        sid2 = self._add_shot("B")
        items = self._shot_items()
        last = next(i for i in items if i["shot_id"] == sid2)
        self.assertEqual(last["next_key"], "")

    def test_middle_shot_previous_key_points_to_predecessor(self):
        self._new_project()
        sid1 = self._add_shot("A")
        sid2 = self._add_shot("B")
        self._add_shot("C")
        items = self._shot_items()
        mid = next(i for i in items if i["shot_id"] == sid2)
        self.assertEqual(mid["previous_key"], f"shot:{sid1}")

    def test_middle_shot_next_key_points_to_successor(self):
        self._new_project()
        self._add_shot("A")
        sid2 = self._add_shot("B")
        sid3 = self._add_shot("C")
        items = self._shot_items()
        mid = next(i for i in items if i["shot_id"] == sid2)
        self.assertEqual(mid["next_key"], f"shot:{sid3}")

    def test_adjacent_keys_use_shot_prefix(self):
        self._new_project()
        sid1 = self._add_shot()
        self._add_shot()
        items = self._shot_items()
        second = items[1]
        self.assertTrue(second["previous_key"].startswith("shot:"), second["previous_key"])
        self.assertIn(sid1, second["previous_key"])

    def test_single_shot_has_empty_previous_and_next_keys(self):
        self._new_project()
        self._add_shot("Solo")
        items = self._shot_items()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["previous_key"], "")
        self.assertEqual(items[0]["next_key"], "")

    # ── key format ────────────────────────────────────────────────────────────

    def test_auto_added_next_shot_inherits_current_scene(self):
        self._new_project()
        shot_id = self._add_shot("Scene anchor")
        updated = _quiet(
            lambda: self.client.patch(
                f"/api/shots/{shot_id}",
                json={"scene": "Kitchen", "scene_id": "scene_kitchen"},
            )
        )
        self.assertEqual(updated.status_code, 200, updated.text)

        response = _quiet(
            lambda: self.client.post(
                "/api/plugin/shots/next",
                json={"current_shot_id": shot_id, "auto_add": True},
            )
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["created"])
        self.assertEqual(response.json()["shot"]["scene"], "Kitchen")
        self.assertEqual(response.json()["shot"]["scene_id"], "scene_kitchen")

    def test_key_uses_shot_prefix(self):
        self._new_project()
        sid = self._add_shot()
        items = self._shot_items()
        self.assertEqual(items[0]["key"], f"shot:{sid}")


if __name__ == "__main__":
    unittest.main()
