from __future__ import annotations

import io
import json
import sys
import time
import types
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from storyboard_tool import comfy_cloud, comfy_images
from storyboard_tool.api import create_app


def _png_bytes(color=(10, 120, 200), size=(64, 36)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format="PNG")
    return buffer.getvalue()


# ── fakes ────────────────────────────────────────────────────────────────────

class _FakeOutput:
    def __init__(self, data: bytes) -> None:
        self.data = data

    def to_file(self, path):
        Path(path).write_bytes(self.data)
        return Path(path)


class _FakeJob:
    def __init__(self, job_id: str, status: str, output_node: str | None) -> None:
        self.id = job_id
        self.status = "queued"
        self._final = status
        self._output_node = output_node
        self.error = None if status == "succeeded" else "boom"

    def wait(self, timeout=None):
        self.status = self._final
        return self

    def get_outputs(self, node_id):
        if self.status != "succeeded":
            return []
        if self._output_node is None or node_id == self._output_node:
            return [_FakeOutput(_png_bytes())]
        return []

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
    uploads: list[str] = []
    final_status = "succeeded"

    def __init__(self, *, api_key=None, client_info=None, timeout=None) -> None:
        assert api_key == "comfyui-test-key"
        self.workflows = types.SimpleNamespace(from_json=_FakeWorkflow)
        self.assets = types.SimpleNamespace(from_file=self._upload)
        self.jobs = types.SimpleNamespace(get=lambda job_id: _FakeJob(job_id, type(self).final_status, None))

    @classmethod
    def _upload(cls, path):
        cls.uploads.append(str(path))
        return {"asset_for": str(path)}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None

    def submit(self, workflow):
        type(self).submitted.append(workflow.json)
        output = comfy_images.EDIT_OUTPUT if "14" in workflow.json else comfy_images.T2I_OUTPUT
        return _FakeJob("cloud-job-1", type(self).final_status, output)


@pytest.fixture
def cloud(monkeypatch):
    store: dict[str, str] = {"key": "comfyui-test-key"}
    monkeypatch.setattr(comfy_cloud, "get_api_key", lambda: store.get("key", ""))
    _FakeComfy.submitted = []
    _FakeComfy.uploads = []
    _FakeComfy.final_status = "succeeded"
    monkeypatch.setitem(sys.modules, "comfy_sdk", types.SimpleNamespace(Comfy=_FakeComfy))
    return store


def _project_client(tmp_path: Path):
    client = TestClient(create_app(tmp_path), raise_server_exceptions=False)
    assert client.post("/api/project/new", json={"path": str(tmp_path / "Demo.sbd")}).status_code == 200
    shot = client.post("/api/shots", json={}).json()["shot"]
    return client, shot


def _with_board_image(client: TestClient, shot_id: str) -> None:
    response = client.post(
        f"/api/shots/{shot_id}/image", files={"file": ("board.png", _png_bytes((200, 190, 170)), "image/png")}
    )
    assert response.status_code == 200, response.text


def _wait_for(client: TestClient, shot_id: str, predicate, label: str) -> dict:
    jobs: list = []
    for _ in range(100):
        jobs = client.get(f"/api/shots/{shot_id}/image-jobs").json()["jobs"]
        if jobs and predicate(jobs[0]):
            return jobs[0]
        time.sleep(0.05)
    raise AssertionError(f"job never reached {label}: {jobs}")


def _wait_status(client, shot_id, status):
    return _wait_for(client, shot_id, lambda job: job["status"] == status, status)


# ── pure helpers ─────────────────────────────────────────────────────────────

def test_image_size_follows_board_aspect_on_a_16px_grid() -> None:
    assert comfy_images.image_size(1920, 1080, 1280) == (1280, 720)
    assert comfy_images.image_size(1080, 1920, 1024) == (576, 1024)
    width, height = comfy_images.image_size(2048, 858, 1280)
    assert width == 1280 and height % 16 == 0


@pytest.mark.parametrize("path", [comfy_images.T2I_TEMPLATE_PATH, comfy_images.EDIT_TEMPLATE_PATH])
def test_image_templates_are_valid_api_format(path: Path) -> None:
    template = json.loads(path.read_text(encoding="utf-8"))
    for node_id, node in template.items():
        assert node_id.isdigit() and "class_type" in node and "inputs" in node
        for value in node["inputs"].values():
            if isinstance(value, list):
                assert value[0] in template, f"node {node_id} links to missing node {value[0]}"


def test_edit_graph_drops_unused_reference_slots() -> None:
    graph = comfy_images._edit_graph(comfy_images.load_edit_template(), 1)
    assert "7" in graph and "8" not in graph and "9" not in graph
    for encoder in comfy_images.EDIT_ENCODERS:
        assert graph[encoder]["inputs"]["image1"] == ["7", 0]
        assert "image2" not in graph[encoder]["inputs"] and "image3" not in graph[encoder]["inputs"]
    for node in graph.values():
        for value in node["inputs"].values():
            if isinstance(value, list):
                assert value[0] in graph


def test_image_templates_use_the_planned_models() -> None:
    t2i = json.dumps(comfy_images.load_t2i_template())
    edit = json.dumps(comfy_images.load_edit_template())
    for name in ("z_image_turbo_bf16.safetensors", "qwen_3_4b.safetensors", "ae.safetensors", "res_multistep"):
        assert name in t2i
    for name in (
        "qwen_image_edit_2511_fp8mixed.safetensors",
        "Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors",
        "qwen_2.5_vl_7b_fp8_scaled.safetensors",
        "qwen_image_vae.safetensors",
    ):
        assert name in edit


def test_check_connection_validates_image_templates(monkeypatch, cloud) -> None:
    graphs = [comfy_cloud.load_template(), comfy_cloud._flf_graph(comfy_cloud.load_template()),
              *comfy_images.validation_graphs()]
    info: dict = {}
    for graph in graphs:
        for node in graph.values():
            info[node["class_type"]] = {"input": {"required": {}}}
    info["UNETLoader"] = {"input": {"required": {"unet_name": [["wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors",
                                                               "wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors",
                                                               "z_image_turbo_bf16.safetensors"]]}}}
    del info["TextEncodeQwenImageEditPlus"]

    class _Response:
        status_code = 200

        def json(self):
            return info

    monkeypatch.setattr(comfy_cloud.httpx, "get", lambda *args, **kwargs: _Response())
    report = comfy_cloud.check_connection()

    assert report["ok"] is False
    assert report["missing_nodes"] == ["TextEncodeQwenImageEditPlus"]
    assert report["missing_models"] == ["qwen_image_edit_2511_fp8mixed.safetensors"]


# ── API ──────────────────────────────────────────────────────────────────────

def test_image_job_requires_key_and_prompt(tmp_path: Path, cloud) -> None:
    client, shot = _project_client(tmp_path)
    url = f"/api/shots/{shot['shot_id']}/image-jobs"

    no_prompt = client.post(url, json={"prompt": "  "})
    cloud.pop("key")
    no_key = client.post(url, json={"prompt": "x"})

    assert no_prompt.status_code == 400 and "prompt" in no_prompt.json()["detail"]
    assert no_key.status_code == 400 and "API key" in no_key.json()["detail"]
    assert _FakeComfy.submitted == []


def test_text_to_image_job_produces_a_candidate_without_touching_the_board(tmp_path: Path, cloud) -> None:
    client, shot = _project_client(tmp_path)

    created = client.post(f"/api/shots/{shot['shot_id']}/image-jobs", json={"prompt": "A lighthouse at dusk", "seed": 7})
    assert created.status_code == 200, created.text
    job = _wait_status(client, shot["shot_id"], "succeeded")

    graph = _FakeComfy.submitted[0]
    assert graph["5"]["inputs"]["text"] == "A lighthouse at dusk"
    assert graph["8"]["inputs"]["seed"] == 7
    assert (graph["7"]["inputs"]["width"], graph["7"]["inputs"]["height"]) == (job["width"], job["height"])
    assert job["mode"] == "t2i" and job["references"] == [] and job["cloud_job_id"] == "cloud-job-1"
    assert job["outputs"] == [{
        "index": 0, "path": f"Images/Generated/{job['job_id']}_0.png", "width": 64, "height": 36,
        "bytes": job["outputs"][0]["bytes"],
    }]
    assert job["applied_index"] is None
    assert (tmp_path / "Demo" / job["outputs"][0]["path"]).is_file()
    output = client.get(f"/api/image-jobs/{job['job_id']}/outputs/0")
    assert output.status_code == 200 and output.headers["content-type"] == "image/png"
    assert client.get(f"/api/image-jobs/{job['job_id']}/outputs/1").status_code == 404
    board = client.get("/api/project").json()["shots"][0]
    assert board["preview_image_path"] == ""
    assert [row["job_id"] for row in client.get("/api/image-jobs").json()["jobs"]] == [job["job_id"]]


def test_edit_job_uploads_board_and_library_references(tmp_path: Path, cloud) -> None:
    client, first = _project_client(tmp_path)
    second = client.post("/api/shots", json={}).json()["shot"]
    _with_board_image(client, first["shot_id"])
    project = client.app.state.project
    ref_path = project.project_root / "Images" / "References" / "hero.png"
    ref_path.parent.mkdir(parents=True, exist_ok=True)
    ref_path.write_bytes(_png_bytes((1, 2, 3)))
    project.settings["reference_links"] = [{"id": "ref1", "title": "Hero", "type": "image",
                                            "path": "Images/References/hero.png"}]

    created = client.post(
        f"/api/shots/{second['shot_id']}/image-jobs",
        json={"prompt": "Same hero, now running", "negative_prompt": "blurry",
              "references": [first["shot_id"], "ref1"]},
    )
    assert created.status_code == 200, created.text
    job = _wait_status(client, second["shot_id"], "succeeded")

    graph = _FakeComfy.submitted[0]
    assert graph["10"]["inputs"]["prompt"] == "Same hero, now running"
    assert graph["11"]["inputs"]["prompt"] == "blurry"
    assert graph["7"]["inputs"]["image"]["asset_for"].endswith(".png")
    assert graph["8"]["inputs"]["image"]["asset_for"].endswith("hero.png")
    assert "9" not in graph and "image3" not in graph["10"]["inputs"]
    assert graph["15"]["inputs"]["seed"] == job["seed"]
    assert max(job["width"], job["height"]) == 1024
    assert [ref["kind"] for ref in job["references"]] == ["board", "reference"]
    assert len(_FakeComfy.uploads) == 2


def test_bad_references_are_rejected_before_submitting(tmp_path: Path, cloud) -> None:
    client, first = _project_client(tmp_path)
    blank = client.post("/api/shots", json={}).json()["shot"]
    url = f"/api/shots/{first['shot_id']}/image-jobs"

    no_image = client.post(url, json={"prompt": "x", "references": [blank["shot_id"]]})
    unknown = client.post(url, json={"prompt": "x", "references": ["nope"]})
    too_many = client.post(url, json={"prompt": "x", "references": ["a", "b", "c", "d"]})

    assert no_image.status_code == 400 and "no image" in no_image.json()["detail"]
    assert unknown.status_code == 400 and "Unknown reference" in unknown.json()["detail"]
    assert too_many.status_code == 422
    assert _FakeComfy.submitted == []


def test_apply_puts_the_output_on_the_board_like_an_import(tmp_path: Path, cloud) -> None:
    client, shot = _project_client(tmp_path)
    client.post(f"/api/shots/{shot['shot_id']}/image-jobs", json={"prompt": "x"})
    job = _wait_status(client, shot["shot_id"], "succeeded")
    revision = client.app.state.project.storage_revision

    applied = client.post(f"/api/image-jobs/{job['job_id']}/apply", json={"index": 0})

    assert applied.status_code == 200, applied.text
    body = applied.json()
    assert body["job"]["applied_index"] == 0 and body["job"]["applied_at"]
    assert body["storage_revision"] == revision + 1
    board = next(row for row in body["shots"] if row["shot_id"] == shot["shot_id"])
    assert board["preview_image_path"]
    assert client.get(f"/api/shots/{shot['shot_id']}/image").status_code == 200
    assert client.get(f"/api/shots/{shot['shot_id']}/thumbnail").status_code == 200
    assert client.post(f"/api/image-jobs/{job['job_id']}/apply", json={"index": 3}).status_code == 409
    # the board keeps its own copy: deleting the job does not remove the board image
    assert client.delete(f"/api/image-jobs/{job['job_id']}").status_code == 200
    assert not (tmp_path / "Demo" / job["outputs"][0]["path"]).exists()
    assert client.get(f"/api/shots/{shot['shot_id']}/image").status_code == 200
    assert client.get(f"/api/shots/{shot['shot_id']}/image-jobs").json()["jobs"] == []


def test_apply_true_applies_the_first_output_when_it_succeeds(tmp_path: Path, cloud) -> None:
    client, shot = _project_client(tmp_path)

    client.post(f"/api/shots/{shot['shot_id']}/image-jobs", json={"prompt": "x", "apply": True})
    job = _wait_for(client, shot["shot_id"], lambda row: row["applied_index"] == 0, "applied")

    assert job["status"] == "succeeded" and job["error"] == ""
    board = client.get("/api/project").json()["shots"][0]
    assert board["preview_image_path"]


def test_failed_cloud_job_is_reported_and_cannot_be_applied(tmp_path: Path, cloud) -> None:
    _FakeComfy.final_status = "failed"
    client, shot = _project_client(tmp_path)

    client.post(f"/api/shots/{shot['shot_id']}/image-jobs", json={"prompt": "x", "apply": True})
    job = _wait_status(client, shot["shot_id"], "failed")

    assert "failed" in job["error"] and job["outputs"] == []
    assert client.post(f"/api/image-jobs/{job['job_id']}/apply", json={}).status_code == 409
    assert client.get("/api/project").json()["shots"][0]["preview_image_path"] == ""


def test_interrupted_running_job_resumes_from_its_cloud_job_id(tmp_path: Path, cloud) -> None:
    client, shot = _project_client(tmp_path)
    project = client.app.state.project
    record = {
        "schema_version": 1, "job_id": "img_0123456789abcdef", "shot_id": shot["shot_id"], "mode": "t2i",
        "status": "running", "cloud_job_id": "cloud-earlier", "prompt": "p", "negative_prompt": "",
        "references": [], "width": 1280, "height": 720, "seed": 1, "apply": False, "outputs": [],
        "applied_index": None, "applied_at": "", "error": "", "created_at": "2026-10-22T00:00:00Z",
    }
    comfy_images._write(project, record)

    job = _wait_status(client, shot["shot_id"], "succeeded")

    assert job["job_id"] == "img_0123456789abcdef"
    assert len(job["outputs"]) == 1
    assert _FakeComfy.submitted == []  # resumed, not resubmitted


def test_job_that_never_reached_the_cloud_is_marked_failed(tmp_path: Path, cloud) -> None:
    client, shot = _project_client(tmp_path)
    project = client.app.state.project
    comfy_images._write(project, {
        "schema_version": 1, "job_id": "img_fedcba9876543210", "shot_id": shot["shot_id"], "mode": "t2i",
        "status": "uploading", "cloud_job_id": "", "outputs": [], "created_at": "2026-10-22T00:00:00Z",
    })

    job = client.get(f"/api/shots/{shot['shot_id']}/image-jobs").json()["jobs"][0]

    assert job["status"] == "failed" and "Interrupted" in job["error"]


def test_malformed_job_ids_are_rejected(tmp_path: Path, cloud) -> None:
    client, _shot = _project_client(tmp_path)

    assert client.get("/api/image-jobs/..%2F..%2Fproject/outputs/0").status_code == 404
    assert client.delete("/api/image-jobs/not-a-job").status_code == 404
    assert client.post("/api/image-jobs/img_0000000000000000/apply", json={}).status_code == 404
