from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
import uuid
import warnings
from pathlib import Path
from unittest import mock

with warnings.catch_warnings():
    warnings.filterwarnings("ignore", message="Using `httpx` with `starlette.testclient`")
    from fastapi.testclient import TestClient

from storyboard_tool import api as api_module


MINI_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000a49444154789c6300010000050001"
    "0d0a2db40000000049454e44ae426082"
)


def _quiet(fn):
    with contextlib.redirect_stderr(io.StringIO()):
        return fn()


def _is_uuid(value: str) -> bool:
    try:
        return str(uuid.UUID(value)) == value
    except ValueError:
        return False


class Scene2DTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.app = api_module.create_app(self.root)
        self.client = TestClient(self.app, raise_server_exceptions=False)
        created = _quiet(lambda: self.client.post("/api/project/new", json={"path": self._tmp.name}))
        self.assertEqual(created.status_code, 200)
        self.project_root = Path(created.json()["project_path"])

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _create_scene(self, title: str = "Layout") -> dict:
        response = _quiet(lambda: self.client.post("/api/project/scenes2d", json={"title": title, "description": "Blockout"}))
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["scene"]

    def test_create_scene2d_creates_index_folder_psd_and_meta_without_shots(self) -> None:
        scene = self._create_scene("Living room layout")

        self.assertTrue(_is_uuid(scene["id"]))
        self.assertTrue(_is_uuid(scene["primary_perspective_id"]))
        self.assertEqual(
            scene["source_file_path"],
            f"scenes2d/{scene['id']}/perspectives/{scene['primary_perspective_id']}/source.psd",
        )
        self.assertEqual(
            scene["preview_image_path"],
            f"scenes2d/{scene['id']}/perspectives/{scene['primary_perspective_id']}/preview.png",
        )
        self.assertTrue(scene["can_be_reference"])
        self.assertEqual(scene["perspectives"][0]["id"], scene["primary_perspective_id"])
        self.assertEqual(scene["perspectives"][0]["source_file_path"], scene["source_file_path"])

        scene_dir = self.project_root / "scenes2d" / scene["id"]
        self.assertTrue((self.project_root / "scenes2d" / "scenes2d.json").is_file())
        self.assertTrue(scene_dir.is_dir())
        self.assertTrue((scene_dir / "perspectives" / scene["primary_perspective_id"] / "source.psd").is_file())
        self.assertTrue((scene_dir / f"{scene['id']}_meta.json").is_file())

        shots_json = self.project_root / "shots.json"
        shots_data = json.loads(shots_json.read_text(encoding="utf-8")) if shots_json.is_file() else {"shots": []}
        self.assertEqual(shots_data.get("shots"), [])
        self.assertEqual(_quiet(lambda: self.client.get("/api/project")).json()["shots"], [])

    def test_scene_list_persists_after_reopening_project(self) -> None:
        created = self._create_scene("Map")

        app = api_module.create_app(self.root)
        client = TestClient(app, raise_server_exceptions=False)
        opened = _quiet(
            lambda: client.post("/api/project/open", json={"project_json_path": str(self.project_root / "project.json")})
        )
        self.assertEqual(opened.status_code, 200, opened.text)
        response = _quiet(lambda: client.get("/api/project/scenes2d"))
        self.assertEqual(response.status_code, 200, response.text)
        scenes = response.json()["scenes"]
        self.assertEqual(len(scenes), 1)
        self.assertEqual(scenes[0]["id"], created["id"])
        self.assertEqual(scenes[0]["title"], "Map")

    def test_update_scene_title_persists_after_reopening_project(self) -> None:
        scene = self._create_scene("Map")
        updated = _quiet(
            lambda: self.client.patch(
                f"/api/project/scenes2d/{scene['id']}",
                json={"title": "Maps"},
            )
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["scene"]["title"], "Maps")

        listed = _quiet(lambda: self.client.get("/api/project/scenes2d"))
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual(listed.json()["scenes"][0]["title"], "Maps")

        app = api_module.create_app(self.root)
        client = TestClient(app, raise_server_exceptions=False)
        opened = _quiet(
            lambda: client.post("/api/project/open", json={"project_json_path": str(self.project_root / "project.json")})
        )
        self.assertEqual(opened.status_code, 200, opened.text)
        reloaded = _quiet(lambda: client.get("/api/project/scenes2d"))
        self.assertEqual(reloaded.status_code, 200, reloaded.text)
        self.assertEqual(reloaded.json()["scenes"][0]["title"], "Maps")

    def test_update_perspective_title_persists_after_reopening_project(self) -> None:
        scene = self._create_scene("Map")
        perspective = scene["perspectives"][0]
        updated = _quiet(
            lambda: self.client.patch(
                f"/api/project/scenes2d/{scene['id']}/perspectives/{perspective['id']}",
                json={"title": "Plan view"},
            )
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["perspective"]["title"], "Plan view")

        listed = _quiet(lambda: self.client.get(f"/api/project/scenes2d/{scene['id']}/perspectives"))
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual(listed.json()["perspectives"][0]["title"], "Plan view")

        app = api_module.create_app(self.root)
        client = TestClient(app, raise_server_exceptions=False)
        opened = _quiet(
            lambda: client.post("/api/project/open", json={"project_json_path": str(self.project_root / "project.json")})
        )
        self.assertEqual(opened.status_code, 200, opened.text)
        reloaded = _quiet(lambda: client.get(f"/api/project/scenes2d/{scene['id']}/perspectives"))
        self.assertEqual(reloaded.status_code, 200, reloaded.text)
        self.assertEqual(reloaded.json()["perspectives"][0]["title"], "Plan view")

    def test_open_missing_source_recreates_psd_and_does_not_mutate_shots(self) -> None:
        scene = self._create_scene("Open source")
        source = self.project_root / scene["source_file_path"]
        source.unlink()

        before = _quiet(lambda: self.client.get("/api/project")).json()["shots"]
        with mock.patch("storyboard_tool.scene2d.project_manager.open_project_file", return_value=source) as opened:
            response = _quiet(lambda: self.client.post(f"/api/project/scenes2d/{scene['id']}/open"))

        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(source.is_file())
        opened.assert_called_once()
        self.assertEqual(opened.call_args.args[1], scene["source_file_path"])
        after = _quiet(lambda: self.client.get("/api/project")).json()["shots"]
        self.assertEqual(after, before)

    def test_open_existing_perspective_does_not_touch_updated_at_but_recreate_does(self) -> None:
        scene = self._create_scene("Open timestamps")
        perspective = scene["perspectives"][0]
        source = self.project_root / perspective["source_file_path"]
        before_shots = _quiet(lambda: self.client.get("/api/project")).json()["shots"]

        with mock.patch("storyboard_tool.scene2d.project_manager.open_project_file", return_value=source):
            opened = _quiet(
                lambda: self.client.post(
                    f"/api/project/scenes2d/{scene['id']}/perspectives/{perspective['id']}/open"
                )
            )
        self.assertEqual(opened.status_code, 200, opened.text)

        listed = _quiet(lambda: self.client.get("/api/project/scenes2d")).json()["scenes"][0]
        self.assertEqual(listed["updated_at"], scene["updated_at"])
        self.assertEqual(listed["perspectives"][0]["updated_at"], perspective["updated_at"])

        source.unlink()
        reopened = _quiet(
            lambda: self.client.post(
                f"/api/project/scenes2d/{scene['id']}/perspectives/{perspective['id']}/open"
            )
        )
        self.assertEqual(reopened.status_code, 400, reopened.text)
        self.assertIn("Source PSD not found", reopened.text)
        self.assertEqual(_quiet(lambda: self.client.get("/api/project")).json()["shots"], before_shots)

    def test_refresh_missing_preview_returns_clean_payload(self) -> None:
        scene = self._create_scene("Preview")
        response = _quiet(lambda: self.client.post(f"/api/project/scenes2d/{scene['id']}/refresh-preview"))

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertFalse(payload["preview_exists"])
        self.assertEqual(payload["message"], "No Scene 2D preview exists yet.")

        preview = _quiet(lambda: self.client.get(f"/api/project/scenes2d/{scene['id']}/preview"))
        self.assertEqual(preview.status_code, 404)

    def test_add_to_references_preserves_scene2d_link_and_normal_reference_upload(self) -> None:
        upload = _quiet(
            lambda: self.client.post(
                "/api/project/references",
                files={"file": ("normal.png", MINI_PNG, "image/png")},
            )
        )
        self.assertEqual(upload.status_code, 200, upload.text)
        normal_reference = upload.json()["reference"]

        scene = self._create_scene("Scene reference")
        preview = self.project_root / scene["preview_image_path"]
        preview.write_bytes(MINI_PNG)

        response = _quiet(lambda: self.client.post(f"/api/project/scenes2d/{scene['id']}/add-to-references"))
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        reference = payload["reference"]
        self.assertEqual(reference["type"], "scene2d")
        self.assertEqual(reference["source_scene2d_id"], scene["id"])
        self.assertEqual(reference["path"], scene["preview_image_path"])

        links = payload["project"]["settings"]["reference_links"]
        self.assertTrue(any(link["id"] == normal_reference["id"] and link["type"] == "image" for link in links))
        self.assertTrue(any(link["id"] == reference["id"] and link["type"] == "scene2d" for link in links))

        reopened = _quiet(lambda: self.client.get("/api/project"))
        self.assertEqual(reopened.status_code, 200, reopened.text)
        reopened_links = reopened.json()["settings"]["reference_links"]
        self.assertTrue(
            any(
                link["type"] == "scene2d" and link.get("source_scene2d_id") == scene["id"]
                for link in reopened_links
            )
        )

    def test_delete_scene_removes_scene2d_reference_links_only(self) -> None:
        scene = self._create_scene("Delete reference")
        preview = self.project_root / scene["preview_image_path"]
        preview.write_bytes(MINI_PNG)
        added = _quiet(lambda: self.client.post(f"/api/project/scenes2d/{scene['id']}/add-to-references"))
        self.assertEqual(added.status_code, 200, added.text)

        response = _quiet(lambda: self.client.delete(f"/api/project/scenes2d/{scene['id']}"))
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse((self.project_root / "scenes2d" / scene["id"]).exists())

        project = _quiet(lambda: self.client.get("/api/project")).json()
        self.assertFalse(
            any(
                link.get("type") == "scene2d" and link.get("source_scene2d_id") == scene["id"]
                for link in project["settings"]["reference_links"]
            )
        )
        self.assertEqual(project["shots"], [])

    def test_flat_scene2d_record_normalizes_to_default_perspective(self) -> None:
        scenes_root = self.project_root / "scenes2d"
        scene_root = scenes_root / "scene_001"
        scene_root.mkdir(parents=True)
        (scene_root / "scene_001.psd").write_bytes(b"legacy psd")
        legacy = {
            "scenes": [
                {
                    "id": "scene_001",
                    "title": "Legacy flat scene",
                    "description": "",
                    "source_file_path": "scenes2d/scene_001/scene_001.psd",
                    "preview_image_path": "scenes2d/scene_001/scene_001_preview.png",
                    "created_at": "2025-01-01T00:00:00Z",
                    "updated_at": "2025-01-01T00:00:00Z",
                    "can_be_reference": True,
                }
            ]
        }
        (scenes_root / "scenes2d.json").write_text(json.dumps(legacy), encoding="utf-8")

        response = _quiet(lambda: self.client.get("/api/project/scenes2d"))

        self.assertEqual(response.status_code, 200, response.text)
        scene = response.json()["scenes"][0]
        self.assertTrue(_is_uuid(scene["id"]))
        self.assertTrue(_is_uuid(scene["primary_perspective_id"]))
        self.assertEqual(len(scene["perspectives"]), 1)
        self.assertEqual(
            scene["perspectives"][0]["source_file_path"],
            f"scenes2d/{scene['id']}/perspectives/{scene['primary_perspective_id']}/source.psd",
        )
        self.assertEqual(scene["source_file_path"], scene["perspectives"][0]["source_file_path"])
        self.assertFalse((self.project_root / "scenes2d" / "scene_001").exists())

    def test_blank_perspective_open_refresh_primary_and_delete_behaviors(self) -> None:
        scene = self._create_scene("Perspective scene")

        created = _quiet(
            lambda: self.client.post(
                f"/api/project/scenes2d/{scene['id']}/perspectives",
                json={"title": "North view"},
            )
        )
        self.assertEqual(created.status_code, 200, created.text)
        perspective = created.json()["perspective"]
        self.assertTrue(_is_uuid(perspective["id"]))
        self.assertTrue((self.project_root / perspective["source_file_path"]).is_file())
        self.assertEqual(perspective["source_file_path"], f"scenes2d/{scene['id']}/perspectives/{perspective['id']}/source.psd")

        refresh = _quiet(
            lambda: self.client.post(
                f"/api/project/scenes2d/{scene['id']}/perspectives/{perspective['id']}/refresh-preview"
            )
        )
        self.assertEqual(refresh.status_code, 200, refresh.text)
        self.assertFalse(refresh.json()["preview_exists"])

        source = self.project_root / perspective["source_file_path"]
        source.unlink()
        before = _quiet(lambda: self.client.get("/api/project")).json()["shots"]
        opened_response = _quiet(
            lambda: self.client.post(
                f"/api/project/scenes2d/{scene['id']}/perspectives/{perspective['id']}/open"
            )
        )
        self.assertEqual(opened_response.status_code, 400, opened_response.text)
        self.assertIn("Source PSD not found", opened_response.text)
        self.assertEqual(_quiet(lambda: self.client.get("/api/project")).json()["shots"], before)

        primary = _quiet(
            lambda: self.client.post(
                f"/api/project/scenes2d/{scene['id']}/perspectives/{perspective['id']}/set-primary"
            )
        )
        self.assertEqual(primary.status_code, 200, primary.text)
        self.assertEqual(primary.json()["scene"]["source_file_path"], perspective["source_file_path"])

        deleted = _quiet(
            lambda: self.client.delete(
                f"/api/project/scenes2d/{scene['id']}/perspectives/{perspective['id']}"
            )
        )
        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertEqual(deleted.json()["scene"]["primary_perspective_id"], scene["primary_perspective_id"])

    def test_import_image_and_psd_perspectives_and_reference_source_ids(self) -> None:
        scene = self._create_scene("Import scene")
        image = _quiet(
            lambda: self.client.post(
                f"/api/project/scenes2d/{scene['id']}/perspectives/import",
                files={"file": ("south.png", MINI_PNG, "image/png")},
                data={"title": "South view"},
            )
        )
        self.assertEqual(image.status_code, 200, image.text)
        image_perspective = image.json()["perspective"]
        self.assertEqual(image_perspective["type"], "image")
        self.assertEqual(image_perspective["source_file_path"], image_perspective["preview_image_path"])
        self.assertTrue((self.project_root / image_perspective["preview_image_path"]).is_file())

        added = _quiet(
            lambda: self.client.post(
                f"/api/project/scenes2d/{scene['id']}/perspectives/{image_perspective['id']}/add-to-references"
            )
        )
        self.assertEqual(added.status_code, 200, added.text)
        reference = added.json()["reference"]
        self.assertEqual(reference["type"], "scene2d")
        self.assertEqual(reference["source_scene2d_id"], scene["id"])
        self.assertEqual(reference["source_scene2d_perspective_id"], image_perspective["id"])

        psd = _quiet(
            lambda: self.client.post(
                f"/api/project/scenes2d/{scene['id']}/perspectives/import",
                files={"file": ("paint.psd", b"psd data", "application/octet-stream")},
                data={"title": "Paint view"},
            )
        )
        self.assertEqual(psd.status_code, 200, psd.text)
        psd_perspective = psd.json()["perspective"]
        self.assertEqual(psd_perspective["type"], "psd")
        preview = _quiet(
            lambda: self.client.get(
                f"/api/project/scenes2d/{scene['id']}/perspectives/{psd_perspective['id']}/preview"
            )
        )
        self.assertEqual(preview.status_code, 404)
        refresh = _quiet(
            lambda: self.client.post(
                f"/api/project/scenes2d/{scene['id']}/perspectives/{psd_perspective['id']}/refresh-preview"
            )
        )
        self.assertEqual(refresh.status_code, 200, refresh.text)
        self.assertFalse(refresh.json()["preview_exists"])

    def test_move_perspective_to_another_scene_updates_paths_primary_and_references(self) -> None:
        source_scene = self._create_scene("Source scene")
        target_scene = self._create_scene("Target scene")
        created = _quiet(
            lambda: self.client.post(
                f"/api/project/scenes2d/{source_scene['id']}/perspectives",
                json={"title": "Move me"},
            )
        )
        self.assertEqual(created.status_code, 200, created.text)
        perspective = created.json()["perspective"]
        source_path = self.project_root / perspective["source_file_path"]
        self.assertTrue(source_path.is_file())
        (self.project_root / perspective["preview_image_path"]).write_bytes(MINI_PNG)

        added = _quiet(
            lambda: self.client.post(
                f"/api/project/scenes2d/{source_scene['id']}/perspectives/{perspective['id']}/add-to-references"
            )
        )
        self.assertEqual(added.status_code, 200, added.text)

        primary = _quiet(
            lambda: self.client.post(
                f"/api/project/scenes2d/{source_scene['id']}/perspectives/{perspective['id']}/set-primary"
            )
        )
        self.assertEqual(primary.status_code, 200, primary.text)

        moved = _quiet(
            lambda: self.client.post(
                f"/api/project/scenes2d/{source_scene['id']}/perspectives/{perspective['id']}/move-to-scene",
                json={"target_scene_id": target_scene["id"]},
            )
        )
        self.assertEqual(moved.status_code, 200, moved.text)
        body = moved.json()
        moved_perspective = body["perspective"]
        self.assertEqual(
            moved_perspective["source_file_path"],
            f"scenes2d/{target_scene['id']}/perspectives/{perspective['id']}/source.psd",
        )
        self.assertFalse(source_path.exists())
        self.assertTrue((self.project_root / moved_perspective["source_file_path"]).is_file())
        self.assertEqual(body["source_scene"]["primary_perspective_id"], source_scene["primary_perspective_id"])
        self.assertIn(perspective["id"], [item["id"] for item in body["target_scene"]["perspectives"]])

        project = _quiet(lambda: self.client.get("/api/project")).json()
        moved_reference = next(
            link
            for link in project["settings"]["reference_links"]
            if link.get("source_scene2d_perspective_id") == perspective["id"]
        )
        self.assertEqual(moved_reference["source_scene2d_id"], target_scene["id"])
        self.assertEqual(
            moved_reference["path"],
            f"scenes2d/{target_scene['id']}/perspectives/{perspective['id']}/preview.png",
        )

    def test_move_perspective_rolls_back_files_metadata_and_references_on_commit_failure(self) -> None:
        source_scene = self._create_scene("Rollback source")
        target_scene = self._create_scene("Rollback target")
        created = _quiet(
            lambda: self.client.post(
                f"/api/project/scenes2d/{source_scene['id']}/perspectives",
                json={"title": "Rollback me"},
            )
        )
        self.assertEqual(created.status_code, 200, created.text)
        perspective = created.json()["perspective"]
        source_path = self.project_root / perspective["source_file_path"]
        preview_path = self.project_root / perspective["preview_image_path"]
        preview_path.write_bytes(MINI_PNG)
        added = _quiet(
            lambda: self.client.post(
                f"/api/project/scenes2d/{source_scene['id']}/perspectives/{perspective['id']}/add-to-references"
            )
        )
        self.assertEqual(added.status_code, 200, added.text)
        before_scenes = _quiet(lambda: self.client.get("/api/project/scenes2d")).json()["scenes"]
        before_settings = json.loads((self.project_root / "settings.json").read_text(encoding="utf-8"))

        with mock.patch("storyboard_tool.scene2d._save_scenes", side_effect=RuntimeError("forced save failure")):
            moved = _quiet(
                lambda: self.client.post(
                    f"/api/project/scenes2d/{source_scene['id']}/perspectives/{perspective['id']}/move-to-scene",
                    json={"target_scene_id": target_scene["id"]},
                )
            )

        self.assertEqual(moved.status_code, 500, moved.text)
        self.assertTrue(source_path.is_file())
        self.assertTrue(preview_path.is_file())
        self.assertFalse(
            (self.project_root / "scenes2d" / target_scene["id"] / "perspectives" / perspective["id"]).exists()
        )
        after_scenes = _quiet(lambda: self.client.get("/api/project/scenes2d")).json()["scenes"]
        after_settings = json.loads((self.project_root / "settings.json").read_text(encoding="utf-8"))
        self.assertEqual(before_scenes, after_scenes)
        self.assertEqual(before_settings, after_settings)

    def test_reorder_perspectives_persists_without_changing_primary(self) -> None:
        scene = self._create_scene("Ordered scene")
        second = _quiet(
            lambda: self.client.post(
                f"/api/project/scenes2d/{scene['id']}/perspectives",
                json={"title": "Second"},
            )
        )
        self.assertEqual(second.status_code, 200, second.text)
        third = _quiet(
            lambda: self.client.post(
                f"/api/project/scenes2d/{scene['id']}/perspectives",
                json={"title": "Third"},
            )
        )
        self.assertEqual(third.status_code, 200, third.text)
        listed = _quiet(lambda: self.client.get(f"/api/project/scenes2d/{scene['id']}/perspectives")).json()
        original_ids = [item["id"] for item in listed["perspectives"]]
        reordered_ids = [original_ids[2], original_ids[0], original_ids[1]]

        response = _quiet(
            lambda: self.client.post(
                f"/api/project/scenes2d/{scene['id']}/perspectives/reorder",
                json={"perspective_ids": reordered_ids},
            )
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual([item["id"] for item in body["scene"]["perspectives"]], reordered_ids)
        self.assertEqual(body["scene"]["primary_perspective_id"], scene["primary_perspective_id"])

        reloaded = _quiet(lambda: self.client.get(f"/api/project/scenes2d/{scene['id']}/perspectives")).json()
        self.assertEqual([item["id"] for item in reloaded["perspectives"]], reordered_ids)


class Scene2DDuplicatePerspectiveTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.app = api_module.create_app(self.root)
        self.client = TestClient(self.app, raise_server_exceptions=False)
        created = _quiet(lambda: self.client.post("/api/project/new", json={"path": self._tmp.name}))
        self.assertEqual(created.status_code, 200)
        self.project_root = Path(created.json()["project_path"])

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _create_scene(self, title: str = "Layout") -> dict:
        response = _quiet(lambda: self.client.post("/api/project/scenes2d", json={"title": title}))
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["scene"]

    def _create_perspective(self, scene_id: str, title: str = "Main") -> dict:
        response = _quiet(
            lambda: self.client.post(
                f"/api/project/scenes2d/{scene_id}/perspectives",
                json={"title": title},
            )
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["perspective"]

    def _duplicate(self, scene_id: str, perspective_id: str) -> tuple[int, dict]:
        response = _quiet(
            lambda: self.client.post(
                f"/api/project/scenes2d/{scene_id}/perspectives/{perspective_id}/duplicate"
            )
        )
        return response.status_code, response.json()

    # ── PSD with preview ─────────────────────────────────────────────────────

    def test_duplicate_psd_with_preview_creates_independent_files(self) -> None:
        scene = self._create_scene()
        original_persp = scene["perspectives"][0]
        source_path = self.project_root / original_persp["source_file_path"]
        preview_path = self.project_root / original_persp["preview_image_path"]
        preview_path.write_bytes(MINI_PNG)
        original_source_bytes = source_path.read_bytes()

        status, body = self._duplicate(scene["id"], original_persp["id"])
        self.assertEqual(status, 200, body)
        dup = body["perspective"]

        self.assertNotEqual(dup["id"], original_persp["id"])
        self.assertTrue(_is_uuid(dup["id"]))
        new_source = self.project_root / dup["source_file_path"]
        new_preview = self.project_root / dup["preview_image_path"]
        self.assertTrue(new_source.is_file())
        self.assertTrue(new_preview.is_file())
        self.assertEqual(new_source.read_bytes(), original_source_bytes)
        self.assertEqual(new_preview.read_bytes(), MINI_PNG)

        # Source directory untouched
        self.assertTrue(source_path.is_file())
        self.assertEqual(source_path.read_bytes(), original_source_bytes)

        # Paths use new UUID folder
        self.assertIn(dup["id"], dup["source_file_path"])
        self.assertIn(dup["id"], dup["preview_image_path"])
        self.assertNotIn(original_persp["id"], dup["source_file_path"])

    # ── PSD without preview ──────────────────────────────────────────────────

    def test_duplicate_psd_without_preview_succeeds_and_no_fake_preview(self) -> None:
        scene = self._create_scene()
        original_persp = scene["perspectives"][0]
        # Don't write preview — it intentionally does not exist

        status, body = self._duplicate(scene["id"], original_persp["id"])
        self.assertEqual(status, 200, body)
        dup = body["perspective"]

        new_source = self.project_root / dup["source_file_path"]
        canonical_preview = (
            f"scenes2d/{scene['id']}/perspectives/{dup['id']}/preview.png"
        )
        self.assertTrue(new_source.is_file())
        self.assertFalse((self.project_root / canonical_preview).is_file())
        self.assertEqual(dup["preview_image_path"], canonical_preview)

    # ── Image perspective ────────────────────────────────────────────────────

    def test_duplicate_image_perspective_preserves_extension_and_preview_eq_source(self) -> None:
        scene = self._create_scene()
        # Import a JPG image perspective via multipart upload
        imported = _quiet(
            lambda: self.client.post(
                f"/api/project/scenes2d/{scene['id']}/perspectives/import",
                files={"file": ("cover.jpg", MINI_PNG, "image/jpeg")},
                data={"title": "Cover"},
            )
        )
        self.assertEqual(imported.status_code, 200, imported.text)
        img_persp = imported.json()["perspective"]
        self.assertEqual(img_persp["type"], "image")
        self.assertTrue(img_persp["source_file_path"].endswith(".jpg"))

        src_bytes = (self.project_root / img_persp["source_file_path"]).read_bytes()

        status, body = self._duplicate(scene["id"], img_persp["id"])
        self.assertEqual(status, 200, body)
        dup = body["perspective"]

        self.assertTrue(dup["source_file_path"].endswith(".jpg"))
        self.assertEqual(dup["source_file_path"], dup["preview_image_path"])
        new_file = self.project_root / dup["source_file_path"]
        self.assertTrue(new_file.is_file())
        self.assertEqual(new_file.read_bytes(), src_bytes)
        self.assertEqual(dup["type"], "image")

    # ── Metadata ─────────────────────────────────────────────────────────────

    def test_duplicate_title_receives_copy_suffix(self) -> None:
        scene = self._create_scene()
        original_persp = scene["perspectives"][0]
        _, body = self._duplicate(scene["id"], original_persp["id"])
        dup = body["perspective"]
        self.assertEqual(dup["title"], f"{original_persp['title']} Copy")

    def test_duplicate_title_collision_uses_incrementing_number(self) -> None:
        scene = self._create_scene()
        original_persp = scene["perspectives"][0]
        expected_base = f"{original_persp['title']} Copy"

        # First duplicate → "{title} Copy"
        _, b1 = self._duplicate(scene["id"], original_persp["id"])
        self.assertEqual(b1["perspective"]["title"], expected_base)

        # Second duplicate → "{title} Copy 2"
        _, b2 = self._duplicate(scene["id"], original_persp["id"])
        self.assertEqual(b2["perspective"]["title"], f"{expected_base} 2")

        # Third duplicate → "{title} Copy 3"
        _, b3 = self._duplicate(scene["id"], original_persp["id"])
        self.assertEqual(b3["perspective"]["title"], f"{expected_base} 3")

    def test_duplicate_copies_linked_scene3d_view_deeply(self) -> None:
        scene = self._create_scene()
        original_persp = scene["perspectives"][0]
        # Patch a linked_scene3d_view via update
        view = {"camera": {"x": 1, "y": 2, "z": 3}, "fov": 45}
        updated = _quiet(
            lambda: self.client.patch(
                f"/api/project/scenes2d/{scene['id']}/perspectives/{original_persp['id']}",
                json={"linked_scene3d_view": view},
            )
        )
        self.assertEqual(updated.status_code, 200, updated.text)

        _, body = self._duplicate(scene["id"], original_persp["id"])
        dup = body["perspective"]
        self.assertEqual(dup["linked_scene3d_view"], view)
        # Modify original view — should not affect duplicate
        view["camera"]["x"] = 99
        listed = _quiet(
            lambda: self.client.get(f"/api/project/scenes2d/{scene['id']}/perspectives")
        ).json()
        dup_fresh = next(p for p in listed["perspectives"] if p["id"] == dup["id"])
        self.assertEqual(dup_fresh["linked_scene3d_view"]["camera"]["x"], 1)

    def test_duplicate_timestamps_are_present_and_self_consistent(self) -> None:
        scene = self._create_scene()
        original_persp = scene["perspectives"][0]
        _, body = self._duplicate(scene["id"], original_persp["id"])
        dup = body["perspective"]
        # Fresh duplicate must have non-empty timestamps (not inherited empty strings)
        self.assertTrue(dup["created_at"], "created_at should be non-empty")
        self.assertTrue(dup["updated_at"], "updated_at should be non-empty")
        # For a brand-new duplicate, created_at and updated_at are set to the same instant
        self.assertEqual(dup["created_at"], dup["updated_at"])

    # ── References ──────────────────────────────────────────────────────────

    def test_duplicate_does_not_affect_existing_references(self) -> None:
        scene = self._create_scene()
        original_persp = scene["perspectives"][0]
        (self.project_root / original_persp["preview_image_path"]).write_bytes(MINI_PNG)
        added = _quiet(
            lambda: self.client.post(
                f"/api/project/scenes2d/{scene['id']}/perspectives/{original_persp['id']}/add-to-references"
            )
        )
        self.assertEqual(added.status_code, 200, added.text)
        before_settings = (self.project_root / "settings.json").read_bytes()

        _, body = self._duplicate(scene["id"], original_persp["id"])
        dup = body["perspective"]

        after_settings = (self.project_root / "settings.json").read_bytes()
        self.assertEqual(before_settings, after_settings)

        project = _quiet(lambda: self.client.get("/api/project")).json()
        links = project["settings"]["reference_links"]
        dup_links = [l for l in links if l.get("source_scene2d_perspective_id") == dup["id"]]
        self.assertEqual(dup_links, [])
        orig_links = [l for l in links if l.get("source_scene2d_perspective_id") == original_persp["id"]]
        self.assertEqual(len(orig_links), 1)

    # ── Ordering ─────────────────────────────────────────────────────────────

    def test_duplicate_inserts_immediately_after_source_in_middle(self) -> None:
        scene = self._create_scene()
        p_a = scene["perspectives"][0]
        p_b = self._create_perspective(scene["id"], "B")
        p_c = self._create_perspective(scene["id"], "C")

        _, body = self._duplicate(scene["id"], p_b["id"])
        dup = body["perspective"]

        ids = [p["id"] for p in body["scene"]["perspectives"]]
        self.assertEqual(ids, [p_a["id"], p_b["id"], dup["id"], p_c["id"]])

    def test_duplicate_inserts_after_first_perspective(self) -> None:
        scene = self._create_scene()
        p_a = scene["perspectives"][0]
        p_b = self._create_perspective(scene["id"], "B")

        _, body = self._duplicate(scene["id"], p_a["id"])
        dup = body["perspective"]

        ids = [p["id"] for p in body["scene"]["perspectives"]]
        self.assertEqual(ids, [p_a["id"], dup["id"], p_b["id"]])

    def test_duplicate_inserts_after_last_perspective(self) -> None:
        scene = self._create_scene()
        p_a = scene["perspectives"][0]
        p_b = self._create_perspective(scene["id"], "B")

        _, body = self._duplicate(scene["id"], p_b["id"])
        dup = body["perspective"]

        ids = [p["id"] for p in body["scene"]["perspectives"]]
        self.assertEqual(ids, [p_a["id"], p_b["id"], dup["id"]])

    def test_primary_perspective_unchanged_after_duplicate(self) -> None:
        scene = self._create_scene()
        original_primary = scene["primary_perspective_id"]
        original_persp = scene["perspectives"][0]

        _, body = self._duplicate(scene["id"], original_persp["id"])
        self.assertEqual(body["scene"]["primary_perspective_id"], original_primary)
        self.assertNotEqual(body["perspective"]["id"], original_primary)

    # ── Failure rollback ─────────────────────────────────────────────────────

    def test_rollback_on_save_failure_leaves_source_intact(self) -> None:
        scene = self._create_scene()
        original_persp = scene["perspectives"][0]
        (self.project_root / original_persp["preview_image_path"]).write_bytes(MINI_PNG)
        source_bytes_before = (self.project_root / original_persp["source_file_path"]).read_bytes()
        index_before = (self.project_root / "scenes2d" / "scenes2d.json").read_bytes()
        meta_before = (self.project_root / "scenes2d" / scene["id"] / f"{scene['id']}_meta.json").read_bytes()

        with mock.patch("storyboard_tool.scene2d._save_scenes", side_effect=RuntimeError("forced failure")):
            status, body = self._duplicate(scene["id"], original_persp["id"])

        self.assertEqual(status, 500, body)

        # Source untouched
        self.assertEqual(
            (self.project_root / original_persp["source_file_path"]).read_bytes(), source_bytes_before
        )

        # Metadata restored
        self.assertEqual(
            (self.project_root / "scenes2d" / "scenes2d.json").read_bytes(), index_before
        )
        self.assertEqual(
            (self.project_root / "scenes2d" / scene["id"] / f"{scene['id']}_meta.json").read_bytes(),
            meta_before,
        )

        # No leftover perspective dirs that aren't the original
        persp_dir = self.project_root / "scenes2d" / scene["id"] / "perspectives"
        known_ids = {original_persp["id"]}
        for child in persp_dir.iterdir():
            if child.name.startswith(".duplicate-"):
                self.fail(f"Orphan staging dir left after rollback: {child.name}")
            if _is_uuid(child.name):
                self.assertIn(child.name, known_ids, f"Unknown perspective dir left: {child.name}")

        # Scene still has exactly original perspectives
        listed = _quiet(lambda: self.client.get("/api/project/scenes2d")).json()["scenes"]
        scene_after = next(s for s in listed if s["id"] == scene["id"])
        self.assertEqual([p["id"] for p in scene_after["perspectives"]], [original_persp["id"]])

    def test_rollback_on_copy_failure_leaves_source_intact(self) -> None:
        scene = self._create_scene()
        original_persp = scene["perspectives"][0]
        source_bytes_before = (self.project_root / original_persp["source_file_path"]).read_bytes()

        with mock.patch("storyboard_tool.scene2d.shutil.copy2", side_effect=OSError("forced copy failure")):
            status, body = self._duplicate(scene["id"], original_persp["id"])

        self.assertEqual(status, 500, body)
        self.assertEqual(
            (self.project_root / original_persp["source_file_path"]).read_bytes(), source_bytes_before
        )
        listed = _quiet(lambda: self.client.get("/api/project/scenes2d")).json()["scenes"]
        scene_after = next(s for s in listed if s["id"] == scene["id"])
        self.assertEqual(len(scene_after["perspectives"]), 1)
        self.assertEqual(scene_after["perspectives"][0]["id"], original_persp["id"])

    # ── API contract ─────────────────────────────────────────────────────────

    def test_duplicate_returns_scene_perspective_scenes_keys(self) -> None:
        scene = self._create_scene()
        original_persp = scene["perspectives"][0]
        status, body = self._duplicate(scene["id"], original_persp["id"])
        self.assertEqual(status, 200, body)
        self.assertIn("scene", body)
        self.assertIn("perspective", body)
        self.assertIn("scenes", body)
        self.assertIsInstance(body["scenes"], list)

    def test_duplicate_returns_404_for_missing_scene(self) -> None:
        import uuid as _uuid
        fake_scene_id = str(_uuid.uuid4())
        fake_persp_id = str(_uuid.uuid4())
        status, body = self._duplicate(fake_scene_id, fake_persp_id)
        self.assertEqual(status, 404, body)

    def test_duplicate_returns_404_for_missing_perspective(self) -> None:
        scene = self._create_scene()
        import uuid as _uuid
        fake_persp_id = str(_uuid.uuid4())
        status, body = self._duplicate(scene["id"], fake_persp_id)
        self.assertEqual(status, 404, body)

    def test_duplicate_new_perspective_appears_in_scenes_payload(self) -> None:
        scene = self._create_scene()
        original_persp = scene["perspectives"][0]
        status, body = self._duplicate(scene["id"], original_persp["id"])
        self.assertEqual(status, 200, body)
        dup_id = body["perspective"]["id"]
        scene_in_payload = next(s for s in body["scenes"] if s["id"] == scene["id"])
        ids_in_payload = [p["id"] for p in scene_in_payload["perspectives"]]
        self.assertIn(dup_id, ids_in_payload)

    def test_duplicate_missing_source_file_returns_404(self) -> None:
        scene = self._create_scene()
        original_persp = scene["perspectives"][0]
        # Delete the source file
        (self.project_root / original_persp["source_file_path"]).unlink()
        status, body = self._duplicate(scene["id"], original_persp["id"])
        self.assertEqual(status, 404, body)

    # ── Failure-injection: preview copy fails ────────────────────────────────

    def test_preview_copy_failure_rolls_back_and_source_intact(self) -> None:
        """source copy succeeds, preview copy fails → HTTP 500, full rollback."""
        scene = self._create_scene()
        original_persp = scene["perspectives"][0]
        preview_path = self.project_root / original_persp["preview_image_path"]
        preview_path.write_bytes(MINI_PNG)
        source_bytes = (self.project_root / original_persp["source_file_path"]).read_bytes()
        index_before = (self.project_root / "scenes2d" / "scenes2d.json").read_bytes()
        meta_before = (self.project_root / "scenes2d" / scene["id"] / f"{scene['id']}_meta.json").read_bytes()

        copy2_calls = []
        real_copy2 = __import__("shutil").copy2

        def patched_copy2(src, dst, **kw):
            copy2_calls.append(str(dst))
            # Fail on preview copy (second call is preview.png)
            if len(copy2_calls) >= 2:
                raise OSError("forced preview copy failure")
            return real_copy2(src, dst, **kw)

        with mock.patch("storyboard_tool.scene2d.shutil.copy2", side_effect=patched_copy2):
            status, body = self._duplicate(scene["id"], original_persp["id"])

        self.assertEqual(status, 500, body)
        # Source untouched
        self.assertEqual(
            (self.project_root / original_persp["source_file_path"]).read_bytes(), source_bytes
        )
        # Index and meta restored
        self.assertEqual(
            (self.project_root / "scenes2d" / "scenes2d.json").read_bytes(), index_before
        )
        self.assertEqual(
            (self.project_root / "scenes2d" / scene["id"] / f"{scene['id']}_meta.json").read_bytes(),
            meta_before,
        )
        # No leftover duplicate perspective dirs
        persp_dir = self.project_root / "scenes2d" / scene["id"] / "perspectives"
        for child in persp_dir.iterdir():
            if child.name.startswith(".duplicate-"):
                self.fail(f"Staging dir left after rollback: {child.name}")
            if _is_uuid(child.name) and child.name != original_persp["id"]:
                self.fail(f"Unknown perspective dir after rollback: {child.name}")
        # Original perspective count unchanged
        listed = _quiet(lambda: self.client.get("/api/project/scenes2d")).json()["scenes"]
        scene_after = next(s for s in listed if s["id"] == scene["id"])
        self.assertEqual([p["id"] for p in scene_after["perspectives"]], [original_persp["id"]])

    # ── Failure-injection: verification fails after successful save ───────────

    def test_verify_failure_after_save_restores_metadata_and_removes_dup_dir(self) -> None:
        from storyboard_tool import scene2d as scene2d_module

        scene = self._create_scene()
        original_persp = scene["perspectives"][0]
        source_bytes = (self.project_root / original_persp["source_file_path"]).read_bytes()
        index_before = (self.project_root / "scenes2d" / "scenes2d.json").read_bytes()
        meta_before = (self.project_root / "scenes2d" / scene["id"] / f"{scene['id']}_meta.json").read_bytes()
        settings_before = (self.project_root / "settings.json").read_bytes()

        with mock.patch.object(
            scene2d_module,
            "_verify_perspective_duplicate",
            side_effect=ValueError("forced verify failure"),
        ):
            status, body = self._duplicate(scene["id"], original_persp["id"])

        self.assertEqual(status, 500, body)
        # Metadata restored byte-for-byte
        self.assertEqual(
            (self.project_root / "scenes2d" / "scenes2d.json").read_bytes(), index_before
        )
        self.assertEqual(
            (self.project_root / "scenes2d" / scene["id"] / f"{scene['id']}_meta.json").read_bytes(),
            meta_before,
        )
        # Duplicate directory removed
        persp_dir = self.project_root / "scenes2d" / scene["id"] / "perspectives"
        for child in persp_dir.iterdir():
            if _is_uuid(child.name) and child.name != original_persp["id"]:
                self.fail(f"Duplicate dir not removed after verify failure: {child.name}")
        # Source unchanged
        self.assertEqual(
            (self.project_root / original_persp["source_file_path"]).read_bytes(), source_bytes
        )
        # References unchanged
        self.assertEqual((self.project_root / "settings.json").read_bytes(), settings_before)

    # ── Failure-injection: partial save (meta write fails) ───────────────────

    def test_partial_save_meta_write_failure_rolls_back_both_files(self) -> None:
        from storyboard_tool import scene2d as scene2d_module

        scene = self._create_scene()
        original_persp = scene["perspectives"][0]
        index_before = (self.project_root / "scenes2d" / "scenes2d.json").read_bytes()
        meta_before = (self.project_root / "scenes2d" / scene["id"] / f"{scene['id']}_meta.json").read_bytes()

        scene_meta_path = str(
            self.project_root / "scenes2d" / scene["id"] / f"{scene['id']}_meta.json"
        )
        real_atomic = scene2d_module.project_manager._atomic_write_json
        write_calls: list[str] = []

        def patched_atomic_write(path, data):
            write_calls.append(str(path))
            # Allow scenes2d.json to be written; fail the scene meta write
            if str(path) == scene_meta_path and len(write_calls) >= 2:
                raise OSError("forced meta write failure")
            return real_atomic(path, data)

        with mock.patch.object(
            scene2d_module.project_manager,
            "_atomic_write_json",
            side_effect=patched_atomic_write,
        ):
            status, body = self._duplicate(scene["id"], original_persp["id"])

        self.assertEqual(status, 500, body)
        # Both metadata files restored
        self.assertEqual(
            (self.project_root / "scenes2d" / "scenes2d.json").read_bytes(), index_before
        )
        self.assertEqual(
            (self.project_root / "scenes2d" / scene["id"] / f"{scene['id']}_meta.json").read_bytes(),
            meta_before,
        )
        # Scene unchanged from caller's perspective
        listed = _quiet(lambda: self.client.get("/api/project/scenes2d")).json()["scenes"]
        scene_after = next(s for s in listed if s["id"] == scene["id"])
        self.assertEqual([p["id"] for p in scene_after["perspectives"]], [original_persp["id"]])

    # ── Failure-injection: index rollback fails ───────────────────────────────

    def test_index_rollback_failure_preserves_dup_dir_and_returns_500(self) -> None:
        from storyboard_tool import scene2d as scene2d_module

        scene = self._create_scene()
        original_persp = scene["perspectives"][0]
        new_dirs_seen: list[str] = []

        real_save = scene2d_module._save_scenes
        save_call_count = [0]

        def patched_save(project, scenes):
            save_call_count[0] += 1
            return real_save(project, scenes)

        def patched_restore(path, data):
            # Fail restoration of scenes2d.json specifically
            if "scenes2d.json" in str(path):
                raise OSError("forced index restore failure")
            real_restore = scene2d_module._restore_bytes.__wrapped__ if hasattr(scene2d_module._restore_bytes, "__wrapped__") else None
            # Use original restore for meta
            import tempfile as _tf
            import os as _os
            if data is None:
                if path.exists():
                    path.unlink()
                return
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = _tf.mkstemp(dir=str(path.parent), prefix=str(path.name) + ".", suffix=".tmp")
            try:
                with _os.fdopen(fd, "wb") as f:
                    f.write(data)
                _os.replace(tmp, path)
            except BaseException:
                try:
                    _os.unlink(tmp)
                except OSError:
                    pass
                raise

        # Track new_dir creation via the staging rename approach
        real_rename = scene2d_module.Path.rename if hasattr(scene2d_module.Path, "rename") else None

        with mock.patch("storyboard_tool.scene2d._save_scenes", side_effect=patched_save):
            with mock.patch("storyboard_tool.scene2d._verify_perspective_duplicate",
                            side_effect=ValueError("forced verify failure")):
                with mock.patch("storyboard_tool.scene2d._restore_bytes", side_effect=patched_restore):
                    status, body = self._duplicate(scene["id"], original_persp["id"])

        self.assertEqual(status, 500, body)
        # The error body should mention rollback failure or be a 500
        # Duplicate dir must be PRESERVED (not deleted) because index restore failed
        persp_dir = self.project_root / "scenes2d" / scene["id"] / "perspectives"
        new_uuid_dirs = [
            c for c in persp_dir.iterdir()
            if _is_uuid(c.name) and c.name != original_persp["id"]
        ]
        self.assertGreater(len(new_uuid_dirs), 0, "Expected duplicate dir to be preserved after rollback failure")

    # ── Failure-injection: scene meta rollback fails ──────────────────────────

    def test_meta_rollback_failure_preserves_dup_dir_and_returns_500(self) -> None:
        from storyboard_tool import scene2d as scene2d_module

        scene = self._create_scene()
        original_persp = scene["perspectives"][0]
        source_bytes = (self.project_root / original_persp["source_file_path"]).read_bytes()
        scene_meta_path = str(
            self.project_root / "scenes2d" / scene["id"] / f"{scene['id']}_meta.json"
        )

        def patched_restore(path, data):
            if str(path) == scene_meta_path:
                raise OSError("forced meta restore failure")
            import tempfile as _tf
            import os as _os
            if data is None:
                if path.exists():
                    path.unlink()
                return
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = _tf.mkstemp(dir=str(path.parent), prefix=str(path.name) + ".", suffix=".tmp")
            try:
                with _os.fdopen(fd, "wb") as f:
                    f.write(data)
                _os.replace(tmp, path)
            except BaseException:
                try:
                    _os.unlink(tmp)
                except OSError:
                    pass
                raise

        with mock.patch("storyboard_tool.scene2d._verify_perspective_duplicate",
                        side_effect=ValueError("forced verify failure")):
            with mock.patch("storyboard_tool.scene2d._restore_bytes", side_effect=patched_restore):
                status, body = self._duplicate(scene["id"], original_persp["id"])

        self.assertEqual(status, 500, body)
        # Source must still be intact
        self.assertEqual(
            (self.project_root / original_persp["source_file_path"]).read_bytes(), source_bytes
        )
        # Duplicate dir preserved because metadata verification failed
        persp_dir = self.project_root / "scenes2d" / scene["id"] / "perspectives"
        new_uuid_dirs = [
            c for c in persp_dir.iterdir()
            if _is_uuid(c.name) and c.name != original_persp["id"]
        ]
        self.assertGreater(len(new_uuid_dirs), 0, "Expected dup dir preserved after meta restore failure")

    # ── Failure-injection: malformed scene meta fails verifier ────────────────

    def test_malformed_scene_meta_fails_verification_and_rolls_back(self) -> None:
        from storyboard_tool import scene2d as scene2d_module

        scene = self._create_scene()
        original_persp = scene["perspectives"][0]
        index_before = (self.project_root / "scenes2d" / "scenes2d.json").read_bytes()
        meta_before = (self.project_root / "scenes2d" / scene["id"] / f"{scene['id']}_meta.json").read_bytes()

        real_save = scene2d_module._save_scenes

        def save_then_corrupt(project, scenes):
            result = real_save(project, scenes)
            # Corrupt the scene meta immediately after saving
            meta_file = (
                self.project_root / "scenes2d" / scene["id"] / f"{scene['id']}_meta.json"
            )
            meta_file.write_bytes(b"not valid json{{")
            return result

        with mock.patch("storyboard_tool.scene2d._save_scenes", side_effect=save_then_corrupt):
            status, body = self._duplicate(scene["id"], original_persp["id"])

        self.assertEqual(status, 500, body)
        # Meta restored to original bytes
        self.assertEqual(
            (self.project_root / "scenes2d" / scene["id"] / f"{scene['id']}_meta.json").read_bytes(),
            meta_before,
        )
        # Index also restored
        self.assertEqual(
            (self.project_root / "scenes2d" / "scenes2d.json").read_bytes(), index_before
        )
        # Duplicate dir removed after verified rollback
        persp_dir = self.project_root / "scenes2d" / scene["id"] / "perspectives"
        for child in persp_dir.iterdir():
            if _is_uuid(child.name) and child.name != original_persp["id"]:
                self.fail(f"Duplicate dir should be removed after verified rollback: {child.name}")

    # ── Failure-injection: perspective order mismatch fails verifier ──────────

    def test_order_mismatch_in_scene_meta_fails_verification(self) -> None:
        """Verifier must reject Perspective order differences (not sorted-ID comparison)."""
        from storyboard_tool import scene2d as scene2d_module

        scene = self._create_scene()
        # Add a second perspective so we have 2 to reorder
        second = self._create_perspective(scene["id"], "Second")
        original_persp = scene["perspectives"][0]
        index_before = (self.project_root / "scenes2d" / "scenes2d.json").read_bytes()
        meta_before = (self.project_root / "scenes2d" / scene["id"] / f"{scene['id']}_meta.json").read_bytes()

        real_save = scene2d_module._save_scenes

        def save_then_swap_meta_order(project, scenes_arg):
            result = real_save(project, scenes_arg)
            meta_file = self.project_root / "scenes2d" / scene["id"] / f"{scene['id']}_meta.json"
            import json as _json
            meta = _json.loads(meta_file.read_text(encoding="utf-8"))
            # Swap perspective order in meta only (not in scenes2d.json)
            if isinstance(meta.get("perspectives"), list) and len(meta["perspectives"]) >= 2:
                meta["perspectives"] = list(reversed(meta["perspectives"]))
                meta_file.write_text(_json.dumps(meta), encoding="utf-8")
            return result

        with mock.patch("storyboard_tool.scene2d._save_scenes", side_effect=save_then_swap_meta_order):
            status, body = self._duplicate(scene["id"], original_persp["id"])

        self.assertEqual(status, 500, body)
        # Meta restored
        self.assertEqual(
            (self.project_root / "scenes2d" / scene["id"] / f"{scene['id']}_meta.json").read_bytes(),
            meta_before,
        )
        # Duplicate dir removed after verified rollback
        persp_dir = self.project_root / "scenes2d" / scene["id"] / "perspectives"
        known = {original_persp["id"], second["id"]}
        for child in persp_dir.iterdir():
            if _is_uuid(child.name) and child.name not in known:
                self.fail(f"Duplicate dir should be removed: {child.name}")

    # ── Failure-injection: path mismatch in scene meta fails verifier ─────────

    def test_path_mismatch_in_scene_meta_fails_verification(self) -> None:
        """Verifier must reject differing source_file_path in scene meta."""
        from storyboard_tool import scene2d as scene2d_module

        scene = self._create_scene()
        original_persp = scene["perspectives"][0]
        index_before = (self.project_root / "scenes2d" / "scenes2d.json").read_bytes()
        meta_before = (self.project_root / "scenes2d" / scene["id"] / f"{scene['id']}_meta.json").read_bytes()

        real_save = scene2d_module._save_scenes

        def save_then_corrupt_path(project, scenes_arg):
            result = real_save(project, scenes_arg)
            meta_file = self.project_root / "scenes2d" / scene["id"] / f"{scene['id']}_meta.json"
            import json as _json
            meta = _json.loads(meta_file.read_text(encoding="utf-8"))
            # Corrupt source_file_path of the last perspective (the duplicate)
            perspectives = meta.get("perspectives") or []
            if perspectives:
                perspectives[-1]["source_file_path"] = "scenes2d/wrong/path/source.psd"
                meta_file.write_text(_json.dumps(meta), encoding="utf-8")
            return result

        with mock.patch("storyboard_tool.scene2d._save_scenes", side_effect=save_then_corrupt_path):
            status, body = self._duplicate(scene["id"], original_persp["id"])

        self.assertEqual(status, 500, body)
        # Both files restored
        self.assertEqual(
            (self.project_root / "scenes2d" / "scenes2d.json").read_bytes(), index_before
        )
        self.assertEqual(
            (self.project_root / "scenes2d" / scene["id"] / f"{scene['id']}_meta.json").read_bytes(),
            meta_before,
        )

    # ── P2: source preview disappears during duplication ──────────────────────

    def test_source_preview_disappears_during_dup_fails_verification(self) -> None:
        """Verifier must raise if source preview existed before but is gone after save."""
        from storyboard_tool import scene2d as scene2d_module

        scene = self._create_scene()
        original_persp = scene["perspectives"][0]
        preview_path = self.project_root / original_persp["preview_image_path"]
        preview_path.write_bytes(MINI_PNG)
        index_before = (self.project_root / "scenes2d" / "scenes2d.json").read_bytes()
        meta_before = (self.project_root / "scenes2d" / scene["id"] / f"{scene['id']}_meta.json").read_bytes()

        real_save = scene2d_module._save_scenes

        def save_then_delete_preview(project, scenes_arg):
            result = real_save(project, scenes_arg)
            preview_path.unlink(missing_ok=True)
            return result

        with mock.patch("storyboard_tool.scene2d._save_scenes", side_effect=save_then_delete_preview):
            status, body = self._duplicate(scene["id"], original_persp["id"])

        self.assertEqual(status, 500, body)
        # Metadata restored
        self.assertEqual(
            (self.project_root / "scenes2d" / "scenes2d.json").read_bytes(), index_before
        )
        self.assertEqual(
            (self.project_root / "scenes2d" / scene["id"] / f"{scene['id']}_meta.json").read_bytes(),
            meta_before,
        )
        # Duplicate dir removed after verified rollback
        persp_dir = self.project_root / "scenes2d" / scene["id"] / "perspectives"
        for child in persp_dir.iterdir():
            if _is_uuid(child.name) and child.name != original_persp["id"]:
                self.fail(f"Duplicate dir should be removed after verified rollback: {child.name}")

    # ── P2: OSError during rollback verification ──────────────────────────────

    def test_oserror_in_bytes_match_sets_metadata_verified_false(self) -> None:
        """If reading the restored file raises OSError, metadata_verified must be False."""
        from storyboard_tool import scene2d as scene2d_module

        scene = self._create_scene()
        original_persp = scene["perspectives"][0]
        real_bytes_match = scene2d_module._bytes_match_original
        calls = [0]

        def patched_bytes_match(path, original):
            calls[0] += 1
            if calls[0] >= 1:
                raise OSError("forced read failure during verify")
            return real_bytes_match(path, original)

        with mock.patch("storyboard_tool.scene2d._verify_perspective_duplicate",
                        side_effect=ValueError("forced verify failure")):
            with mock.patch("storyboard_tool.scene2d._bytes_match_original",
                            side_effect=patched_bytes_match):
                status, body = self._duplicate(scene["id"], original_persp["id"])

        # OSError from _bytes_match_original must NOT escape — should still return 500
        self.assertEqual(status, 500, body)
        # metadata_verified=False → duplicate dir must be preserved (not deleted)
        persp_dir = self.project_root / "scenes2d" / scene["id"] / "perspectives"
        new_uuid_dirs = [
            c for c in persp_dir.iterdir()
            if _is_uuid(c.name) and c.name != original_persp["id"]
        ]
        self.assertGreater(len(new_uuid_dirs), 0, "Expected dup dir preserved when metadata_verified=False")

    # ── P2: cleanup failure after verified rollback ────────────────────────────

    def test_cleanup_failure_after_verified_rollback_reports_orphan_dir(self) -> None:
        """If shutil.rmtree(new_dir) fails after verified rollback, error must mention cleanup."""
        from storyboard_tool import scene2d as scene2d_module

        scene = self._create_scene()
        original_persp = scene["perspectives"][0]
        real_rmtree = __import__("shutil").rmtree
        rmtree_calls: list[str] = []

        def patched_rmtree(path, *args, **kwargs):
            rmtree_calls.append(str(path))
            # Fail the first rmtree call (new_dir removal)
            if len(rmtree_calls) == 1:
                raise OSError("forced rmtree failure")
            return real_rmtree(path, *args, **kwargs)

        with mock.patch("storyboard_tool.scene2d._verify_perspective_duplicate",
                        side_effect=ValueError("forced verify failure")):
            with mock.patch("storyboard_tool.scene2d.shutil.rmtree", side_effect=patched_rmtree):
                status, body = self._duplicate(scene["id"], original_persp["id"])

        self.assertEqual(status, 500, body)
        # metadata_verified=True but duplicate_files_removed=False → new dir is preserved
        persp_dir = self.project_root / "scenes2d" / scene["id"] / "perspectives"
        new_uuid_dirs = [
            c for c in persp_dir.iterdir()
            if _is_uuid(c.name) and c.name != original_persp["id"]
        ]
        self.assertGreater(len(new_uuid_dirs), 0, "Expected orphan dup dir to be preserved after cleanup failure")


if __name__ == "__main__":
    unittest.main()
