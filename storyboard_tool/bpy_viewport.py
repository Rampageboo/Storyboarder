"""Managed headless-Blender viewport for the built-in Scene3D workspace."""

from __future__ import annotations

import json
import secrets
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from .external_tools import ensure_project_blend_file
from .models import Project
from .system_utils import detect_blender_paths, resolve_blender_executable


WORKER_SCRIPT = Path(__file__).resolve().parent / "blender_worker" / "worker.py"
WORKER_TOKEN_HEADER = "X-Storyboarder-Worker-Token"


class BpyViewportError(RuntimeError):
    pass


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def project_blend_path(project: Project) -> Path:
    """Resolve the active Scene3D .blend, falling back to the project template."""
    from . import scene3d

    active = scene3d.active_scene(project)
    relative = str((active or {}).get("blend_file_path") or "").strip()
    if not relative:
        return ensure_project_blend_file(project).resolve()
    root = project.root_path.resolve()
    candidate = (root / relative).resolve()
    if candidate != root and root not in candidate.parents:
        raise BpyViewportError("Blender scene path must stay inside the project.")
    if candidate.suffix.lower() != ".blend":
        raise BpyViewportError("The active built-in Blender scene must be a .blend file.")
    if not candidate.is_file():
        raise BpyViewportError(f"Blender scene not found: {relative}")
    return candidate


class BpyViewportManager:
    """Own at most one warm, single-threaded bpy worker for the active project."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._process: subprocess.Popen[bytes] | None = None
        self._blend_path: Path | None = None
        self._port = 0
        self._token = ""

    @property
    def running(self) -> bool:
        process = self._process
        return process is not None and process.poll() is None

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "running": self.running,
                "blend_path": str(self._blend_path or ""),
                "engine": "bpy",
            }

    def start(self, project: Project) -> dict[str, Any]:
        with self._lock:
            blend_path = project_blend_path(project)
            if self.running and self._blend_path == blend_path:
                return self.status()
            self.stop()

            configured = str(project.settings.get("blender_path", "")).strip()
            if not configured:
                candidates = detect_blender_paths()
                configured = candidates[0] if candidates else ""
            if not configured:
                raise BpyViewportError(
                    "Blender is required for the built-in viewport. Configure blender.exe in Settings."
                )
            try:
                executable = resolve_blender_executable(configured)
            except (FileNotFoundError, ValueError) as exc:
                raise BpyViewportError(str(exc)) from exc
            if not WORKER_SCRIPT.is_file():
                raise BpyViewportError(f"Bundled Blender worker is missing: {WORKER_SCRIPT}")

            self._port = _free_loopback_port()
            self._token = secrets.token_urlsafe(24)
            args = [
                str(executable),
                "--factory-startup",
                "--background",
                str(blend_path),
                "--python",
                str(WORKER_SCRIPT),
                "--",
                "--port",
                str(self._port),
                "--token",
                self._token,
            ]
            kwargs: dict[str, Any] = {
                "stdin": subprocess.DEVNULL,
                "stdout": subprocess.DEVNULL,
                "stderr": subprocess.DEVNULL,
            }
            if sys.platform.startswith("win"):
                kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            try:
                self._process = subprocess.Popen(args, **kwargs)
            except OSError as exc:
                self._reset()
                raise BpyViewportError(f"Could not start the built-in Blender worker: {exc}") from exc
            self._blend_path = blend_path

            # Cold starts can exceed 20 seconds on Windows when Blender first
            # scans bundled assets or antivirus inspects the executable.
            deadline = time.monotonic() + 45.0
            last_error = ""
            while time.monotonic() < deadline:
                if self._process.poll() is not None:
                    code = self._process.returncode
                    self._reset()
                    raise BpyViewportError(f"Built-in Blender stopped during startup (exit {code}).")
                try:
                    self._request("/healthz", timeout=0.75)
                    return self.status()
                except BpyViewportError as exc:
                    last_error = str(exc)
                    time.sleep(0.1)
            self.stop()
            raise BpyViewportError(
                f"Built-in Blender did not become ready in time. {last_error}".strip()
            )

    def stop(self) -> None:
        with self._lock:
            process = self._process
            if process is None:
                self._reset()
                return
            if process.poll() is None:
                try:
                    self._request("/shutdown", method="POST", timeout=1.0)
                except BpyViewportError:
                    pass
                try:
                    process.wait(timeout=3.0)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    try:
                        process.wait(timeout=2.0)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=2.0)
            self._reset()

    def frame(self, query: dict[str, Any]) -> tuple[bytes, dict[str, str]]:
        with self._lock:
            self._require_running()
            encoded = urllib.parse.urlencode(
                {key: value for key, value in query.items() if value is not None}
            )
            return self._request(f"/frame?{encoded}", timeout=30.0)

    def create_camera_path(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self._require_running()
            body, _headers = self._request(
                "/camera-path",
                method="POST",
                payload=payload,
                timeout=30.0,
            )
            try:
                result = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise BpyViewportError(
                    "Built-in Blender returned an invalid camera-path result."
                ) from exc
            if not isinstance(result, dict):
                raise BpyViewportError("Built-in Blender returned an invalid camera-path result.")
            return result

    def save(self) -> dict[str, Any]:
        with self._lock:
            self._require_running()
            body, _headers = self._request("/save", method="POST", timeout=30.0)
            try:
                return dict(json.loads(body.decode("utf-8")))
            except (TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise BpyViewportError("Built-in Blender returned an invalid save result.") from exc

    def save_if_running(self) -> dict[str, Any] | None:
        """Flush Blender-owned scene data without stopping the warm viewport."""
        with self._lock:
            if not self.running:
                return None
            return self.save()

    def save_and_stop(self) -> dict[str, Any] | None:
        """Durably save and release the built-in writer as one ordered action."""
        with self._lock:
            if not self.running:
                return None
            result = self.save()
            self.stop()
            return result

    def _require_running(self) -> None:
        if not self.running:
            raise BpyViewportError("Built-in Blender is not running.")

    def _request(
        self,
        path: str,
        *,
        method: str = "GET",
        payload: dict[str, Any] | None = None,
        timeout: float,
    ) -> tuple[bytes, dict[str, str]]:
        data = None
        headers = {WORKER_TOKEN_HEADER: self._token}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            f"http://127.0.0.1:{self._port}{path}",
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read(), dict(response.headers.items())
        except (OSError, urllib.error.URLError, urllib.error.HTTPError) as exc:
            detail = ""
            if isinstance(exc, urllib.error.HTTPError):
                try:
                    detail = exc.read().decode("utf-8", errors="replace")
                except OSError:
                    detail = ""
            message = detail or str(exc)
            raise BpyViewportError(message) from exc

    def _reset(self) -> None:
        self._process = None
        self._blend_path = None
        self._port = 0
        self._token = ""


def manager_for_app(app: Any) -> BpyViewportManager:
    manager = getattr(app.state, "bpy_viewport_manager", None)
    if manager is None:
        manager = BpyViewportManager()
        app.state.bpy_viewport_manager = manager
    return manager


def stop_worker(app: Any) -> None:
    manager = getattr(app.state, "bpy_viewport_manager", None)
    if manager is not None:
        manager.stop()


def save_and_stop_worker(app: Any) -> dict[str, Any] | None:
    """Save/release the active built-in Blender writer, if one exists."""
    manager = getattr(app.state, "bpy_viewport_manager", None)
    if manager is None:
        return None
    save_and_stop = getattr(manager, "save_and_stop", None)
    if callable(save_and_stop):
        return save_and_stop()
    # Compatibility for injected managers/test doubles.
    result = manager.save_if_running()
    if result is not None:
        manager.stop()
    return result
