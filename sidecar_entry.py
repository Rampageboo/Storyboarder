"""Thin entry point for PyInstaller — wraps storyboard_tool.sidecar_main.

Do not run directly; use the Tauri build script or `tauri build`.
"""
from storyboard_tool.sidecar_main import main

if __name__ == "__main__":
    raise SystemExit(main())
