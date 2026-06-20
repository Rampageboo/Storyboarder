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


def _quiet(fn):
    with contextlib.redirect_stderr(io.StringIO()):
        return fn()


class Scene3DLibraryTests(unittest.TestCase):
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

    def test_singleton_settings_scene3d_normalizes_to_active_collection_scene(self) -> None:
        response = _quiet(lambda: self.client.get("/api/project/scenes3d"))

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["active_scene3d_id"], "scene3d_001")
        self.assertEqual(payload["scenes"][0]["id"], "scene3d_001")
        self.assertTrue((self.project_root / "scenes3d" / "scenes3d.json").is_file())

        project = _quiet(lambda: self.client.get("/api/project")).json()
        self.assertEqual(project["settings"]["active_scene3d_id"], "scene3d_001")
        self.assertEqual(project["settings"]["scene3d"]["id"], "scene3d_001")

    def test_create_import_set_active_and_singleton_routes_use_active_scene(self) -> None:
        created = _quiet(lambda: self.client.post("/api/project/scenes3d", json={"title": "Warehouse"}))
        self.assertEqual(created.status_code, 200, created.text)
        scene = created.json()["scene"]
        self.assertEqual(scene["id"], "scene3d_002")

        imported = _quiet(
            lambda: self.client.post(
                f"/api/project/scenes3d/{scene['id']}/import",
                files={"file": ("warehouse.glb", b"glb bytes", "model/gltf-binary")},
            )
        )
        self.assertEqual(imported.status_code, 200, imported.text)
        imported_scene = imported.json()["scene"]
        self.assertEqual(imported_scene["file_name"], "warehouse.glb")
        self.assertTrue(imported_scene["file_path"].startswith(f"scenes3d/{scene['id']}/"))

        active = _quiet(lambda: self.client.post(f"/api/project/scenes3d/{scene['id']}/set-active"))
        self.assertEqual(active.status_code, 200, active.text)
        self.assertEqual(active.json()["active_scene3d_id"], scene["id"])

        singleton_file = _quiet(lambda: self.client.get("/api/project/scene3d/file"))
        self.assertEqual(singleton_file.status_code, 200, singleton_file.text)
        self.assertEqual(singleton_file.content, b"glb bytes")

        collection_file = _quiet(lambda: self.client.get(f"/api/project/scenes3d/{scene['id']}/file"))
        self.assertEqual(collection_file.status_code, 200, collection_file.text)
        self.assertEqual(collection_file.content, b"glb bytes")

        project = _quiet(lambda: self.client.get("/api/project")).json()
        self.assertEqual(project["settings"]["active_scene3d_id"], scene["id"])
        self.assertEqual(project["settings"]["scene3d"]["file_name"], "warehouse.glb")

    def test_legacy_scene3d_import_route_imports_into_active_scene(self) -> None:
        response = _quiet(
            lambda: self.client.post(
                "/api/project/scene3d/import",
                files={"file": ("active.glb", b"active glb", "model/gltf-binary")},
            )
        )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["scene3d"]["file_name"], "active.glb")
        self.assertEqual(payload["scenes3d"]["active_scene3d_id"], "scene3d_001")
        self.assertEqual(payload["scenes3d"]["scene"]["file_name"], "active.glb")

        file_response = _quiet(lambda: self.client.get("/api/project/scene3d/file"))
        self.assertEqual(file_response.status_code, 200, file_response.text)
        self.assertEqual(file_response.content, b"active glb")

    def test_scene2d_linked_scene3d_id_persists(self) -> None:
        scene3d = _quiet(lambda: self.client.post("/api/project/scenes3d", json={"title": "Street"})).json()["scene"]
        scene2d = _quiet(lambda: self.client.post("/api/project/scenes2d", json={"title": "Street plan"})).json()["scene"]

        patched = _quiet(
            lambda: self.client.patch(
                f"/api/project/scenes2d/{scene2d['id']}",
                json={"linked_scene3d_id": scene3d["id"]},
            )
        )

        self.assertEqual(patched.status_code, 200, patched.text)
        self.assertEqual(patched.json()["scene"]["linked_scene3d_id"], scene3d["id"])
        listed = _quiet(lambda: self.client.get("/api/project/scenes2d"))
        self.assertEqual(listed.json()["scenes"][0]["linked_scene3d_id"], scene3d["id"])

    def test_delete_scene3d_clears_scene2d_group_and_perspective_links(self) -> None:
        existing = _quiet(lambda: self.client.get("/api/project/scenes3d"))
        self.assertEqual(existing.status_code, 200, existing.text)
        scene3d_b = _quiet(lambda: self.client.post("/api/project/scenes3d", json={"title": "Delete target"})).json()["scene"]
        scene2d = _quiet(lambda: self.client.post("/api/project/scenes2d", json={"title": "Linked 2D"})).json()["scene"]
        before_shots = _quiet(lambda: self.client.get("/api/project")).json()["shots"]

        patched = _quiet(
            lambda: self.client.patch(
                f"/api/project/scenes2d/{scene2d['id']}",
                json={"linked_scene3d_id": scene3d_b["id"]},
            )
        )
        self.assertEqual(patched.status_code, 200, patched.text)

        perspective = _quiet(
            lambda: self.client.post(
                f"/api/project/scenes2d/{scene2d['id']}/perspectives",
                json={"title": "Linked perspective", "linked_scene3d_id": scene3d_b["id"]},
            )
        ).json()["perspective"]
        self.assertEqual(perspective["linked_scene3d_id"], scene3d_b["id"])

        deleted = _quiet(lambda: self.client.delete(f"/api/project/scenes3d/{scene3d_b['id']}"))
        self.assertEqual(deleted.status_code, 200, deleted.text)

        scenes2d = _quiet(lambda: self.client.get("/api/project/scenes2d")).json()["scenes"]
        self.assertEqual(len(scenes2d), 1)
        scene = scenes2d[0]
        self.assertEqual(scene["id"], scene2d["id"])
        self.assertEqual(scene["linked_scene3d_id"], "")
        self.assertEqual(len(scene["perspectives"]), 2)
        cleared_perspective = next(item for item in scene["perspectives"] if item["id"] == perspective["id"])
        self.assertEqual(cleared_perspective["linked_scene3d_id"], "")
        self.assertEqual(_quiet(lambda: self.client.get("/api/project")).json()["shots"], before_shots)


if __name__ == "__main__":
    unittest.main()
