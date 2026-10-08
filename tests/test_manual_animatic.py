"""Manual timing acceptance uses decoded MP4 frames, not file-exists proxies."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from storyboard_tool import export_service, export_utils, project_manager, story_graph, video_export
from storyboard_tool.api import create_app


def test_chinese_animatic_caption_has_real_glyphs_and_stays_inside_frame(tmp_path):
    import numpy as np
    project = project_manager.create_project(tmp_path / "caption", canvas_width=240, canvas_height=90)
    shot = project_manager.add_shot(project)
    shot.title = ""
    shot.dialogue = ""
    baseline = Image.new("RGB", (240, 90), "red")
    video_export._draw_caption(baseline, 1, shot)
    shot.title = "中文对白测试" * 30 + "\n第二行"
    actual = Image.new("RGB", (240, 90), "red")
    video_export._draw_caption(actual, 1, shot)
    pixels = np.asarray(actual)
    assert np.any(pixels != np.asarray(baseline)), "Chinese caption must add visible glyphs after board number"
    assert np.all(pixels[:60] == (255, 0, 0)), "Caption cannot escape its 30px footer"
    assert np.all(pixels[60:, :10] == 0)
    assert np.all(pixels[60:, 230:] == 0), "Ellipsis and long Chinese caption must stay within right padding"


@pytest.mark.parametrize("fps", [24, 60])
def test_one_frame_api_shot_save_reopen_and_actual_export(tmp_path, monkeypatch, fps):
    project, colors = _colored_project(tmp_path, monkeypatch, fps)
    app_dir = tmp_path / "api"
    app_dir.mkdir()
    app = create_app(app_dir)
    app.state.project = project
    app.state.project_disk_mtime = project_manager.project_disk_mtime(project)
    shot = project.shots[1]
    with TestClient(app) as client:
        updated = client.patch(f"/api/shots/{shot.shot_id}", json={"duration_seconds": 1 / fps})
        assert updated.status_code == 200, updated.text
        assert shot.duration_seconds == 1 / fps, "The shared shot write path must preserve one frame"
        assert client.post("/api/project/save").status_code == 200
        reopened = project_manager.open_project(project.reopen_path)
        assert reopened.shots[1].duration_seconds == 1 / fps
        output = video_export.export_animatic(reopened, tmp_path / "api-one-frame.mp4", fps=fps)
        expected = [0, 1] + [2] * (7 if fps == 24 else 18)
        assert _decoded_colors(output, colors) == expected


def test_timing_json_keeps_frame_precision_and_accumulates_short_shots(tmp_path, monkeypatch):
    project, _ = _colored_project(tmp_path, monkeypatch, 60)
    project.shots[1].duration_seconds = 1 / 24
    output = export_utils.export_timing_json(project, tmp_path / "timing.json")
    actual = json.loads(output.read_text(encoding="utf-8"))
    assert [row["duration_seconds"] for row in actual["shots"]] == [.016667, .041667, .3]
    assert actual["shots"][1]["start_seconds"] == .016667
    assert actual["shots"][2]["start_seconds"] == .058333
    assert actual["total_seconds"] == .358333


def _colored_project(tmp_path, monkeypatch, fps):
    project = project_manager.create_project(tmp_path / "project", canvas_width=160, canvas_height=90)
    project.settings["backup_on_save"] = False
    colors = [(255, 0, 0), (0, 255, 0), (0, 0, 255)]
    for seconds in (1 / fps, .125, .3):
        shot = project_manager.add_shot(project)
        shot.duration_seconds = seconds
    mapping = {shot.shot_id: color for shot, color in zip(project.shots, colors)}
    monkeypatch.setattr(video_export, "render_shot_composite_image", lambda _, shot: Image.new("RGB", (160, 90), mapping[shot.shot_id]))
    return project, colors


def _decoded_colors(output, colors):
    import cv2
    capture = cv2.VideoCapture(str(output))
    assert capture.isOpened(), output
    labels = []
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            actual = tuple(int(value) for value in frame[frame.shape[0] // 2, frame.shape[1] // 2, ::-1])
            distance = [sum(abs(a - b) for a, b in zip(actual, color)) for color in colors]
            assert min(distance) < 40, f"frame {len(labels)} has unexpected center RGB {actual}"
            labels.append(distance.index(min(distance)))
    finally:
        capture.release()
    return labels


@pytest.mark.parametrize("fps", [24, 60])
@pytest.mark.parametrize("encoder", ["ffmpeg", "opencv"])
def test_actual_mp4_one_frame_and_short_board_color_boundaries(tmp_path, monkeypatch, fps, encoder):
    project, colors = _colored_project(tmp_path, monkeypatch, fps)
    if encoder == "ffmpeg":
        assert shutil.which("ffmpeg"), "actual ffmpeg verification requires the existing system encoder"
        monkeypatch.setattr(video_export, "_encode_cv2", lambda *_: (_ for _ in ()).throw(AssertionError("ffmpeg must encode; no silent fallback")))
    else:
        monkeypatch.setattr(video_export, "_encode_ffmpeg", lambda *_: False)
    output = video_export.export_animatic(project, tmp_path / f"short-{fps}-{encoder}.mp4", fps=fps)
    expected_counts = [1, 3 if fps == 24 else 8, 7 if fps == 24 else 18]
    expected = [index for index, count in enumerate(expected_counts) for _ in range(count)]
    assert _decoded_colors(output, colors) == expected, "decoded color transitions must exactly match frame timing"


@pytest.mark.parametrize("fps", [24, 60])
def test_route_actual_order_scope_save_reopen_and_download(tmp_path, monkeypatch, fps):
    project, colors = _colored_project(tmp_path, monkeypatch, fps)
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    app = create_app(app_dir)
    app.state.project = project
    app.state.project_disk_mtime = project_manager.project_disk_mtime(project)
    global_ids = [shot.shot_id for shot in project.shots]
    with TestClient(app, raise_server_exceptions=False) as client:
        graph = story_graph.get_graph(project)
        graph["routes"] = [{"id": "reverse/../../outside", "name": "Reordered route", "shot_ids": list(reversed(global_ids))}]
        graph["active_route_id"] = graph["routes"][0]["id"]
        accepted = client.put("/api/project/story-graph", json=graph)
        assert accepted.status_code == 200, accepted.text
        saved_graph = accepted.json()["story_graph"]
        assert [shot.shot_id for shot in project.shots] == global_ids, "route order must not alter global board order"
        assert client.post("/api/project/save").status_code == 200
        reopened = project_manager.open_project(project.reopen_path)
        assert story_graph.get_graph(reopened) == saved_graph
        route_id = saved_graph["active_route_id"]
        view, suffix = export_service.scope_to_route(project, route_id)
        assert [shot.shot_id for shot in view.shots] == list(reversed(global_ids))
        assert view.board_numbers == [3, 2, 1]
        result = client.post("/api/export/animatic", json={"fps": fps, "captions": False, "route_id": route_id})
        assert result.status_code == 200, result.text
        output = Path(result.json()["path"])
        assert output.parent == project.exports_dir
        assert output.name == f"animatic{suffix}.mp4"
        counts = [1, 3 if fps == 24 else 8, 7 if fps == 24 else 18]
        assert _decoded_colors(output, colors) == [index for index in [2, 1, 0] for _ in range(counts[index])]
        downloaded = client.get(result.json()["download_url"])
        assert downloaded.status_code == 200
        assert downloaded.content == output.read_bytes()
        monkeypatch.setattr(export_service, "open_export", lambda current, kind, export_suffix: export_service.check_export_exists(current, kind, export_suffix))
        opened = client.post("/api/export/open", json={"type": "animatic", "route_id": route_id})
        assert opened.status_code == 200, opened.text
        assert Path(opened.json()["path"]) == output
        # An ambiguous or missing route must never replace a previous export.
        before = output.read_bytes()
        for body in ({"boards": "1", "route_id": route_id}, {"route_id": "missing"}):
            rejected = client.post("/api/export/animatic", json=body)
            assert rejected.status_code == 400, rejected.text
        assert output.read_bytes() == before


def test_animatic_board_range_is_passed_to_actual_encoder(tmp_path, monkeypatch):
    project, colors = _colored_project(tmp_path, monkeypatch, 24)
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    app = create_app(app_dir)
    app.state.project = project
    app.state.project_disk_mtime = project_manager.project_disk_mtime(project)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post("/api/export/animatic", json={"fps": 24, "boards": "2", "captions": False})
        assert response.status_code == 200, response.text
        assert _decoded_colors(Path(response.json()["path"]), colors) == [1] * 3
        assert client.get(response.json()["download_url"]).status_code == 200


@pytest.mark.parametrize("seconds,expected", [(1 / 60, 1), (.125, 8), (.3, 18), (0, 180), (-1, 180), (float("nan"), 180), (float("inf"), 180)])
def test_duration_frames_positive_half_up_and_invalid_fallback(seconds, expected):
    assert video_export.duration_frames(seconds, 60) == expected
