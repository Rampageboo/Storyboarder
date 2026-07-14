from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from storyboard_tool.models import Shot
from storyboard_tool.schemas import ShotUpdateRequest
from storyboard_tool.shot_store import load_shots_json, save_shots_json


class TestGenerationAuthoringCompatibility(unittest.TestCase):
    def test_legacy_shot_receives_safe_generation_defaults(self) -> None:
        shot = Shot.from_dict({"shot_id": "legacy", "title": "Old project"})
        self.assertEqual(shot.prompt_config["mode"], "auto")
        self.assertEqual(shot.continuity["mode"], "continuous")
        self.assertEqual(shot.generation_state["execution_status"], "idle")
        self.assertEqual(shot.shot_design["story_beat"], "")

    def test_missing_new_api_fields_remain_none_for_legacy_clients(self) -> None:
        request = ShotUpdateRequest(title="Legacy update")
        payload = request.model_dump()
        self.assertIsNone(payload["shot_design"])
        self.assertIsNone(payload["prompt_config"])
        self.assertIsNone(payload["continuity"])

    def test_generation_authoring_records_round_trip_through_canonical_json(self) -> None:
        shot = Shot(shot_id="shot_1")
        shot.shot_design["story_beat"] = "A door opens"
        shot.prompt_config.update({"mode": "manual", "manual_prompt": "Rough storyboard frame"})
        shot.continuity.update({"expected_out": "Door is open", "resolved_out": "Door remains closed"})
        shot.generation_state.update({"execution_status": "succeeded", "active_output_id": "output_1"})

        with tempfile.TemporaryDirectory() as tmp:
            path = save_shots_json(Path(tmp), [shot])
            loaded = load_shots_json(path)

        self.assertIsNotNone(loaded)
        restored = loaded[0]  # type: ignore[index]
        self.assertEqual(restored.shot_design["story_beat"], "A door opens")
        self.assertEqual(restored.prompt_config["manual_prompt"], "Rough storyboard frame")
        self.assertEqual(restored.continuity["expected_out"], "Door is open")
        self.assertEqual(restored.continuity["resolved_out"], "Door remains closed")
        self.assertEqual(restored.generation_state["active_output_id"], "output_1")

    def test_invalid_generation_enums_and_variant_count_are_normalized(self) -> None:
        shot = Shot.from_dict({
            "shot_id": "invalid",
            "prompt_config": {"mode": "surprise", "variant_count": 0},
            "continuity": {"mode": "teleport"},
            "generation_state": {
                "execution_status": "unknown",
                "review_status": "maybe",
                "freshness_status": "ancient",
            },
        })
        self.assertEqual(shot.prompt_config["mode"], "auto")
        self.assertEqual(shot.prompt_config["variant_count"], 1)
        self.assertEqual(shot.continuity["mode"], "continuous")
        self.assertEqual(shot.generation_state["execution_status"], "idle")
        self.assertEqual(shot.generation_state["review_status"], "unreviewed")
        self.assertEqual(shot.generation_state["freshness_status"], "current")


if __name__ == "__main__":
    unittest.main()
