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


class Scene2DMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.app = api_module.create_app(self.root)
        self.client = TestClient(self.app, raise_server_exceptions=False)
        created = _quiet(lambda: self.client.post("/api/project/new", json={"path": self._tmp.name}))
        self.assertEqual(created.status_code, 200, created.text)
        self.project_root = Path(created.json()["project_path"])

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write_legacy_scene(self, *, include_source: bool = True, image: bool = False) -> None:
        scenes_root = self.project_root / "scenes2d"
        scene_root = scenes_root / "scene_001"
        scene_root.mkdir(parents=True, exist_ok=True)
        source_rel = "scenes2d/scene_001/perspectives/persp_001/source.png" if image else "scenes2d/scene_001/scene_001.psd"
        preview_rel = source_rel if image else "scenes2d/scene_001/scene_001_preview.png"
        if include_source:
            source = self.project_root / source_rel
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_bytes(MINI_PNG if image else b"legacy psd")
        if not image:
            (scene_root / "scene_001_preview.png").write_bytes(MINI_PNG)
        legacy = {
            "scenes": [
                {
                    "id": "scene_001",
                    "title": "Legacy scene",
                    "description": "Old layout",
                    "linked_scene3d_id": "scene3d_002",
                    "primary_perspective_id": "persp_001",
                    "source_file_path": "scenes2d/scene_001/scene_001.psd",
                    "preview_image_path": "scenes2d/scene_001/scene_001_preview.png",
                    "created_at": "2025-01-01T00:00:00Z",
                    "updated_at": "2025-01-01T00:00:00Z",
                    "can_be_reference": True,
                    "perspectives": [
                        {
                            "id": "persp_001",
                            "title": "Legacy perspective",
                            "type": "image" if image else "psd",
                            "source_file_path": source_rel,
                            "preview_image_path": preview_rel,
                            "linked_scene3d_id": "scene3d_002",
                            "linked_scene3d_view": None,
                            "created_at": "2025-01-01T00:00:00Z",
                            "updated_at": "2025-01-01T00:00:00Z",
                        }
                    ],
                }
            ]
        }
        (scenes_root / "scenes2d.json").write_text(json.dumps(legacy), encoding="utf-8")
        settings = json.loads((self.project_root / "settings.json").read_text(encoding="utf-8"))
        settings["reference_links"] = [
            {
                "id": "ref_scene_001_persp_001",
                "title": "Legacy ref",
                "type": "scene2d",
                "path": preview_rel,
                "source_scene2d_id": "scene_001",
                "source_scene2d_perspective_id": "persp_001",
            }
        ]
        (self.project_root / "settings.json").write_text(json.dumps(settings), encoding="utf-8")
        opened = _quiet(
            lambda: self.client.post(
                "/api/project/open",
                json={"project_json_path": str(self.project_root / "project.json")},
            )
        )
        self.assertEqual(opened.status_code, 200, opened.text)

    def test_legacy_ids_paths_and_references_migrate_to_uuid_once(self) -> None:
        self._write_legacy_scene()
        response = _quiet(lambda: self.client.get("/api/project/scenes2d"))
        self.assertEqual(response.status_code, 200, response.text)
        scene = response.json()["scenes"][0]
        perspective = scene["perspectives"][0]

        self.assertTrue(_is_uuid(scene["id"]))
        self.assertTrue(_is_uuid(perspective["id"]))
        self.assertEqual(scene["primary_perspective_id"], perspective["id"])
        self.assertEqual(perspective["source_file_path"], f"scenes2d/{scene['id']}/perspectives/{perspective['id']}/source.psd")
        self.assertEqual(perspective["preview_image_path"], f"scenes2d/{scene['id']}/perspectives/{perspective['id']}/preview.png")
        self.assertTrue((self.project_root / perspective["source_file_path"]).is_file())
        self.assertTrue((self.project_root / perspective["preview_image_path"]).is_file())
        self.assertFalse((self.project_root / "scenes2d" / "scene_001").exists())

        project = _quiet(lambda: self.client.get("/api/project")).json()
        link = project["settings"]["reference_links"][0]
        self.assertEqual(link["id"], "ref_scene_001_persp_001")
        self.assertEqual(link["source_scene2d_id"], scene["id"])
        self.assertEqual(link["source_scene2d_perspective_id"], perspective["id"])
        self.assertEqual(link["path"], perspective["preview_image_path"])
        self.assertTrue((self.project_root / link["path"]).is_file())

        second = _quiet(lambda: self.client.get("/api/project/scenes2d")).json()["scenes"][0]
        self.assertEqual(second["id"], scene["id"])
        self.assertEqual(second["perspectives"][0]["id"], perspective["id"])

    def test_image_perspective_migration_preserves_source_extension(self) -> None:
        self._write_legacy_scene(image=True)
        response = _quiet(lambda: self.client.get("/api/project/scenes2d"))
        self.assertEqual(response.status_code, 200, response.text)
        perspective = response.json()["scenes"][0]["perspectives"][0]
        self.assertTrue(perspective["source_file_path"].endswith("/source.png"))
        self.assertEqual(perspective["preview_image_path"], perspective["source_file_path"])
        self.assertTrue((self.project_root / perspective["source_file_path"]).is_file())

    def test_missing_required_source_fails_without_deleting_legacy_files(self) -> None:
        self._write_legacy_scene(include_source=False)
        response = _quiet(lambda: self.client.get("/api/project/scenes2d"))
        self.assertNotEqual(response.status_code, 200)
        self.assertTrue((self.project_root / "scenes2d" / "scene_001").exists())
        index = json.loads((self.project_root / "scenes2d" / "scenes2d.json").read_text(encoding="utf-8"))
        self.assertEqual(index["scenes"][0]["id"], "scene_001")

    def test_already_uuid_project_is_not_rewritten_unnecessarily(self) -> None:
        created = _quiet(lambda: self.client.post("/api/project/scenes2d", json={"title": "UUID scene"})).json()["scene"]
        index_path = self.project_root / "scenes2d" / "scenes2d.json"
        before = index_path.read_text(encoding="utf-8")
        listed = _quiet(lambda: self.client.get("/api/project/scenes2d"))
        self.assertEqual(listed.status_code, 200, listed.text)
        after = index_path.read_text(encoding="utf-8")
        self.assertEqual(after, before)
        self.assertEqual(listed.json()["scenes"][0]["id"], created["id"])

    def test_renames_do_not_change_ids_paths_or_reference_links(self) -> None:
        scene = _quiet(lambda: self.client.post("/api/project/scenes2d", json={"title": "Original"})).json()["scene"]
        perspective = scene["perspectives"][0]
        (self.project_root / perspective["preview_image_path"]).write_bytes(MINI_PNG)
        reference = _quiet(
            lambda: self.client.post(
                f"/api/project/scenes2d/{scene['id']}/perspectives/{perspective['id']}/add-to-references"
            )
        ).json()["reference"]

        patched_scene = _quiet(
            lambda: self.client.patch(f"/api/project/scenes2d/{scene['id']}", json={"title": "Renamed"})
        ).json()["scene"]
        patched_perspective = _quiet(
            lambda: self.client.patch(
                f"/api/project/scenes2d/{scene['id']}/perspectives/{perspective['id']}",
                json={"title": "Renamed perspective"},
            )
        ).json()["perspective"]

        self.assertEqual(patched_scene["id"], scene["id"])
        self.assertEqual(patched_perspective["id"], perspective["id"])
        self.assertEqual(patched_perspective["source_file_path"], perspective["source_file_path"])
        self.assertEqual(patched_perspective["preview_image_path"], perspective["preview_image_path"])
        project = _quiet(lambda: self.client.get("/api/project")).json()
        link = next(item for item in project["settings"]["reference_links"] if item["id"] == reference["id"])
        self.assertEqual(link["source_scene2d_id"], scene["id"])
        self.assertEqual(link["source_scene2d_perspective_id"], perspective["id"])

    def test_delete_uuid_scene_and_perspective_clear_references_without_mutating_shots(self) -> None:
        scene = _quiet(lambda: self.client.post("/api/project/scenes2d", json={"title": "Delete me"})).json()["scene"]
        created = _quiet(lambda: self.client.post(f"/api/project/scenes2d/{scene['id']}/perspectives", json={"title": "Extra"})).json()
        perspective = created["perspective"]
        (self.project_root / perspective["preview_image_path"]).write_bytes(MINI_PNG)
        added = _quiet(
            lambda: self.client.post(
                f"/api/project/scenes2d/{scene['id']}/perspectives/{perspective['id']}/add-to-references"
            )
        )
        self.assertEqual(added.status_code, 200, added.text)
        before_shots = _quiet(lambda: self.client.get("/api/project")).json()["shots"]

        deleted_perspective = _quiet(lambda: self.client.delete(f"/api/project/scenes2d/{scene['id']}/perspectives/{perspective['id']}"))
        self.assertEqual(deleted_perspective.status_code, 200, deleted_perspective.text)
        self.assertFalse((self.project_root / "scenes2d" / scene["id"] / "perspectives" / perspective["id"]).exists())

        deleted_scene = _quiet(lambda: self.client.delete(f"/api/project/scenes2d/{scene['id']}"))
        self.assertEqual(deleted_scene.status_code, 200, deleted_scene.text)
        self.assertFalse((self.project_root / "scenes2d" / scene["id"]).exists())
        project = _quiet(lambda: self.client.get("/api/project")).json()
        self.assertEqual(project["settings"]["reference_links"], [])
        self.assertEqual(project["shots"], before_shots)


if __name__ == "__main__":
    unittest.main()
