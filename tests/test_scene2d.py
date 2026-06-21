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
        recreated_time = "2099-01-01T00:00:00Z"
        with (
            mock.patch("storyboard_tool.scene2d._now_iso", return_value=recreated_time),
            mock.patch("storyboard_tool.scene2d.project_manager.open_project_file", return_value=source),
        ):
            reopened = _quiet(
                lambda: self.client.post(
                    f"/api/project/scenes2d/{scene['id']}/perspectives/{perspective['id']}/open"
                )
            )
        self.assertEqual(reopened.status_code, 200, reopened.text)
        self.assertTrue(source.is_file())

        relisted = _quiet(lambda: self.client.get("/api/project/scenes2d")).json()["scenes"][0]
        self.assertEqual(relisted["updated_at"], recreated_time)
        self.assertEqual(relisted["perspectives"][0]["updated_at"], recreated_time)
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
        with mock.patch("storyboard_tool.scene2d.project_manager.open_project_file", return_value=source) as opened:
            opened_response = _quiet(
                lambda: self.client.post(
                    f"/api/project/scenes2d/{scene['id']}/perspectives/{perspective['id']}/open"
                )
            )
        self.assertEqual(opened_response.status_code, 200, opened_response.text)
        opened.assert_called_once()
        self.assertEqual(opened.call_args.args[1], perspective["source_file_path"])
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


if __name__ == "__main__":
    unittest.main()
