from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


SHOT_STATUSES = ("Draft", "In Progress", "Review", "Approved", "Final")

SHOT_DESIGN_TEXT_FIELDS = (
    "story_beat",
    "shot_size",
    "camera_position",
    "camera_height",
    "camera_angle",
    "camera_direction",
    "camera_movement",
    "lens_intent",
    "subject_movement",
    "composition",
    "focal_point",
    "foreground",
    "midground",
    "background",
    "axis_of_action",
)
PROMPT_MODES = ("auto", "manual")
CONTINUITY_MODES = ("continuous", "insert", "montage", "parallel", "time-jump", "reset")
GENERATION_EXECUTION_STATUSES = ("idle", "queued", "running", "succeeded", "failed", "cancelled")
GENERATION_REVIEW_STATUSES = ("unreviewed", "needs-review", "accepted", "rejected")
GENERATION_FRESHNESS_STATUSES = ("current", "stale")


def default_shot_design() -> dict[str, Any]:
    return {
        **{field_name: "" for field_name in SHOT_DESIGN_TEXT_FIELDS},
        "intentional_axis_crossing": False,
    }


def normalize_shot_design(value: Any) -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    normalized = default_shot_design()
    for field_name in SHOT_DESIGN_TEXT_FIELDS:
        normalized[field_name] = str(raw.get(field_name, ""))
    normalized["intentional_axis_crossing"] = bool(raw.get("intentional_axis_crossing", False))
    return normalized


def default_prompt_config() -> dict[str, Any]:
    return {
        "mode": "auto",
        "manual_prompt": "",
        "prompt_extra": "",
        "negative_prompt": "",
        "style_profile_id": "",
        "aspect_ratio_override": "",
        "variant_count": 1,
        "reference_bindings": [],
    }


def normalize_prompt_config(value: Any) -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    normalized = default_prompt_config()
    mode = str(raw.get("mode", "auto"))
    normalized["mode"] = mode if mode in PROMPT_MODES else "auto"
    for field_name in (
        "manual_prompt",
        "prompt_extra",
        "negative_prompt",
        "style_profile_id",
        "aspect_ratio_override",
    ):
        normalized[field_name] = str(raw.get(field_name, ""))
    try:
        variant_count = int(raw.get("variant_count", 1))
    except (TypeError, ValueError):
        variant_count = 1
    normalized["variant_count"] = max(1, min(8, variant_count))
    bindings = raw.get("reference_bindings", [])
    normalized["reference_bindings"] = [dict(item) for item in bindings if isinstance(item, dict)] if isinstance(bindings, list) else []
    return normalized


def default_continuity() -> dict[str, Any]:
    return {
        "mode": "continuous",
        "depends_on_shot_ids": [],
        "primary_continuity_source_shot_id": "",
        "expected_in": "",
        "expected_out": "",
        "observed_out": "",
        "resolved_out": "",
        "preserve": [],
        "intentional_changes": [],
    }


def normalize_continuity(value: Any) -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    normalized = default_continuity()
    mode = str(raw.get("mode", "continuous"))
    normalized["mode"] = mode if mode in CONTINUITY_MODES else "continuous"
    normalized["depends_on_shot_ids"] = _unique_string_list(raw.get("depends_on_shot_ids", []))
    normalized["primary_continuity_source_shot_id"] = str(raw.get("primary_continuity_source_shot_id", ""))
    for field_name in ("expected_in", "expected_out", "observed_out", "resolved_out"):
        normalized[field_name] = str(raw.get(field_name, ""))
    normalized["preserve"] = _unique_string_list(raw.get("preserve", []))
    normalized["intentional_changes"] = _unique_string_list(raw.get("intentional_changes", []))
    return normalized


def default_generation_state() -> dict[str, Any]:
    return {
        "execution_status": "idle",
        "review_status": "unreviewed",
        "freshness_status": "current",
        "active_output_id": "",
        "approved_output_id": "",
        "latest_attempt_id": "",
    }


def normalize_generation_state(value: Any) -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    normalized = default_generation_state()
    execution = str(raw.get("execution_status", "idle"))
    review = str(raw.get("review_status", "unreviewed"))
    freshness = str(raw.get("freshness_status", "current"))
    normalized["execution_status"] = execution if execution in GENERATION_EXECUTION_STATUSES else "idle"
    normalized["review_status"] = review if review in GENERATION_REVIEW_STATUSES else "unreviewed"
    normalized["freshness_status"] = freshness if freshness in GENERATION_FRESHNESS_STATUSES else "current"
    for field_name in ("active_output_id", "approved_output_id", "latest_attempt_id"):
        normalized[field_name] = str(raw.get(field_name, ""))
    return normalized


@dataclass
class Shot:
    shot_id: str
    title: str = ""
    scene: str = ""
    scene_id: str = ""
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
    ref_video_path: str = ""
    ref_video_time: float = 0.0
    ref_segment_time: float = 0.0
    shot_design: dict[str, Any] = field(default_factory=default_shot_design)
    prompt_config: dict[str, Any] = field(default_factory=default_prompt_config)
    continuity: dict[str, Any] = field(default_factory=default_continuity)
    generation_state: dict[str, Any] = field(default_factory=default_generation_state)

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
            scene_id=str(data.get("scene_id", "")),
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
            ref_video_path=str(data.get("ref_video_path", "")),
            ref_video_time=float(data.get("ref_video_time", 0.0) or 0.0),
            ref_segment_time=float(data.get("ref_segment_time", 0.0) or 0.0),
            shot_design=normalize_shot_design(data.get("shot_design")),
            prompt_config=normalize_prompt_config(data.get("prompt_config")),
            continuity=normalize_continuity(data.get("continuity")),
            generation_state=normalize_generation_state(data.get("generation_state")),
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
    def scenes2d_dir(self) -> Path:
        return self.root_path / "scenes2d"

    @property
    def scenes3d_dir(self) -> Path:
        return self.root_path / "scenes3d"

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
        return {
            "name": self.name,
            "root_path": str(self.root_path),
            "shots": [shot.to_dict() for shot in self.shots],
            "settings": dict(self.settings),
        }


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, list):
        return [str(item) for item in value]
    return []


def _unique_string_list(value: Any) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in _string_list(value):
        cleaned = item.strip()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            result.append(cleaned)
    return result
