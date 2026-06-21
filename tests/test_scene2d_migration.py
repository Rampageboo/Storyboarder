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

    def _write_legacy_scene(self, *, include_source: bool = True, image: bool = False, perspectives: int = 1) -> None:
        scenes_root = self.project_root / "scenes2d"
        scene_root = scenes_root / "scene_001"
        scene_root.mkdir(parents=True, exist_ok=True)
        perspective_records = []
        source_rel = ""
        preview_rel = ""
        for index in range(1, perspectives + 1):
            persp_id = f"persp_{index:03d}"
            source_rel = f"scenes2d/scene_001/perspectives/{persp_id}/source.png" if image else f"scenes2d/scene_001/scene_001_{index}.psd"
            preview_rel = source_rel if image else f"scenes2d/scene_001/scene_001_{index}_preview.png"
            if include_source:
                source = self.project_root / source_rel
                source.parent.mkdir(parents=True, exist_ok=True)
                source.write_bytes(MINI_PNG if image else f"legacy psd {index}".encode("utf-8"))
            if not image:
                (scene_root / f"scene_001_{index}_preview.png").write_bytes(MINI_PNG)
            perspective_records.append(
                {
                    "id": persp_id,
                    "title": f"Legacy perspective {index}",
                    "type": "image" if image else "psd",
                    "source_file_path": source_rel,
                    "preview_image_path": preview_rel,
                    "linked_scene3d_id": "scene3d_002",
                    "linked_scene3d_view": None,
                    "created_at": f"2025-01-01T00:00:0{index}Z",
                    "updated_at": f"2025-01-01T00:00:0{index}Z",
                }
            )
        if perspectives == 1 and not image:
            old_source = scene_root / "scene_001.psd"
            old_preview = scene_root / "scene_001_preview.png"
            if include_source:
                old_source.write_bytes(b"legacy psd")
                perspective_records[0]["source_file_path"] = "scenes2d/scene_001/scene_001.psd"
            old_preview.write_bytes(MINI_PNG)
            perspective_records[0]["preview_image_path"] = "scenes2d/scene_001/scene_001_preview.png"
            source_rel = perspective_records[0]["source_file_path"]
            preview_rel = perspective_records[0]["preview_image_path"]
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
                    "perspectives": perspective_records,
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

    def _settings_bytes(self) -> bytes:
        return (self.project_root / "settings.json").read_bytes()

    def _index_bytes(self) -> bytes:
        return (self.project_root / "scenes2d" / "scenes2d.json").read_bytes()

    def _uuid_scene_dirs(self) -> list[Path]:
        return [path for path in (self.project_root / "scenes2d").iterdir() if path.is_dir() and _is_uuid(path.name)]

    def _write_v2_backup(self, rel_path: str) -> dict:
        source = self.project_root / rel_path
        backup_rel = f"scenes2d/.uuid_migration_backup/{rel_path.removeprefix('scenes2d/')}"
        backup = self.project_root / backup_rel
        existed = source.is_file()
        if existed:
            backup.parent.mkdir(parents=True, exist_ok=True)
            backup.write_bytes(source.read_bytes())
        return {"path": rel_path, "backup_path": backup_rel, "existed": existed}

    def _write_v2_journal(self, **overrides) -> None:
        journal = {
            "version": 2,
            "state": "files_staged",
            "scene_map": {},
            "perspective_map": {},
            "created_paths": [],
            "legacy_roots": [],
            "backup_root": "scenes2d/.uuid_migration_backup",
            "original_files": [],
            "started_at": "2025-01-01T00:00:00Z",
        }
        journal.update(overrides)
        (self.project_root / "scenes2d" / ".uuid_migration.json").write_text(json.dumps(journal), encoding="utf-8")

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

    def test_failure_saving_settings_restores_legacy_metadata_files_and_memory(self) -> None:
        self._write_legacy_scene()
        original_index = self._index_bytes()
        original_settings = self._settings_bytes()
        original_memory = dict(self.app.state.project.settings)
        before_shots = _quiet(lambda: self.client.get("/api/project")).json()["shots"]

        from storyboard_tool import scene2d

        real_write = scene2d.project_manager._atomic_write_json

        def fail_settings(path, payload):
            if Path(path).name == "settings.json":
                raise OSError("settings write failed")
            return real_write(path, payload)

        with mock.patch("storyboard_tool.scene2d.project_manager._atomic_write_json", side_effect=fail_settings):
            response = _quiet(lambda: self.client.get("/api/project/scenes2d"))

        self.assertNotEqual(response.status_code, 200)
        self.assertEqual(self._index_bytes(), original_index)
        self.assertEqual(self._settings_bytes(), original_settings)
        self.assertEqual(self.app.state.project.settings, original_memory)
        self.assertTrue((self.project_root / "scenes2d" / "scene_001" / "scene_001.psd").is_file())
        self.assertTrue((self.project_root / "scenes2d" / "scene_001" / "scene_001_preview.png").is_file())
        self.assertEqual(self._uuid_scene_dirs(), [])
        self.assertEqual(_quiet(lambda: self.client.get("/api/project")).json()["shots"], before_shots)

        retry = _quiet(lambda: self.client.get("/api/project/scenes2d"))
        self.assertEqual(retry.status_code, 200, retry.text)
        self.assertTrue(_is_uuid(retry.json()["scenes"][0]["id"]))

    def test_failure_writing_scene_index_leaves_settings_and_legacy_files(self) -> None:
        self._write_legacy_scene()
        original_index = self._index_bytes()
        original_settings = self._settings_bytes()

        from storyboard_tool import scene2d

        real_write = scene2d.project_manager._atomic_write_json

        def fail_index(path, payload):
            if Path(path).name == "scenes2d.json":
                raise OSError("index write failed")
            return real_write(path, payload)

        with mock.patch("storyboard_tool.scene2d.project_manager._atomic_write_json", side_effect=fail_index):
            response = _quiet(lambda: self.client.get("/api/project/scenes2d"))

        self.assertNotEqual(response.status_code, 200)
        self.assertEqual(self._index_bytes(), original_index)
        self.assertEqual(self._settings_bytes(), original_settings)
        self.assertTrue((self.project_root / "scenes2d" / "scene_001" / "scene_001.psd").is_file())
        self.assertEqual(self._uuid_scene_dirs(), [])

    def test_failure_copying_second_perspective_cleans_staged_uuid_files(self) -> None:
        self._write_legacy_scene(perspectives=2)
        original_index = self._index_bytes()
        original_settings = self._settings_bytes()

        from storyboard_tool import scene2d

        real_copy = scene2d.shutil.copy2
        calls = {"count": 0}

        def fail_second_copy(src, dst):
            calls["count"] += 1
            if calls["count"] == 2:
                raise OSError("copy failed")
            return real_copy(src, dst)

        with mock.patch("storyboard_tool.scene2d.shutil.copy2", side_effect=fail_second_copy):
            response = _quiet(lambda: self.client.get("/api/project/scenes2d"))

        self.assertNotEqual(response.status_code, 200)
        self.assertEqual(self._index_bytes(), original_index)
        self.assertEqual(self._settings_bytes(), original_settings)
        self.assertEqual(self._uuid_scene_dirs(), [])
        self.assertTrue((self.project_root / "scenes2d" / "scene_001").is_dir())

    def test_cleanup_failure_after_metadata_commit_leaves_uuid_project_usable_and_retry_cleans(self) -> None:
        self._write_legacy_scene()

        from storyboard_tool import scene2d

        real_rmtree = scene2d.shutil.rmtree

        def fail_legacy_cleanup(path, *args, **kwargs):
            if Path(path).name == "scene_001":
                raise OSError("cleanup failed")
            return real_rmtree(path, *args, **kwargs)

        with mock.patch("storyboard_tool.scene2d.shutil.rmtree", side_effect=fail_legacy_cleanup):
            response = _quiet(lambda: self.client.get("/api/project/scenes2d"))

        self.assertEqual(response.status_code, 200, response.text)
        scene = response.json()["scenes"][0]
        self.assertTrue(_is_uuid(scene["id"]))
        self.assertTrue((self.project_root / "scenes2d" / "scene_001").exists())
        self.assertTrue((self.project_root / "scenes2d" / ".uuid_migration.json").is_file())
        self.assertTrue((self.project_root / "scenes2d" / ".uuid_migration_backup").is_dir())
        project = _quiet(lambda: self.client.get("/api/project")).json()
        self.assertEqual(project["settings"]["reference_links"][0]["source_scene2d_id"], scene["id"])

        retry = _quiet(lambda: self.client.get("/api/project/scenes2d"))
        self.assertEqual(retry.status_code, 200, retry.text)
        self.assertFalse((self.project_root / "scenes2d" / "scene_001").exists())
        self.assertFalse((self.project_root / "scenes2d" / ".uuid_migration.json").exists())
        self.assertFalse((self.project_root / "scenes2d" / ".uuid_migration_backup").exists())

    def test_normal_migration_removes_backup_area_after_success(self) -> None:
        self._write_legacy_scene()

        response = _quiet(lambda: self.client.get("/api/project/scenes2d"))

        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse((self.project_root / "scenes2d" / ".uuid_migration.json").exists())
        self.assertFalse((self.project_root / "scenes2d" / ".uuid_migration_backup").exists())

    def test_files_staged_journal_recovery_removes_staged_uuid_dir_only(self) -> None:
        self._write_legacy_scene()
        staged_uuid = str(uuid.uuid4())
        staged_dir = self.project_root / "scenes2d" / staged_uuid
        staged_dir.mkdir(parents=True)
        (staged_dir / "temporary.txt").write_text("staged", encoding="utf-8")
        journal = {
            "version": 1,
            "state": "files_staged",
            "scene_map": {"scene_001": staged_uuid},
            "perspective_map": {"scene_001/persp_001": str(uuid.uuid4())},
            "created_paths": [f"scenes2d/{staged_uuid}"],
            "legacy_roots": ["scenes2d/scene_001"],
            "started_at": "2025-01-01T00:00:00Z",
        }
        (self.project_root / "scenes2d" / ".uuid_migration.json").write_text(json.dumps(journal), encoding="utf-8")

        response = _quiet(lambda: self.client.get("/api/project/scenes2d"))

        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(staged_dir.exists())
        self.assertFalse((self.project_root / "scenes2d" / ".uuid_migration.json").exists())
        self.assertTrue((self.project_root / "scenes2d" / "scene_001").exists())

    def test_v2_files_staged_recovery_restores_canonical_metadata_from_backup(self) -> None:
        self._write_legacy_scene()
        original_index = self._index_bytes()
        original_settings = self._settings_bytes()
        original_files = [
            self._write_v2_backup("scenes2d/scenes2d.json"),
            self._write_v2_backup("settings.json"),
        ]
        staged_uuid = str(uuid.uuid4())
        staged_dir = self.project_root / "scenes2d" / staged_uuid
        staged_dir.mkdir(parents=True)
        (self.project_root / "scenes2d" / "scenes2d.json").write_text('{"scenes":[]}', encoding="utf-8")
        (self.project_root / "settings.json").write_text('{"reference_links":[]}', encoding="utf-8")
        self._write_v2_journal(
            state="files_staged",
            scene_map={"scene_001": staged_uuid},
            created_paths=[f"scenes2d/{staged_uuid}"],
            legacy_roots=["scenes2d/scene_001"],
            original_files=original_files,
        )

        response = _quiet(lambda: self.client.get("/api/project/scenes2d"))

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self._index_bytes(), original_index)
        self.assertEqual(self._settings_bytes(), original_settings)
        self.assertFalse(staged_dir.exists())
        self.assertFalse((self.project_root / "scenes2d" / ".uuid_migration_backup").exists())

    def test_v2_metadata_committing_rolls_back_when_uuid_payload_incomplete(self) -> None:
        self._write_legacy_scene()
        original_index = self._index_bytes()
        original_settings = self._settings_bytes()
        original_files = [
            self._write_v2_backup("scenes2d/scenes2d.json"),
            self._write_v2_backup("settings.json"),
        ]
        scene_uuid = str(uuid.uuid4())
        perspective_uuid = str(uuid.uuid4())
        staged_dir = self.project_root / "scenes2d" / scene_uuid
        staged_dir.mkdir(parents=True)
        incomplete = {
            "scenes": [
                {
                    "id": scene_uuid,
                    "title": "Migrated",
                    "primary_perspective_id": perspective_uuid,
                    "perspectives": [
                        {
                            "id": perspective_uuid,
                            "title": "Missing source",
                            "type": "psd",
                            "source_file_path": f"scenes2d/{scene_uuid}/perspectives/{perspective_uuid}/source.psd",
                            "preview_image_path": f"scenes2d/{scene_uuid}/perspectives/{perspective_uuid}/preview.png",
                        }
                    ],
                }
            ]
        }
        (self.project_root / "scenes2d" / "scenes2d.json").write_text(json.dumps(incomplete), encoding="utf-8")
        self._write_v2_journal(
            state="metadata_committing",
            scene_map={"scene_001": scene_uuid},
            perspective_map={"scene_001/persp_001": perspective_uuid},
            created_paths=[f"scenes2d/{scene_uuid}"],
            legacy_roots=["scenes2d/scene_001"],
            original_files=original_files,
        )

        response = _quiet(lambda: self.client.get("/api/project/scenes2d"))

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self._index_bytes(), original_index)
        self.assertEqual(self._settings_bytes(), original_settings)
        self.assertFalse(staged_dir.exists())
        self.assertFalse((self.project_root / "scenes2d" / ".uuid_migration.json").exists())
        self.assertFalse((self.project_root / "scenes2d" / ".uuid_migration_backup").exists())

    def test_v2_metadata_committing_rolls_forward_when_uuid_payload_complete(self) -> None:
        self._write_legacy_scene()
        migrated = _quiet(lambda: self.client.get("/api/project/scenes2d")).json()["scenes"][0]
        legacy_root = self.project_root / "scenes2d" / "scene_001"
        legacy_root.mkdir(parents=True, exist_ok=True)
        self._write_v2_journal(
            state="metadata_committing",
            scene_map={"scene_001": migrated["id"]},
            perspective_map={"scene_001/persp_001": migrated["perspectives"][0]["id"]},
            created_paths=[f"scenes2d/{migrated['id']}"],
            legacy_roots=["scenes2d/scene_001"],
            original_files=[],
        )

        response = _quiet(lambda: self.client.get("/api/project/scenes2d"))

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["scenes"][0]["id"], migrated["id"])
        self.assertFalse(legacy_root.exists())
        self.assertFalse((self.project_root / "scenes2d" / ".uuid_migration.json").exists())

    def test_metadata_committed_journal_recovery_finishes_legacy_cleanup(self) -> None:
        self._write_legacy_scene()
        migrated = _quiet(lambda: self.client.get("/api/project/scenes2d")).json()["scenes"][0]
        legacy_root = self.project_root / "scenes2d" / "scene_001"
        legacy_root.mkdir(parents=True, exist_ok=True)
        (legacy_root / "leftover.psd").write_bytes(b"leftover")
        journal = {
            "version": 1,
            "state": "metadata_committed",
            "scene_map": {"scene_001": migrated["id"]},
            "perspective_map": {"scene_001/persp_001": migrated["perspectives"][0]["id"]},
            "created_paths": [f"scenes2d/{migrated['id']}"],
            "legacy_roots": ["scenes2d/scene_001"],
            "started_at": "2025-01-01T00:00:00Z",
        }
        (self.project_root / "scenes2d" / ".uuid_migration.json").write_text(json.dumps(journal), encoding="utf-8")

        response = _quiet(lambda: self.client.get("/api/project/scenes2d"))

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["scenes"][0]["id"], migrated["id"])
        self.assertFalse(legacy_root.exists())
        self.assertFalse((self.project_root / "scenes2d" / ".uuid_migration.json").exists())

    def test_corrupt_journal_does_not_delete_project_data(self) -> None:
        self._write_legacy_scene()
        legacy_root = self.project_root / "scenes2d" / "scene_001"
        (self.project_root / "scenes2d" / ".uuid_migration.json").write_text("{broken", encoding="utf-8")

        response = _quiet(lambda: self.client.get("/api/project/scenes2d"))

        self.assertNotEqual(response.status_code, 200)
        self.assertTrue(legacy_root.exists())
        self.assertTrue((self.project_root / "scenes2d" / ".uuid_migration.json").exists())


if __name__ == "__main__":
    unittest.main()
