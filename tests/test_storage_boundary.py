"""Storage compatibility boundary tests.

Verifies the canonical vs legacy storage contract for shots metadata:

  Canonical store (shots.json):
    - Written by save_project / save_shots on every mutation.
    - Preferred unconditionally by open_project when it exists.
    - Atomic write (temp-file replace).

  Compatibility snapshot (shots.csv):
    - Regenerated alongside shots.json on every save_project.
    - Ignored by open_project when shots.json is present.
    - The only load source for legacy CSV-only projects (migrated on first open).

  Legacy inline shots (project.json "shots" key):
    - Loaded only when both shots.json and shots.csv are absent.
    - Migrated to shots.json non-destructively on first open.
    - Never written by the current save_project path.

  Asset ownership guardrail:
    - image_path / preview_image_path must never point to _background.png.
"""
from __future__ import annotations

import contextlib
import csv
import io
import json
import os
import shutil
import tempfile
import time
import unittest
import warnings
from pathlib import Path

with warnings.catch_warnings():
    warnings.filterwarnings("ignore", message="Using `httpx` with `starlette.testclient` is deprecated")
    from fastapi.testclient import TestClient

from storyboard_tool import api as api_module, project_manager
from storyboard_tool.image_utils import board_background_filename
from storyboard_tool.models import Shot
from storyboard_tool.shot_store import (
    load_shots_csv,
    load_shots_json,
    save_shots,
    save_shots_csv,
    save_shots_json,
    shots_csv_path,
    shots_json_path,
)


def _make_client(tmp: str) -> TestClient:
    return TestClient(api_module.create_app(Path(tmp)), raise_server_exceptions=False)


def _quiet(fn):
    with contextlib.redirect_stderr(io.StringIO()):
        return fn()


def _make_project(tmp: str) -> "project_manager.models.Project":
    return project_manager.create_project(Path(tmp))


def _reload(project) -> "project_manager.models.Project":
    return project_manager.open_project(project.json_path)


# ---------------------------------------------------------------------------
# Canonical save — shots.json and shots.csv both written
# ---------------------------------------------------------------------------

class TestCanonicalSave(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_save_project_creates_shots_json(self):
        """save_project must always write shots.json — the canonical store."""
        project = _make_project(self._tmp)
        project_manager.add_shot(project)
        project_manager.save_project(project)
        self.assertTrue(
            shots_json_path(project.root_path).is_file(),
            "shots.json must exist after save_project",
        )

    def test_save_project_creates_shots_csv(self):
        """save_project must also regenerate shots.csv as a compatibility snapshot."""
        project = _make_project(self._tmp)
        project_manager.add_shot(project)
        project_manager.save_project(project)
        self.assertTrue(
            shots_csv_path(project.root_path).is_file(),
            "shots.csv compatibility snapshot must exist after save_project",
        )

    def test_shots_json_contains_canonical_version_key(self):
        """shots.json must have a top-level version key (structured format)."""
        project = _make_project(self._tmp)
        project_manager.add_shot(project)
        project_manager.save_project(project)
        payload = json.loads(shots_json_path(project.root_path).read_text(encoding="utf-8"))
        self.assertIn("version", payload, "shots.json must have a 'version' key")
        self.assertIn("shots", payload, "shots.json must have a 'shots' key")

    def test_project_json_does_not_contain_inline_shots(self):
        """project.json must never contain an inline 'shots' key after a modern save."""
        project = _make_project(self._tmp)
        project_manager.add_shot(project)
        project_manager.save_project(project)
        manifest = json.loads(project.json_path.read_text(encoding="utf-8"))
        self.assertNotIn(
            "shots", manifest,
            "project.json must not contain an inline 'shots' key — "
            "shots live in shots.json",
        )

    def test_shots_json_and_csv_agree_on_shot_ids(self):
        """The canonical shots.json and the CSV snapshot must contain the same shot IDs."""
        project = _make_project(self._tmp)
        project_manager.add_shot(project)
        project_manager.add_shot(project)
        project_manager.save_project(project)

        json_shots = load_shots_json(shots_json_path(project.root_path))
        csv_shots = load_shots_csv(shots_csv_path(project.root_path))

        json_ids = {s.shot_id for s in json_shots}
        csv_ids = {s.shot_id for s in csv_shots}
        self.assertEqual(
            json_ids, csv_ids,
            "shots.json and shots.csv must contain the same shot IDs after save_project",
        )


# ---------------------------------------------------------------------------
# Load priority — shots.json beats shots.csv
# ---------------------------------------------------------------------------

class TestLoadPriority(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_shots_json_preferred_over_csv_when_both_exist(self):
        """open_project must load from shots.json and ignore shots.csv when both exist."""
        project = _make_project(self._tmp)
        a = project_manager.add_shot(project)
        project_manager.save_project(project)

        # Corrupt the CSV with a fake shot ID that does not exist in shots.json.
        csv_path = shots_csv_path(project.root_path)
        rows = []
        with csv_path.open(newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            fieldnames = reader.fieldnames
            rows = list(reader)
        # Overwrite the first row's shot_id in CSV to something wrong.
        if rows:
            rows[0]["shot_id"] = "csv_only_ghost_shot"
        with csv_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

        # Reload: must use shots.json, not the tampered CSV.
        reloaded = _reload(project)
        shot_ids = {s.shot_id for s in reloaded.shots}
        self.assertIn(a.shot_id, shot_ids, "Original shot must be present (from shots.json)")
        self.assertNotIn(
            "csv_only_ghost_shot", shot_ids,
            "Ghost shot injected into CSV must not appear — shots.json takes precedence",
        )

    def test_csv_loaded_when_shots_json_absent(self):
        """open_project must fall back to shots.csv for legacy CSV-only projects."""
        project = _make_project(self._tmp)
        a = project_manager.add_shot(project)
        project_manager.save_project(project)

        # Remove shots.json to simulate a legacy CSV-only project.
        shots_json_path(project.root_path).unlink()

        reloaded = _reload(project)
        shot_ids = {s.shot_id for s in reloaded.shots}
        self.assertIn(
            a.shot_id, shot_ids,
            "Shot must still load from shots.csv when shots.json is absent",
        )


# ---------------------------------------------------------------------------
# Canonical shots.json safety
# ---------------------------------------------------------------------------

class TestCanonicalJsonSafety(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_invalid_shots_json_raises_clear_error(self):
        project = _make_project(self._tmp)
        json_path = shots_json_path(project.root_path)
        json_path.write_text("{not valid json", encoding="utf-8")

        with self.assertRaisesRegex(ValueError, r"shots\.json.*canonical shot metadata.*invalid JSON"):
            _reload(project)

    def test_container_corrupt_shots_json_raises_clear_error(self):
        project = _make_project(self._tmp)
        json_path = shots_json_path(project.root_path)

        corrupt_payloads = [
            "null",
            json.dumps("not a container"),
            json.dumps({"version": 1, "shots": 42}),
        ]
        for payload in corrupt_payloads:
            with self.subTest(payload=payload):
                json_path.write_text(payload, encoding="utf-8")
                with self.assertRaisesRegex(ValueError, r"shots\.json.*corrupt.*canonical shot metadata"):
                    _reload(project)

    def test_valid_empty_shots_json_opens_zero_shots(self):
        project = _make_project(self._tmp)
        shots_json_path(project.root_path).write_text(
            json.dumps({"version": 1, "shots": []}),
            encoding="utf-8",
        )

        reloaded = _reload(project)
        self.assertEqual(reloaded.shots, [])

    def test_top_level_array_shots_json_still_loads(self):
        project = _make_project(self._tmp)
        shot = Shot(shot_id="array_shot", title="Array shape")
        shots_json_path(project.root_path).write_text(
            json.dumps([shot.to_dict()]),
            encoding="utf-8",
        )

        reloaded = _reload(project)
        self.assertEqual([item.shot_id for item in reloaded.shots], ["array_shot"])

    def test_malformed_entry_is_skipped_but_valid_entries_load(self):
        project = _make_project(self._tmp)
        valid = Shot(shot_id="valid_shot", title="Keep me")
        shots_json_path(project.root_path).write_text(
            json.dumps({"version": 1, "shots": [None, {"title": "missing id"}, valid.to_dict()]}),
            encoding="utf-8",
        )

        reloaded = _reload(project)
        self.assertEqual([item.shot_id for item in reloaded.shots], ["valid_shot"])

    def test_object_without_shots_key_is_lenient_empty_list(self):
        project = _make_project(self._tmp)
        shots_json_path(project.root_path).write_text(json.dumps({"version": 1}), encoding="utf-8")

        reloaded = _reload(project)
        self.assertEqual(reloaded.shots, [])

    def test_corrupt_shots_json_api_open_returns_project_open_failed(self):
        project = _make_project(self._tmp)
        shots_json_path(project.root_path).write_text("{broken", encoding="utf-8")
        client = _make_client(self._tmp)

        response = _quiet(lambda: client.post(
            "/api/project/open",
            json={"project_json_path": str(project.json_path)},
        ))

        self.assertEqual(response.status_code, 400)
        body = response.json()
        self.assertEqual(body.get("code"), "PROJECT_OPEN_FAILED")
        self.assertIn("shots.json", body.get("detail", ""))

    def test_background_refresh_keeps_in_memory_project_when_disk_json_is_corrupt(self):
        client = _make_client(self._tmp)
        created = _quiet(lambda: client.post("/api/project/new", json={"path": self._tmp}))
        self.assertEqual(created.status_code, 200)
        added = _quiet(lambda: client.post("/api/shots", json={}))
        self.assertEqual(added.status_code, 200)
        before = added.json()
        shot_id = before["shot"]["shot_id"]
        project_root = Path(before["project_path"])
        json_path = shots_json_path(project_root)
        json_path.write_text("{transiently broken", encoding="utf-8")
        future = time.time() + 2.0
        os.utime(json_path, (future, future))

        response = _quiet(lambda: client.get("/api/project"))

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn(shot_id, {shot["shot_id"] for shot in body["shots"]})


# ---------------------------------------------------------------------------
# Legacy migration — shots.json written non-destructively on open
# ---------------------------------------------------------------------------

class TestLegacyMigration(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_csv_only_project_migrates_to_shots_json_on_open(self):
        """open_project creates shots.json for a legacy CSV-only project (non-destructive)."""
        project = _make_project(self._tmp)
        project_manager.add_shot(project)
        project_manager.save_project(project)

        # Remove shots.json to simulate a CSV-only project.
        json_path = shots_json_path(project.root_path)
        json_path.unlink()
        self.assertFalse(json_path.is_file(), "shots.json removed for test setup")

        # open_project must recreate shots.json from the CSV.
        _reload(project)
        self.assertTrue(
            json_path.is_file(),
            "open_project must write shots.json as part of legacy CSV migration",
        )

    def test_csv_preserved_after_migration(self):
        """The legacy shots.csv is left intact after open_project migration."""
        project = _make_project(self._tmp)
        project_manager.add_shot(project)
        project_manager.save_project(project)

        csv_path = shots_csv_path(project.root_path)
        shots_json_path(project.root_path).unlink()

        _reload(project)
        self.assertTrue(
            csv_path.is_file(),
            "shots.csv must survive open_project migration — non-destructive",
        )

    def test_inline_shots_project_migrates_to_shots_json_on_open(self):
        """open_project creates shots.json from inline shots embedded in project.json."""
        project = _make_project(self._tmp)
        shot = project_manager.add_shot(project)
        project_manager.save_project(project)

        # Simulate a very old project.json that embeds shots inline,
        # with no shots.json or shots.csv.
        json_path = shots_json_path(project.root_path)
        csv_path = shots_csv_path(project.root_path)
        json_path.unlink(missing_ok=True)
        csv_path.unlink(missing_ok=True)

        manifest = json.loads(project.json_path.read_text(encoding="utf-8"))
        manifest["shots"] = [shot.to_dict()]
        project.json_path.write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )

        # open_project must read inline shots and create shots.json.
        reloaded = _reload(project)
        self.assertTrue(
            json_path.is_file(),
            "open_project must write shots.json from inline shots in project.json",
        )
        shot_ids = {s.shot_id for s in reloaded.shots}
        self.assertIn(shot.shot_id, shot_ids, "Inline shot must be present after migration")

    def test_migrated_shots_json_matches_original_shot_ids(self):
        """Shots migrated from CSV must preserve their shot IDs in the new shots.json."""
        project = _make_project(self._tmp)
        a = project_manager.add_shot(project)
        b = project_manager.add_shot(project)
        project_manager.save_project(project)

        json_path = shots_json_path(project.root_path)
        json_path.unlink()

        _reload(project)

        migrated = load_shots_json(json_path)
        migrated_ids = {s.shot_id for s in migrated}
        self.assertIn(a.shot_id, migrated_ids)
        self.assertIn(b.shot_id, migrated_ids)


# ---------------------------------------------------------------------------
# save_shots — entry-point writes both canonical and snapshot
# ---------------------------------------------------------------------------

class TestSaveShotsEntryPoint(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_save_shots_writes_json_and_csv(self):
        """save_shots() must write both shots.json and shots.csv in one call."""
        root = Path(self._tmp) / "proj"
        root.mkdir()
        shots = [Shot(shot_id="shot_001"), Shot(shot_id="shot_002")]
        save_shots(root, shots)
        self.assertTrue(shots_json_path(root).is_file(), "shots.json missing after save_shots")
        self.assertTrue(shots_csv_path(root).is_file(), "shots.csv missing after save_shots")

    def test_save_shots_returns_json_path(self):
        """save_shots() must return the path to shots.json."""
        root = Path(self._tmp) / "proj"
        root.mkdir()
        result = save_shots(root, [Shot(shot_id="shot_001")])
        self.assertEqual(result, shots_json_path(root))

    def test_save_shots_json_is_atomic(self):
        """save_shots must leave no .tmp file after a successful write."""
        root = Path(self._tmp) / "proj"
        root.mkdir()
        save_shots(root, [Shot(shot_id="shot_a")])
        tmp_files = list(root.glob("*.tmp"))
        self.assertEqual(tmp_files, [], "Stale .tmp file found after save_shots — not atomic")


# ---------------------------------------------------------------------------
# Annotation persistence
# ---------------------------------------------------------------------------

class TestAnnotationPersistence(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.client = _make_client(self._tmp)
        created = _quiet(lambda: self.client.post("/api/project/new", json={"path": self._tmp}))
        self.assertEqual(created.status_code, 200)
        added = _quiet(lambda: self.client.post("/api/shots", json={}))
        self.assertEqual(added.status_code, 200)
        body = added.json()
        self.shot_id = body["shot"]["shot_id"]
        self.project_root = Path(body["project_path"])

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _annotation_path(self) -> Path:
        project = project_manager.open_project(self.project_root / "project.json")
        shot = next(item for item in project.shots if item.shot_id == self.shot_id)
        return self.project_root / shot.annotation_path

    def test_save_annotations_writes_valid_json(self):
        payload = [{"id": "a1", "points": [[1, 2], [3, 4]], "label": "note"}]

        response = _quiet(lambda: self.client.put(
            f"/api/shots/{self.shot_id}/annotations",
            json={"annotations": payload},
        ))

        self.assertEqual(response.status_code, 200)
        saved = json.loads(self._annotation_path().read_text(encoding="utf-8"))
        self.assertEqual(saved, payload)

    def test_save_annotations_preserves_requested_payload(self):
        payload = [
            {"type": "rect", "x": 10, "y": 20, "meta": {"color": "#ff00aa"}},
            {"type": "legacy", "points": ["array", "entry"]},
        ]

        response = _quiet(lambda: self.client.put(
            f"/api/shots/{self.shot_id}/annotations",
            json={"annotations": payload},
        ))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["annotations"], payload)
        self.assertEqual(json.loads(self._annotation_path().read_text(encoding="utf-8")), payload)

    def test_missing_annotation_file_is_recreated_as_empty_list(self):
        path = self._annotation_path()
        path.unlink()

        response = _quiet(lambda: self.client.get(f"/api/shots/{self.shot_id}/annotations"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["annotations"], [])
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), [])


# ---------------------------------------------------------------------------
# Asset ownership guardrail — background never in preview metadata
# ---------------------------------------------------------------------------

class TestBackgroundAssetGuardrail(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_relink_preview_rejects_background_filename(self):
        """relink_preview_image must raise ValueError if the path is a _background.png."""
        project = _make_project(self._tmp)
        shot = project_manager.add_shot(project)
        shot_dir = project_manager.get_shot_dir(project, shot)
        bg_name = board_background_filename(shot.shot_id)
        bg_file = shot_dir / bg_name
        bg_file.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8)
        bg_rel = bg_file.relative_to(project.root_path).as_posix()

        with self.assertRaises(ValueError, msg="Background file must be rejected as preview"):
            project_manager.relink_preview_image(project, shot, bg_rel)

    def test_relink_preview_rejects_background_does_not_mutate_metadata(self):
        """After rejecting a background path, shot metadata must be unchanged."""
        project = _make_project(self._tmp)
        shot = project_manager.add_shot(project)
        original_preview = shot.preview_image_path
        shot_dir = project_manager.get_shot_dir(project, shot)
        bg_name = board_background_filename(shot.shot_id)
        (shot_dir / bg_name).write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8)
        bg_rel = (shot_dir / bg_name).relative_to(project.root_path).as_posix()

        try:
            project_manager.relink_preview_image(project, shot, bg_rel)
        except ValueError:
            pass

        self.assertEqual(
            shot.preview_image_path, original_preview,
            "preview_image_path must not change after rejection",
        )

    def test_background_filename_never_matches_preview_after_save_reload(self):
        """After save/reload, image_path and preview_image_path must not point to _background.png."""
        project = _make_project(self._tmp)
        shot = project_manager.add_shot(project)
        shot_dir = project_manager.get_shot_dir(project, shot)
        bg_name = board_background_filename(shot.shot_id)
        (shot_dir / bg_name).write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8)

        project_manager.save_project(project)
        reloaded = _reload(project)
        for s in reloaded.shots:
            self.assertNotIn(
                "_background", s.image_path,
                f"image_path must not reference _background.png: {s.image_path}",
            )
            self.assertNotIn(
                "_background", s.preview_image_path,
                f"preview_image_path must not reference _background.png: {s.preview_image_path}",
            )


if __name__ == "__main__":
    unittest.main()
