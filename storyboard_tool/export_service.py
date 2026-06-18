from __future__ import annotations

from pathlib import Path
from typing import Literal

from .export_utils import (
    export_contact_sheet as _export_contact_sheet,
    export_image_sequence as _export_image_sequence,
    export_shot_list_csv,
    export_timing_json,
    missing_files,
)
from .models import Project

VALID_PDF_LAYOUTS: frozenset[str] = frozenset({"one_per_page", "two_per_page", "thumbnails"})
DEFAULT_PDF_LAYOUT: str = "two_per_page"

_OUTPUT_PATHS: dict[str, str] = {
    "pdf": "storyboard.pdf",
    "shot_list": "shot_list.csv",
    "timing": "timing.json",
    "contact_sheet": "contact_sheet.png",
    "image_sequence": "image_sequence",
}


def resolve_output_path(project: Project, export_type: str) -> Path:
    filename = _OUTPUT_PATHS.get(export_type)
    if filename is None:
        raise ValueError(f"Unknown export type: {export_type!r}")
    return project.exports_dir / filename


def check_export_exists(project: Project, export_type: str) -> Path:
    path = resolve_output_path(project, export_type)
    if not path.exists():
        raise FileNotFoundError(f"No {export_type} export found. Run the export first.")
    return path


def get_missing_media(project: Project) -> list[dict]:
    return missing_files(project)


def export_pdf(project: Project, layout: str = DEFAULT_PDF_LAYOUT) -> Path:
    from .pdf_exporter import export_storyboard_pdf

    chosen = layout if layout in VALID_PDF_LAYOUTS else DEFAULT_PDF_LAYOUT
    output_path = resolve_output_path(project, "pdf")
    export_storyboard_pdf(project, output_path, layout=chosen)
    return output_path


def export_shot_list(project: Project) -> Path:
    output_path = resolve_output_path(project, "shot_list")
    return export_shot_list_csv(project, output_path)


def export_timing(project: Project) -> Path:
    output_path = resolve_output_path(project, "timing")
    return export_timing_json(project, output_path)


def export_contact_sheet(project: Project) -> Path:
    output_path = resolve_output_path(project, "contact_sheet")
    return _export_contact_sheet(project, output_path)


def export_image_sequence(project: Project) -> Path:
    output_dir = resolve_output_path(project, "image_sequence")
    return _export_image_sequence(project, output_dir)
