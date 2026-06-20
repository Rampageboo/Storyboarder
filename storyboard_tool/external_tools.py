from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import BinaryIO

from . import project_manager as pm
from .image_utils import is_psd_path
from .models import Project, Shot

BLEND_TEMPLATE_PATH = Path(__file__).resolve().parent / "assets" / "scene_template.blend"
SCENE3D_EXTENSIONS = {".glb", ".gltf"}


def blend_template_path() -> Path:
    return BLEND_TEMPLATE_PATH


def get_project_blend_path(project: Project) -> Path:
    return project.root_path / "scene3d" / "scene.blend"


def ensure_project_blend_file(project: Project) -> Path:
    """Copy bundled scene_template.blend into the project when scene.blend is missing."""
    scene_dir = project.root_path / "scene3d"
    scene_dir.mkdir(parents=True, exist_ok=True)
    blend_path = get_project_blend_path(project)
    if not blend_path.exists():
        template = blend_template_path()
        if template.is_file():
            shutil.copy2(template, blend_path)
    scene_settings = dict(project.settings.get("scene3d") or {})
    if blend_path.exists():
        scene_settings["blend_file_path"] = blend_path.relative_to(project.root_path).as_posix()
    project.settings["scene3d"] = scene_settings
    pm.save_settings(project)
    return blend_path


def open_blender_scene(project: Project) -> Path:
    from .system_utils import detect_blender_paths, resolve_blender_executable

    blend_path = ensure_project_blend_file(project)
    if not blend_path.exists():
        template = blend_template_path()
        if not template.is_file():
            raise FileNotFoundError(
                "scene3d/scene.blend is missing and no template was found. "
                "Place scene_template.blend in storyboard_tool/assets/."
            )
    blender_path = str(project.settings.get("blender_path", "")).strip()
    if not blender_path:
        candidates = detect_blender_paths()
        if candidates:
            blender_path = candidates[0]
    if not blender_path:
        raise FileNotFoundError("Blender path not configured. Open Blender Setup and choose blender.exe.")
    try:
        configured = resolve_blender_executable(blender_path)
    except (FileNotFoundError, ValueError) as exc:
        raise FileNotFoundError(str(exc)) from exc
    args = [str(configured)]
    if blend_path.exists():
        args.append(str(blend_path.resolve()))
    subprocess.Popen(args)
    return blend_path


def preheat_photoshop(photoshop_path: str = "") -> dict[str, object]:
    """Best-effort Photoshop warmup without opening or modifying project files."""
    from .system_utils import detect_photoshop_paths, validate_photoshop_path

    configured_path = str(photoshop_path or "").strip()
    if not configured_path:
        candidates = detect_photoshop_paths()
        configured_path = candidates[0] if candidates else ""
    if not configured_path:
        return {
            "ok": True,
            "attempted": False,
            "launched": False,
            "message": "Photoshop path is not configured.",
        }
    try:
        executable = validate_photoshop_path(configured_path)
        subprocess.Popen([executable])
    except (OSError, ValueError) as exc:
        return {
            "ok": True,
            "attempted": True,
            "launched": False,
            "message": str(exc),
        }
    return {
        "ok": True,
        "attempted": True,
        "launched": True,
        "message": "",
    }


def import_scene3d_stream(project: Project, source_stream: BinaryIO, filename: str) -> dict:
    suffix = Path(filename).suffix.lower()
    if suffix not in SCENE3D_EXTENSIONS:
        raise ValueError("Only .glb and .gltf Blender exports are supported.")
    scene_dir = project.root_path / "scene3d"
    scene_dir.mkdir(exist_ok=True)
    destination = scene_dir / f"scene{suffix}"
    fd, tmp_name = tempfile.mkstemp(dir=str(scene_dir), prefix=f"{destination.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as file:
            shutil.copyfileobj(source_stream, file)
        os.replace(tmp_name, destination)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    relative_path = destination.relative_to(project.root_path).as_posix()
    scene_settings = dict(project.settings.get("scene3d") or {})
    scene_settings.update(
        {
            "source": "blender",
            "file_path": relative_path,
            "file_name": Path(filename).name,
        }
    )
    project.settings["scene3d"] = scene_settings
    pm.save_settings(project)
    return scene_settings


def get_scene3d_file_path(project: Project) -> Path | None:
    relative_path = str((project.settings.get("scene3d") or {}).get("file_path", "")).strip()
    if not relative_path:
        return None
    candidate = (project.root_path / relative_path).resolve()
    root = project.root_path.resolve()
    if root not in candidate.parents and candidate != root:
        raise ValueError("Scene file path must be inside the project folder.")
    if not candidate.exists() or not candidate.is_file():
        raise FileNotFoundError(f"Scene file not found: {relative_path}")
    return candidate


def open_project_file(
    project: Project,
    relative_path: str,
    app_path: str = "",
    shot: Shot | None = None,
) -> Path:
    if shot is not None:
        pm.write_bridge_file(project, shot)
    file_path = (project.root_path / relative_path).resolve()
    root = project.root_path.resolve()
    if root not in file_path.parents and file_path != root:
        raise ValueError("File path must be inside the project folder.")
    if not file_path.exists() or not file_path.is_file():
        raise FileNotFoundError(f"File not found: {relative_path}")
    if shot is not None and is_psd_path(file_path):
        pm.sync_psd_board_background(project, shot, file_path)
    if app_path:
        configured_app = Path(app_path).expanduser()
        if not configured_app.exists():
            raise FileNotFoundError(f"Configured editor not found: {configured_app}")
        subprocess.Popen([str(configured_app), str(file_path)])
    elif sys.platform.startswith("win"):
        os.startfile(file_path)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(file_path)])
    else:
        subprocess.Popen(["xdg-open", str(file_path)])
    return file_path
