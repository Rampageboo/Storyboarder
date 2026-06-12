from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn

from .api import create_app
from .desktop import open_desktop_window


def main() -> int:
    parser = argparse.ArgumentParser(description="Storyboard Tool")
    parser.add_argument(
        "--browser",
        action="store_true",
        help="Run as a local web server and open in the system browser",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    app = create_app(Path.cwd())

    if args.browser:
        print(f"Storyboard Tool running at {args.host}:{args.port}")
        uvicorn.run(app, host=args.host, port=args.port)
        return 0

    return open_desktop_window(app)


if __name__ == "__main__":
    raise SystemExit(main())
