"""Grid, outline and sequence render: the agent's view of a project."""
from __future__ import annotations

import io
import json
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from storyboard_tool import comfy_cloud
from storyboard_tool.api import create_app
from storyboard_tool.project_layout import generation_metadata_path, generation_video_relative, resolve_project_path

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")
needs_ffmpeg = pytest.mark.skipif(not (FFMPEG and FFPROBE), reason="ffmpeg/ffprobe not on PATH")


def _client(tmp_path: Path, boards: int = 3) -> tuple[TestClient, list[str]]:
    client = TestClient(create_app(tmp_path), raise_server_exceptions=False)
    assert client.post("/api/project/new", json={"path": str(tmp_path / "Demo.sbd")}).status_code == 200
    ids = []
    for index in range(boards):
        shot = client.post("/api/shots", json={}).json()["shot"]
        response = client.patch(f"/api/shots/{shot['shot_id']}", json={
            "title": f"Beat {index + 1}", "description": f"Story {index + 1}",
            "dialogue": f"Line {index + 1}", "duration_seconds": 1.0 + index * 0.5,
        })
        assert response.status_code == 200, response.text
        ids.append(shot["shot_id"])
    return client, ids


def _upload_image(client: TestClient, shot_id: str, tmp_path: Path, color=(200, 60, 60)) -> None:
    image = tmp_path / f"{shot_id}.png"
    Image.new("RGB", (320, 180), color).save(image)
    with image.open("rb") as handle:
        response = client.post(f"/api/shots/{shot_id}/image", files={"file": ("board.png", handle, "image/png")})
    assert response.status_code == 200, response.text


def _project(client: TestClient):
    return client.app.state.project


def _fake_take(client: TestClient, shot_id: str, seconds: float, *, status: str = "succeeded",
               created_at: str = "2026-10-23T10:00:00Z", size=(320, 176)) -> str:
    """Write a take record (and, when succeeded, a real tiny mp4) as comfy_cloud would."""
    project = _project(client)
    take_id = f"vid_{uuid.uuid4().hex[:16]}"
    relative = generation_video_relative(project, take_id)
    if status == "succeeded":
        target = resolve_project_path(project, relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([
            FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
            "-i", f"testsrc=size={size[0]}x{size[1]}:rate=16:duration={seconds}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(target),
        ], check=True)
    record = {
        "schema_version": 1, "take_id": take_id, "shot_id": shot_id, "status": status,
        "mode": "i2v", "seconds": seconds, "width": size[0], "height": size[1],
        "video_path": relative if status == "succeeded" else "", "job_id": "job",
        "created_at": created_at, "error": "",
    }
    path = generation_metadata_path(project, "video", f"{take_id}.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record), encoding="utf-8")
    return take_id


def _probe(path: Path) -> dict:
    result = subprocess.run([
        FFPROBE, "-v", "error", "-select_streams", "v:0", "-show_entries",
        "stream=width,height,codec_name,r_frame_rate:format=duration", "-of", "json", str(path),
    ], capture_output=True, text=True, check=True)
    data = json.loads(result.stdout)
    return {**data["streams"][0], "duration": float(data["format"]["duration"])}


# ── grid ────────────────────────────────────────────────────────────────────

def test_grid_is_a_capped_png_laid_out_by_columns(tmp_path: Path) -> None:
    client, ids = _client(tmp_path, boards=5)
    _upload_image(client, ids[0], tmp_path)

    default = client.get("/api/project/grid.png")
    wide = client.get("/api/project/grid.png", params={"columns": 5, "max_edge": 800})

    assert default.status_code == 200 and default.headers["content-type"] == "image/png"
    sheet = Image.open(io.BytesIO(default.content))
    assert max(sheet.size) <= 1600
    assert sheet.width > sheet.height  # 5 boards -> 3 x 2 of 16:9 cells
    one_row = Image.open(io.BytesIO(wide.content))
    assert max(one_row.size) <= 800 and one_row.width > 3 * one_row.height
    # The first cell shows the uploaded red board, the second the grey placeholder.
    gap = round(one_row.width / (5 + 6 * 0.04) * 0.04)
    cell = (one_row.width - 6 * gap) // 5
    first = one_row.getpixel((gap + cell // 2, gap + cell * 9 // 32 + 10))
    second = one_row.getpixel((2 * gap + cell + cell // 2, gap + cell * 9 // 32 + 10))
    assert first[0] > 150 and first[1] < 120
    assert second[0] > 200 and second[1] > 200


def test_grid_rejects_unknown_route_and_bad_params(tmp_path: Path) -> None:
    client, _ids = _client(tmp_path, boards=1)

    assert client.get("/api/project/grid.png", params={"route_id": "nope"}).status_code == 404
    assert client.get("/api/project/grid.png", params={"columns": 0}).status_code == 422
    assert client.get("/api/project/grid.png", params={"max_edge": 10}).status_code == 422


def test_grid_and_outline_follow_route_order(tmp_path: Path) -> None:
    client, ids = _client(tmp_path, boards=3)
    graph = client.get("/api/project").json()["story_graph"]
    graph = graph or {"version": 1, "revision": 0, "active_route_id": "main",
                      "routes": [{"id": "main", "name": "Main", "shot_ids": ids}], "positions": {}}
    graph["routes"] = [
        {"id": "main", "name": "Main", "shot_ids": ids},
        {"id": "alt", "name": "Alt", "shot_ids": [ids[0], ids[2]]},  # skips board 2
    ]
    saved = client.put("/api/project/story-graph", json=graph)
    assert saved.status_code == 200, saved.text

    alt = client.get("/api/project/outline", params={"route_id": "alt"}).json()
    main = client.get("/api/project/outline").json()

    assert [b["shot_id"] for b in alt["boards"]] == [ids[0], ids[2]]
    assert [b["number"] for b in alt["boards"]] == [1, 2]
    assert alt["route"] == {"id": "alt", "name": "Alt"}
    assert [b["shot_id"] for b in main["boards"]] == ids
    assert {r["id"]: r["active"] for r in main["routes"]} == {"main": True, "alt": False}
    assert client.get("/api/project/grid.png", params={"route_id": "alt"}).status_code == 200


# ── outline ─────────────────────────────────────────────────────────────────

@needs_ffmpeg
def test_outline_lists_board_fields_and_latest_take(tmp_path: Path) -> None:
    client, ids = _client(tmp_path, boards=2)
    _upload_image(client, ids[0], tmp_path)
    _fake_take(client, ids[0], 1.0, created_at="2026-10-23T09:00:00Z")
    newest = _fake_take(client, ids[0], 1.0, status="failed", created_at="2026-10-23T11:00:00Z")

    outline = client.get("/api/project/outline").json()

    assert outline["project"] == {"name": "Demo", "canvas": {"width": 1920, "height": 1080}}
    assert outline["board_count"] == 2 and outline["total_seconds"] == 2.5
    first, second = outline["boards"]
    assert first["number"] == 1 and first["title"] == "Beat 1" and first["dialogue"] == "Line 1"
    assert first["description"] == "Story 1" and first["duration_seconds"] == 1.0
    assert second["start_seconds"] == 1.0
    assert first["has_image"] is True and second["has_image"] is False
    assert first["latest_video_take"]["take_id"] == newest
    assert first["latest_video_take"]["status"] == "failed"
    assert first["video_takes"] == {"total": 2, "succeeded": 1}
    assert second["latest_video_take"] is None
    assert first["latest_image_job"] is None  # filled once comfy_images lands
    assert first["video_prompt"].startswith("Story 1")
    assert set(first["prompt"]) == {"mode", "manual_prompt", "prompt_extra", "negative_prompt"}


def test_outline_without_project_is_a_clear_error(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path), raise_server_exceptions=False)
    response = client.get("/api/project/outline")
    assert response.status_code >= 400


# ── sequence ────────────────────────────────────────────────────────────────

@needs_ffmpeg
def test_sequence_uses_newest_succeeded_take_and_stills(tmp_path: Path) -> None:
    client, ids = _client(tmp_path, boards=3)  # durations 1.0, 1.5, 2.0
    _upload_image(client, ids[1], tmp_path)
    _fake_take(client, ids[0], 2.0, created_at="2026-10-23T09:00:00Z")
    newest = _fake_take(client, ids[0], 1.0, created_at="2026-10-23T10:00:00Z")
    _fake_take(client, ids[0], 1.0, status="failed", created_at="2026-10-23T11:00:00Z")

    response = client.post("/api/project/sequence/render", json={})

    assert response.status_code == 200, response.text
    body = response.json()
    assert [(b["shot_id"], b["source"], b.get("take_id")) for b in body["boards"]] == [
        (ids[0], "take", newest), (ids[1], "still", None), (ids[2], "still", None),
    ]
    assert [b["seconds"] for b in body["boards"][1:]] == [1.5, 2.0]
    output = Path(body["path"])
    assert output.is_file() and output.parent.name == "Exports" and output.name.startswith("sequence_")
    assert body["relative_path"] == f"Exports/{output.name}"
    probe = _probe(output)
    assert probe["codec_name"] == "h264" and probe["r_frame_rate"] == "16/1"
    assert (probe["width"], probe["height"]) == (320, 176) == (body["width"], body["height"])
    assert abs(probe["duration"] - 4.5) < 0.15
    assert abs(body["duration_seconds"] - 4.5) < 0.15
    assert not list(output.parent.glob(".*"))  # no staging leftovers


@needs_ffmpeg
def test_sequence_with_only_stills_uses_canvas_aspect_832(tmp_path: Path) -> None:
    client, ids = _client(tmp_path, boards=2)
    _upload_image(client, ids[0], tmp_path)

    body = client.post("/api/project/sequence/render", json={"shot_ids": [ids[1], ids[0]]}).json()

    assert [b["shot_id"] for b in body["boards"]] == [ids[1], ids[0]]
    assert {b["source"] for b in body["boards"]} == {"still"}
    probe = _probe(Path(body["path"]))
    assert (probe["width"], probe["height"]) == comfy_cloud.frame_size(1920, 1080) == (832, 464)
    assert abs(probe["duration"] - 2.5) < 0.15


@needs_ffmpeg
def test_sequence_honours_chosen_take_and_validates_it(tmp_path: Path) -> None:
    client, ids = _client(tmp_path, boards=2)
    older = _fake_take(client, ids[0], 2.0, created_at="2026-10-23T09:00:00Z")
    _fake_take(client, ids[0], 1.0, created_at="2026-10-23T10:00:00Z")
    failed = _fake_take(client, ids[1], 1.0, status="failed")

    # Untrimmed: the 2 s take plays in full on its 1 s board.
    chosen = client.post("/api/project/sequence/render", json={"takes": {ids[0]: older}, "trim_to_board": False})
    bad_status = client.post("/api/project/sequence/render", json={"takes": {ids[1]: failed}})
    wrong_board = client.post("/api/project/sequence/render", json={"takes": {ids[1]: older}})
    both = client.post("/api/project/sequence/render", json={"route_id": "main", "shot_ids": [ids[0]]})

    assert chosen.status_code == 200, chosen.text
    assert chosen.json()["trim_to_board"] is False
    first = chosen.json()["boards"][0]
    assert first["take_id"] == older and first["seconds"] == first["take_seconds"] == 2.0
    assert abs(_probe(Path(chosen.json()["path"]))["duration"] - 3.5) < 0.15
    assert bad_status.status_code == 400 and "not succeeded" in bad_status.json()["detail"]
    assert wrong_board.status_code == 400
    assert both.status_code == 400


@needs_ffmpeg
def test_sequence_trims_takes_to_board_duration_by_default(tmp_path: Path) -> None:
    client, ids = _client(tmp_path, boards=3)  # durations 1.0, 1.5, 2.0
    _fake_take(client, ids[0], 2.0)  # longer than its board: cut to 16 frames
    _fake_take(client, ids[1], 1.5625)  # a Wan-style 25-frame take on a 24-frame board
    _fake_take(client, ids[2], 1.0)  # shorter than its board: never extended

    response = client.post("/api/project/sequence/render", json={})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["trim_to_board"] is True
    assert [(b["source"], b["seconds"]) for b in body["boards"]] == [("take", 1.0), ("take", 1.5), ("take", 1.0)]
    assert [b["take_seconds"] for b in body["boards"]] == pytest.approx([2.0, 1.5625, 1.0], abs=0.01)
    output = Path(body["path"])
    assert abs(_probe(output)["duration"] - 3.5) < 0.1
    frames = subprocess.run([
        FFPROBE, "-v", "error", "-select_streams", "v:0", "-count_frames",
        "-show_entries", "stream=nb_read_frames", "-of", "default=nw=1:nk=1", str(output),
    ], capture_output=True, text=True, check=True).stdout.strip()
    assert int(frames) == 16 + 24 + 16


def test_sequence_without_ffmpeg_fails_cleanly(tmp_path: Path, monkeypatch) -> None:
    client, _ids = _client(tmp_path, boards=1)
    real_which = shutil.which
    monkeypatch.setattr("storyboard_tool.agent_views.shutil.which",
                        lambda name: None if name in ("ffmpeg", "ffprobe") else real_which(name))

    response = client.post("/api/project/sequence/render", json={})

    assert response.status_code == 500 and "ffmpeg" in response.json()["detail"]
    exports = tmp_path / "Demo" / "Exports"
    assert not exports.exists() or not list(exports.iterdir())


def test_shot_patch_only_changes_the_fields_sent(tmp_path: Path) -> None:
    client, ids = _client(tmp_path, boards=1)
    shot_id = ids[0]
    assert client.patch(f"/api/shots/{shot_id}", json={"title": "Opening", "dialogue": "Hello"}).status_code == 200
    assert client.patch(f"/api/shots/{shot_id}", json={"duration_seconds": 4.5}).status_code == 200
    shot = next(item for item in client.get("/api/project").json()["shots"] if item["shot_id"] == shot_id)
    assert (shot["title"], shot["dialogue"], shot["duration_seconds"]) == ("Opening", "Hello", 4.5)
