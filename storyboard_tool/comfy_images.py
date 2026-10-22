"""Comfy Cloud: generate board images (text → image, reference(s) → image).

An *image job* mirrors a video take (see ``comfy_cloud``): a JSON record under
the project's generation metadata (``generation/image/<job>.json``) run on a
daemon thread — upload references, submit, poll, download — and resumed from its
cloud job id after a restart. Outputs land in ``Images/Generated/<job>_<n>.png``
as candidates; a board only changes when a job is *applied*, which goes through
the same import path as a user image import.

- No references: Z-Image Turbo text → image (8 steps).
- 1–3 references: Qwen-Image-Edit 2511 with the Lightning 4-step LoRA. A
  reference is a board id (that board's current image) or the id of an image in
  the project reference library.
"""

from __future__ import annotations

import copy
import json
import logging
import os
import random
import re
import tempfile
import threading
import uuid
from pathlib import Path
from typing import Any

from PIL import Image

from . import comfy_cloud, project_manager
from .comfy_cloud import ComfyCloudError
from .models import Project, Shot
from .project_layout import generation_metadata_path, resolve_project_path
from .project_storage import atomic_write_json
from .reference_metadata import REFERENCE_IMAGE_EXTENSIONS
from .shot_files import resolve_project_relative_path

logger = logging.getLogger(__name__)

_WORKFLOWS = Path(__file__).resolve().parent / "assets" / "comfy_workflows"
T2I_TEMPLATE_PATH = _WORKFLOWS / "z_image_turbo_t2i_api.json"
EDIT_TEMPLATE_PATH = _WORKFLOWS / "qwen_image_edit_2511_api.json"
T2I_TEMPLATE_NAME = "Z-Image Turbo text-to-image (8-step)"
EDIT_TEMPLATE_NAME = "Qwen-Image-Edit 2511 references-to-image (Lightning 4-step)"

# Node ids inside the templates that Storyboarder fills in.
T2I_POSITIVE, T2I_LATENT, T2I_SAMPLER, T2I_OUTPUT = "5", "7", "8", "10"
EDIT_REFERENCES = ("7", "8", "9")
EDIT_ENCODERS = ("10", "11")  # positive, negative
EDIT_LATENT, EDIT_SAMPLER, EDIT_OUTPUT = "14", "15", "17"

T2I_LONG_EDGE = 1280
EDIT_LONG_EDGE = 1024
MAX_REFERENCES = 3
JOB_TIMEOUT_SECONDS = 20 * 60
ACTIVE_STATUSES = comfy_cloud.ACTIVE_STATUSES
_JOB_ID_RE = re.compile(r"^img_[0-9a-f]{16}$")

_running: set[str] = set()
_running_lock = threading.Lock()
_records_lock = threading.Lock()


# ── templates ────────────────────────────────────────────────────────────────

def load_t2i_template() -> dict[str, Any]:
    return json.loads(T2I_TEMPLATE_PATH.read_text(encoding="utf-8"))


def load_edit_template() -> dict[str, Any]:
    return json.loads(EDIT_TEMPLATE_PATH.read_text(encoding="utf-8"))


def validation_graphs() -> list[dict[str, Any]]:
    """Every graph an image job can submit, for ``comfy_cloud.check_connection``."""
    return [load_t2i_template(), load_edit_template()]


def _edit_graph(graph: dict[str, Any], reference_count: int) -> dict[str, Any]:
    """Drop the reference loaders (and encoder inputs) a job does not use."""
    if not 1 <= reference_count <= MAX_REFERENCES:
        raise ValueError("An edit job needs 1 to 3 references.")
    graph = copy.deepcopy(graph)
    for slot in range(reference_count, MAX_REFERENCES):
        graph.pop(EDIT_REFERENCES[slot], None)
        for encoder in EDIT_ENCODERS:
            graph[encoder]["inputs"].pop(f"image{slot + 1}", None)
    return graph


def build_workflow(record: dict[str, Any]) -> dict[str, Any]:
    if record["mode"] == "t2i":
        graph = load_t2i_template()
        graph[T2I_POSITIVE]["inputs"]["text"] = record["prompt"]
        graph[T2I_LATENT]["inputs"].update(width=record["width"], height=record["height"])
        graph[T2I_SAMPLER]["inputs"]["seed"] = record["seed"]
        return graph
    graph = _edit_graph(load_edit_template(), len(record["references"]))
    graph[EDIT_ENCODERS[0]]["inputs"]["prompt"] = record["prompt"]
    graph[EDIT_ENCODERS[1]]["inputs"]["prompt"] = record["negative_prompt"]
    graph[EDIT_LATENT]["inputs"].update(width=record["width"], height=record["height"])
    graph[EDIT_SAMPLER]["inputs"]["seed"] = record["seed"]
    return graph


def image_size(canvas_width: Any, canvas_height: Any, long_edge: int) -> tuple[int, int]:
    """Board aspect, the given long edge, both sides multiples of 16."""
    width = max(1, int(canvas_width or 1920))
    height = max(1, int(canvas_height or 1080))
    scale = long_edge / max(width, height)
    return (
        max(256, int(round(width * scale / 16)) * 16),
        max(256, int(round(height * scale / 16)) * 16),
    )


# ── records ──────────────────────────────────────────────────────────────────

def _record_path(project: Project, job_id: str) -> Path:
    if not _JOB_ID_RE.match(str(job_id or "")):
        raise ValueError("Invalid image job id.")
    return generation_metadata_path(project, "image", f"{job_id}.json")


def read_job(project: Project, job_id: str) -> dict[str, Any]:
    return _read_record_file(_record_path(project, job_id))


def _read_record_file(path: Path) -> dict[str, Any]:
    # Windows cannot replace a file another thread is reading: record reads and
    # writes take one lock so a poll never makes the worker's write fail.
    with _records_lock:
        return json.loads(path.read_text(encoding="utf-8"))


def _write(project: Project, record: dict[str, Any]) -> dict[str, Any]:
    record["updated_at"] = comfy_cloud._now()
    path = _record_path(project, record["job_id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    with _records_lock:
        atomic_write_json(path, record)
    return record


def output_relative(job_id: str, index: int) -> str:
    if not _JOB_ID_RE.match(str(job_id or "")) or index < 0:
        raise ValueError("Invalid image output.")
    return f"Images/Generated/{job_id}_{index}.png"


def resolve_reference(project: Project, ref_id: str) -> dict[str, str]:
    """A board id (its current image) or an image in the project reference library."""
    ref_id = str(ref_id or "").strip()
    if not ref_id:
        raise ComfyCloudError("A reference id is empty.")
    shot = next((item for item in project.shots if item.shot_id == ref_id), None)
    if shot is not None:
        try:
            path = comfy_cloud.board_frame_path(project, shot)
        except ComfyCloudError as exc:
            raise ComfyCloudError(f"Reference board {ref_id} has no image yet.") from exc
        return {"id": ref_id, "kind": "board", "path": str(path)}
    for link in project.settings.get("reference_links") or []:
        if not isinstance(link, dict) or str(link.get("id") or "") != ref_id:
            continue
        relative = str(link.get("path") or "")
        if Path(relative).suffix.lower() not in REFERENCE_IMAGE_EXTENSIONS:
            raise ComfyCloudError(f"Reference {ref_id} is not an image.")
        try:
            path = resolve_project_relative_path(project, relative)
        except ValueError as exc:
            raise ComfyCloudError(f"Reference {ref_id} has an invalid path.") from exc
        if not path.is_file():
            raise ComfyCloudError(f"Reference {ref_id} is missing on disk.")
        return {"id": ref_id, "kind": "reference", "path": str(path)}
    raise ComfyCloudError(f"Unknown reference {ref_id}: use a board id or a project reference image id.")


def create_job(
    app: Any,
    project: Project,
    shot: Shot,
    *,
    prompt: str,
    negative: str = "",
    references: list[str] | None = None,
    seed: int | None = None,
    apply: bool = False,
) -> dict[str, Any]:
    comfy_cloud._require_key()
    prompt = str(prompt or "").strip()
    if not prompt:
        raise ComfyCloudError("Write a prompt before generating an image.")
    ref_ids = [str(item or "").strip() for item in references or []]
    if len(ref_ids) > MAX_REFERENCES:
        raise ComfyCloudError("Use at most 3 references.")
    if len(set(ref_ids)) != len(ref_ids):
        raise ComfyCloudError("A reference is listed twice.")
    resolved = [resolve_reference(project, ref_id) for ref_id in ref_ids]
    mode = "edit" if resolved else "t2i"
    width, height = image_size(
        project.settings.get("canvas_width"),
        project.settings.get("canvas_height"),
        EDIT_LONG_EDGE if resolved else T2I_LONG_EDGE,
    )
    if seed is not None and not 0 <= int(seed) < 2**63:
        raise ComfyCloudError("Seed must be a non-negative integer.")
    job_id = f"img_{uuid.uuid4().hex[:16]}"
    record = {
        "schema_version": 1,
        "job_id": job_id,
        "shot_id": shot.shot_id,
        "provider": "comfy-cloud",
        "mode": mode,
        "template": EDIT_TEMPLATE_NAME if resolved else T2I_TEMPLATE_NAME,
        "status": "queued",
        "prompt": prompt,
        "negative_prompt": str(negative or "").strip(),
        "references": resolved,
        "width": width,
        "height": height,
        "seed": int(seed) if seed is not None else random.randint(0, 2**48),
        "apply": bool(apply),
        "cloud_job_id": "",
        "outputs": [],
        "applied_index": None,
        "applied_at": "",
        "error": "",
        "created_at": comfy_cloud._now(),
    }
    _write(project, record)
    _start(app, project, job_id)
    return record


def list_jobs(app: Any, project: Project, shot_id: str | None = None) -> list[dict[str, Any]]:
    directory = generation_metadata_path(project, "image")
    jobs: list[dict[str, Any]] = []
    if directory.is_dir():
        for path in directory.glob("img_*.json"):
            try:
                record = _read_record_file(path)
            except (OSError, json.JSONDecodeError):
                continue
            if shot_id is not None and record.get("shot_id") != shot_id:
                continue
            if record.get("status") in ACTIVE_STATUSES and not _is_running(record["job_id"]):
                if record.get("cloud_job_id"):
                    _start(app, project, record["job_id"])  # resume after a restart
                else:
                    record.update(status="failed", error="Interrupted before it reached Comfy Cloud.")
                    _write(project, record)
            jobs.append(record)
    jobs.sort(key=lambda row: str(row.get("created_at") or ""), reverse=True)
    return jobs


def output_file(project: Project, job_id: str, index: int) -> Path:
    record = read_job(project, job_id)
    outputs = record.get("outputs") or []
    if record.get("status") != "succeeded" or not 0 <= index < len(outputs):
        raise ComfyCloudError("This image job has no such output.")
    return resolve_project_path(project, outputs[index]["path"])


def mark_applied(project: Project, job_id: str, index: int) -> dict[str, Any]:
    record = read_job(project, job_id)
    record.update(applied_index=index, applied_at=comfy_cloud._now())
    return _write(project, record)


def delete_job(project: Project, job_id: str) -> None:
    record = read_job(project, job_id)
    if record.get("status") in ACTIVE_STATUSES:
        raise ComfyCloudError("Wait for this image job to finish before deleting it.")
    for output in record.get("outputs") or []:
        resolve_project_path(project, output["path"]).unlink(missing_ok=True)
    with _records_lock:
        _record_path(project, job_id).unlink(missing_ok=True)


# ── runner ───────────────────────────────────────────────────────────────────

def _is_running(job_id: str) -> bool:
    with _running_lock:
        return job_id in _running


def _start(app: Any, project: Project, job_id: str) -> None:
    with _running_lock:
        if job_id in _running:
            return
        _running.add(job_id)
    threading.Thread(target=_run, args=(app, project, job_id), name=f"comfy-image-{job_id}", daemon=True).start()


def _fail(project: Project, record: dict[str, Any], message: str) -> None:
    record.update(status="failed", error=message)
    _write(project, record)


def _run(app: Any, project: Project, job_id: str) -> None:
    try:
        from comfy_sdk import Comfy

        record = read_job(project, job_id)
        output_node = T2I_OUTPUT if record["mode"] == "t2i" else EDIT_OUTPUT
        with Comfy(api_key=comfy_cloud._require_key(), client_info="storyboarder", timeout=120.0) as client:
            if record.get("cloud_job_id"):
                job = client.jobs.get(record["cloud_job_id"])
            else:
                record.update(status="uploading")
                _write(project, record)
                workflow = client.workflows.from_json(build_workflow(record))
                for node_id, reference in zip(EDIT_REFERENCES, record.get("references") or []):
                    workflow.set_input(node_id, "image", client.assets.from_file(reference["path"]))
                job = client.submit(workflow)
                record.update(status="running", cloud_job_id=job.id)
                _write(project, record)
            job.wait(timeout=JOB_TIMEOUT_SECONDS)
            if job.status != "succeeded":
                detail = job.error if isinstance(job.error, str) else (json.dumps(job.error)[:500] if job.error else "")
                _fail(project, record, f"Comfy Cloud job {job.status}. {detail}".strip())
                return
            outputs = job.get_outputs(output_node) or list(job.outputs)
            if not outputs:
                _fail(project, record, "The job finished without an image output.")
                return
            record.update(status="downloading")
            _write(project, record)
            _save_outputs(project, record, outputs)
        if record.get("apply"):
            _auto_apply(app, project, record)
    except Exception as exc:  # report every failure on the job itself
        logger.exception("Comfy Cloud image job %s failed", job_id)
        try:
            record = read_job(project, job_id)
            if record.get("status") in ACTIVE_STATUSES:
                _fail(project, record, str(exc)[:500] or type(exc).__name__)
        except Exception:
            logger.exception("Could not record the failure of image job %s", job_id)
    finally:
        with _running_lock:
            _running.discard(job_id)


def _save_outputs(project: Project, record: dict[str, Any], outputs: list[Any]) -> None:
    saved: list[dict[str, Any]] = []
    targets: list[tuple[str, Path]] = []
    for index, output in enumerate(outputs):
        relative = output_relative(record["job_id"], index)
        target = resolve_project_path(project, relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(dir=str(target.parent), prefix=".tmp-", suffix=".png")
        os.close(fd)
        targets.append((temporary, target))
        output.to_file(temporary)
        if os.path.getsize(temporary) <= 0:
            raise ComfyCloudError("Comfy Cloud returned an empty image.")
        with Image.open(temporary) as image:  # also proves the bytes are an image
            width, height = image.size
        saved.append({"index": index, "path": relative, "width": width, "height": height,
                      "bytes": os.path.getsize(temporary)})
    try:
        with project_manager.PROJECT_LOCK:
            for temporary, target in targets:
                os.replace(temporary, target)
            record.update(status="succeeded", outputs=saved, error="")
            _write(project, record)
    finally:
        for temporary, _target in targets:
            Path(temporary).unlink(missing_ok=True)


def _auto_apply(app: Any, project: Project, record: dict[str, Any]) -> None:
    """``apply: true`` — put the first output on the board, as a user apply would."""
    from .backend_service import StoryboardBackendService

    if getattr(app.state, "project", None) is not project:
        record.update(error="Not applied: the project was closed before the image arrived.")
        _write(project, record)
        return
    try:
        StoryboardBackendService(app).method_apply_image_job(record["job_id"], 0)
    except Exception as exc:
        detail = getattr(exc, "detail", None) or str(exc) or type(exc).__name__
        logger.warning("Could not apply image job %s: %s", record["job_id"], detail)
        current = read_job(project, record["job_id"])
        current.update(error=f"Generated, but not applied: {detail}"[:500])
        _write(project, current)
