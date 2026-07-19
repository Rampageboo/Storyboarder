from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
import warnings
from pathlib import Path

from PIL import Image

with warnings.catch_warnings():
    warnings.filterwarnings("ignore", message="Using `httpx` with `starlette.testclient` is deprecated")
    from fastapi.testclient import TestClient

from storyboard_tool import api as api_module
from storyboard_tool import export_utils, generation_service, project_manager


def _quiet(call):
    with contextlib.redirect_stderr(io.StringIO()):
        return call()


class TestGenerationRequests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.client = TestClient(api_module.create_app(self.base), raise_server_exceptions=False)
        created = _quiet(lambda: self.client.post("/api/project/new", json={"path": str(self.base)}))
        self.assertEqual(created.status_code, 200, created.text)
        added = _quiet(lambda: self.client.post("/api/shots", json={}))
        self.assertEqual(added.status_code, 200, added.text)
        self.shot_id = added.json()["shot"]["shot_id"]
        self.project_root = Path(added.json()["project_path"])

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_send_to_queue_creates_immutable_snapshot_and_updates_shot_state(self) -> None:
        updated = _quiet(lambda: self.client.patch(
            f"/api/shots/{self.shot_id}",
            json={
                "description": "A detective enters the archive",
                "action_note": "A detective enters the archive",
                "camera_note": "Keep the detective framed against the doorway",
                "shot_design": {"shot_size": "wide", "camera_height": "eye level"},
                "prompt_config": {"mode": "auto", "variant_count": 2},
            },
        ))
        self.assertEqual(updated.status_code, 200, updated.text)

        response = _quiet(lambda: self.client.post(
            f"/api/shots/{self.shot_id}/generation-requests",
            json={"destination": "queue"},
        ))
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        request = body["request"]
        self.assertEqual(request["destination"], "queue")
        self.assertEqual(request["shot"]["description"], "A detective enters the archive")
        self.assertEqual(request["prompt"]["variant_count"], 2)
        self.assertIn("Shot size: wide", request["prompt"]["compiled_prompt"])
        self.assertIn(
            "Camera note: Keep the detective framed against the doorway",
            request["prompt"]["compiled_prompt"],
        )
        self.assertNotIn("Action: A detective enters the archive", request["prompt"]["compiled_prompt"])
        request_path = self.project_root / "generation" / "requests" / f"{request['request_id']}.json"
        self.assertTrue(request_path.is_file())
        shot = next(item for item in body["project"]["shots"] if item["shot_id"] == self.shot_id)
        self.assertEqual(shot["generation_state"]["execution_status"], "queued")
        self.assertEqual(shot["generation_state"]["latest_attempt_id"], request["request_id"])

        listed = self.client.get("/api/generation/requests", params={"shot_id": self.shot_id})
        self.assertEqual(listed.status_code, 200)
        self.assertEqual([item["request_id"] for item in listed.json()["requests"]], [request["request_id"]])

    def test_send_to_codex_returns_copyable_handoff_prompt(self) -> None:
        response = _quiet(lambda: self.client.post(
            f"/api/shots/{self.shot_id}/generation-requests",
            json={"destination": "codex"},
        ))
        self.assertEqual(response.status_code, 200, response.text)
        request_id = response.json()["request"]["request_id"]
        self.assertIn(request_id, response.json()["codex_prompt"])
        self.assertIn("Storyboarder MCP", response.json()["codex_prompt"])

    def test_scene_character_and_shot_prompts_compile_in_fixed_layers(self) -> None:
        scene_response = _quiet(lambda: self.client.post(
            "/api/project/scenes2d",
            json={
                "title": "Archive interior",
                "environment_prompt": "A narrow municipal archive with dark green steel shelving and cold fluorescent light.",
                "consistency_anchors": [
                    "The security door remains on the north wall",
                    "Shelving remains dark green",
                ],
            },
        ))
        self.assertEqual(scene_response.status_code, 200, scene_response.text)
        scene = scene_response.json()["scene"]
        settings = _quiet(lambda: self.client.patch(
            "/api/project/settings",
            json={
                "character_bible_prompt": (
                    "MAYA — short black bob, amber wool coat, silver watch; preserve face, hair, and wardrobe."
                ),
            },
        ))
        self.assertEqual(settings.status_code, 200, settings.text)
        updated = _quiet(lambda: self.client.patch(
            f"/api/shots/{self.shot_id}",
            json={
                "scene": scene["title"],
                "scene_id": scene["id"],
                "description": "Maya searches the third shelf",
                "character_note": "Maya is visible, tense, reaching upward",
                "camera_note": "Medium profile from the aisle",
            },
        ))
        self.assertEqual(updated.status_code, 200, updated.text)

        queued = _quiet(lambda: self.client.post(
            f"/api/shots/{self.shot_id}/generation-requests",
            json={"destination": "codex"},
        ))
        self.assertEqual(queued.status_code, 200, queued.text)
        request = queued.json()["request"]
        self.assertEqual(request["shot"]["scene_id"], scene["id"])
        self.assertEqual(request["scene_bible"]["scene_id"], scene["id"])
        self.assertEqual(request["scene_bible"]["consistency_anchors"], scene["consistency_anchors"])
        self.assertIn("MAYA", request["character_bible"]["prompt"])
        self.assertTrue(request["consistency_revision"])
        scene_reference = next(item for item in request["references"] if item["role"] == "scene-environment")
        self.assertEqual(scene_reference["project_relative_path"], scene["preview_image_path"])
        compiled = request["prompt"]["compiled_prompt"]
        self.assertLess(compiled.index("SCENE BIBLE"), compiled.index("CHARACTER BIBLE"))
        self.assertLess(compiled.index("CHARACTER BIBLE"), compiled.index("SHOT OVERRIDE"))
        self.assertIn("Environment: A narrow municipal archive", compiled)
        self.assertIn("Story beat: Maya searches the third shelf", compiled)
        self.assertEqual(request["prompt"]["layers"]["scene"], scene["environment_prompt"])

    def test_manual_prompt_remains_a_shot_override_below_consistency_bibles(self) -> None:
        scene = self.client.post(
            "/api/project/scenes2d",
            json={"title": "Station", "environment_prompt": "A fixed tiled railway platform at blue hour."},
        ).json()["scene"]
        self.client.patch(
            "/api/project/settings",
            json={"character_bible_prompt": "NOAH — shaved head, red scarf, charcoal coat."},
        )
        self.client.patch(
            f"/api/shots/{self.shot_id}",
            json={
                "scene": scene["title"],
                "scene_id": scene["id"],
                "prompt_config": {"mode": "manual", "manual_prompt": "Extreme close-up as Noah looks left."},
            },
        )
        request = self.client.post(
            f"/api/shots/{self.shot_id}/generation-requests",
            json={"destination": "queue"},
        ).json()["request"]
        compiled = request["prompt"]["compiled_prompt"]
        self.assertIn("SCENE BIBLE", compiled)
        self.assertIn("CHARACTER BIBLE", compiled)
        self.assertIn("SHOT OVERRIDE", compiled)
        self.assertIn("Extreme close-up as Noah looks left.", compiled)

    def test_scene_and_character_bible_changes_mark_existing_generation_stale(self) -> None:
        scene = self.client.post(
            "/api/project/scenes2d",
            json={"title": "Kitchen", "environment_prompt": "A compact blue kitchen."},
        ).json()["scene"]
        self.client.patch(
            f"/api/shots/{self.shot_id}",
            json={"scene": scene["title"], "scene_id": scene["id"], "description": "A cook enters."},
        )
        self.client.post(
            f"/api/shots/{self.shot_id}/generation-requests",
            json={"destination": "queue"},
        )

        changed_scene = self.client.patch(
            f"/api/project/scenes2d/{scene['id']}",
            json={"environment_prompt": "A compact blue kitchen with a fixed copper range."},
        )
        self.assertEqual(changed_scene.status_code, 200, changed_scene.text)
        project_after_scene = self.client.get("/api/project").json()
        shot_after_scene = next(item for item in project_after_scene["shots"] if item["shot_id"] == self.shot_id)
        self.assertEqual(shot_after_scene["generation_state"]["freshness_status"], "stale")

        self.client.post(
            f"/api/shots/{self.shot_id}/generation-requests",
            json={"destination": "queue"},
        )
        changed_characters = self.client.patch(
            "/api/project/settings",
            json={"character_bible_prompt": "CHEF — white jacket, blue apron, round glasses."},
        )
        self.assertEqual(changed_characters.status_code, 200, changed_characters.text)
        shot_after_characters = next(
            item for item in changed_characters.json()["shots"] if item["shot_id"] == self.shot_id
        )
        self.assertEqual(shot_after_characters["generation_state"]["freshness_status"], "stale")

    def test_invalid_destination_is_rejected_without_writing_request(self) -> None:
        response = _quiet(lambda: self.client.post(
            f"/api/shots/{self.shot_id}/generation-requests",
            json={"destination": "unknown"},
        ))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "GENERATION_REQUEST_FAILED")
        request_dir = self.project_root / "generation" / "requests"
        self.assertFalse(request_dir.exists() and any(request_dir.iterdir()))

    def test_reconcile_imports_mcp_result_as_needs_review(self) -> None:
        queued = self.client.post(
            f"/api/shots/{self.shot_id}/generation-requests",
            json={"destination": "codex"},
        )
        request_id = queued.json()["request"]["request_id"]
        request_path = self.project_root / "generation" / "requests" / f"{request_id}.json"
        original_snapshot = request_path.read_bytes()
        source = self.base / "candidate.png"
        Image.new("RGB", (32, 18), (10, 20, 30)).save(source)
        project = project_manager.open_project(self.project_root / "project.json")
        result = generation_service.submit_result(project, request_id, [str(source)], summary="First pass")

        reconciled = _quiet(lambda: self.client.post("/api/generation/reconcile"))
        self.assertEqual(reconciled.status_code, 200, reconciled.text)
        body = reconciled.json()
        self.assertIn(request_id, body["updated_request_ids"])
        shot = next(item for item in body["project"]["shots"] if item["shot_id"] == self.shot_id)
        self.assertEqual(shot["generation_state"]["execution_status"], "succeeded")
        self.assertEqual(shot["generation_state"]["review_status"], "needs-review")
        self.assertEqual(shot["generation_state"]["active_output_id"], result["result_id"])
        latest = next(item for item in body["requests"] if item["request_id"] == request_id)
        self.assertEqual(latest["status"], "needs-review")
        artifact = self.project_root / result["artifacts"][0]["project_relative_path"]
        self.assertTrue(artifact.is_file())
        self.assertEqual(request_path.read_bytes(), original_snapshot)

    def test_accept_candidate_creates_separate_codex_layer_and_preserves_artist_preview(self) -> None:
        artwork = io.BytesIO()
        Image.new("RGBA", (32, 18), (220, 30, 40, 128)).save(artwork, "PNG")
        uploaded = self.client.post(
            f"/api/shots/{self.shot_id}/image",
            files={"file": ("artwork.png", artwork.getvalue(), "image/png")},
        )
        self.assertEqual(uploaded.status_code, 200, uploaded.text)
        uploaded_shot = next(item for item in uploaded.json()["shots"] if item["shot_id"] == self.shot_id)
        preview = self.project_root / uploaded_shot["preview_image_path"]
        original_preview = preview.read_bytes()

        queued = self.client.post(
            f"/api/shots/{self.shot_id}/generation-requests",
            json={"destination": "codex"},
        )
        request_id = queued.json()["request"]["request_id"]
        source = self.base / "codex-candidate.png"
        Image.new("RGB", (32, 18), (10, 80, 180)).save(source)
        project = project_manager.open_project(self.project_root / "project.json")
        result = generation_service.submit_result(project, request_id, [str(source)])
        artifact_path = result["artifacts"][0]["project_relative_path"]

        accepted = _quiet(lambda: self.client.post(
            f"/api/shots/{self.shot_id}/codex-layer/accept",
            json={
                "request_id": request_id,
                "result_id": result["result_id"],
                "artifact_path": artifact_path,
            },
        ))
        self.assertEqual(accepted.status_code, 200, accepted.text)
        shot = next(item for item in accepted.json()["project"]["shots"] if item["shot_id"] == self.shot_id)
        self.assertTrue(shot["has_codex_layer"])
        self.assertEqual(shot["generation_state"]["review_status"], "accepted")
        self.assertEqual(shot["generation_state"]["approved_output_id"], result["result_id"])
        self.assertEqual(preview.read_bytes(), original_preview)
        codex_path = self.project_root / "shots" / self.shot_id / f"{self.shot_id}_codex.png"
        self.assertTrue(codex_path.is_file())
        exported_dir = export_utils.export_image_sequence(
            project_manager.open_project(self.project_root / "project.json"),
            self.project_root / "exports" / "layer-test",
        )
        with Image.open(exported_dir / f"0001_{self.shot_id}.png") as composite:
            center = composite.convert("RGB").getpixel((composite.width // 2, composite.height // 2))
        self.assertNotEqual(center, (10, 80, 180), "artist artwork must be composited above Codex")
        self.assertNotEqual(center, (220, 30, 40), "Codex must remain visible below translucent artwork")

        removed = self.client.delete(f"/api/shots/{self.shot_id}/layers/codex")
        self.assertEqual(removed.status_code, 200, removed.text)
        removed_shot = next(item for item in removed.json()["shots"] if item["shot_id"] == self.shot_id)
        self.assertFalse(removed_shot["has_codex_layer"])
        self.assertEqual(removed_shot["generation_state"]["approved_output_id"], "")
        self.assertEqual(preview.read_bytes(), original_preview)


if __name__ == "__main__":
    unittest.main()
