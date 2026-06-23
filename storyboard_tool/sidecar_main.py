"""Entry point for the Tauri sidecar mode.

Starts FastAPI + uvicorn only — no pywebview. Prints PORT:<n> to stdout so
the Tauri host process knows where to point the WebView.
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path


_HOST = "127.0.0.1"


def main() -> int:
    from .api import create_app
    from .live_bridge import resolve_server_port

    app = create_app(Path.cwd())

    port = resolve_server_port(_HOST, 0)
    app.state.bridge_port = port

    import uvicorn

    config = uvicorn.Config(app, host=_HOST, port=port, log_level="warning")
    server = uvicorn.Server(config)

    ready = threading.Event()

    def _on_startup() -> None:
        ready.set()

    server.config.callback_notify = _on_startup  # type: ignore[attr-defined]

    thread = threading.Thread(target=server.run, name="storyboard-sidecar", daemon=True)
    thread.start()

    # Wait for uvicorn to bind, then announce the port.
    deadline = time.time() + 15.0
    while time.time() < deadline:
        import socket
        try:
            with socket.create_connection((_HOST, port), timeout=0.5):
                break
        except OSError:
            time.sleep(0.05)

    sys.stdout.write(f"PORT:{port}\n")
    sys.stdout.flush()

    thread.join()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
