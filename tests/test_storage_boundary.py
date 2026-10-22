"""Storage boundary tests.

Verifies the storage contract for shots metadata:

  Canonical store (.storyboarder/data/shots.json):
    - Written by save_project / save_shots_json on every mutation.
    - The only shot metadata open_project reads; there is no shots.csv.
    - Atomic write (temp-file replace).
    - project.json is a manifest and never carries inline shots.

  Asset ownership guardrail:
    - image_path / preview_image_path must never point to _background.png.
"""
from __future__ import annotations

import contextlib
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
from storyboard_tool.image_utils import board_background_filename, codex_layer_filename
from storyboard_tool.models import Shot
from storyboard_tool.shot_store import (
    load_shots_json,
    save_shots_json,
    shots_json_path,
)


def _make_client(tmp: str) -> TestClient:
    return TestClient(api_module.create_app(Path(tmp)), raise_server_exceptions=False)


def _quiet(fn):
    with contextlib.redirect_stderr(io.StringIO()):
        return fn()


def _make_project(tmp: str) -> "project_manager.models.Project":
    return project_manager.create_project(Path(tmp) / "Demo.sbd")


def _reload(project) -> "project_manager.models.Project":
    return project_manager.open_project(project.document_path)


# ---------------------------------------------------------------------------
# Canonical save — shots.json written in the data folder
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
            shots_json_path(project.metadata_root).is_file(),
            "shots.json must exist after save_project",
        )

    def test_save_project_writes_no_shots_csv(self):
        """shots.csv is gone: save_project must not write it anywhere in the project."""
        project = _make_project(self._tmp)
        project_manager.add_shot(project)
        project_manager.save_project(project)
        self.assertEqual(list(project.project_root.rglob("shots.csv")), [])
        self.assertEqual(
            shots_json_path(project.metadata_root),
            project.project_root / ".storyboarder" / "data" / "shots.json",
        )

    def test_shots_json_contains_canonical_version_key(self):
        """shots.json must have a top-level version key (structured format)."""
        project = _make_project(self._tmp)
        project_manager.add_shot(project)
        project_manager.save_project(project)
        payload = json.loads(shots_json_path(project.metadata_root).read_text(encoding="utf-8"))
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

    def test_shots_json_round_trips_shot_ids_in_order(self):
        """shots.json must hold the in-memory shots, in order, after save_project."""
        project = _make_project(self._tmp)
        project_manager.add_shot(project)
        project_manager.add_shot(project)
        project_manager.save_project(project)

        json_shots = load_shots_json(shots_json_path(project.metadata_root))
        self.assertEqual(
            [s.shot_id for s in json_shots],
            [s.shot_id for s in project.shots],
        )
        self.assertEqual(
            [s.shot_id for s in _reload(project).shots],
            [s.shot_id for s in project.shots],
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
        json_path = shots_json_path(project.metadata_root)
        json_path.write_text("{not valid json", encoding="utf-8")

        with self.assertRaisesRegex(ValueError, r"shots\.json.*canonical shot metadata.*invalid JSON"):
            _reload(project)

    def test_container_corrupt_shots_json_raises_clear_error(self):
        project = _make_project(self._tmp)
        json_path = shots_json_path(project.metadata_root)

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
        shots_json_path(project.metadata_root).write_text(
            json.dumps({"version": 1, "shots": []}),
            encoding="utf-8",
        )

        reloaded = _reload(project)
        self.assertEqual(reloaded.shots, [])

    def test_top_level_array_shots_json_still_loads(self):
        project = _make_project(self._tmp)
        shot = Shot(shot_id="array_shot", title="Array shape")
        shots_json_path(project.metadata_root).write_text(
            json.dumps([shot.to_dict()]),
            encoding="utf-8",
        )

        reloaded = _reload(project)
        self.assertEqual([item.shot_id for item in reloaded.shots], ["array_shot"])

    def test_malformed_entry_is_skipped_but_valid_entries_load(self):
        project = _make_project(self._tmp)
        valid = Shot(shot_id="valid_shot", title="Keep me")
        shots_json_path(project.metadata_root).write_text(
            json.dumps({"version": 1, "shots": [None, {"title": "missing id"}, valid.to_dict()]}),
            encoding="utf-8",
        )

        reloaded = _reload(project)
        self.assertEqual([item.shot_id for item in reloaded.shots], ["valid_shot"])

    def test_object_without_shots_key_is_lenient_empty_list(self):
        project = _make_project(self._tmp)
        shots_json_path(project.metadata_root).write_text(json.dumps({"version": 1}), encoding="utf-8")

        reloaded = _reload(project)
        self.assertEqual(reloaded.shots, [])

    def test_corrupt_shots_json_api_open_returns_project_open_failed(self):
        project = _make_project(self._tmp)
        shots_json_path(project.metadata_root).write_text("{broken", encoding="utf-8")
        client = _make_client(self._tmp)

        response = _quiet(lambda: client.post(
            "/api/project/open",
            json={"project_json_path": str(project.document_path)},
        ))

        self.assertEqual(response.status_code, 400)
        body = response.json()
        self.assertEqual(body.get("code"), "PROJECT_OPEN_FAILED")
        self.assertIn("shots.json", body.get("detail", ""))

    def test_background_refresh_keeps_in_memory_project_when_disk_json_is_corrupt(self):
        client = _make_client(self._tmp)
        created = _quiet(lambda: client.post("/api/project/new", json={"path": str(Path(self._tmp) / "Demo.sbd")}))
        self.assertEqual(created.status_code, 200)
        added = _quiet(lambda: client.post("/api/shots", json={}))
        self.assertEqual(added.status_code, 200)
        before = added.json()
        shot_id = before["shot"]["shot_id"]
        project_root = Path(before["project_path"]).parent
        json_path = shots_json_path(project_root / ".storyboarder" / "data")
        json_path.write_text("{transiently broken", encoding="utf-8")
        future = time.time() + 2.0
        os.utime(json_path, (future, future))

        response = _quiet(lambda: client.get("/api/project"))

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn(shot_id, {shot["shot_id"] for shot in body["shots"]})


# ---------------------------------------------------------------------------
# save_shots_json — the canonical writer
# ---------------------------------------------------------------------------

class TestSaveShotsEntryPoint(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_save_shots_json_writes_only_json(self):
        """save_shots_json() writes shots.json and no CSV snapshot."""
        root = Path(self._tmp) / "data"
        root.mkdir()
        shots = [Shot(shot_id="shot_001"), Shot(shot_id="shot_002")]
        save_shots_json(root, shots)
        self.assertTrue(shots_json_path(root).is_file(), "shots.json missing after save_shots_json")
        self.assertEqual(sorted(path.name for path in root.iterdir()), ["shots.json"])
        self.assertEqual(
            [s.shot_id for s in load_shots_json(shots_json_path(root))],
            ["shot_001", "shot_002"],
        )

    def test_save_shots_json_returns_json_path(self):
        """save_shots_json() must return the path to shots.json."""
        root = Path(self._tmp) / "data"
        root.mkdir()
        result = save_shots_json(root, [Shot(shot_id="shot_001")])
        self.assertEqual(result, shots_json_path(root))

    def test_save_shots_json_is_atomic(self):
        """save_shots_json must leave no .tmp file after a successful write."""
        root = Path(self._tmp) / "data"
        root.mkdir()
        save_shots_json(root, [Shot(shot_id="shot_a")])
        tmp_files = list(root.glob("*.tmp"))
        self.assertEqual(tmp_files, [], "Stale .tmp file found after save_shots_json — not atomic")


# ---------------------------------------------------------------------------
# Annotation persistence
# ---------------------------------------------------------------------------

class TestAnnotationPersistence(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.client = _make_client(self._tmp)
        created = _quiet(lambda: self.client.post("/api/project/new", json={"path": str(Path(self._tmp) / "Demo.sbd")}))
        self.assertEqual(created.status_code, 200)
        added = _quiet(lambda: self.client.post("/api/shots", json={}))
        self.assertEqual(added.status_code, 200)
        body = added.json()
        self.shot_id = body["shot"]["shot_id"]
        self.document_path = Path(body["project_path"])
        self.project_root = self.document_path.parent

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _annotation_path(self) -> Path:
        project = project_manager.open_project(self.document_path)
        shot = next(item for item in project.shots if item.shot_id == self.shot_id)
        path = self.project_root / shot.annotation_path
        self.assertEqual(
            path,
            self.project_root / ".storyboarder" / "data" / "annotations" / f"{self.shot_id}.json",
        )
        return path

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

    def test_save_annotations_normalizes_known_shapes(self):
        payload = [
            {"type": "arrow", "start": {"x": -0.5, "y": 0.2}, "end": {"x": 1.7, "y": 0.4}, "color": "#ff4d2e"},
            {"type": "box", "start": {"x": "bad"}, "end": {"x": 0.1, "y": 0.1}},
            {"type": "text", "start": {"x": 0.5, "y": 0.5}, "text": "  " + "x" * 600, "color": "red"},
            {"type": "legacy", "points": [[1, 2]]},
        ]

        response = _quiet(lambda: self.client.put(
            f"/api/shots/{self.shot_id}/annotations",
            json={"annotations": payload},
        ))

        self.assertEqual(response.status_code, 200)
        saved = response.json()["annotations"]
        self.assertEqual(len(saved), 3)
        self.assertEqual(saved[0]["start"], {"x": 0.0, "y": 0.2})
        self.assertEqual(saved[0]["end"], {"x": 1.0, "y": 0.4})
        self.assertEqual(saved[0]["color"], "#ff4d2e")
        self.assertEqual(saved[1]["type"], "text")
        self.assertEqual(saved[1]["end"], {"x": 0.5, "y": 0.5})
        self.assertEqual(len(saved[1]["text"]), 500)
        self.assertNotIn("color", saved[1])
        self.assertEqual(saved[2], {"type": "legacy", "points": [[1, 2]]})

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

    def test_relink_preview_rejects_codex_layer_filename(self):
        project = _make_project(self._tmp)
        shot = project_manager.add_shot(project)
        shot_dir = project_manager.get_shot_dir(project, shot)
        codex_file = shot_dir / codex_layer_filename(shot.shot_id)
        codex_file.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8)
        codex_rel = codex_file.relative_to(project.root_path).as_posix()

        with self.assertRaises(ValueError, msg="Codex layer must be rejected as artist preview"):
            project_manager.relink_preview_image(project, shot, codex_rel)

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


def test_atomic_write_retries_a_replace_blocked_by_a_reader(tmp_path, monkeypatch) -> None:
    from storyboard_tool import project_storage

    real_replace = project_storage.os.replace
    calls = {"n": 0}

    def flaky_replace(source, destination):
        calls["n"] += 1
        if calls["n"] < 3:
            raise PermissionError(5, "Access is denied")
        return real_replace(source, destination)

    monkeypatch.setattr(project_storage.os, "replace", flaky_replace)
    target = tmp_path / "record.json"
    project_storage.atomic_write_json(target, {"ok": True})
    assert calls["n"] == 3
    assert target.read_text(encoding="utf-8").strip().endswith("}")
    assert not list(tmp_path.glob("*.tmp"))
