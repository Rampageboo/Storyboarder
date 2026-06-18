from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException

from . import app_state, export_service, project_manager
from .errors import AppErrorCode, app_error

logger = logging.getLogger(__name__)

_DOWNLOAD_URLS: dict[str, str] = {
    "pdf": "/api/export/pdf",
    "shot_list": "/api/export/shot-list",
    "timing": "/api/export/timing",
    "contact_sheet": "/api/export/contact-sheet",
}

_MEDIA_TYPES: dict[str, str] = {
    "pdf": "application/pdf",
    "shot_list": "text/csv",
    "timing": "application/json",
    "contact_sheet": "image/png",
}

_FILENAMES: dict[str, str] = {
    "pdf": "storyboard.pdf",
    "shot_list": "shot_list.csv",
    "timing": "timing.json",
    "contact_sheet": "contact_sheet.png",
}


class ExportServiceMixin:
    """Export generation, download lookups, and project file serving."""

    def method_export_pdf(self, layout: str = "two_per_page") -> dict[str, str]:
        project = app_state._require_project(self.app)
        chosen = layout if layout in export_service.VALID_PDF_LAYOUTS else export_service.DEFAULT_PDF_LAYOUT
        try:
            output_path = export_service.export_pdf(project, chosen)
        except Exception as exc:
            logger.exception("PDF export failed (layout=%s)", chosen)
            raise app_error(AppErrorCode.EXPORT_FAILED, str(exc), status=500) from exc
        project.settings["pdf_layout"] = chosen
        project_manager.save_settings(project)
        return {"path": str(output_path), "download_url": _DOWNLOAD_URLS["pdf"]}

    def method_export_shot_list(self) -> dict[str, str]:
        project = app_state._require_project(self.app)
        try:
            output_path = export_service.export_shot_list(project)
        except Exception as exc:
            logger.exception("Shot list export failed")
            raise app_error(AppErrorCode.EXPORT_FAILED, str(exc), status=500) from exc
        return {"path": str(output_path), "download_url": _DOWNLOAD_URLS["shot_list"]}

    def method_export_timing(self) -> dict[str, str]:
        project = app_state._require_project(self.app)
        try:
            output_path = export_service.export_timing(project)
        except Exception as exc:
            logger.exception("Timing export failed")
            raise app_error(AppErrorCode.EXPORT_FAILED, str(exc), status=500) from exc
        return {"path": str(output_path), "download_url": _DOWNLOAD_URLS["timing"]}

    def method_export_contact_sheet(self) -> dict[str, str]:
        project = app_state._require_project(self.app)
        try:
            output_path = export_service.export_contact_sheet(project)
        except Exception as exc:
            logger.exception("Contact sheet export failed")
            raise app_error(AppErrorCode.EXPORT_FAILED, str(exc), status=500) from exc
        return {"path": str(output_path), "download_url": _DOWNLOAD_URLS["contact_sheet"]}

    def method_export_image_sequence(self) -> dict[str, str]:
        project = app_state._require_project(self.app)
        try:
            output_dir = export_service.export_image_sequence(project)
        except Exception as exc:
            logger.exception("Image sequence export failed")
            raise app_error(AppErrorCode.EXPORT_FAILED, str(exc), status=500) from exc
        return {"path": str(output_dir)}

    def method_get_scene3d_file(self) -> dict[str, str]:
        project = app_state._require_project(self.app)
        try:
            path = project_manager.get_scene3d_file_path(project)
        except (FileNotFoundError, ValueError) as exc:
            raise app_error(AppErrorCode.MEDIA_NOT_FOUND, str(exc), status=404) from exc
        if path is None:
            raise app_error(AppErrorCode.MEDIA_NOT_FOUND, "No Blender scene imported.", status=404)
        media_type = "model/gltf-binary" if path.suffix.lower() == ".glb" else "model/gltf+json"
        return {"path": str(path), "media_type": media_type, "filename": path.name}

    def method_get_shot_image(self, shot_id: str) -> dict[str, str]:
        project = app_state._require_project(self.app)
        shot = app_state._find_shot(project, shot_id)
        image_path = project_manager.resolve_shot_preview_path(project, shot)
        if image_path is None:
            raise app_error(AppErrorCode.MEDIA_NOT_FOUND, "No image for this shot.", status=404)
        return {"path": str(image_path), "media_type": "", "filename": image_path.name}

    def method_get_shot_thumbnail(self, shot_id: str) -> dict[str, str]:
        project = app_state._require_project(self.app)
        shot = app_state._find_shot(project, shot_id)
        image_path = project_manager.resolve_shot_thumbnail_path(project, shot)
        if image_path is None:
            raise app_error(AppErrorCode.MEDIA_NOT_FOUND, "No thumbnail for this shot.", status=404)
        return {"path": str(image_path), "media_type": "", "filename": image_path.name}

    def method_get_shot_board_background(self, shot_id: str) -> dict[str, str]:
        project = app_state._require_project(self.app)
        shot = app_state._find_shot(project, shot_id)
        background_path = project_manager.get_shot_board_background_path(project, shot)
        if background_path is None or not background_path.is_file():
            raise app_error(AppErrorCode.MEDIA_NOT_FOUND, "No board background for this shot.", status=404)
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
        try:
            output_path = export_service.check_export_exists(project, "shot_list")
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {
            "path": str(output_path),
            "media_type": _MEDIA_TYPES["shot_list"],
            "filename": _FILENAMES["shot_list"],
        }

    def method_download_timing(self) -> dict[str, str]:
        project = app_state._require_project(self.app)
        try:
            output_path = export_service.check_export_exists(project, "timing")
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {
            "path": str(output_path),
            "media_type": _MEDIA_TYPES["timing"],
            "filename": _FILENAMES["timing"],
        }

    def method_download_contact_sheet(self) -> dict[str, str]:
        project = app_state._require_project(self.app)
        try:
            output_path = export_service.check_export_exists(project, "contact_sheet")
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {
            "path": str(output_path),
            "media_type": _MEDIA_TYPES["contact_sheet"],
            "filename": _FILENAMES["contact_sheet"],
        }

    def method_download_pdf(self) -> dict[str, str]:
        project = app_state._require_project(self.app)
        try:
            output_path = export_service.check_export_exists(project, "pdf")
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {
            "path": str(output_path),
            "media_type": _MEDIA_TYPES["pdf"],
            "filename": _FILENAMES["pdf"],
        }
