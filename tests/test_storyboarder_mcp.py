from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from storyboard_tool import generation_service, mcp_server, session_store
from storyboard_tool.models import Project, Shot


class TestStoryboarderMcp(unittest.TestCase):
    def test_live_bridge_project_takes_priority_over_saved_document_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            unpacked = base / "active" / "project.json"
            unpacked.parent.mkdir()
            unpacked.write_text("{}", encoding="utf-8")
            document = base / "Untitled.sbd"
            document.write_bytes(b"not opened")
            session_store.write_session(base, {"last_project_json_path": str(document)})
            bridge_path = base / "Sessions" / "storyboard_live_bridge.json"
            bridge_path.write_text(
                '{"app_running": true, "project_json_path": ' + json.dumps(str(unpacked)) + '}',
                encoding="utf-8",
            )

            self.assertEqual(mcp_server.resolve_project_json(session_base=base), unpacked.resolve())

    def test_initialize_and_tool_catalog_follow_stdio_mcp_contract(self) -> None:
        initialized = mcp_server.handle_message(
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
            session_base=Path.cwd(),
        )
        self.assertEqual(initialized["result"]["protocolVersion"], "2025-06-18")  # type: ignore[index]
        self.assertIn("tools", initialized["result"]["capabilities"])  # type: ignore[index]
        listed = mcp_server.handle_message(
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            session_base=Path.cwd(),
        )
        names = {item["name"] for item in listed["result"]["tools"]}  # type: ignore[index]
        self.assertEqual(names, {
            "storyboard_list_generation_requests",
            "storyboard_get_generation_request",
            "storyboard_submit_generation_result",
        })

    def test_tools_list_fetch_and_submit_without_mutating_shot_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Project(
                root_path=Path(tmp),
                shots=[Shot(shot_id="shot_1", description="A lone figure crosses the bridge")],
                settings={"canvas_width": 1600, "canvas_height": 900},
            )
            request = generation_service.create_request(project, project.shots[0], "codex")
            source = Path(tmp) / "generated.png"
            Image.new("RGB", (16, 9), (1, 2, 3)).save(source)
            with patch("storyboard_tool.mcp_server._project", return_value=project):
                rows = mcp_server.dispatch_tool(
                    "storyboard_list_generation_requests",
                    {},
                    session_base=Path(tmp),
                )
                fetched = mcp_server.dispatch_tool(
                    "storyboard_get_generation_request",
                    {"request_id": request["request_id"]},
                    session_base=Path(tmp),
                )
                submitted = mcp_server.dispatch_tool(
                    "storyboard_submit_generation_result",
                    {"request_id": request["request_id"], "artifact_paths": [str(source)]},
                    session_base=Path(tmp),
                )
            self.assertEqual(rows["requests"][0]["request_id"], request["request_id"])
            self.assertEqual(fetched["shot_id"], "shot_1")
            self.assertTrue(submitted["result"]["artifacts"][0]["project_relative_path"].startswith("generation/"))
            self.assertEqual(project.shots[0].generation_state["execution_status"], "idle")


if __name__ == "__main__":
    unittest.main()
