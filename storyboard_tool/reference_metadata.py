"""Pure normalization for persisted reference-library metadata.

Storage and reference workflows share these helpers without importing one
another. They operate on JSON-compatible values and do not access project files.
"""
from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any

REFERENCE_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp"}
REFERENCE_VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v"}
REFERENCE_MODEL_EXTENSIONS = {".glb", ".gltf"}


def _normalize_reference_path(path: str) -> str:
    return str(path or "").replace("\\", "/").strip()


def normalize_reference_links(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    normalized: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        path = _normalize_reference_path(str(item.get("path") or item.get("url") or "").strip())
        if not path or re.match(r"^https?://", path, re.IGNORECASE):
            continue
        media_type = str(item.get("type") or "").strip().lower()
        if media_type not in {"image", "video", "model", "scene2d"}:
            media_type = reference_media_type(path)
        title = str(item.get("title", "") or "").strip() or Path(path).name or path
        ref_id = str(item.get("id", "") or "").strip() or uuid.uuid4().hex
        while ref_id in seen_ids:
            ref_id = uuid.uuid4().hex
        seen_ids.add(ref_id)
        normalized_link: dict[str, Any] = {"id": ref_id, "title": title, "type": media_type, "path": path}
        if media_type == "scene2d":
            source_scene2d_id = str(item.get("source_scene2d_id", "") or "").strip()
            if source_scene2d_id:
                normalized_link["source_scene2d_id"] = source_scene2d_id
            source_scene2d_perspective_id = str(item.get("source_scene2d_perspective_id", "") or "").strip()
            if source_scene2d_perspective_id:
                normalized_link["source_scene2d_perspective_id"] = source_scene2d_perspective_id
        normalized.append(normalized_link)
    return normalized


def reference_media_type(path: str) -> str:
    suffix = Path(path).suffix.lower()
    if suffix in REFERENCE_MODEL_EXTENSIONS:
        return "model"
    if suffix in REFERENCE_VIDEO_EXTENSIONS:
        return "video"
    return "image"


def ensure_reference_library(settings: dict[str, Any]) -> None:
    links = normalize_reference_links(settings.get("reference_links"))
    video_path = _normalize_reference_path(str(settings.get("reference_video_path") or "").strip())
    if video_path and not any(link["path"] == video_path for link in links):
        links.insert(
            0,
            {
                "id": uuid.uuid4().hex,
                "title": Path(video_path).name or "Reference video",
                "type": "video",
                "path": video_path,
            },
        )
    model_path = _normalize_reference_path(str(settings.get("reference_model_path") or "").strip())
    if model_path and not any(link["path"] == model_path for link in links):
        links.insert(
            0,
            {
                "id": uuid.uuid4().hex,
                "title": Path(model_path).name or "Reference model",
                "type": "model",
                "path": model_path,
            },
        )
    image_path = _normalize_reference_path(str(settings.get("reference_image_path") or "").strip())
    if image_path and not any(link["path"] == image_path for link in links):
        links.insert(
            0,
            {
                "id": uuid.uuid4().hex,
                "title": Path(image_path).name or "Reference image",
                "type": "image",
                "path": image_path,
            },
        )
    scene3d_path = _normalize_reference_path(str((settings.get("scene3d") or {}).get("file_path", "") or "").strip())
    if scene3d_path and scene3d_path not in {link["path"] for link in links}:
        media_type = reference_media_type(scene3d_path)
        if media_type == "model":
            links.append(
                {
                    "id": uuid.uuid4().hex,
                    "title": Path(scene3d_path).name or "Scene model",
                    "type": "model",
                    "path": scene3d_path,
                }
            )
    for link in links:
        if link["type"] == "scene2d":
            continue
        inferred = reference_media_type(link["path"])
        if inferred != link["type"]:
            link["type"] = inferred
    settings["reference_links"] = links
