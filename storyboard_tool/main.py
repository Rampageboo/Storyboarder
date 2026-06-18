from __future__ import annotations

from pathlib import Path

from .api import create_app
from .desktop import open_desktop_window


def main() -> int:
    app = create_app(Path.cwd())
    return open_desktop_window(app)


if __name__ == "__main__":
    raise SystemExit(main())
