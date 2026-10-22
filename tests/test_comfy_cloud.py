from __future__ import annotations

import json
import sys
import time
import types
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from storyboard_tool import comfy_cloud
from storyboard_tool.api import create_app


# ── fakes ────────────────────────────────────────────────────────────────────

class _FakeOutput:
    def __init__(self, data: bytes) -> None:
        self.data = data

    def to_file(self, path):
        Path(path).write_bytes(self.data)
        return Path(path)


class _FakeJob:
    def __init__(self, job_id: str, status: str = "succeeded", data: bytes = b"\x00\x00\x00\x18ftypmp42") -> None:
        self.id = job_id
        self.status = "queued"
        self._final = status
        self.error = None if status == "succeeded" else "boom"
        self._data = data

    def wait(self, timeout=None):
        self.status = self._final
        return self

    def get_outputs(self, node_id):
        return [_FakeOutput(self._data)] if self.status == "succeeded" and node_id == comfy_cloud.NODE_OUTPUT else []

    @property
    def outputs(self):
        return []


class _FakeWorkflow:
    def __init__(self, graph):
        self.json = graph

    def set_input(self, node_id, field, value):
        self.json[node_id]["inputs"][field] = value


class _FakeComfy:
    submitted: list[dict] = []
    final_status = "succeeded"

    def __init__(self, *, api_key=None, client_info=None, timeout=None) -> None:
        assert api_key == "comfyui-test-key"
        self.workflows = types.SimpleNamespace(from_json=_FakeWorkflow)
        self.assets = types.SimpleNamespace(from_file=lambda path: {"asset_for": str(path)})
        self.jobs = types.SimpleNamespace(get=lambda job_id: _FakeJob(job_id, self.final_status))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None

    def submit(self, workflow):
        type(self).submitted.append(workflow.json)
        return _FakeJob("job-1", type(self).final_status)


@pytest.fixture
def cloud(monkeypatch):
    store: dict[str, str] = {}
    monkeypatch.setattr(comfy_cloud, "get_api_key", lambda: store.get("key", ""))
    monkeypatch.setattr(comfy_cloud, "set_api_key", lambda value: store.__setitem__("key", value))
    monkeypatch.setattr(comfy_cloud, "clear_api_key", lambda: store.pop("key", None))
    _FakeComfy.submitted = []
    _FakeComfy.final_status = "succeeded"
    monkeypatch.setitem(sys.modules, "comfy_sdk", types.SimpleNamespace(Comfy=_FakeComfy))
    return store


def _project_client(tmp_path: Path):
    client = TestClient(create_app(tmp_path), raise_server_exceptions=False)
    assert client.post("/api/project/new", json={"path": str(tmp_path)}).status_code == 200
    shot = client.post("/api/shots", json={}).json()["shot"]
    return client, shot


def _with_board_image(client: TestClient, shot_id: str, tmp_path: Path) -> None:
    image = tmp_path / "board.png"
    Image.new("RGB", (320, 180), (200, 190, 170)).save(image)
    with image.open("rb") as handle:
        response = client.post(f"/api/shots/{shot_id}/image", files={"file": ("board.png", handle, "image/png")})
    assert response.status_code == 200, response.text


def _wait_for(client: TestClient, shot_id: str, status: str) -> dict:
    for _ in range(100):
        takes = client.get(f"/api/shots/{shot_id}/video-takes").json()["takes"]
        if takes and takes[0]["status"] == status:
            return takes[0]
        time.sleep(0.05)
    raise AssertionError(f"take never reached {status}: {takes}")


# ── pure helpers ─────────────────────────────────────────────────────────────

def test_frame_count_snaps_to_wan_lengths_and_clamps() -> None:
    assert comfy_cloud.frame_count(3) == 49
    assert comfy_cloud.frame_count(0.2) == 17
    assert comfy_cloud.frame_count(30) == 81
    assert all((comfy_cloud.frame_count(s) - 1) % 4 == 0 for s in (1, 1.7, 2.5, 4.2))


def test_frame_size_keeps_board_aspect_on_a_16px_grid() -> None:
    assert comfy_cloud.frame_size(1920, 1080) == (832, 464)
    assert comfy_cloud.frame_size(1080, 1920) == (464, 832)
    width, height = comfy_cloud.frame_size(2048, 858)
    assert width == 832 and height % 16 == 0


def test_validate_template_names_missing_nodes_models_and_bad_values() -> None:
    template = comfy_cloud.load_template()
    info = {node["class_type"]: {"input": {"required": {}}} for node in template.values()}
    info["UNETLoader"] = {"input": {"required": {"unet_name": [["other.safetensors"]], "weight_dtype": [["default"]]}}}
    info["KSamplerAdvanced"] = {"input": {"required": {"sampler_name": ["COMBO", {"options": ["dpmpp_2m"]}]}}}
    del info["CreateVideo"]

    report = comfy_cloud.validate_template(template, info)

    assert report["missing_nodes"] == ["CreateVideo"]
    assert "wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors" in report["missing_models"]
    assert any("sampler_name='euler'" in item for item in report["invalid_values"])


def test_video_prompt_uses_motion_fields_not_image_style() -> None:
    from storyboard_tool.models import Shot

    shot = Shot(shot_id="s1", description="A match flares in the dark.")
    shot.shot_design.update(camera_movement="Slow push in", subject_movement="Mara turns her head")

    prompt = comfy_cloud.compile_video_prompt(shot)

    assert prompt.startswith("A match flares in the dark.")
    assert "Camera movement: Slow push in" in prompt
    assert "Subject movement: Mara turns her head" in prompt
    assert "STORYBOARD" not in prompt.upper()


# ── API ──────────────────────────────────────────────────────────────────────

def test_key_routes_never_echo_the_key(tmp_path: Path, cloud) -> None:
    client, _shot = _project_client(tmp_path)

    saved = client.put("/api/comfy-cloud/key", json={"api_key": "comfyui-test-key"})
    status = client.get("/api/comfy-cloud")

    assert saved.status_code == 200 and saved.json()["configured"] is True
    assert "comfyui-test-key" not in saved.text + status.text
    assert client.delete("/api/comfy-cloud/key").json()["configured"] is False


def test_video_take_requires_key_and_board_image(tmp_path: Path, cloud) -> None:
    client, shot = _project_client(tmp_path)

    no_key = client.post(f"/api/shots/{shot['shot_id']}/video-takes", json={"prompt": "x"})
    cloud["key"] = "comfyui-test-key"
    no_image = client.post(f"/api/shots/{shot['shot_id']}/video-takes", json={"prompt": "x"})

    assert no_key.status_code == 400 and "API key" in no_key.json()["detail"]
    assert no_image.status_code == 400 and "no image" in no_image.json()["detail"]


def test_video_take_runs_to_a_playable_project_file(tmp_path: Path, cloud) -> None:
    cloud["key"] = "comfyui-test-key"
    client, shot = _project_client(tmp_path)
    _with_board_image(client, shot["shot_id"], tmp_path)

    created = client.post(
        f"/api/shots/{shot['shot_id']}/video-takes",
        json={"prompt": "She lights the match", "seconds": 2},
    )
    assert created.status_code == 200, created.text
    take = _wait_for(client, shot["shot_id"], "succeeded")

    graph = _FakeComfy.submitted[0]
    assert graph["8"]["inputs"]["text"] == "She lights the match"
    assert graph["12"]["inputs"]["length"] == 33
    assert graph["11"]["inputs"]["image"]["asset_for"].endswith(".png")
    assert graph["13"]["inputs"]["noise_seed"] == graph["14"]["inputs"]["noise_seed"] == take["seed"]
    assert take["video_path"] == f"generation/video/{take['take_id']}.mp4"
    video = client.get(f"/api/video-takes/{take['take_id']}/video")
    assert video.status_code == 200
    assert video.headers["content-type"] == "video/mp4"
    assert client.delete(f"/api/video-takes/{take['take_id']}").status_code == 200
    assert client.get(f"/api/shots/{shot['shot_id']}/video-takes").json()["takes"] == []


def test_failed_cloud_job_is_reported_on_the_take(tmp_path: Path, cloud) -> None:
    cloud["key"] = "comfyui-test-key"
    _FakeComfy.final_status = "failed"
    client, shot = _project_client(tmp_path)
    _with_board_image(client, shot["shot_id"], tmp_path)

    client.post(f"/api/shots/{shot['shot_id']}/video-takes", json={"prompt": "x"})
    take = _wait_for(client, shot["shot_id"], "failed")

    assert "failed" in take["error"]
    assert take["video_path"] == ""


def test_interrupted_running_take_resumes_from_its_job_id(tmp_path: Path, cloud) -> None:
    cloud["key"] = "comfyui-test-key"
    client, shot = _project_client(tmp_path)
    project = client.app.state.project
    record = {
        "schema_version": 1, "take_id": "vid_0123456789abcdef", "shot_id": shot["shot_id"],
        "status": "running", "job_id": "job-earlier", "prompt": "p", "negative_prompt": "n",
        "frames": 49, "fps": 16, "width": 832, "height": 464, "seed": 1, "video_path": "", "error": "",
        "created_at": "2026-10-22T00:00:00Z",
    }
    comfy_cloud._write(project, record)

    take = _wait_for(client, shot["shot_id"], "succeeded")

    assert take["take_id"] == "vid_0123456789abcdef"
    assert _FakeComfy.submitted == []  # resumed, not resubmitted


def test_malformed_take_id_is_rejected(tmp_path: Path, cloud) -> None:
    client, _shot = _project_client(tmp_path)

    assert client.get("/api/video-takes/..%2F..%2Fproject/video").status_code == 404
    assert client.delete("/api/video-takes/not-a-take").status_code == 404


def test_template_file_is_valid_api_format() -> None:
    template = json.loads(comfy_cloud.TEMPLATE_PATH.read_text(encoding="utf-8"))
    for node_id, node in template.items():
        assert node_id.isdigit() and "class_type" in node and "inputs" in node
        for value in node["inputs"].values():
            if isinstance(value, list):
                assert value[0] in template, f"node {node_id} links to missing node {value[0]}"
