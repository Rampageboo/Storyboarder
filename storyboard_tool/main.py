from __future__ import annotations

from pathlib import Path

from .api import create_app
from .desktop import _log_stage, open_desktop_window


def main() -> int:
    _log_stage("desktop process entered main()")
    app = create_app(Path.cwd())
    _log_stage("FastAPI app created")
    return open_desktop_window(app)


if __name__ == "__main__":
    raise SystemExit(main())
