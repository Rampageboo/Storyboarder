from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, BinaryIO, Callable

from . import project_document, project_manager as pm
from .file_transactions import atomic_copy_file, atomic_copy_stream
from .image_utils import is_psd_path
from .models import Project, Shot
from .project_layout import LAYOUT_2, resolve_scene3d_asset

BLEND_TEMPLATE_PATH = Path(__file__).resolve().parent / "assets" / "scene_template.blend"
SCENE3D_EXTENSIONS = {".glb", ".gltf"}


def blend_template_path() -> Path:
    return BLEND_TEMPLATE_PATH


def get_project_blend_path(project: Project, scene_id: str | None = None) -> Path:
    if project.layout == LAYOUT_2:
        if not scene_id:
            from . import scene3d

            scene_id = scene3d.ensure_active_scene(project)["id"]
        return resolve_scene3d_asset(project, scene_id, ".blend")
    return pm.resolve_project_child(project, "scene3d", "scene.blend")


def blender_portable_reference(
    project: Project,
    blend_path: Path,
    asset_path: Path,
) -> str:
    """Return Blender's portable ``//`` form for a project-contained asset."""
    blend = pm.resolve_project_path(project, pm.project_relative_posix(project, blend_path))
    asset = pm.resolve_project_path(project, pm.project_relative_posix(project, asset_path))
    relative = os.path.relpath(asset, start=blend.parent).replace("\\", "/")
    return f"//{relative}"


def ensure_project_blend_file(
    project: Project,
    *,
    scene_id: str | None = None,
) -> Path:
    """Lazily copy the bundled template to the active layout-owned Blend path."""
    blend_path = get_project_blend_path(project, scene_id)
    if project.layout == LAYOUT_2:
        project_document.enlist_layout2_mutation_paths(
            project.project_root,
            (blend_path,),
        )
    scene_dir = blend_path.parent
    scene_dir.mkdir(parents=True, exist_ok=True)
    if not blend_path.exists():
        template = blend_template_path()
        if template.is_file():
            atomic_copy_file(template, blend_path)
    scene_settings = dict(project.settings.get("scene3d") or {})
    if blend_path.exists():
        scene_settings["blend_file_path"] = pm.project_relative_posix(project, blend_path)
    project.settings["scene3d"] = scene_settings
    pm.save_settings(project)
    return blend_path


def open_blender_scene(
    project: Project,
    relative_path: str = "",
    *,
    python_script: Path | None = None,
    script_args: list[str] | None = None,
    on_launch: Callable[[subprocess.Popen[Any]], None] | None = None,
) -> Path:
    from .system_utils import detect_blender_paths, resolve_blender_executable

    cleaned_path = pm._normalize_rel_path(str(relative_path or "").strip())
    if cleaned_path:
        blend_path = pm.resolve_project_path(
            project,
            cleaned_path,
            required_suffixes=(".blend",),
        )
        if blend_path.suffix.lower() != ".blend":
            raise ValueError("Attached Blender asset must be a .blend file.")
        if not blend_path.is_file():
            raise FileNotFoundError(f"Blender file not found: {cleaned_path}")
    else:
        if project.layout == LAYOUT_2:
            from . import scene3d

            scene_id = scene3d.ensure_active_scene(project)["id"]
            blend_path = ensure_project_blend_file(project, scene_id=scene_id)
        else:
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
    if python_script is not None:
        resolved_script = python_script.resolve()
        if not resolved_script.is_file():
            raise FileNotFoundError(f"Blender integration script not found: {resolved_script}")
        args.extend(["--python", str(resolved_script)])
    if script_args:
        args.extend(["--", *[str(item) for item in script_args]])
    process = subprocess.Popen(args)
    if on_launch is not None:
        on_launch(process)
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
    if project.layout == LAYOUT_2:
        from . import scene3d

        active = scene3d.ensure_active_scene(project)
        destination = resolve_scene3d_asset(project, active["id"], suffix)
        atomic_copy_stream(source_stream, destination)
        relative_path = pm.project_relative_posix(project, destination)
    else:
        scene_dir = pm.resolve_project_child(project, "scene3d")
        scene_dir.mkdir(exist_ok=True)
        destination = pm.resolve_project_child(project, "scene3d", f"scene{suffix}")
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
        relative_path = pm.project_relative_posix(project, destination)
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
    candidate = pm.resolve_project_path(project, relative_path)
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
    file_path = pm.resolve_project_path(project, relative_path)
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
