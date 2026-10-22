"""The MCP server is an HTTP client of the running app (plan 2026-10-23, decision 1).

Existing endpoints are exercised against a real ``create_app`` backend through a
TestClient-backed transport; endpoints still being built are checked for the HTTP
request the server sends, through a recording transport.
"""
from __future__ import annotations

import base64
import io
import json
import socket
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from storyboard_tool import comfy_cloud, live_bridge, mcp_server
from storyboard_tool.api import create_app
from storyboard_tool.mcp_server import HttpResponse, StoryboarderClient

TOKEN = "mcp-test-token"


def _rpc(client: StoryboarderClient, method: str, params: dict | None = None, request_id: int = 1) -> dict:
    message = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}}
    response = mcp_server.handle_message(message, client=client)
    assert response is not None and "error" not in response, response
    return response["result"]


def _call(client: StoryboarderClient, name: str, **arguments) -> dict:
    return _rpc(client, "tools/call", {"name": name, "arguments": arguments})


def _value(result: dict) -> dict:
    assert result["isError"] is False, result
    return json.loads(result["content"][-1]["text"])


def _error(result: dict) -> str:
    assert result["isError"] is True, result
    return json.loads(result["content"][0]["text"])["error"]


def _write_bridge(path: Path, port: int = 59999, token: str = TOKEN) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "app_running": True,
        "port": port,
        "api_token": token,
        "bridge_url": f"http://127.0.0.1:{port}/api/bridge/live",
    }), encoding="utf-8")


@pytest.fixture
def bridge_file(tmp_path, monkeypatch) -> Path:
    path = tmp_path / "bridge" / "storyboard_live_bridge.json"
    monkeypatch.setattr(live_bridge, "global_bridge_file_path", lambda: path)
    monkeypatch.setattr(live_bridge, "shared_bridge_file_path", lambda: tmp_path / "bridge" / "shared.json")
    return path


@pytest.fixture
def backend(tmp_path, monkeypatch, bridge_file):
    """A real backend with an open project, reached through a TestClient transport."""
    monkeypatch.setenv("STORYBOARDER_LAUNCH_TOKEN", TOKEN)
    monkeypatch.setattr(comfy_cloud, "get_api_key", lambda: "")
    http = TestClient(create_app(tmp_path / "app"), raise_server_exceptions=False)
    opened = http.post("/api/project/new", json={"path": str(tmp_path / "Demo.sbd")}, headers={"x-storyboarder-token": TOKEN})
    assert opened.status_code == 200, opened.text
    # The backend publishes its own bridge file too; ours is written last and wins.
    _write_bridge(bridge_file)

    def transport(method, url, headers, body, timeout):
        parts = urlsplit(url)
        target = parts.path + (f"?{parts.query}" if parts.query else "")
        response = http.request(method, target, headers=headers, content=body)
        return HttpResponse(response.status_code, response.headers.get("content-type", ""), response.content)

    return http, StoryboarderClient(transport=transport)


def _png(path: Path, size=(320, 180), color=(200, 120, 40)) -> Path:
    Image.new("RGB", size, color).save(path)
    return path


def _decoded_image(block: dict) -> Image.Image:
    assert block["type"] == "image" and block["mimeType"] == "image/png"
    return Image.open(io.BytesIO(base64.b64decode(block["data"])))


# ── protocol ─────────────────────────────────────────────────────────────────

def test_initialize_and_tool_catalog() -> None:
    client = StoryboarderClient(transport=lambda *a: pytest.fail("no HTTP during listing"))
    initialized = _rpc(client, "initialize", {"protocolVersion": "2025-06-18"})
    assert initialized["protocolVersion"] == "2025-06-18"
    assert "tools" in initialized["capabilities"]

    tools = _rpc(client, "tools/list")["tools"]
    names = {tool["name"] for tool in tools}
    assert names == {
        "storyboard_status", "storyboard_outline", "storyboard_grid", "storyboard_board_image",
        "storyboard_add_board", "storyboard_update_board", "storyboard_delete_board",
        "storyboard_reorder_boards", "storyboard_set_board_image", "storyboard_generate_image",
        "storyboard_image_jobs", "storyboard_image_candidate", "storyboard_apply_image",
        "storyboard_generate_video", "storyboard_video_takes", "storyboard_render_sequence",
        "storyboard_list_generation_requests", "storyboard_get_generation_request",
        "storyboard_submit_generation_result",
        "storyboard_new_project", "storyboard_open_project", "storyboard_recent_projects",
        "storyboard_close_project",
    }
    for tool in tools:
        assert tool["inputSchema"]["type"] == "object" and tool["description"]
        if tool["name"] in {"storyboard_generate_image", "storyboard_generate_video"}:
            assert "Comfy Cloud credits" in tool["description"]
        if tool["name"] in {"storyboard_new_project", "storyboard_open_project"}:
            assert "user's Storyboarder window" in tool["description"]
    unknown = _rpc(client, "tools/call", {"name": "storyboard_nope", "arguments": {}})
    assert unknown["isError"] is True


# ── discovery ────────────────────────────────────────────────────────────────

def test_missing_bridge_says_open_storyboarder_first(bridge_file) -> None:
    client = StoryboarderClient(transport=lambda *a: pytest.fail("must not call HTTP"))

    assert mcp_server.NOT_RUNNING in _error(_call(client, "storyboard_outline"))
    status = _value(_call(client, "storyboard_status"))
    assert status["app_running"] is False and mcp_server.NOT_RUNNING in status["message"]


def test_stale_bridge_with_nothing_listening_is_reported_as_not_running(bridge_file) -> None:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    _write_bridge(bridge_file, port=port)
    client = StoryboarderClient()  # real urllib transport

    message = _error(_call(client, "storyboard_board_image", shot_id="shot_1"))

    assert "not reachable" in message and mcp_server.NOT_RUNNING in message


# ── against a real backend ───────────────────────────────────────────────────

def test_status_reports_project_and_comfy(backend) -> None:
    _http, client = backend
    status = _value(_call(client, "storyboard_status"))
    assert status == {
        "app_running": True,
        "project_open": True,
        "project_name": "Demo",
        "board_count": 0,
        "comfy_cloud_configured": False,
    }


def test_project_lifecycle_switches_the_app_project(backend, tmp_path) -> None:
    _http, client = backend
    (tmp_path / "work").mkdir()

    created = _value(_call(client, "storyboard_new_project", path=str(tmp_path / "work" / "Film.sbd"),
                           project_type="video", canvas_width=1280, canvas_height=720))
    assert created["name"] == "Film" and created["board_count"] == 0
    film_path = Path(created["project_path"])
    assert film_path.is_file() and film_path == tmp_path / "work" / "Film" / "Film.sbd"
    status = _value(_call(client, "storyboard_status"))
    assert status["project_open"] is True and status["project_name"] == "Film"

    _value(_call(client, "storyboard_add_board", title="Opening"))
    assert _value(_call(client, "storyboard_status"))["board_count"] == 1

    demo = _value(_call(client, "storyboard_open_project", path=str(tmp_path / "Demo")))
    assert demo["name"] == "Demo" and demo["board_count"] == 0
    assert _value(_call(client, "storyboard_status"))["project_name"] == "Demo"

    recents = _value(_call(client, "storyboard_recent_projects"))["recents"]
    by_name = {row["name"]: row for row in recents}
    assert {"Film", "Demo"} <= set(by_name)
    assert by_name["Film"]["boards"] == 1 and by_name["Film"]["exists"] is True
    assert Path(by_name["Film"]["path"]) == film_path and by_name["Film"]["modified"]
    assert "thumbnail" not in by_name["Film"]

    reopened = _value(_call(client, "storyboard_open_project", path=by_name["Film"]["path"]))
    assert reopened["name"] == "Film" and reopened["board_count"] == 1

    assert _value(_call(client, "storyboard_close_project")) == {"closed": True}
    status = _value(_call(client, "storyboard_status"))
    assert status["project_open"] is False
    assert "storyboard_new_project" in status["message"] and "storyboard_open_project" in status["message"]
    assert "storyboard_open_project" in _error(_call(client, "storyboard_outline"))
    assert _value(_call(client, "storyboard_close_project")) == {"closed": False}

    assert "project_type" in _error(_call(client, "storyboard_new_project", path=str(tmp_path / "x.sbd"), project_type="film"))
    assert "HTTP 400" in _error(_call(client, "storyboard_open_project", path=str(tmp_path / "missing.sbd")))


def test_token_is_sent_and_a_wrong_token_surfaces_the_backend_detail(backend, bridge_file) -> None:
    _http, client = backend
    _write_bridge(bridge_file, token="wrong-token")

    message = _error(_call(client, "storyboard_add_board", title="x"))

    assert "HTTP 403" in message and "Missing or invalid API token" in message


def test_board_lifecycle_preserves_untouched_fields(backend) -> None:
    http, client = backend
    first = _value(_call(client, "storyboard_add_board", title="Opening", description="A match flares.",
                         dialogue="Who's there?", duration_seconds=2.5, prompt="ink sketch, dark room"))["board"]
    assert first["number"] == 1 and first["title"] == "Opening"
    assert first["duration_seconds"] == 2.5 and first["prompt"] == "ink sketch, dark room"

    second = _value(_call(client, "storyboard_add_board", title="Reveal"))["board"]
    third = _value(_call(client, "storyboard_add_board", after_shot_id=first["shot_id"], title="Between"))
    assert third["board"]["number"] == 2 and third["board_count"] == 3

    updated = _value(_call(client, "storyboard_update_board", shot_id=first["shot_id"], title="Cold open",
                           shot_design={"camera_movement": "slow push in"}))["board"]
    assert updated["title"] == "Cold open"
    # PATCH replaces declared fields, so the server must send the board's current values back.
    assert updated["description"] == "A match flares." and updated["dialogue"] == "Who's there?"
    assert updated["duration_seconds"] == 2.5 and updated["prompt"] == "ink sketch, dark room"
    stored = next(s for s in http.get("/api/project").json()["shots"] if s["shot_id"] == first["shot_id"])
    assert stored["shot_design"]["camera_movement"] == "slow push in"
    assert stored["prompt_config"]["mode"] == "manual"

    assert "Nothing to update" in _error(_call(client, "storyboard_update_board", shot_id=first["shot_id"]))

    order = [second["shot_id"], first["shot_id"], third["board"]["shot_id"]]
    reordered = _value(_call(client, "storyboard_reorder_boards", shot_ids=order))["boards"]
    assert [row["shot_id"] for row in reordered] == order

    deleted = _value(_call(client, "storyboard_delete_board", shot_id=second["shot_id"]))
    assert deleted == {"deleted": second["shot_id"], "board_count": 2}
    assert "Board not found" in _error(_call(client, "storyboard_update_board", shot_id="missing", title="x"))
    assert "HTTP 404" in _error(_call(client, "storyboard_delete_board", shot_id="missing"))


def test_set_board_image_uploads_bytes_and_board_image_returns_capped_png(backend, tmp_path) -> None:
    _http, client = backend
    board = _value(_call(client, "storyboard_add_board", title="Wide"))["board"]
    assert board["has_image"] is False
    assert "HTTP 404" in _error(_call(client, "storyboard_board_image", shot_id=board["shot_id"]))

    source = _png(tmp_path / "agent render.png", size=(2400, 1350))
    result = _value(_call(client, "storyboard_set_board_image", shot_id=board["shot_id"], path=str(source)))
    assert result["board"]["has_image"] is True

    image_result = _call(client, "storyboard_board_image", shot_id=board["shot_id"])
    assert image_result["isError"] is False
    image = _decoded_image(image_result["content"][-1])
    assert max(image.size) <= mcp_server.BOARD_MAX_EDGE

    missing = _error(_call(client, "storyboard_set_board_image", shot_id=board["shot_id"], path=str(tmp_path / "nope.png")))
    assert "not found" in missing


def test_video_takes_and_generation_errors_come_from_the_backend(backend) -> None:
    _http, client = backend
    board = _value(_call(client, "storyboard_add_board", title="Walk", description="She walks away."))["board"]

    assert _value(_call(client, "storyboard_video_takes", shot_id=board["shot_id"])) == {"takes": []}
    assert _value(_call(client, "storyboard_video_takes")) == {"takes": []}
    # No Comfy key configured: the backend's own message reaches the agent.
    assert "API key" in _error(_call(client, "storyboard_generate_video", shot_id=board["shot_id"]))


def test_generation_handoff_tools_work_over_http(backend) -> None:
    http, client = backend
    board = _value(_call(client, "storyboard_add_board", description="A lone figure crosses the bridge"))["board"]
    created = http.post(
        f"/api/shots/{board['shot_id']}/generation-requests",
        json={"destination": "codex"},
        headers={"x-storyboarder-token": TOKEN},
    )
    assert created.status_code == 200, created.text

    rows = _value(_call(client, "storyboard_list_generation_requests"))["requests"]
    assert len(rows) == 1 and rows[0]["shot_id"] == board["shot_id"]
    fetched = _value(_call(client, "storyboard_get_generation_request", request_id=rows[0]["request_id"]))
    assert fetched["request_id"] == rows[0]["request_id"]
    assert "not found" in _error(_call(client, "storyboard_get_generation_request", request_id="gen_missing"))


# ── endpoints being built in parallel: check the request shape ───────────────

class Recorder:
    def __init__(self, responses: dict[tuple[str, str], HttpResponse]) -> None:
        self.responses = responses
        self.calls: list[dict] = []

    def __call__(self, method, url, headers, body, timeout):
        parts = urlsplit(url)
        self.calls.append({
            "method": method, "path": parts.path, "query": parse_qs(parts.query),
            "headers": headers, "body": body,
        })
        return self.responses.get((method, parts.path), HttpResponse(200, "application/json", b"{}"))


def _json(value) -> HttpResponse:
    return HttpResponse(200, "application/json", json.dumps(value).encode())


def _png_response(size=(1800, 1000)) -> HttpResponse:
    out = io.BytesIO()
    Image.new("RGB", size, (10, 20, 30)).save(out, format="PNG")
    return HttpResponse(200, "image/png", out.getvalue())


@pytest.fixture
def recorder(bridge_file):
    _write_bridge(bridge_file, port=8123)

    def make(responses: dict | None = None) -> tuple[Recorder, StoryboarderClient]:
        rec = Recorder(responses or {})
        return rec, StoryboarderClient(transport=rec)

    return make


def test_outline_and_grid_requests(recorder) -> None:
    outline = {"boards": [{"number": 1, "shot_id": "s1", "title": "Open", "duration_seconds": 3.0, "has_image": False}]}
    rec, client = recorder({
        ("GET", "/api/project/outline"): _json(outline),
        ("GET", "/api/project/grid.png"): _png_response(),
    })

    assert _value(_call(client, "storyboard_outline", route_id="main")) == outline
    grid = _call(client, "storyboard_grid", route_id="main", columns=4, max_edge=4000)

    assert rec.calls[0]["path"] == "/api/project/outline" and rec.calls[0]["query"] == {"route_id": ["main"]}
    grid_call = rec.calls[1]
    assert grid_call["method"] == "GET" and grid_call["path"] == "/api/project/grid.png"
    assert grid_call["query"] == {"route_id": ["main"], "columns": ["4"], "max_edge": ["1600"]}
    assert grid["isError"] is False
    assert "1. Open [s1] 3.0s (no image)" in grid["content"][0]["text"]
    assert max(_decoded_image(grid["content"][1]).size) <= mcp_server.GRID_MAX_EDGE
    assert all(call["headers"].get("x-storyboarder-token") == TOKEN for call in rec.calls)


def test_image_job_requests(recorder) -> None:
    rec, client = recorder({("GET", "/api/image-jobs/img_1/outputs/2"): _png_response((64, 64))})

    _value(_call(client, "storyboard_generate_image", shot_id="s 1", prompt="a red door",
                 references=["s0", "ref_abc"], seed=7, apply=True))
    _value(_call(client, "storyboard_image_jobs", shot_id="s1"))
    _value(_call(client, "storyboard_image_jobs"))
    candidate = _call(client, "storyboard_image_candidate", job_id="img_1", index=2)
    _value(_call(client, "storyboard_apply_image", job_id="img_1", index=1))

    create, per_shot, all_jobs, output, apply = rec.calls
    assert (create["method"], create["path"]) == ("POST", "/api/shots/s%201/image-jobs")
    assert json.loads(create["body"]) == {"prompt": "a red door", "references": ["s0", "ref_abc"], "seed": 7, "apply": True}
    assert (per_shot["method"], per_shot["path"]) == ("GET", "/api/shots/s1/image-jobs")
    assert (all_jobs["method"], all_jobs["path"]) == ("GET", "/api/image-jobs")
    assert (output["method"], output["path"]) == ("GET", "/api/image-jobs/img_1/outputs/2")
    assert candidate["content"][-1]["type"] == "image"
    assert (apply["method"], apply["path"]) == ("POST", "/api/image-jobs/img_1/apply")
    assert json.loads(apply["body"]) == {"index": 1}


def test_render_sequence_and_video_take_requests(recorder) -> None:
    rec, client = recorder({("POST", "/api/project/sequence/render"): _json({"path": "Exports/x.mp4", "duration_seconds": 9.5, "boards": []})})

    rendered = _value(_call(client, "storyboard_render_sequence", route_id="main", takes={"s1": "vid_1"}))
    _value(_call(client, "storyboard_generate_video", shot_id="s1", seconds=3, end_shot_id="s2"))

    render, video = rec.calls
    assert (render["method"], render["path"]) == ("POST", "/api/project/sequence/render")
    assert json.loads(render["body"]) == {"route_id": "main", "takes": {"s1": "vid_1"}}
    assert rendered["duration_seconds"] == 9.5
    assert (video["method"], video["path"]) == ("POST", "/api/shots/s1/video-takes")
    assert json.loads(video["body"]) == {"end_shot_id": "s2", "seconds": 3.0}


def test_submit_generation_result_uploads_files(recorder, tmp_path) -> None:
    rec, client = recorder()
    first = _png(tmp_path / "a.png")
    second = _png(tmp_path / "b.png", color=(1, 2, 3))

    _value(_call(client, "storyboard_submit_generation_result", request_id="gen_1",
                 artifact_paths=[str(first), str(second)], summary="two takes"))

    call = rec.calls[0]
    assert (call["method"], call["path"]) == ("POST", "/api/generation/requests/gen_1/results")
    assert call["headers"]["content-type"].startswith("multipart/form-data; boundary=")
    assert call["body"].count(b'name="files"') == 2 and b"two takes" in call["body"]
    assert first.read_bytes() in call["body"]


def test_missing_endpoint_is_explained(recorder) -> None:
    _rec, client = recorder({("GET", "/api/project/outline"): HttpResponse(404, "application/json", b'{"detail":"Not Found"}')})
    assert "may not have this endpoint" in _error(_call(client, "storyboard_outline"))
