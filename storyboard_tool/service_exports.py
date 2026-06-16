from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import HTTPException

from . import app_state, project_manager
from .export_utils import (
    export_contact_sheet,
    export_image_sequence,
    export_shot_list_csv,
    export_timing_json,
)


def _export_storyboard_pdf(project, output_path: Path, *, layout: str) -> None:
    from .pdf_exporter import export_storyboard_pdf

    export_storyboard_pdf(project, output_path, layout=layout)


class ExportServiceMixin:
    """Export generation, download lookups, and project file serving."""

    def method_export_pdf(self, layout: str = "two_per_page") -> dict[str, str]:
        project = app_state._require_project(self.app)
        output_path = project.exports_dir / "storyboard.pdf"
        chosen = layout if layout in {"one_per_page", "two_per_page", "thumbnails"} else "two_per_page"
        try:
            _export_storyboard_pdf(project, output_path, layout=chosen)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        project.settings["pdf_layout"] = chosen
        project_manager.save_settings(project)
        return {"path": str(output_path), "download_url": "/api/export/pdf"}

    def method_export_shot_list(self) -> dict[str, str]:
        project = app_state._require_project(self.app)
        output_path = project.exports_dir / "shot_list.csv"
        try:
            export_shot_list_csv(project, output_path)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return {"path": str(output_path), "download_url": "/api/export/shot-list"}

    def method_export_timing(self) -> dict[str, str]:
        project = app_state._require_project(self.app)
        output_path = project.exports_dir / "timing.json"
        try:
            export_timing_json(project, output_path)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return {"path": str(output_path), "download_url": "/api/export/timing"}

    def method_export_contact_sheet(self) -> dict[str, str]:
        project = app_state._require_project(self.app)
        output_path = project.exports_dir / "contact_sheet.png"
        try:
            export_contact_sheet(project, output_path)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return {"path": str(output_path), "download_url": "/api/export/contact-sheet"}

    def method_export_image_sequence(self) -> dict[str, str]:
        project = app_state._require_project(self.app)
        output_dir = project.exports_dir / "image_sequence"
        try:
            export_image_sequence(project, output_dir)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return {"path": str(output_dir)}

    def method_get_scene3d_file(self) -> dict[str, str]:
        project = app_state._require_project(self.app)
        try:
            path = project_manager.get_scene3d_file_path(project)
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if path is None:
            raise HTTPException(status_code=404, detail="No Blender scene imported.")
        media_type = "model/gltf-binary" if path.suffix.lower() == ".glb" else "model/gltf+json"
        return {"path": str(path), "media_type": media_type, "filename": path.name}

    def method_get_shot_image(self, shot_id: str) -> dict[str, str]:
        project = app_state._require_project(self.app)
        shot = app_state._find_shot(project, shot_id)
        image_path = project_manager.resolve_shot_preview_path(project, shot)
        if image_path is None:
            raise HTTPException(status_code=404, detail="No image for this shot.")
        return {"path": str(image_path), "media_type": "", "filename": image_path.name}

    def method_get_shot_thumbnail(self, shot_id: str) -> dict[str, str]:
        project = app_state._require_project(self.app)
        shot = app_state._find_shot(project, shot_id)
        image_path = project_manager.resolve_shot_thumbnail_path(project, shot)
        if image_path is None:
            raise HTTPException(status_code=404, detail="No thumbnail for this shot.")
        return {"path": str(image_path), "media_type": "", "filename": image_path.name}

    def method_get_shot_board_background(self, shot_id: str) -> dict[str, str]:
        project = app_state._require_project(self.app)
        shot = app_state._find_shot(project, shot_id)
        background_path = project_manager.get_shot_board_background_path(project, shot)
        if background_path is None or not background_path.is_file():
            raise HTTPException(status_code=404, detail="No board background for this shot.")
        return {"path": str(background_path), "media_type": "", "filename": background_path.name}

    def method_get_project_file(self, path: str) -> dict[str, str]:
        project = app_state._require_project(self.app)
        file_path = (project.root_path / path).resolve()
        root = project.root_path.resolve()
        if root not in file_path.parents and file_path != root:
            raise HTTPException(status_code=400, detail="File path is outside the project.")
        if not file_path.exists() or not file_path.is_file():
            raise HTTPException(status_code=404, detail="File is missing.")
        return {"path": str(file_path), "media_type": "", "filename": file_path.name}

    def method_download_shot_list(self) -> dict[str, str]:
        project = app_state._require_project(self.app)
        output_path = project.exports_dir / "shot_list.csv"
        if not output_path.exists():
            raise HTTPException(status_code=404, detail="Export the shot list first.")
        return {
            "path": str(output_path),
            "media_type": "text/csv",
            "filename": "shot_list.csv",
        }

    def method_download_timing(self) -> dict[str, str]:
        project = app_state._require_project(self.app)
        output_path = project.exports_dir / "timing.json"
        if not output_path.exists():
            raise HTTPException(status_code=404, detail="Export timing data first.")
        return {
            "path": str(output_path),
            "media_type": "application/json",
            "filename": "timing.json",
        }

    def method_download_contact_sheet(self) -> dict[str, str]:
        project = app_state._require_project(self.app)
        output_path = project.exports_dir / "contact_sheet.png"
        if not output_path.exists():
            raise HTTPException(status_code=404, detail="Export the contact sheet first.")
        return {
            "path": str(output_path),
            "media_type": "image/png",
            "filename": "contact_sheet.png",
        }

    def method_download_pdf(self) -> dict[str, str]:
        project = app_state._require_project(self.app)
        output_path = project.exports_dir / "storyboard.pdf"
        if not output_path.exists():
            raise HTTPException(status_code=404, detail="Export the PDF first.")
        return {
            "path": str(output_path),
            "media_type": "application/pdf",
            "filename": "storyboard.pdf",
        }
