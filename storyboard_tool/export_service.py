from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from typing import Literal

from . import board_range
from .file_transactions import atomic_output_directory, atomic_output_file
from .export_utils import (
    export_contact_sheet as _export_contact_sheet,
    export_image_sequence as _export_image_sequence,
    export_shot_list_csv,
    export_timing_json,
    missing_files,
)
from .models import Project
from .project_layout import resolve_root_child

VALID_PDF_LAYOUTS: frozenset[str] = frozenset({"one_per_page", "two_per_page", "thumbnails"})
DEFAULT_PDF_LAYOUT: str = "two_per_page"

_OUTPUT_PATHS: dict[str, str] = {
    "pdf": "storyboard.pdf",
    "shot_list": "shot_list.csv",
    "timing": "timing.json",
    "contact_sheet": "contact_sheet.png",
    "image_sequence": "image_sequence",
    "animatic": "animatic.mp4",
}


def scope_to_boards(project: Project, boards: str) -> tuple[Project, str]:
    """Narrow an export to a board range, e.g. ``1-5, 8``.

    Returns a read-only project view holding just those boards plus the filename
    suffix their outputs use, so a partial export never overwrites the
    whole-storyboard one. An empty spec means the whole storyboard.
    """
    if not str(boards or "").strip():
        return project, ""
    total = len(project.shots)
    indexes = board_range.parse(boards, total)
    # Shallow view: same paths and settings, fewer boards. Exporters only read.
    # board_numbers carries the real storyboard positions so a partial export
    # still labels boards 5-7 as 5, 6, 7 rather than renumbering them 1, 2, 3.
    selected = [project.shots[index] for index in indexes]
    view = replace(project, shots=selected, board_numbers=[index + 1 for index in indexes])
    return view, board_range.filename_suffix(indexes, total)


def resolve_output_path(project: Project, export_type: str, suffix: str = "") -> Path:
    filename = _OUTPUT_PATHS.get(export_type)
    if filename is None:
        raise ValueError(f"Unknown export type: {export_type!r}")
    if suffix:
        stem, dot, extension = filename.partition(".")
        filename = f"{stem}{suffix}{dot}{extension}"
    return resolve_root_child(project.exports_dir, filename)


def check_export_exists(project: Project, export_type: str, suffix: str = "") -> Path:
    path = resolve_output_path(project, export_type, suffix)
    if not path.exists():
        raise FileNotFoundError(f"No {export_type} export found. Run the export first.")
    return path


def open_export(project: Project, export_type: str, suffix: str = "") -> Path:
    """Open a previously generated export in the OS default application."""
    path = check_export_exists(project, export_type, suffix)
    if sys.platform.startswith("win"):
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])
    return path


def get_missing_media(project: Project) -> list[dict]:
    return missing_files(project)


def export_pdf(project: Project, layout: str = DEFAULT_PDF_LAYOUT, suffix: str = "") -> Path:
    from .pdf_exporter import export_storyboard_pdf

    chosen = layout if layout in VALID_PDF_LAYOUTS else DEFAULT_PDF_LAYOUT
    output_path = resolve_output_path(project, "pdf", suffix)
    with atomic_output_file(output_path) as staged:
        export_storyboard_pdf(project, staged, layout=chosen)
    return output_path


def export_shot_list(project: Project, suffix: str = "") -> Path:
    output_path = resolve_output_path(project, "shot_list", suffix)
    with atomic_output_file(output_path) as staged:
        export_shot_list_csv(project, staged)
    return output_path


def export_timing(project: Project, suffix: str = "") -> Path:
    output_path = resolve_output_path(project, "timing", suffix)
    with atomic_output_file(output_path) as staged:
        export_timing_json(project, staged)
    return output_path


def export_contact_sheet(project: Project, suffix: str = "") -> Path:
    output_path = resolve_output_path(project, "contact_sheet", suffix)
    with atomic_output_file(output_path) as staged:
        _export_contact_sheet(project, staged)
    return output_path


def export_image_sequence(project: Project, suffix: str = "") -> Path:
    output_dir = resolve_output_path(project, "image_sequence", suffix)
    with atomic_output_directory(output_dir) as staged:
        _export_image_sequence(project, staged)
    return output_dir


def export_animatic(
    project: Project,
    *,
    fps: int = 24,
    seconds_per_board: float | None = None,
    captions: bool = False,
    suffix: str = "",
) -> Path:
    from .video_export import export_animatic as _export_animatic

    output_path = resolve_output_path(project, "animatic", suffix)
    with atomic_output_file(output_path) as staged:
        _export_animatic(
            project,
            staged,
            fps=fps,
            seconds_per_board=seconds_per_board,
            captions=captions,
        )
    return output_path
