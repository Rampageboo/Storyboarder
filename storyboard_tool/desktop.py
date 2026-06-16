from __future__ import annotations

import sys
import tempfile
import threading
import time
from pathlib import Path

import uvicorn

from . import project_manager
from .live_bridge import global_bridge_dir, resolve_server_port, server_identity_url


HOST = "127.0.0.1"
PORT = 8000
ICON_PATH = Path(__file__).resolve().parent / "assets" / "icon.ico"
APP_USER_MODEL_ID = "StoryboardTool.StoryboardTool.1"
_WEBVIEW_STORAGE_WARNED_PATHS: set[str] = set()


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

    try:
        asyncio.get_event_loop().set_exception_handler(_ignore_connection_reset)
    except RuntimeError:
        pass

    if getattr(asyncio.proactor_events._ProactorBasePipeTransport, "_storyboard_patched", False):
        return

    _orig_call_connection_lost = asyncio.proactor_events._ProactorBasePipeTransport._call_connection_lost

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

    asyncio.proactor_events._ProactorBasePipeTransport._call_connection_lost = _quiet_call_connection_lost
    asyncio.proactor_events._ProactorBasePipeTransport._storyboard_patched = True


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


def start_server(app, host: str = HOST, port: int = PORT) -> tuple[threading.Thread, int]:
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


def open_desktop_window(app, title: str = "Storyboard Tool") -> int:
    try:
        import webview
    except ImportError as exc:
        raise RuntimeError(
            "Desktop mode requires pywebview. Install dependencies with: pip install -r requirements.txt"
        ) from exc

    from .bridge import DesktopBridge
    from .live_bridge import publish

    try:
        port = resolve_server_port(HOST, PORT)
    except RuntimeError as exc:
        print(str(exc))
        return 1

    app.state.bridge_port = port
    publish(app.state.base_dir, None, port=port)

    bridge = DesktopBridge(app)
    _configure_windows_asyncio_noise()
    start_server(app, HOST, port)
    app_url = f"http://{HOST}:{port}"
    _configure_windows_taskbar_identity()
    webview.create_window(
        title,
        app_url,
        width=1440,
        height=900,
        min_size=(1024, 680),
        text_select=False,
        js_api=bridge,
    )
    start_kwargs: dict = {
        "private_mode": False,
        "storage_path": str(webview_storage_path()),
    }
    if ICON_PATH.is_file():
        start_kwargs["icon"] = str(ICON_PATH.resolve())
    webview.start(**start_kwargs)
    try:
        project_manager.shutdown_reference_cleanup(
            app.state.project,
            save_if_dirty=bool(getattr(app.state, "dirty", False)),
            dirty=bool(getattr(app.state, "dirty", False)),
        )
    except Exception as exc:
        print(f"Reference cleanup failed: {exc}")
    return 0
