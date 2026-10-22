"""Comfy Cloud: generate a short video from one board.

The API key lives in the operating system credential store (Windows Credential
Manager via ``keyring``) and is never written to a project, the app folder or a
log. Each request is a *video take*: a JSON record under the project's generation
metadata plus, once finished, an MP4 next to the other generated assets.

A take runs on a daemon thread: upload the board frame, submit the Wan 2.2
image-to-video workflow, poll the job, download the result. The record is written
at every step, so a take interrupted by a restart is resumed from its job id the
next time the board's takes are listed.
"""

from __future__ import annotations

import copy
import json
import logging
import math
import os
import random
import re
import tempfile
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from . import project_manager
from .models import Project, Shot
from .project_layout import (
    generation_metadata_path,
    generation_video_relative,
    resolve_project_path,
)
from .project_storage import atomic_write_json
from .shot_files import resolve_project_relative_path

logger = logging.getLogger(__name__)

CLOUD_BASE_URL = "https://cloud.comfy.org"
KEYRING_SERVICE = "Storyboarder Comfy Cloud"
KEYRING_USER = "api_key"
TEMPLATE_PATH = Path(__file__).resolve().parent / "assets" / "comfy_workflows" / "wan22_i2v_api.json"
TEMPLATE_NAME = "Wan 2.2 image-to-video (14B, 4-step)"
FLF_TEMPLATE_NAME = "Wan 2.2 first + last frame (14B, 4-step)"
# Node ids inside the template that Storyboarder fills in.
NODE_POSITIVE, NODE_NEGATIVE, NODE_IMAGE, NODE_I2V = "8", "9", "11", "12"
NODE_SAMPLERS = ("13", "14")
NODE_OUTPUT = "17"
NODE_END_IMAGE = "18"  # added only when the take ends on a chosen frame
FPS = 16
MAX_EDGE = 832
MIN_SECONDS, MAX_SECONDS = 1.0, 5.0
JOB_TIMEOUT_SECONDS = 45 * 60
DEFAULT_NEGATIVE = (
    "static image, frozen frame, blurry, low quality, jpeg artifacts, distorted anatomy, "
    "extra limbs, malformed hands, flicker, subtitles, watermark, text"
)
ACTIVE_STATUSES = frozenset({"queued", "uploading", "running", "downloading"})
_TAKE_ID_RE = re.compile(r"^vid_[0-9a-f]{16}$")
_MODEL_SUFFIXES = (".safetensors", ".gguf", ".ckpt", ".pt", ".pth", ".bin", ".sft")

_running: set[str] = set()
_running_lock = threading.Lock()


class ComfyCloudError(RuntimeError):
    """A user-facing failure (no secrets in the message)."""


# ── API key ──────────────────────────────────────────────────────────────────

def get_api_key() -> str:
    try:
        import keyring

        return str(keyring.get_password(KEYRING_SERVICE, KEYRING_USER) or "")
    except Exception:  # a missing or broken credential backend reads as "not set"
        logger.warning("Could not read the Comfy Cloud key from the credential store", exc_info=True)
        return ""


def set_api_key(value: str) -> None:
    key = str(value or "").strip()
    if not key:
        raise ComfyCloudError("Paste an API key first.")
    if any(ch.isspace() for ch in key) or len(key) > 512:
        raise ComfyCloudError("That does not look like a Comfy API key.")
    import keyring

    keyring.set_password(KEYRING_SERVICE, KEYRING_USER, key)


def clear_api_key() -> None:
    import keyring

    try:
        keyring.delete_password(KEYRING_SERVICE, KEYRING_USER)
    except keyring.errors.PasswordDeleteError:
        pass


def status() -> dict[str, Any]:
    return {"configured": bool(get_api_key()), "template": TEMPLATE_NAME, "provider": "comfy-cloud"}


def _require_key() -> str:
    key = get_api_key()
    if not key:
        raise ComfyCloudError("Add your Comfy Cloud API key in Settings first.")
    return key


# ── template + connection check ──────────────────────────────────────────────

def load_template() -> dict[str, Any]:
    return json.loads(TEMPLATE_PATH.read_text(encoding="utf-8"))


def _enum_options(spec: Any) -> list[Any] | None:
    """Options of a combo input spec, in either ComfyUI object_info shape."""
    if not isinstance(spec, list) or not spec:
        return None
    head = spec[0]
    if isinstance(head, list):
        return head
    if head == "COMBO" and len(spec) > 1 and isinstance(spec[1], dict):
        options = spec[1].get("options")
        return options if isinstance(options, list) else None
    return None


def validate_template(template: dict[str, Any], object_info: dict[str, Any]) -> dict[str, list[str]]:
    """Name every node class or model file the template needs that the server lacks."""
    missing_nodes: list[str] = []
    missing_models: list[str] = []
    invalid_values: list[str] = []
    for node_id, node in template.items():
        class_type = str(node.get("class_type") or "")
        info = object_info.get(class_type)
        if not isinstance(info, dict):
            missing_nodes.append(class_type)
            continue
        specs: dict[str, Any] = {}
        for group in ("required", "optional"):
            specs.update((info.get("input") or {}).get(group) or {})
        for name, value in (node.get("inputs") or {}).items():
            if isinstance(value, list):  # a link to another node
                continue
            options = _enum_options(specs.get(name))
            if options is None or value in options or value == "":
                continue
            if str(value).lower().endswith(_MODEL_SUFFIXES):
                missing_models.append(str(value))
            else:
                invalid_values.append(f"{class_type}.{name}={value!r} (node {node_id})")
    return {"missing_nodes": missing_nodes, "missing_models": missing_models, "invalid_values": invalid_values}


def _http_error(response: httpx.Response) -> ComfyCloudError:
    messages = {
        401: "Comfy Cloud rejected the API key. Create a new one at platform.comfy.org.",
        402: "Your Comfy Cloud credits are used up.",
        429: "Comfy Cloud says the subscription is inactive or the account is rate limited.",
    }
    return ComfyCloudError(messages.get(response.status_code, f"Comfy Cloud returned HTTP {response.status_code}."))


def check_connection() -> dict[str, Any]:
    """Authenticate and check the video and image templates against the cloud's nodes and models."""
    from . import comfy_images

    key = _require_key()
    try:
        response = httpx.get(f"{CLOUD_BASE_URL}/api/object_info", headers={"X-API-Key": key}, timeout=60.0)
    except httpx.HTTPError as exc:
        raise ComfyCloudError(f"Could not reach Comfy Cloud: {type(exc).__name__}.") from exc
    if response.status_code != 200:
        raise _http_error(response)
    object_info = response.json()
    report: dict[str, list[str]] = {"missing_nodes": [], "missing_models": [], "invalid_values": []}
    for graph in (load_template(), _flf_graph(load_template()), *comfy_images.validation_graphs()):
        for key, values in validate_template(graph, object_info).items():
            report[key].extend(value for value in values if value not in report[key])
    return {
        "ok": not any(report.values()),
        "template": TEMPLATE_NAME,
        "image_templates": [comfy_images.T2I_TEMPLATE_NAME, comfy_images.EDIT_TEMPLATE_NAME],
        "node_count": len(object_info),
        **report,
    }


# ── prompt, size, length ─────────────────────────────────────────────────────

def compile_video_prompt(shot: Shot) -> str:
    """Motion-first prompt from the board's own fields (not the image prompt)."""
    design = shot.shot_design or {}
    story = str(design.get("story_beat") or shot.description or "").strip()
    parts = [story]
    for label, value in (
        ("Action", shot.action_note),
        ("Subject movement", design.get("subject_movement")),
        ("Camera movement", design.get("camera_movement")),
        ("Shot size", design.get("shot_size")),
        ("Lens", design.get("lens_intent")),
        ("Lighting", shot.lighting_note),
        ("Characters", shot.character_note),
        ("Dialogue", shot.dialogue),
    ):
        text = str(value or "").strip()
        if text and text.casefold() not in story.casefold():
            parts.append(f"{label}: {text}")
    return "\n".join(part for part in parts if part).strip()


def frame_size(canvas_width: int, canvas_height: int) -> tuple[int, int]:
    """Wan-friendly size: longest edge 832, multiples of 16, board aspect kept."""
    width = max(1, int(canvas_width or 1920))
    height = max(1, int(canvas_height or 1080))
    scale = MAX_EDGE / max(width, height)
    return (
        max(256, int(round(width * scale / 16)) * 16),
        max(256, int(round(height * scale / 16)) * 16),
    )


def frame_count(seconds: float) -> int:
    """Clamp to 1–5 s at 16 fps and snap to Wan's 4n+1 frame counts."""
    seconds = min(MAX_SECONDS, max(MIN_SECONDS, float(seconds or 3.0)))
    frames = int(round(seconds * FPS))
    return 4 * max(4, math.ceil((frames - 1) / 4)) + 1


# ── takes ────────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _record_path(project: Project, take_id: str) -> Path:
    if not _TAKE_ID_RE.match(str(take_id or "")):
        raise ValueError("Invalid video take id.")
    return generation_metadata_path(project, "video", f"{take_id}.json")


def _read(project: Project, take_id: str) -> dict[str, Any]:
    return json.loads(_record_path(project, take_id).read_text(encoding="utf-8"))


def _write(project: Project, record: dict[str, Any]) -> dict[str, Any]:
    record["updated_at"] = _now()
    path = _record_path(project, record["take_id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, record)
    return record


def board_frame_path(project: Project, shot: Shot) -> Path:
    for relative in (shot.preview_image_path, shot.image_path):
        if relative:
            path = resolve_project_relative_path(project, relative)
            if path.is_file():
                return path
    raise ComfyCloudError("This board has no image yet. Draw it or upload one before generating video.")


def create_take(
    app: Any,
    project: Project,
    shot: Shot,
    *,
    prompt: str,
    negative: str,
    seconds: float,
    end_shot: Shot | None = None,
) -> dict[str, Any]:
    _require_key()
    frame = board_frame_path(project, shot)
    if end_shot is not None and end_shot.shot_id == shot.shot_id:
        raise ComfyCloudError("Pick a different board as the end frame.")
    end_frame = board_frame_path(project, end_shot) if end_shot is not None else None
    width, height = frame_size(project.settings.get("canvas_width"), project.settings.get("canvas_height"))
    prompt = str(prompt or "").strip() or compile_video_prompt(shot)
    if not prompt:
        raise ComfyCloudError("Describe what happens in this shot (Story & action) before generating video.")
    take_id = f"vid_{uuid.uuid4().hex[:16]}"
    record = {
        "schema_version": 1,
        "take_id": take_id,
        "shot_id": shot.shot_id,
        "provider": "comfy-cloud",
        "template": FLF_TEMPLATE_NAME if end_frame else TEMPLATE_NAME,
        "mode": "flf" if end_frame else "i2v",
        "status": "queued",
        "prompt": prompt,
        "negative_prompt": str(negative or "").strip() or DEFAULT_NEGATIVE,
        "seconds": round(frame_count(seconds) / FPS, 3),
        "frames": frame_count(seconds),
        "fps": FPS,
        "width": width,
        "height": height,
        "seed": random.randint(0, 2**48),
        "source_frame": str(frame),
        "end_shot_id": end_shot.shot_id if end_shot is not None else "",
        "end_frame": str(end_frame) if end_frame else "",
        "job_id": "",
        "video_path": "",
        "error": "",
        "created_at": _now(),
    }
    _write(project, record)
    _start(app, project, take_id)
    return record


def list_takes(app: Any, project: Project, shot_id: str) -> list[dict[str, Any]]:
    directory = generation_metadata_path(project, "video")
    takes: list[dict[str, Any]] = []
    if directory.is_dir():
        for path in directory.glob("vid_*.json"):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if record.get("shot_id") != shot_id:
                continue
            if record.get("status") in ACTIVE_STATUSES and not _is_running(record["take_id"]):
                if record.get("job_id"):
                    _start(app, project, record["take_id"])  # resume after a restart
                else:
                    record.update(status="failed", error="Interrupted before it reached Comfy Cloud.")
                    _write(project, record)
            takes.append(record)
    takes.sort(key=lambda row: str(row.get("created_at") or ""), reverse=True)
    return takes


def video_file(project: Project, take_id: str) -> Path:
    record = _read(project, take_id)
    relative = str(record.get("video_path") or "")
    if record.get("status") != "succeeded" or not relative:
        raise ComfyCloudError("This take has no video yet.")
    return resolve_project_path(project, relative)


def delete_take(project: Project, take_id: str) -> None:
    record = _read(project, take_id)
    if record.get("status") in ACTIVE_STATUSES:
        raise ComfyCloudError("Wait for this take to finish before deleting it.")
    if record.get("video_path"):
        resolve_project_path(project, record["video_path"]).unlink(missing_ok=True)
    _record_path(project, take_id).unlink(missing_ok=True)


def _is_running(take_id: str) -> bool:
    with _running_lock:
        return take_id in _running


def _start(app: Any, project: Project, take_id: str) -> None:
    with _running_lock:
        if take_id in _running:
            return
        _running.add(take_id)
    threading.Thread(target=_run, args=(app, project, take_id), name=f"comfy-take-{take_id}", daemon=True).start()


def _flf_graph(graph: dict[str, Any]) -> dict[str, Any]:
    """Switch the template to first + last frame: same models, an extra end image."""
    graph = copy.deepcopy(graph)
    graph[NODE_I2V]["class_type"] = "WanFirstLastFrameToVideo"
    graph[NODE_I2V]["inputs"]["end_image"] = [NODE_END_IMAGE, 0]
    graph[NODE_END_IMAGE] = {"class_type": "LoadImage", "_meta": {"title": "End frame"}, "inputs": {"image": ""}}
    return graph


def _build_workflow(record: dict[str, Any]) -> dict[str, Any]:
    graph = copy.deepcopy(load_template())
    if record.get("end_frame"):
        graph = _flf_graph(graph)
    graph[NODE_POSITIVE]["inputs"]["text"] = record["prompt"]
    graph[NODE_NEGATIVE]["inputs"]["text"] = record["negative_prompt"]
    graph[NODE_I2V]["inputs"].update(width=record["width"], height=record["height"], length=record["frames"])
    for node_id in NODE_SAMPLERS:
        graph[node_id]["inputs"]["noise_seed"] = record["seed"]
    return graph


def _run(app: Any, project: Project, take_id: str) -> None:
    try:
        from comfy_sdk import Comfy

        record = _read(project, take_id)
        with Comfy(api_key=_require_key(), client_info="storyboarder", timeout=120.0) as client:
            if record.get("job_id"):
                job = client.jobs.get(record["job_id"])
            else:
                record.update(status="uploading")
                _write(project, record)
                workflow = client.workflows.from_json(_build_workflow(record))
                workflow.set_input(NODE_IMAGE, "image", client.assets.from_file(record["source_frame"]))
                if record.get("end_frame"):
                    workflow.set_input(NODE_END_IMAGE, "image", client.assets.from_file(record["end_frame"]))
                job = client.submit(workflow)
                record.update(status="running", job_id=job.id)
                _write(project, record)
            job.wait(timeout=JOB_TIMEOUT_SECONDS)
            if job.status != "succeeded":
                detail = job.error if isinstance(job.error, str) else (json.dumps(job.error)[:500] if job.error else "")
                record.update(status="failed", error=f"Comfy Cloud job {job.status}. {detail}".strip())
                _write(project, record)
                return
            outputs = job.get_outputs(NODE_OUTPUT) or list(job.outputs)
            if not outputs:
                record.update(status="failed", error="The job finished without a video output.")
                _write(project, record)
                return
            record.update(status="downloading")
            _write(project, record)
            _save_video(project, record, outputs[0])
    except Exception as exc:  # report every failure on the take itself
        logger.exception("Comfy Cloud video take %s failed", take_id)
        try:
            record = _read(project, take_id)
            record.update(status="failed", error=str(exc)[:500] or type(exc).__name__)
            _write(project, record)
        except Exception:
            logger.exception("Could not record the failure of take %s", take_id)
    finally:
        with _running_lock:
            _running.discard(take_id)


def _save_video(project: Project, record: dict[str, Any], output: Any) -> None:
    relative = generation_video_relative(project, record["take_id"])
    target = resolve_project_path(project, relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=str(target.parent), prefix=".tmp-", suffix=".mp4")
    os.close(fd)
    try:
        output.to_file(temporary)
        if os.path.getsize(temporary) <= 0:
            raise ComfyCloudError("Comfy Cloud returned an empty video.")
        with project_manager.PROJECT_LOCK:
            os.replace(temporary, target)
            record.update(status="succeeded", video_path=relative, error="", bytes=target.stat().st_size)
            _write(project, record)
    finally:
        Path(temporary).unlink(missing_ok=True)
