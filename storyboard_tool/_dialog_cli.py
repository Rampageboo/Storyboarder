"""Run native file/folder pickers in a standalone process (main thread)."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def _safe_initial_dir(initial_dir: str) -> str | None:
    if not initial_dir:
        return None
    candidate = Path(initial_dir).expanduser()
    if candidate.is_file():
        candidate = candidate.parent
    if candidate.is_dir():
        return str(candidate.resolve())
    return None


def _pick_folder(initial_dir: str | None) -> str:
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    root.update_idletasks()
    try:
        return filedialog.askdirectory(title="Choose folder", initialdir=initial_dir) or ""
    finally:
        root.destroy()


def _pick_file(initial_dir: str | None, kind: str) -> str:
    import tkinter as tk
    from tkinter import filedialog

    if kind == "project-json":
        title = "Choose project.json"
        filetypes = [
            ("Project file", "project.json"),
            ("JSON", "*.json"),
            ("All files", "*.*"),
        ]
    elif kind == "blender":
        title = "Choose Blender executable"
        filetypes = [
            ("Blender", "blender.exe"),
            ("Executable", "*.exe"),
            ("All files", "*.*"),
        ]
    else:
        title = "Choose Photoshop executable"
        filetypes = [
            ("Photoshop", "Photoshop.exe"),
            ("Executable", "*.exe"),
            ("All files", "*.*"),
        ]

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    root.update_idletasks()
    try:
        return filedialog.askopenfilename(title=title, initialdir=initial_dir, filetypes=filetypes) or ""
    finally:
        root.destroy()


def main() -> int:
    kind = sys.argv[1] if len(sys.argv) > 1 else ""
    initial = sys.argv[2] if len(sys.argv) > 2 else ""
    initial_dir = _safe_initial_dir(initial)

    if kind == "folder":
        selected = _pick_folder(initial_dir)
    elif kind in {"project-json", "photoshop", "blender"}:
        selected = _pick_file(initial_dir, kind)
    else:
        print(json.dumps({"error": f"Unknown dialog kind: {kind}"}, ensure_ascii=False))
        return 2

    print(
        json.dumps(
            {"path": selected, "cancelled": not selected},
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
