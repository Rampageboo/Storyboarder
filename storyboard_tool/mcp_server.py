"""Minimal STDIO MCP server exposing Storyboarder generation handoffs."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import generation_service, project_manager, session_store

SERVER_NAME = "storyboarder"
SERVER_VERSION = "0.1.0"
SUPPORTED_PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")


TOOLS: list[dict[str, Any]] = [
    {
        "name": "storyboard_list_generation_requests",
        "description": "List immutable Storyboarder generation requests, normally Codex handoffs waiting for work.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "shot_id": {"type": "string", "description": "Optional shot id filter."},
                "destination": {
                    "type": "string",
                    "enum": ["codex", "queue"],
                    "default": "codex",
                },
                "status": {
                    "type": "string",
                    "enum": ["queued", "needs-review", "completed", "failed", "cancelled"],
                },
            },
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
    },
    {
        "name": "storyboard_get_generation_request",
        "description": "Fetch one complete Storyboarder shot generation package by request id.",
        "inputSchema": {
            "type": "object",
            "properties": {"request_id": {"type": "string"}},
            "required": ["request_id"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
    },
    {
        "name": "storyboard_submit_generation_result",
        "description": (
            "Copy generated storyboard image files into the project and signal Storyboarder to import the result. "
            "The deposited result is durable and will be recovered after a Storyboarder restart; this never edits "
            "shots.json directly."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "request_id": {"type": "string"},
                "artifact_paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                    "maxItems": generation_service.MAX_ARTIFACTS,
                },
                "summary": {"type": "string"},
            },
            "required": ["request_id", "artifact_paths"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False},
    },
]


def resolve_project_json(*, session_base: Path, explicit_project: str = "") -> Path:
    raw = str(explicit_project or "").strip()
    if raw:
        candidate = Path(raw).expanduser()
        if candidate.is_dir():
            candidate = candidate / "project.json"
    else:
        candidate = _live_project_json(session_base)
        if candidate is None:
            session = session_store.read_session(session_base)
            candidate = Path(str(session.get("last_project_json_path") or "")).expanduser()
    if not str(candidate) or not candidate.is_file():
        raise ValueError("No active Storyboarder project. Open a project in Storyboarder and try again.")
    return candidate.resolve()


def _live_project_json(session_base: Path) -> Path | None:
    """Return the running desktop app's working project, including unpacked .sbd files."""
    bridge_path = session_base / "Sessions" / "storyboard_live_bridge.json"
    try:
        bridge = json.loads(bridge_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(bridge, dict) or not bridge.get("app_running"):
        return None
    candidate = Path(str(bridge.get("project_json_path") or "")).expanduser()
    return candidate if candidate.is_file() else None


def _project(session_base: Path, explicit_project: str = ""):
    return project_manager.open_project(resolve_project_json(session_base=session_base, explicit_project=explicit_project))


def dispatch_tool(
    name: str,
    arguments: dict[str, Any],
    *,
    session_base: Path,
    explicit_project: str = "",
) -> dict[str, Any]:
    project = _project(session_base, explicit_project)
    if name == "storyboard_list_generation_requests":
        destination = str(arguments.get("destination") or "codex")
        rows = generation_service.list_requests(
            project,
            shot_id=str(arguments.get("shot_id") or ""),
            destination=destination,
            status=str(arguments.get("status") or ""),
        )
        return {"project": project.name, "requests": rows}
    if name == "storyboard_get_generation_request":
        return generation_service.get_request(project, str(arguments.get("request_id") or ""))
    if name == "storyboard_submit_generation_result":
        paths = arguments.get("artifact_paths")
        if not isinstance(paths, list):
            raise ValueError("artifact_paths must be a list of image paths.")
        result = generation_service.submit_result(
            project,
            str(arguments.get("request_id") or ""),
            [str(path) for path in paths],
            summary=str(arguments.get("summary") or ""),
        )
        return {
            "result": result,
            "next_step": "Storyboarder has been signaled to import this candidate into the matching shot.",
        }
    raise ValueError(f"Unknown tool: {name}")


def _text_result(value: Any, *, is_error: bool = False) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False, indent=2)}],
        "isError": is_error,
    }


def handle_message(
    message: dict[str, Any],
    *,
    session_base: Path,
    explicit_project: str = "",
) -> dict[str, Any] | None:
    method = str(message.get("method") or "")
    request_id = message.get("id")
    if request_id is None:
        return None
    if method == "initialize":
        requested = str((message.get("params") or {}).get("protocolVersion") or "")
        protocol = requested if requested in SUPPORTED_PROTOCOLS else SUPPORTED_PROTOCOLS[0]
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": protocol,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                "instructions": (
                    "Storyboarder owns queue, retries, review, and approval. Read immutable generation requests with "
                    "the list/get tools. Submit only generated image artifacts with the submit tool. Never edit shots.json "
                    "or generation request files directly."
                ),
            },
        }
    if method == "ping":
        return {"jsonrpc": "2.0", "id": request_id, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": TOOLS}}
    if method == "tools/call":
        params = message.get("params") if isinstance(message.get("params"), dict) else {}
        name = str(params.get("name") or "")
        arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
        try:
            value = dispatch_tool(
                name,
                arguments,
                session_base=session_base,
                explicit_project=explicit_project,
            )
            result = _text_result(value)
        except (OSError, ValueError) as exc:
            result = _text_result({"error": str(exc)}, is_error=True)
        return {"jsonrpc": "2.0", "id": request_id, "result": result}
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Storyboarder MCP server")
    parser.add_argument("--session-base", default=".", help="Directory containing the Storyboarder Sessions folder.")
    parser.add_argument("--project", default="", help="Optional explicit project root or project.json path.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    session_base = Path(args.session_base).expanduser().resolve()
    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
            if not isinstance(message, dict):
                raise ValueError("JSON-RPC message must be an object.")
            response = handle_message(
                message,
                session_base=session_base,
                explicit_project=str(args.project or ""),
            )
        except (json.JSONDecodeError, ValueError) as exc:
            response = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": str(exc)},
            }
        if response is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
