from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


SHOT_STATUSES = ("Draft", "In Progress", "Review", "Approved", "Final")


@dataclass
class Shot:
    shot_id: str
    title: str = ""
    scene: str = ""
    sequence: str = ""
    description: str = ""
    action_note: str = ""
    camera_note: str = ""
    character_note: str = ""
    dialogue: str = ""
    lighting_note: str = ""
    transition_note: str = ""
    duration_seconds: float = 3.0
    camera_data: dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    comments: list[dict[str, Any]] = field(default_factory=list)
    status: str = "Draft"
    image_path: str = ""
    preview_image_path: str = ""
    thumbnail_path: str = ""
    source_file_path: str = ""
    source_sync_mtime: float = 0.0
    annotation_path: str = ""
    reference_image_paths: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Shot":
        status = str(data.get("status", "Draft"))
        if status not in SHOT_STATUSES:
            status = "Draft"
        image_path = str(data.get("image_path", ""))
        preview_path = str(data.get("preview_image_path", "")) or image_path
        return cls(
            shot_id=str(data.get("shot_id", "")),
            title=str(data.get("title", "")),
            scene=str(data.get("scene", "")),
            sequence=str(data.get("sequence", "")),
            description=str(data.get("description", "")),
            action_note=str(data.get("action_note", "")),
            camera_note=str(data.get("camera_note", "")),
            character_note=str(data.get("character_note", "")),
            dialogue=str(data.get("dialogue", "")),
            lighting_note=str(data.get("lighting_note", "")),
            transition_note=str(data.get("transition_note", "")),
            duration_seconds=float(data.get("duration_seconds", 3.0) or 3.0),
            camera_data=data.get("camera_data", {}) if isinstance(data.get("camera_data", {}), dict) else {},
            tags=_string_list(data.get("tags", [])),
            comments=[item for item in data.get("comments", []) if isinstance(item, dict)],
            status=status,
            image_path=image_path,
            preview_image_path=preview_path,
            thumbnail_path=str(data.get("thumbnail_path", "")),
            source_file_path=str(data.get("source_file_path", "")),
            source_sync_mtime=float(data.get("source_sync_mtime", 0.0) or 0.0),
            annotation_path=str(data.get("annotation_path", "")),
            reference_image_paths=_string_list(data.get("reference_image_paths", [])),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Project:
    root_path: Path
    shots: list[Shot] = field(default_factory=list)
    settings: dict[str, Any] = field(default_factory=dict)

    @property
    def json_path(self) -> Path:
        return self.root_path / "project.json"

    @property
    def images_dir(self) -> Path:
        return self.root_path / "images"

    @property
    def shots_dir(self) -> Path:
        return self.root_path / "shots"

    @property
    def references_dir(self) -> Path:
        return self.root_path / "references"

    @property
    def exports_dir(self) -> Path:
        return self.root_path / "exports"

    @property
    def scripts_dir(self) -> Path:
        return self.root_path / "scripts"

    @property
    def backups_dir(self) -> Path:
        return self.root_path / "backups"

    @property
    def settings_path(self) -> Path:
        return self.root_path / "settings.json"

    @property
    def name(self) -> str:
        return self.root_path.name

    def to_dict(self) -> dict[str, Any]:
        return {}


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, list):
        return [str(item) for item in value]
    return []
