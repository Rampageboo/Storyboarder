from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path


PHOTOSHOP_EXE_NAMES = ("Photoshop.exe", "photoshop.exe")
BLENDER_EXE_NAMES = ("blender.exe", "Blender")


def detect_blender_paths() -> list[str]:
    """Return existing Blender executable paths without expensive recursive scans."""
    found: list[str] = []

    def add_if_file(path: Path) -> None:
        if path.is_file():
            found.append(str(path.resolve()))

    if sys.platform == "darwin":
        for candidate in Path("/Applications").glob("Blender*.app/Contents/MacOS/Blender"):
            add_if_file(candidate)
        return _dedupe_sorted(found)

    direct_paths = [
        Path(r"C:\Program Files (x86)\Steam\steamapps\common\Blender\blender.exe"),
        Path(r"C:\Program Files\Steam\steamapps\common\Blender\blender.exe"),
    ]
    for path in direct_paths:
        add_if_file(path)

    for base in (
        Path(r"C:\Program Files\Blender Foundation"),
        Path(r"C:\Program Files (x86)\Blender Foundation"),
    ):
        if not base.is_dir():
            continue
        for install_dir in sorted(base.iterdir(), reverse=True):
            if not install_dir.is_dir():
                continue
            add_if_file(install_dir / "blender.exe")

    return _dedupe_sorted(found)


def resolve_blender_executable(path: str) -> Path:
    value = path.strip().strip('"')
    if not value:
        raise ValueError("Choose the Blender executable (blender.exe).")
    candidate = Path(value).expanduser()
    if not candidate.exists():
        raise FileNotFoundError(f"File not found: {candidate}")
    if candidate.is_dir():
        direct = candidate / "blender.exe"
        if direct.is_file():
            return direct.resolve()
        for item in candidate.iterdir():
            if item.is_file() and item.name.lower() == "blender.exe":
                return item.resolve()
        raise ValueError(f"No blender.exe found in folder: {candidate}")
    if candidate.is_file():
        name = candidate.name.lower()
        if name in {"blender.exe", "blender"} or candidate.suffix.lower() == ".exe":
            return candidate.resolve()
    raise ValueError("Choose the Blender executable (blender.exe).")


def validate_blender_path(path: str) -> str:
    if not path.strip():
        return ""
    return str(resolve_blender_executable(path))


def detect_photoshop_paths() -> list[str]:
    """Return existing Photoshop.exe paths, newest versions first."""
    found: list[str] = []
    search_roots = [
        Path(r"C:\Program Files\Adobe"),
        Path(r"C:\Program Files (x86)\Adobe"),
    ]
    if sys.platform == "darwin":
        search_roots = [Path("/Applications")]

    for root in search_roots:
        if not root.is_dir():
            continue
        for candidate in root.rglob("Photoshop.app/Contents/MacOS/Photoshop"):
            if candidate.is_file():
                found.append(str(candidate.resolve()))
        for candidate in root.rglob("Photoshop.exe"):
            if candidate.is_file():
                found.append(str(candidate.resolve()))

    return _dedupe_sorted(found)


def validate_photoshop_path(path: str) -> str:
    value = path.strip().strip('"')
    if not value:
        return ""
    candidate = Path(value).expanduser()
    if not candidate.exists():
        raise FileNotFoundError(f"File not found: {candidate}")
    if not candidate.is_file():
        raise ValueError(f"Path is not a file: {candidate}")
    if candidate.suffix.lower() != ".exe" and candidate.name not in {"Photoshop", "photoshop"}:
        raise ValueError("Choose the Photoshop executable (Photoshop.exe).")
    return str(candidate.resolve())


def validate_folder_path(path: str) -> str:
    value = path.strip().strip('"')
    if not value:
        return ""
    candidate = Path(value).expanduser()
    if not candidate.exists():
        raise FileNotFoundError(f"Folder not found: {candidate}")
    if not candidate.is_dir():
        raise ValueError(f"Path is not a folder: {candidate}")
    return str(candidate.resolve())


def validate_project_json_path(path: str) -> str:
    value = path.strip().strip('"')
    if not value:
        raise ValueError("Choose a project.json file.")
    candidate = Path(value).expanduser()
    if not candidate.exists():
        raise FileNotFoundError(f"File not found: {candidate}")
    if not candidate.is_file():
        raise ValueError(f"Path is not a file: {candidate}")
    if candidate.name.lower() != "project.json":
        raise ValueError("Choose a project.json file.")
    return str(candidate.resolve())


def browse_folder(initial_dir: str = "") -> str | None:
    return _run_dialog_process("folder", initial_dir)


def browse_project_json(initial_dir: str = "") -> str | None:
    return _run_dialog_process("project-json", initial_dir)


def browse_photoshop_executable(initial_dir: str = "") -> str | None:
    return _run_dialog_process("photoshop", initial_dir)


def browse_blender_executable(initial_dir: str = "") -> str | None:
    return _run_dialog_process("blender", initial_dir)


def _run_dialog_process(kind: str, initial_dir: str = "") -> str | None:
    """Spawn a child process so tk/file dialogs run on a proper GUI main thread."""
    command = [sys.executable, "-m", "storyboard_tool._dialog_cli", kind]
    if initial_dir:
        command.append(initial_dir)

    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=600,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("File picker timed out. Try again.") from exc
    except OSError as exc:
        raise RuntimeError(f"Could not start file picker: {exc}") from exc

    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip() or "File picker process failed."
        raise RuntimeError(message)

    try:
        payload = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError("File picker returned an invalid result.") from exc

    if payload.get("error"):
        raise RuntimeError(str(payload["error"]))
    if payload.get("cancelled"):
        return None
    path = str(payload.get("path", "")).strip()
    return path or None


def _dedupe_sorted(paths: list[str]) -> list[str]:
    unique = list(dict.fromkeys(paths))

    def sort_key(path: str) -> tuple[int, str]:
        match = re.search(r"(\d{4})", path)
        year = int(match.group(1)) if match else 0
        return (year, path.lower())

    return sorted(unique, key=sort_key, reverse=True)
