#!/usr/bin/env python3
"""Call one Storyboarder MCP tool from the shell (for agents without MCP loaded).

Usage:
    python scripts/mcp_call.py --list
    python scripts/mcp_call.py storyboard_status
    python scripts/mcp_call.py storyboard_update_board --args '{"shot_id": "shot_1", "title": "Open"}'
    python scripts/mcp_call.py storyboard_grid --save-images-dir out/

Starts ``python -m storyboard_tool.mcp_server`` over stdio, sends initialize and
one tools/call, prints text content, and saves image content as files (printing
their paths). Exits 1 when the tool reports an error.
"""
from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def utf8_console() -> None:
    """Print board titles etc. on any console: a cp1252 Windows console cannot encode them."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def _rpc(proc: subprocess.Popen, message: dict) -> dict | None:
    assert proc.stdin and proc.stdout
    proc.stdin.write(json.dumps(message) + "\n")
    proc.stdin.flush()
    if "id" not in message:
        return None
    line = proc.stdout.readline()
    if not line:
        raise SystemExit("The MCP server exited without answering.")
    return json.loads(line)


def main(argv: list[str] | None = None) -> int:
    utf8_console()
    parser =argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("tool", nargs="?", help="Tool name, e.g. storyboard_outline.")
    parser.add_argument("--args", default="{}", help="Tool arguments as a JSON object, or @file.json.")
    parser.add_argument("--list", action="store_true", help="List the tools and their input schemas.")
    parser.add_argument("--save-images-dir", default="", help="Directory for image results (default: current directory).")
    parser.add_argument("--bridge-file", default="", help="Override the live-bridge file the server reads.")
    options = parser.parse_args(argv)
    if not options.list and not options.tool:
        parser.error("give a tool name or --list")

    raw_args = options.args
    if raw_args.startswith("@"):
        raw_args = Path(raw_args[1:]).read_text(encoding="utf-8")
    arguments = json.loads(raw_args)
    if not isinstance(arguments, dict):
        parser.error("--args must be a JSON object")

    command = [sys.executable, "-m", "storyboard_tool.mcp_server"]
    if options.bridge_file:
        command += ["--bridge-file", options.bridge_file]
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(filter(None, [str(ROOT), os.environ.get("PYTHONPATH", "")]))}
    proc = subprocess.Popen(
        command, cwd=ROOT, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        text=True, encoding="utf-8", bufsize=1,
    )
    try:
        _rpc(proc, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                               "clientInfo": {"name": "mcp_call", "version": "1"}}})
        _rpc(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"})
        if options.list:
            tools = (_rpc(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}) or {})["result"]["tools"]
            for tool in tools:
                print(f"{tool['name']}\n  {tool['description']}\n  args: {json.dumps(tool['inputSchema'].get('properties', {}))}\n")
            return 0
        response = _rpc(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                               "params": {"name": options.tool, "arguments": arguments}}) or {}
    finally:
        if proc.stdin:
            proc.stdin.close()
        proc.wait(timeout=10)

    if "error" in response:
        print(json.dumps(response["error"], indent=2), file=sys.stderr)
        return 1
    result = response["result"]
    out_dir = Path(options.save_images_dir or ".")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    image_count = 0
    for block in result.get("content", []):
        if block.get("type") == "text":
            print(block["text"])
        elif block.get("type") == "image":
            out_dir.mkdir(parents=True, exist_ok=True)
            suffix = mimetypes.guess_extension(block.get("mimeType", "image/png")) or ".png"
            image_count += 1
            path = out_dir / f"{options.tool}_{stamp}_{image_count}{suffix}"
            path.write_bytes(base64.b64decode(block["data"]))
            print(f"[image saved] {path.resolve()}")
    return 1 if result.get("isError") else 0


if __name__ == "__main__":
    raise SystemExit(main())
