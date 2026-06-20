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


MINI_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000a49444154789c6300010000050001"
    "0d0a2db40000000049454e44ae426082"
)


def _quiet(fn):
    with contextlib.redirect_stderr(io.StringIO()):
        return fn()


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

        self.assertEqual(scene["id"], "scene_001")
        self.assertEqual(scene["source_file_path"], "scenes2d/scene_001/scene_001.psd")
        self.assertEqual(scene["preview_image_path"], "scenes2d/scene_001/scene_001_preview.png")
        self.assertTrue(scene["can_be_reference"])

        scene_dir = self.project_root / "scenes2d" / "scene_001"
        self.assertTrue((self.project_root / "scenes2d" / "scenes2d.json").is_file())
        self.assertTrue(scene_dir.is_dir())
        self.assertTrue((scene_dir / "scene_001.psd").is_file())
        self.assertTrue((scene_dir / "scene_001_meta.json").is_file())

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


if __name__ == "__main__":
    unittest.main()
