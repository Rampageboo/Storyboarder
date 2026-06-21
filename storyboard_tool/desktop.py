from __future__ import annotations

import json
import logging
import os
import re
import sys
import tempfile
import threading
import time
from pathlib import Path

import uvicorn

from . import project_manager
from .live_bridge import global_bridge_dir, resolve_server_port, server_identity_url


# The desktop shell starts a private localhost server for the React bundle and API.
# This is an implementation detail for pywebview — not a supported browser workflow.
_HOST = "127.0.0.1"
_PORT = 0  # 0 = resolved dynamically at startup; see resolve_server_port()
ICON_PATH = Path(__file__).resolve().parent / "assets" / "icon.ico"
APP_USER_MODEL_ID = "StoryboardTool.StoryboardTool.1"
_WEBVIEW_STORAGE_WARNED_PATHS: set[str] = set()
_LOGGER = logging.getLogger(__name__)

# t0 is set at process entry; all stage timings are relative to it.
_t0: float = time.perf_counter()


def _log_stage(label: str) -> None:
    elapsed = time.perf_counter() - _t0
    _LOGGER.info("[startup] %+.3fs  %s", elapsed, label)


_TOKEN_RE_DESKTOP = re.compile(r'^[a-zA-Z0-9_-]{1,64}$')


def _write_launch_ready_marker() -> None:
    """Option A: write the per-launch ready marker from the pywebview shown callback."""
    token = os.environ.get("STORYBOARDER_LAUNCH_TOKEN", "").strip()
    if not token or not _TOKEN_RE_DESKTOP.match(token):
        return
    try:
        Path(tempfile.gettempdir()).joinpath(f"storyboarder-launch-{token}.ready").write_text(
            "ready", encoding="utf-8"
        )
        _log_stage("pywebview shown: ready marker written (Option A fallback)")
    except OSError:
        pass


def _configure_windows_taskbar_identity() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except Exception:
        # intentional: optional Windows shell API
        pass


def wait_for_server(host: str, port: int, timeout: float = 15.0) -> None:
    deadline = time.time() + timeout
    url = server_identity_url(host, port)
    while time.time() < deadline:
        try:
            import urllib.request

            with urllib.request.urlopen(url, timeout=1.0) as response:
                if response.status == 200:
                    return
        except Exception:
            # intentional: poll until the local server accepts connections
            pass
        time.sleep(0.1)
    raise RuntimeError(f"Storyboard Tool server did not start on http://{host}:{port}")


def _configure_windows_asyncio_noise() -> None:
    if sys.platform != "win32":
        return
    import asyncio
    import asyncio.proactor_events

    try:
        asyncio.get_event_loop().set_exception_handler(_ignore_connection_reset)
    except RuntimeError:
        pass

    transport_cls = getattr(asyncio.proactor_events, "_ProactorBasePipeTransport", None)
    if transport_cls is None:
        _LOGGER.warning("asyncio proactor transport patch skipped: _ProactorBasePipeTransport is unavailable")
        return

    if getattr(transport_cls, "_storyboard_patched", False):
        return

    _orig_call_connection_lost = getattr(transport_cls, "_call_connection_lost", None)
    if _orig_call_connection_lost is None:
        _LOGGER.warning("asyncio proactor transport patch skipped: _call_connection_lost is unavailable")
        return

    def _quiet_call_connection_lost(self, exc):
        try:
            _orig_call_connection_lost(self, exc)
        except ConnectionResetError:
            pass
        except OSError as os_err:
            if os_err.winerror in (10053, 10054):
                pass
            else:
                raise
        except Exception as inner_exc:
            if isinstance(inner_exc, ConnectionResetError):
                return
            if isinstance(inner_exc, OSError) and getattr(inner_exc, "winerror", None) in (10053, 10054):
                return
            raise

    transport_cls._call_connection_lost = _quiet_call_connection_lost
    transport_cls._storyboard_patched = True


def _ignore_connection_reset(loop, context) -> None:
    exc = context.get("exception")
    if isinstance(exc, (ConnectionResetError, BrokenPipeError)):
        return
    if isinstance(exc, OSError) and getattr(exc, "winerror", None) in (10053, 10054):
        return
    message = str(context.get("message", ""))
    if "_call_connection_lost" in message:
        return
    loop.default_exception_handler(context)


def start_internal_server(app, host: str = _HOST, port: int = _PORT) -> tuple[threading.Thread, int]:
    """Start the private localhost server that pywebview loads. Not a public endpoint."""
    _log_stage("internal server thread starting")
    if port <= 0:
        port = resolve_server_port(host, port)
    app.state.bridge_port = port
    config = uvicorn.Config(app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(config)

    def run() -> None:
        _configure_windows_asyncio_noise()
        if sys.platform == "win32":
            import asyncio

            loop = asyncio.new_event_loop()
            loop.set_exception_handler(_ignore_connection_reset)
            asyncio.set_event_loop(loop)
        server.run()

    thread = threading.Thread(target=run, name="storyboard-server", daemon=True)
    thread.start()
    wait_for_server(host, port)
    _log_stage("server ready")
    return thread, port




def webview_storage_path() -> Path:
    candidates = [
        global_bridge_dir() / "webview",
        Path(tempfile.gettempdir()) / "StoryboardTool" / "webview",
    ]
    for path in candidates:
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            key = str(path)
            if key not in _WEBVIEW_STORAGE_WARNED_PATHS:
                _WEBVIEW_STORAGE_WARNED_PATHS.add(key)
                print(f"Webview storage path unavailable: {path} ({exc})", file=sys.stderr)
            continue
        return path
    return Path(tempfile.gettempdir())


def _window_state_path() -> Path:
    return global_bridge_dir() / "window_state.json"


def _load_window_state() -> dict | None:
    try:
        return json.loads(_window_state_path().read_text(encoding="utf-8"))
    except Exception:
        return None


def _save_window_state(window, maximized: bool = False) -> None:
    try:
        state = {"width": window.width, "height": window.height, "maximized": maximized}
        _window_state_path().write_text(json.dumps(state), encoding="utf-8")
    except Exception:
        pass


def open_desktop_window(app, title: str = "Storyboard Tool") -> int:
    _log_stage("desktop process entered open_desktop_window")
    try:
        import webview
    except ImportError as exc:
        raise RuntimeError(
            "Desktop mode requires pywebview. Install dependencies with: pip install -r requirements.txt"
        ) from exc

    from .live_bridge import publish

    try:
        port = resolve_server_port(_HOST, _PORT)
    except RuntimeError as exc:
        print(str(exc))
        return 1

    app.state.bridge_port = port
    publish(app.state.base_dir, None, port=port)

    _configure_windows_asyncio_noise()
    start_internal_server(app, _HOST, port)
    _log_stage("pywebview window about to be created")
    react_index = Path(__file__).resolve().parent / "web" / "dist" / "index.html"
    if not react_index.is_file():
        print(
            "React build not found. Run: cd frontend && npm run build",
            file=sys.stderr,
        )
        return 1
    internal_app_url = f"http://{_HOST}:{port}/"
    _configure_windows_taskbar_identity()

    saved_state = _load_window_state()
    # Default to maximized; restore previous size only when user had explicitly unmaximized.
    restore_maximized = saved_state is None or saved_state.get("maximized", True)
    win_width = saved_state["width"] if saved_state and not restore_maximized else 1440
    win_height = saved_state["height"] if saved_state and not restore_maximized else 900

    window = webview.create_window(
        title,
        internal_app_url,
        width=win_width,
        height=win_height,
        min_size=(1024, 680),
        text_select=False,
    )
    app.state.main_window = window

    # Track whether the window is currently maximized so we can save it on close.
    _maximized = [restore_maximized]

    def _on_shown():
        if restore_maximized:
            try:
                window.maximize()
            except Exception:
                pass
        # Option A fallback: write ready marker once the native window is visible,
        # so the splash closes even when /api/app/ui-ready is not reached.
        _write_launch_ready_marker()

    def _on_resized(width, height):
        # Any user-driven resize means the window is no longer maximized.
        _maximized[0] = False

    window.events.shown += _on_shown
    try:
        window.events.resized += _on_resized
    except Exception:
        pass  # older pywebview versions may not have resized event

    start_kwargs: dict = {
        "private_mode": False,
        "storage_path": str(webview_storage_path()),
    }
    if ICON_PATH.is_file():
        start_kwargs["icon"] = str(ICON_PATH.resolve())
    webview.start(**start_kwargs)

    # webview.start() blocks until the window closes — save state now.
    _save_window_state(window, maximized=_maximized[0])

    try:
        project_manager.shutdown_reference_cleanup(
            app.state.project,
            save_if_dirty=bool(getattr(app.state, "dirty", False)),
            dirty=bool(getattr(app.state, "dirty", False)),
        )
    except Exception as exc:
        print(f"Reference cleanup failed: {exc}")
    return 0
