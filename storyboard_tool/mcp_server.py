"""STDIO MCP server that lets an agent use the running Storyboarder app.

The server is a thin HTTP client of the desktop backend: it discovers the running
app from the live-bridge file (base URL + per-launch API token) and maps each MCP
tool onto backend endpoints listed in ``ROUTES``. It never opens project files
itself, so agent edits go through the same mutation path as the UI and appear live.
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import mimetypes
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

SERVER_NAME = "storyboarder"
SERVER_VERSION = "0.2.0"
SUPPORTED_PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")

TOKEN_HEADER = "x-storyboarder-token"
NOT_RUNNING = "Open Storyboarder with a project first."
NO_PROJECT = "No project is open: start one with storyboard_new_project or open one with storyboard_open_project (storyboard_recent_projects lists recent ones)."
GRID_MAX_EDGE = 1600
BOARD_MAX_EDGE = 1280
MAX_GENERATION_ARTIFACTS = 8
HTTP_TIMEOUT_SECONDS = 120.0

# ── HTTP mapping ─────────────────────────────────────────────────────────────
# One line per backend endpoint. Contract tweaks at merge time belong here.
ROUTES: dict[str, tuple[str, str]] = {
    "project": ("GET", "/api/project"),
    "outline": ("GET", "/api/project/outline"),
    "grid": ("GET", "/api/project/grid.png"),
    "comfy_status": ("GET", "/api/comfy-cloud"),
    "add_shot": ("POST", "/api/shots"),
    "update_shot": ("PATCH", "/api/shots/{shot_id}"),
    "delete_shot": ("DELETE", "/api/shots/{shot_id}"),
    "reorder_shots": ("POST", "/api/shots/reorder"),
    "shot_image": ("GET", "/api/shots/{shot_id}/image"),
    "upload_shot_image": ("POST", "/api/shots/{shot_id}/image"),
    "create_image_job": ("POST", "/api/shots/{shot_id}/image-jobs"),
    "shot_image_jobs": ("GET", "/api/shots/{shot_id}/image-jobs"),
    "image_jobs": ("GET", "/api/image-jobs"),
    "image_job_output": ("GET", "/api/image-jobs/{job_id}/outputs/{index}"),
    "apply_image_job": ("POST", "/api/image-jobs/{job_id}/apply"),
    "create_video_take": ("POST", "/api/shots/{shot_id}/video-takes"),
    "shot_video_takes": ("GET", "/api/shots/{shot_id}/video-takes"),
    "render_sequence": ("POST", "/api/project/sequence/render"),
    "generation_requests": ("GET", "/api/generation/requests"),
    "new_project": ("POST", "/api/project/new"),
    "open_project": ("POST", "/api/project/open"),
    "recents": ("GET", "/api/app/recents"),
    "close_project": ("POST", "/api/app/close-project"),
    # Not in the backend yet (see docs/plans/2026-10-23-agent-mcp-and-cloud-images.md).
    "submit_generation_result": ("POST", "/api/generation/requests/{request_id}/results"),
}

# ShotUpdateRequest replaces every field it declares (missing ones fall back to
# defaults), so a board update reads the board and sends all of these back.
FULL_UPDATE_FIELDS = (
    "title", "scene", "sequence", "description", "action_note", "camera_note",
    "character_note", "dialogue", "lighting_note", "transition_note",
    "duration_seconds", "camera_data", "tags", "status",
)
TEXT_FIELDS = (
    "title", "scene", "description", "action_note", "camera_note", "character_note",
    "dialogue", "lighting_note", "transition_note", "status",
)


class ToolError(Exception):
    """A tool failure reported to the agent as an ``isError`` result."""


@dataclass
class HttpResponse:
    status: int
    content_type: str
    body: bytes

    def json(self) -> Any:
        return json.loads(self.body.decode("utf-8")) if self.body else {}


Transport = Callable[[str, str, dict[str, str], "bytes | None", float], HttpResponse]


class TransportUnavailable(Exception):
    """The app could not be reached at all (connection refused, timeout)."""


def urllib_transport(method: str, url: str, headers: dict[str, str], body: bytes | None, timeout: float) -> HttpResponse:
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return HttpResponse(response.status, response.headers.get("content-type", ""), response.read())
    except urllib.error.HTTPError as exc:
        return HttpResponse(exc.code, exc.headers.get("content-type", "") if exc.headers else "", exc.read() or b"")
    except (urllib.error.URLError, OSError) as exc:
        raise TransportUnavailable(str(getattr(exc, "reason", exc))) from exc


def default_bridge_path() -> Path:
    from . import live_bridge

    return live_bridge.global_bridge_file_path()


@dataclass
class Multipart:
    fields: dict[str, str] = field(default_factory=dict)
    files: list[tuple[str, str, bytes]] = field(default_factory=list)  # (field, filename, data)

    def encode(self) -> tuple[bytes, str]:
        boundary = f"storyboarder-{uuid.uuid4().hex}"
        out = io.BytesIO()
        for name, value in self.fields.items():
            out.write(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
            out.write(str(value).encode("utf-8") + b"\r\n")
        for name, filename, data in self.files:
            mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"
            safe_name = filename.replace('"', "_")
            out.write(
                f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{safe_name}"\r\n'
                f"Content-Type: {mime}\r\n\r\n".encode("utf-8")
            )
            out.write(data + b"\r\n")
        out.write(f"--{boundary}--\r\n".encode())
        return out.getvalue(), f"multipart/form-data; boundary={boundary}"


class StoryboarderClient:
    """Calls the running app. The bridge file is re-read per call: ports change on restart."""

    def __init__(self, transport: Transport | None = None, bridge_path: Path | None = None) -> None:
        self.transport = transport or urllib_transport
        self.bridge_path = bridge_path

    def connection(self) -> tuple[str, str]:
        path = self.bridge_path or default_bridge_path()
        try:
            bridge = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ToolError(f"Storyboarder is not running (no live bridge at {path}). {NOT_RUNNING}") from exc
        if not isinstance(bridge, dict) or not bridge.get("app_running"):
            raise ToolError(f"Storyboarder is not running. {NOT_RUNNING}")
        parsed = urllib.parse.urlsplit(str(bridge.get("bridge_url") or ""))
        if parsed.scheme and parsed.netloc:
            base = f"{parsed.scheme}://{parsed.netloc}"
        elif bridge.get("port"):
            base = f"http://127.0.0.1:{int(bridge['port'])}"
        else:
            raise ToolError(f"The Storyboarder live bridge has no address. {NOT_RUNNING}")
        return base, str(bridge.get("api_token") or "")

    def request(
        self,
        route: str,
        *,
        params: dict[str, Any] | None = None,
        query: dict[str, Any] | None = None,
        json_body: Any = None,
        multipart: Multipart | None = None,
    ) -> HttpResponse:
        method, template = ROUTES[route]
        path = template.format(**{key: urllib.parse.quote(str(value), safe="") for key, value in (params or {}).items()})
        clean_query = {key: value for key, value in (query or {}).items() if value not in (None, "")}
        if clean_query:
            path += "?" + urllib.parse.urlencode(clean_query)
        base, token = self.connection()
        headers = {"accept": "application/json, image/png, */*"}
        if token:
            headers[TOKEN_HEADER] = token
        body: bytes | None = None
        if multipart is not None:
            body, headers["content-type"] = multipart.encode()
        elif json_body is not None:
            body = json.dumps(json_body).encode("utf-8")
            headers["content-type"] = "application/json"
        elif method in {"POST", "PUT", "PATCH"}:
            body = b""
        try:
            response = self.transport(method, base + path, headers, body, HTTP_TIMEOUT_SECONDS)
        except TransportUnavailable as exc:
            raise ToolError(f"Storyboarder is not reachable at {base} ({exc}). {NOT_RUNNING}") from exc
        if response.status >= 400:
            raise ToolError(_error_text(method, path, response))
        return response

    def json(self, route: str, **kwargs: Any) -> Any:
        response = self.request(route, **kwargs)
        try:
            return response.json()
        except ValueError as exc:
            raise ToolError(f"{ROUTES[route][1]} returned a non-JSON response.") from exc


def _error_text(method: str, path: str, response: HttpResponse) -> str:
    detail: Any = ""
    try:
        payload = response.json()
        detail = payload.get("detail", payload) if isinstance(payload, dict) else payload
    except ValueError:
        detail = response.body[:300].decode("utf-8", "replace")
    if not isinstance(detail, str):
        detail = json.dumps(detail, ensure_ascii=False)
    if response.status in {404, 405} and detail in {"Not Found", "Method Not Allowed"}:
        detail += " (this Storyboarder version may not have this endpoint yet)"
    if detail == "No project opened.":
        detail += f" {NO_PROJECT}"
    return f"{method} {path} failed with HTTP {response.status}: {detail}"


# ── result content ───────────────────────────────────────────────────────────

@dataclass
class Content:
    """Explicit MCP content blocks (text and images) returned by a tool."""

    blocks: list[dict[str, Any]]


def _text_block(value: Any) -> dict[str, Any]:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2)
    return {"type": "text", "text": text}


def _image_block(response: HttpResponse, max_edge: int) -> dict[str, Any]:
    data = response.body
    mime = (response.content_type or "").split(";")[0].strip() or "image/png"
    try:
        from PIL import Image

        with Image.open(io.BytesIO(data)) as image:
            if max(image.size) > max_edge or mime not in {"image/png", "image/jpeg"}:
                image.thumbnail((max_edge, max_edge))
                out = io.BytesIO()
                image.convert("RGBA" if image.mode in {"RGBA", "LA", "P"} else "RGB").save(out, format="PNG")
                data, mime = out.getvalue(), "image/png"
    except Exception:
        # Pillow missing or an unreadable image: pass the bytes through unchanged.
        pass
    return {"type": "image", "data": base64.b64encode(data).decode("ascii"), "mimeType": mime}


# ── board helpers ────────────────────────────────────────────────────────────

def _board(shot: dict[str, Any], number: int | None = None) -> dict[str, Any]:
    prompt = shot.get("prompt_config") if isinstance(shot.get("prompt_config"), dict) else {}
    row: dict[str, Any] = {}
    if number is not None:
        row["number"] = number
    row.update({
        "shot_id": shot.get("shot_id", ""),
        "title": shot.get("title", ""),
        "description": shot.get("description", ""),
        "dialogue": shot.get("dialogue", ""),
        "duration_seconds": shot.get("duration_seconds"),
        "status": shot.get("status", ""),
        "has_image": bool(shot.get("preview_image_path") or shot.get("image_path")),
        "prompt": prompt.get("manual_prompt", ""),
        "prompt_extra": prompt.get("prompt_extra", ""),
        "negative_prompt": prompt.get("negative_prompt", ""),
    })
    return row


def _find_board(project: dict[str, Any], shot_id: str) -> tuple[int, dict[str, Any]]:
    for index, shot in enumerate(project.get("shots") or []):
        if shot.get("shot_id") == shot_id:
            return index + 1, shot
    raise ToolError(f"Board not found: {shot_id}")


def _require(args: dict[str, Any], key: str) -> str:
    value = str(args.get(key) or "").strip()
    if not value:
        raise ToolError(f"'{key}' is required.")
    return value


def _board_patch(shot: dict[str, Any], args: dict[str, Any]) -> dict[str, Any] | None:
    """Full ShotUpdateRequest body: the board's current values plus the agent's changes."""
    changes: dict[str, Any] = {}
    for key in TEXT_FIELDS:
        if args.get(key) is not None:
            changes[key] = str(args[key])
    if args.get("duration_seconds") is not None:
        changes["duration_seconds"] = float(args["duration_seconds"])
    if isinstance(args.get("tags"), list):
        changes["tags"] = [str(tag) for tag in args["tags"]]
    prompt_config = dict(shot.get("prompt_config") or {})
    prompt_changed = False
    if args.get("prompt") is not None:
        prompt_config["manual_prompt"] = str(args["prompt"])
        prompt_config["mode"] = "manual" if str(args["prompt"]).strip() else "auto"
        prompt_changed = True
    for key in ("prompt_extra", "negative_prompt"):
        if args.get(key) is not None:
            prompt_config[key] = str(args[key])
            prompt_changed = True
    if prompt_changed:
        changes["prompt_config"] = prompt_config
    if isinstance(args.get("shot_design"), dict) and args["shot_design"]:
        changes["shot_design"] = {**dict(shot.get("shot_design") or {}), **args["shot_design"]}
    if not changes:
        return None
    body = {key: shot[key] for key in FULL_UPDATE_FIELDS if key in shot}
    body.update(changes)
    return body


def _update(client: StoryboarderClient, shot: dict[str, Any], args: dict[str, Any]) -> dict[str, Any] | None:
    body = _board_patch(shot, args)
    if body is None:
        return None
    return client.json("update_shot", params={"shot_id": shot["shot_id"]}, json_body=body)


# ── tools ────────────────────────────────────────────────────────────────────

def tool_status(client: StoryboarderClient, args: dict[str, Any]) -> Any:
    try:
        client.connection()
    except ToolError as exc:
        return {"app_running": False, "project_open": False, "message": str(exc)}
    status: dict[str, Any] = {"app_running": True, "project_open": False}
    try:
        project = client.json("project")
        status.update(project_open=True, project_name=project.get("name", ""), board_count=len(project.get("shots") or []))
    except ToolError as exc:
        if "not reachable" in str(exc):
            return {"app_running": False, "project_open": False, "message": str(exc)}
        status["message"] = NO_PROJECT if "No project opened" in str(exc) else str(exc)
    try:
        comfy = client.json("comfy_status")
        status["comfy_cloud_configured"] = bool(comfy.get("configured"))
    except ToolError as exc:
        status["comfy_cloud_configured"] = None
        status.setdefault("message", str(exc))
    return status


def _opened(project: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": project.get("name", ""),
        "project_path": project.get("document_path") or project.get("project_json_path", ""),
        "board_count": len(project.get("shots") or []),
    }


def tool_new_project(client: StoryboarderClient, args: dict[str, Any]) -> Any:
    path = _require(args, "path")
    project_type = str(args.get("project_type") or "video")
    if project_type not in {"video", "comic"}:
        raise ToolError("project_type must be 'video' or 'comic'.")
    body: dict[str, Any] = {"path": path, "project_type": project_type}
    for key in ("canvas_width", "canvas_height"):
        if args.get(key) is not None:
            body[key] = int(args[key])
    return _opened(client.json("new_project", json_body=body))


def tool_open_project(client: StoryboarderClient, args: dict[str, Any]) -> Any:
    return _opened(client.json("open_project", json_body={"project_json_path": _require(args, "path")}))


def tool_recent_projects(client: StoryboarderClient, args: dict[str, Any]) -> Any:
    rows = client.json("recents").get("recents") or []
    return {"recents": [
        {
            "name": row.get("name", ""),
            "path": row.get("open_path") or row.get("path", ""),
            "boards": int(row.get("shot_count") or 0),
            "modified": (
                datetime.fromtimestamp(float(row["modified_ms"]) / 1000.0).isoformat(timespec="seconds")
                if row.get("modified_ms") else ""
            ),
            "exists": bool(row.get("exists")),
        }
        for row in rows
    ]}


def tool_close_project(client: StoryboarderClient, args: dict[str, Any]) -> Any:
    return {"closed": bool(client.json("close_project").get("closed"))}


def tool_outline(client: StoryboarderClient, args: dict[str, Any]) -> Any:
    return client.json("outline", query={"route_id": args.get("route_id")})


def tool_grid(client: StoryboarderClient, args: dict[str, Any]) -> Any:
    max_edge = min(int(args.get("max_edge") or GRID_MAX_EDGE), GRID_MAX_EDGE)
    response = client.request(
        "grid",
        query={"route_id": args.get("route_id"), "columns": args.get("columns"), "max_edge": max_edge},
    )
    blocks = [_image_block(response, GRID_MAX_EDGE)]
    try:
        outline = client.json("outline", query={"route_id": args.get("route_id")})
        boards = outline.get("boards") if isinstance(outline, dict) else None
        if isinstance(boards, list):
            lines = [
                f"{row.get('number', i + 1)}. {row.get('title') or '(untitled)'} "
                f"[{row.get('shot_id', '')}] {row.get('duration_seconds', '')}s"
                + ("" if row.get("has_image", True) else " (no image)")
                for i, row in enumerate(boards)
            ]
            blocks.insert(0, _text_block("Board grid:\n" + "\n".join(lines)))
    except ToolError:
        pass
    return Content(blocks)


def tool_board_image(client: StoryboarderClient, args: dict[str, Any]) -> Any:
    shot_id = _require(args, "shot_id")
    response = client.request("shot_image", params={"shot_id": shot_id})
    return Content([_text_block(f"Board {shot_id}"), _image_block(response, BOARD_MAX_EDGE)])


def tool_add_board(client: StoryboarderClient, args: dict[str, Any]) -> Any:
    after = str(args.get("after_shot_id") or "").strip() or None
    created = client.json("add_shot", json_body={"after_shot_id": after})
    shot = created.get("shot") or {}
    project = _update(client, shot, args) or created
    number, shot = _find_board(project, shot.get("shot_id", ""))
    return {"board": _board(shot, number), "board_count": len(project.get("shots") or [])}


def tool_update_board(client: StoryboarderClient, args: dict[str, Any]) -> Any:
    shot_id = _require(args, "shot_id")
    _number, shot = _find_board(client.json("project"), shot_id)
    project = _update(client, shot, args)
    if project is None:
        raise ToolError("Nothing to update: pass at least one field to change.")
    number, shot = _find_board(project, shot_id)
    return {"board": _board(shot, number)}


def tool_delete_board(client: StoryboarderClient, args: dict[str, Any]) -> Any:
    shot_id = _require(args, "shot_id")
    project = client.json("delete_shot", params={"shot_id": shot_id})
    return {"deleted": shot_id, "board_count": len(project.get("shots") or [])}


def tool_reorder_boards(client: StoryboarderClient, args: dict[str, Any]) -> Any:
    shot_ids = args.get("shot_ids")
    if not isinstance(shot_ids, list) or not shot_ids:
        raise ToolError("'shot_ids' must be a non-empty list of board ids.")
    project = client.json("reorder_shots", json_body={"shot_ids": [str(item) for item in shot_ids]})
    return {"boards": [
        {"number": index + 1, "shot_id": shot.get("shot_id"), "title": shot.get("title", "")}
        for index, shot in enumerate(project.get("shots") or [])
    ]}


def tool_set_board_image(client: StoryboarderClient, args: dict[str, Any]) -> Any:
    shot_id = _require(args, "shot_id")
    path = Path(_require(args, "path")).expanduser()
    if not path.is_file():
        raise ToolError(f"Image file not found: {path}")
    upload = Multipart(files=[("file", path.name, path.read_bytes())])
    project = client.json("upload_shot_image", params={"shot_id": shot_id}, multipart=upload)
    number, shot = _find_board(project, shot_id)
    return {"board": _board(shot, number)}


def tool_generate_image(client: StoryboarderClient, args: dict[str, Any]) -> Any:
    shot_id = _require(args, "shot_id")
    body: dict[str, Any] = {"prompt": _require(args, "prompt")}
    for key in ("negative_prompt", "references", "seed", "apply"):
        if args.get(key) is not None:
            body[key] = args[key]
    return client.json("create_image_job", params={"shot_id": shot_id}, json_body=body)


def tool_image_jobs(client: StoryboarderClient, args: dict[str, Any]) -> Any:
    shot_id = str(args.get("shot_id") or "").strip()
    if shot_id:
        return client.json("shot_image_jobs", params={"shot_id": shot_id})
    return client.json("image_jobs")


def tool_image_candidate(client: StoryboarderClient, args: dict[str, Any]) -> Any:
    job_id = _require(args, "job_id")
    index = int(args.get("index") or 0)
    response = client.request("image_job_output", params={"job_id": job_id, "index": index})
    return Content([_text_block(f"Image job {job_id} output {index}"), _image_block(response, BOARD_MAX_EDGE)])


def tool_apply_image(client: StoryboarderClient, args: dict[str, Any]) -> Any:
    job_id = _require(args, "job_id")
    return client.json("apply_image_job", params={"job_id": job_id}, json_body={"index": int(args.get("index") or 0)})


def tool_generate_video(client: StoryboarderClient, args: dict[str, Any]) -> Any:
    shot_id = _require(args, "shot_id")
    body: dict[str, Any] = {}
    for key in ("prompt", "negative_prompt", "end_shot_id"):
        if args.get(key):
            body[key] = str(args[key])
    if args.get("seconds") is not None:
        body["seconds"] = float(args["seconds"])
    return client.json("create_video_take", params={"shot_id": shot_id}, json_body=body)


def tool_video_takes(client: StoryboarderClient, args: dict[str, Any]) -> Any:
    shot_id = str(args.get("shot_id") or "").strip()
    if shot_id:
        return {"takes": client.json("shot_video_takes", params={"shot_id": shot_id}).get("takes", [])}
    takes: list[dict[str, Any]] = []
    for shot in client.json("project").get("shots") or []:
        takes.extend(client.json("shot_video_takes", params={"shot_id": shot["shot_id"]}).get("takes", []))
    return {"takes": takes}


def tool_render_sequence(client: StoryboarderClient, args: dict[str, Any]) -> Any:
    body = {key: args[key] for key in ("route_id", "shot_ids", "takes") if args.get(key)}
    return client.json("render_sequence", json_body=body)


def tool_list_generation_requests(client: StoryboarderClient, args: dict[str, Any]) -> Any:
    query = {
        "shot_id": args.get("shot_id"),
        "destination": args.get("destination") or "codex",
        "status": args.get("status"),
    }
    return {"requests": client.json("generation_requests", query=query).get("requests", [])}


def tool_get_generation_request(client: StoryboarderClient, args: dict[str, Any]) -> Any:
    request_id = _require(args, "request_id")
    # No single-request endpoint yet: the list rows carry the full immutable package.
    for status in ("", "cancelled"):
        for row in client.json("generation_requests", query={"status": status}).get("requests", []):
            if row.get("request_id") == request_id:
                return row
    raise ToolError(f"Generation request not found: {request_id}")


def tool_submit_generation_result(client: StoryboarderClient, args: dict[str, Any]) -> Any:
    request_id = _require(args, "request_id")
    paths = args.get("artifact_paths")
    if not isinstance(paths, list) or not 1 <= len(paths) <= MAX_GENERATION_ARTIFACTS:
        raise ToolError(f"artifact_paths must list 1 to {MAX_GENERATION_ARTIFACTS} image paths.")
    upload = Multipart(fields={"summary": str(args.get("summary") or "")})
    for raw in paths:
        path = Path(str(raw)).expanduser()
        if not path.is_file():
            raise ToolError(f"Artifact not found: {path}")
        upload.files.append(("files", path.name, path.read_bytes()))
    result = client.json("submit_generation_result", params={"request_id": request_id}, multipart=upload)
    return {
        "result": result,
        "next_step": "Storyboarder imports this candidate into the matching board for review.",
    }


# ── tool catalog ─────────────────────────────────────────────────────────────

CREDIT_NOTE = "Costs Comfy Cloud credits (billed to the Owner's account): call only when needed and avoid retry loops."
_READ = {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False}
_WRITE = {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}
_DESTRUCTIVE = {"readOnlyHint": False, "destructiveHint": True, "openWorldHint": False}
_CLOUD = {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True}


def _schema(properties: dict[str, Any] | None = None, required: list[str] | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "object", "properties": properties or {}, "additionalProperties": False}
    if required:
        schema["required"] = required
    return schema


_STR = {"type": "string"}
_SHOT_ID = {"type": "string", "description": "Board id (shot_id) from storyboard_outline."}
_ROUTE_ID = {"type": "string", "description": "Story route id; omit for the main route."}
_BOARD_FIELDS: dict[str, Any] = {
    "title": _STR,
    "description": {"type": "string", "description": "Story & action: what happens in the board."},
    "dialogue": _STR,
    "duration_seconds": {"type": "number", "exclusiveMinimum": 0},
    "action_note": _STR,
    "camera_note": _STR,
    "character_note": _STR,
    "lighting_note": _STR,
    "transition_note": _STR,
    "scene": {"type": "string", "description": "Free-text scene label."},
    "status": {"type": "string", "description": "Board status, e.g. Draft."},
    "tags": {"type": "array", "items": {"type": "string"}},
    "prompt": {"type": "string", "description": "Manual image prompt for the board; empty string returns to the automatic prompt."},
    "prompt_extra": {"type": "string", "description": "Extra text appended to the automatic prompt."},
    "negative_prompt": _STR,
    "shot_design": {
        "type": "object",
        "description": "Partial shot design merged into the board's, e.g. {\"camera_movement\": \"slow push in\", \"subject_movement\": \"she turns\"} (used by video prompts).",
    },
}


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    schema: dict[str, Any]
    annotations: dict[str, Any]
    handler: Callable[[StoryboarderClient, dict[str, Any]], Any]

    def spec(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description, "inputSchema": self.schema, "annotations": self.annotations}


TOOL_LIST: list[Tool] = [
    Tool("storyboard_status", "Is Storyboarder running, which project is open, how many boards, and is Comfy Cloud configured. Free.",
         _schema(), _READ, tool_status),
    Tool("storyboard_new_project",
         "Create a new project and open it in the user's Storyboarder window, replacing the project shown there (the current one is saved first). "
         "path is the requested <parent>/<Name>.sbd; <parent> must exist; the app creates the folder <parent>/<Name>/ holding <Name>.sbd. Returns name, project_path and board_count. Free.",
         _schema({
             "path": {"type": "string", "description": "Requested document path, e.g. D:/Boards/MyFilm.sbd (creates D:/Boards/MyFilm/MyFilm.sbd)."},
             "project_type": {"type": "string", "enum": ["video", "comic"], "default": "video"},
             "canvas_width": {"type": "integer", "minimum": 1, "description": "Board canvas width in px (default 1920)."},
             "canvas_height": {"type": "integer", "minimum": 1, "description": "Board canvas height in px (default 1080)."},
         }, ["path"]), {**_WRITE, "idempotentHint": False}, tool_new_project),
    Tool("storyboard_open_project",
         "Open an existing project in the user's Storyboarder window, replacing the project shown there (the current one is saved first). Returns name, project_path and board_count. Free.",
         _schema({"path": {"type": "string", "description": "A .sbd document or a project folder."}}, ["path"]),
         _WRITE, tool_open_project),
    Tool("storyboard_recent_projects", "Recently opened projects (name, path to pass to storyboard_open_project, board count, last modified, whether it still exists). Free.",
         _schema(), _READ, tool_recent_projects),
    Tool("storyboard_close_project", "Close the open project (saving it) and return the user's Storyboarder window to its Home screen. Free.",
         _schema(), _WRITE, tool_close_project),
    Tool("storyboard_outline", "Project outline as JSON: per board in route order its id, number, title, description, dialogue, duration, prompt fields, has_image, latest image job and video take status. Free.",
         _schema({"route_id": _ROUTE_ID}), _READ, tool_outline),
    Tool("storyboard_grid", "Numbered contact-sheet image of the boards (long edge <= 1600 px) plus a text legend. Free.",
         _schema({
             "route_id": _ROUTE_ID,
             "columns": {"type": "integer", "minimum": 1, "maximum": 12},
             "max_edge": {"type": "integer", "minimum": 256, "maximum": GRID_MAX_EDGE},
         }), _READ, tool_grid),
    Tool("storyboard_board_image", "One board's current image (long edge <= 1280 px). Free.",
         _schema({"shot_id": _SHOT_ID}, ["shot_id"]), _READ, tool_board_image),
    Tool("storyboard_add_board", "Create a board (after after_shot_id, or at the end) and set its fields; returns the board. Free.",
         _schema({"after_shot_id": {"type": "string", "description": "Insert after this board; omit to append."}, **_BOARD_FIELDS}),
         {**_WRITE, "idempotentHint": False}, tool_add_board),
    Tool("storyboard_update_board", "Change a board's text fields, duration, prompt fields or shot design. Only the fields you pass change. Free.",
         _schema({"shot_id": _SHOT_ID, **_BOARD_FIELDS}, ["shot_id"]), _WRITE, tool_update_board),
    Tool("storyboard_delete_board", "Delete a board (undoable in the app). Free.",
         _schema({"shot_id": _SHOT_ID}, ["shot_id"]), _DESTRUCTIVE, tool_delete_board),
    Tool("storyboard_reorder_boards", "Set the board order: pass every board id in the new order. Free.",
         _schema({"shot_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1}}, ["shot_ids"]), _WRITE, tool_reorder_boards),
    Tool("storyboard_set_board_image", "Put a local image file (PNG/JPEG/WebP made by you or downloaded) onto a board, replacing its image like a user import. The file is read here and uploaded; Storyboarder never reads your path. Free.",
         _schema({"shot_id": _SHOT_ID, "path": {"type": "string", "description": "Local image file path on this machine."}}, ["shot_id", "path"]),
         _WRITE, tool_set_board_image),
    Tool("storyboard_generate_image",
         "Generate board image candidates on Comfy Cloud: text-to-image (Z-Image Turbo) without references, reference-to-image (Qwen-Image-Edit, up to 3 references) with them. Returns a job to poll with storyboard_image_jobs. Nothing replaces the board image until applied (or apply=true). " + CREDIT_NOTE,
         _schema({
             "shot_id": _SHOT_ID,
             "prompt": _STR,
             "negative_prompt": _STR,
             "references": {"type": "array", "items": {"type": "string"}, "maxItems": 3,
                            "description": "Board ids (their current image) and/or project reference asset ids."},
             "seed": {"type": "integer", "minimum": 0},
             "apply": {"type": "boolean", "description": "Apply the first output to the board when the job succeeds."},
         }, ["shot_id", "prompt"]), _CLOUD, tool_generate_image),
    Tool("storyboard_image_jobs", "Poll image generation jobs, for one board or the whole project. Free.",
         _schema({"shot_id": _SHOT_ID}), _READ, tool_image_jobs),
    Tool("storyboard_image_candidate", "View one output image of a finished image job before applying it. Free.",
         _schema({"job_id": _STR, "index": {"type": "integer", "minimum": 0, "default": 0}}, ["job_id"]), _READ, tool_image_candidate),
    Tool("storyboard_apply_image", "Make one output of a finished image job the board's image (like a user import; undoable). Free.",
         _schema({"job_id": _STR, "index": {"type": "integer", "minimum": 0, "default": 0}}, ["job_id"]), _WRITE, tool_apply_image),
    Tool("storyboard_generate_video",
         "Start a video take for a board on Comfy Cloud (Wan 2.2 image-to-video from the board image; with end_shot_id, a first+last-frame move to that board's image). Prompt defaults to the board's story and shot design. Returns the take; poll with storyboard_video_takes. " + CREDIT_NOTE,
         _schema({
             "shot_id": _SHOT_ID,
             "prompt": _STR,
             "negative_prompt": _STR,
             "seconds": {"type": "number", "minimum": 0.5, "maximum": 10, "description": "Defaults to the board duration."},
             "end_shot_id": {"type": "string", "description": "Board whose image is the last frame."},
         }, ["shot_id"]), _CLOUD, tool_generate_video),
    Tool("storyboard_video_takes", "Poll video takes for one board, or every board when shot_id is omitted. Free.",
         _schema({"shot_id": _SHOT_ID}), _READ, tool_video_takes),
    Tool("storyboard_render_sequence",
         "Render one MP4 from each board's chosen succeeded video take, in board order (boards without a take become stills for their duration), into the project's Exports folder. Returns the path, duration and per-board list. Local ffmpeg, free.",
         _schema({
             "route_id": _ROUTE_ID,
             "shot_ids": {"type": "array", "items": {"type": "string"}, "description": "Limit to these boards."},
             "takes": {"type": "object", "additionalProperties": {"type": "string"},
                       "description": "shot_id -> take_id overrides; default is each board's newest succeeded take."},
         }), {**_WRITE, "idempotentHint": False}, tool_render_sequence),
    Tool("storyboard_list_generation_requests", "List Storyboarder generation requests, normally Codex handoffs waiting for work. Free.",
         _schema({
             "shot_id": {"type": "string", "description": "Optional board id filter."},
             "destination": {"type": "string", "enum": ["codex", "queue"], "default": "codex"},
             "status": {"type": "string", "enum": ["queued", "needs-review", "completed", "failed", "cancelled"]},
         }), _READ, tool_list_generation_requests),
    Tool("storyboard_get_generation_request", "Fetch one complete board generation package by request id. Free.",
         _schema({"request_id": _STR}, ["request_id"]), _READ, tool_get_generation_request),
    Tool("storyboard_submit_generation_result",
         "Upload generated image files as the result of a generation request; Storyboarder imports them as a candidate for review. Free.",
         _schema({
             "request_id": _STR,
             "artifact_paths": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": MAX_GENERATION_ARTIFACTS},
             "summary": _STR,
         }, ["request_id", "artifact_paths"]), {**_WRITE, "idempotentHint": False}, tool_submit_generation_result),
]
TOOLS_BY_NAME = {tool.name: tool for tool in TOOL_LIST}
TOOLS: list[dict[str, Any]] = [tool.spec() for tool in TOOL_LIST]

INSTRUCTIONS = (
    "Storyboarder must be running; check with storyboard_status. If no project is open, start one with storyboard_new_project "
    "or open one with storyboard_open_project (these switch the project shown in the user's app window). "
    "Read the board with storyboard_outline and storyboard_grid, edit boards with the add/update/delete/reorder tools, "
    "put your own images on boards with storyboard_set_board_image, generate images and video takes on Comfy Cloud "
    "(these spend the Owner's credits), poll jobs, and assemble a cut with storyboard_render_sequence. "
    "Every change goes through the app and appears live in its UI. Never edit project files directly."
)


def call_tool(name: str, arguments: dict[str, Any], client: StoryboarderClient) -> dict[str, Any]:
    tool = TOOLS_BY_NAME.get(name)
    if tool is None:
        return {"content": [_text_block({"error": f"Unknown tool: {name}"})], "isError": True}
    try:
        value = tool.handler(client, arguments)
    except ToolError as exc:
        return {"content": [_text_block({"error": str(exc)})], "isError": True}
    except (TypeError, ValueError, KeyError, OSError) as exc:
        return {"content": [_text_block({"error": f"{type(exc).__name__}: {exc}"})], "isError": True}
    blocks = value.blocks if isinstance(value, Content) else [_text_block(value)]
    return {"content": blocks, "isError": False}


def handle_message(message: dict[str, Any], *, client: StoryboarderClient | None = None) -> dict[str, Any] | None:
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
                "instructions": INSTRUCTIONS,
            },
        }
    if method == "ping":
        return {"jsonrpc": "2.0", "id": request_id, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": TOOLS}}
    if method == "tools/call":
        params = message.get("params") if isinstance(message.get("params"), dict) else {}
        arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
        result = call_tool(str(params.get("name") or ""), arguments, client or StoryboarderClient())
        return {"jsonrpc": "2.0", "id": request_id, "result": result}
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Storyboarder MCP server (HTTP client of the running app)")
    parser.add_argument("--bridge-file", default="", help="Live-bridge JSON to discover the app (default: the app's global bridge file).")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    client = StoryboarderClient(bridge_path=Path(args.bridge_file).expanduser() if args.bridge_file else None)
    stdin = io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8")
    stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", newline="\n")
    for raw_line in stdin:
        line = raw_line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
            if not isinstance(message, dict):
                raise ValueError("JSON-RPC message must be an object.")
            response = handle_message(message, client=client)
        except ValueError as exc:
            response = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": str(exc)}}
        if response is not None:
            stdout.write(json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n")
            stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
