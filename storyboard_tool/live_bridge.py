from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import Project, Shot
from .project_manager import get_canvas_color, get_shot_dir

LIVE_BRIDGE_VERSION = 1
LIVE_BRIDGE_FILENAME = "storyboard_live_bridge.json"
PLUGIN_HEARTBEAT_FILENAME = "storyboard_plugin_heartbeat.json"
DEFAULT_PORT = 8000


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def global_bridge_dir() -> Path:
    if sys.platform == "win32":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support"
    else:
        root = Path.home() / ".local" / "share"
    return root / "StoryboardTool"


def shared_bridge_dir() -> Path:
    """Fixed path readable by Photoshop UXP without HTTP."""
    if sys.platform == "win32":
        return Path("C:/Users/Public/StoryboardTool")
    return global_bridge_dir()


def global_bridge_file_path() -> Path:
    return global_bridge_dir() / LIVE_BRIDGE_FILENAME


def shared_bridge_file_path() -> Path:
    return shared_bridge_dir() / LIVE_BRIDGE_FILENAME


def plugin_heartbeat_file_path() -> Path:
    return shared_bridge_dir() / PLUGIN_HEARTBEAT_FILENAME


def read_plugin_heartbeat_mtime() -> float:
    path = plugin_heartbeat_file_path()
    if not path.is_file():
        return 0.0
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict) and payload.get("at"):
            parsed = datetime.fromisoformat(str(payload["at"]).replace("Z", "+00:00"))
            return parsed.timestamp()
    except (OSError, ValueError, json.JSONDecodeError):
        pass
    return path.stat().st_mtime


def build_payload(
    *,
    project: Project | None,
    selected_shot_id: str = "",
    port: int = DEFAULT_PORT,
) -> dict[str, Any]:
    shot: Shot | None = None
    if project and selected_shot_id:
        shot = next((item for item in project.shots if item.shot_id == selected_shot_id), None)

    project_root = str(project.root_path) if project else ""
    shot_folder = ""
    source_file_path = ""
    if project and shot is not None:
        shot_folder = str(get_shot_dir(project, shot))
        source_file_path = shot.source_file_path or ""

    bridge_url = f"http://127.0.0.1:{port}/api/bridge/live"
    shared_path = str(shared_bridge_file_path())
    return {
        "version": LIVE_BRIDGE_VERSION,
        "app_running": True,
        "connected": project is not None,
        "updated_at": _now_iso(),
        "port": port,
        "bridge_url": bridge_url,
        "global_bridge_path": str(global_bridge_file_path()),
        "shared_bridge_path": shared_path,
        "plugin_heartbeat_path": str(plugin_heartbeat_file_path()),
        "project_root": project_root,
        "project_json_path": str(project.json_path) if project else "",
        "project_name": project.name if project else "",
        "canvas_background_color": get_canvas_color(project) if project else "#E8E8E8",
        "selected_shot_id": selected_shot_id if project else "",
        "shot_folder": shot_folder,
        "source_file_path": source_file_path,
        "shot_count": len(project.shots) if project else 0,
    }


def write_payload_files(base_dir: Path, project: Project | None, payload: dict[str, Any]) -> None:
    text = json.dumps(payload, indent=2)
    sessions_dir = base_dir / "Sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    (sessions_dir / LIVE_BRIDGE_FILENAME).write_text(text, encoding="utf-8")

    global_dir = global_bridge_dir()
    global_dir.mkdir(parents=True, exist_ok=True)
    global_bridge_file_path().write_text(text, encoding="utf-8")

    shared_dir = shared_bridge_dir()
    shared_dir.mkdir(parents=True, exist_ok=True)
    shared_bridge_file_path().write_text(text, encoding="utf-8")

    if project is not None:
        (project.root_path / LIVE_BRIDGE_FILENAME).write_text(text, encoding="utf-8")


def publish(
    base_dir: Path,
    project: Project | None,
    *,
    selected_shot_id: str = "",
    port: int = DEFAULT_PORT,
) -> dict[str, Any]:
    payload = build_payload(project=project, selected_shot_id=selected_shot_id, port=port)
    write_payload_files(base_dir, project, payload)
    return payload


def server_identity_url(host: str, port: int) -> str:
    return f"http://{host}:{port}/api/bridge/status"


def is_storyboard_server(host: str, port: int, timeout: float = 1.5) -> bool:
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(server_identity_url(host, port), timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return bool(payload.get("app_running"))
    except urllib.error.HTTPError as exc:
        return exc.code != 404
    except Exception:
        return False


def resolve_server_port(host: str = "127.0.0.1", preferred: int = DEFAULT_PORT) -> int:
    """Pick a free port, skipping stale listeners that are not this app."""
    import socket

    for port in range(preferred, preferred + 50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind((host, port))
                return port
            except OSError:
                if is_storyboard_server(host, port):
                    raise RuntimeError(
                        f"Port {port} is already used by Storyboard Tool. "
                        "Close the other Storyboard window and try again."
                    )
                continue
    raise RuntimeError(f"No free Storyboard Tool port found near {preferred}")
