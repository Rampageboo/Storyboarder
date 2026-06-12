from __future__ import annotations

import threading
import time
from pathlib import Path

import uvicorn

from .live_bridge import resolve_server_port, server_identity_url


HOST = "127.0.0.1"
PORT = 8000


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
            pass
        time.sleep(0.1)
    raise RuntimeError(f"Storyboard Tool server did not start on http://{host}:{port}")


def start_server(app, host: str = HOST, port: int = PORT) -> tuple[threading.Thread, int]:
    app.state.bridge_port = port
    config = uvicorn.Config(app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(config)

    def run() -> None:
        server.run()

    thread = threading.Thread(target=run, name="storyboard-server", daemon=True)
    thread.start()
    wait_for_server(host, port)
    return thread, port


def open_desktop_window(app, title: str = "Storyboard Tool") -> int:
    try:
        import webview
    except ImportError as exc:
        raise RuntimeError(
            "Desktop mode requires pywebview. Install dependencies with: pip install -r requirements.txt"
        ) from exc

    from .bridge import DesktopBridge
    from .live_bridge import publish

    port = resolve_server_port(HOST, PORT)
    app.state.bridge_port = port
    publish(app.state.base_dir, None, port=port)

    bridge = DesktopBridge(app)
    start_server(app, HOST, port)
    app_url = f"http://{HOST}:{port}"
    webview.create_window(
        title,
        app_url,
        width=1440,
        height=900,
        min_size=(1024, 680),
        text_select=True,
        js_api=bridge,
    )
    webview.start()
    return 0
