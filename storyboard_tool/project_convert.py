"""Transactional, source-preserving Layout 1 to Layout 2 conversion."""
from __future__ import annotations

import copy
import json
import os
import shutil
import tempfile
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from . import generation_service, project_document, project_manager, scene2d, scene3d
from .models import Project, Shot
from .project_layout import (
    LAYOUT_1,
    LAYOUT_2,
    ensure_no_casefold_collisions,
    generation_asset_relative,
    generation_metadata_path,
    project_manifest,
    reference_asset_relative,
    resolve_project_path,
    resolve_root_child,
    scene2d_asset_relative,
    scene3d_asset_relative,
    scene3d_preview_path,
    shot_asset_relative,
    validate_project_relative_posix,
)
from .project_save_as import (
    FileRecord,
    TreeInventory,
    _copy_inventory,
    _destination_paths,
    _is_reparse,
    _record,
    _scan_tree,
    _snapshot_hash,
    validate_layout2_stored_references,
)
from .project_storage import atomic_write_json, save_settings
from .shot_store import save_shots_json


class Layout2ConvertError(RuntimeError):
    """A failed conversion with its durable inventory report when available."""

    def __init__(
        self,
        stage: str,
        message: str,
        *,
        operation_path: Path | None = None,
        report_path: Path | None = None,
        destination_root: Path | None = None,
    ) -> None:
        self.stage = stage
        self.operation_path = operation_path
        self.report_path = report_path
        self.destination_root = destination_root
        suffix = f" Report: {report_path}." if report_path else ""
        super().__init__(f"Layout 1 to Layout 2 conversion failed during {stage}: {message}.{suffix}")


@dataclass(frozen=True)
class Layout2ConvertResult:
    destination_root: Path
    document_path: Path
    snapshot_hash: str
    source_hash: str
    source_file_count: int
    destination_file_count: int
    excluded_paths: tuple[str, ...]
    report: dict[str, Any]


def _write_report(path: Path, report: dict[str, Any]) -> None:
    """Atomically replace and fsync a conversion checkpoint."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    fd, temporary = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        with path.open("r+b") as handle:
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _input_inventory(source: TreeInventory) -> TreeInventory:
    def portable(name: str) -> bool:
        return not (name == "backups" or name.startswith("backups/"))

    return TreeInventory(
        files=source.files,
        copy_files={name: record for name, record in source.copy_files.items() if portable(name)},
        copy_directories=tuple(name for name in source.copy_directories if portable(name)),
        excluded=tuple(sorted(set(source.excluded).union(
            name for name in source.copy_files if not portable(name)
        ))),
    )


def _analysis_project(project: Project, root: Path) -> Project:
    frozen = copy.deepcopy(project)
    frozen.layout = LAYOUT_1
    frozen.root_path = root
    frozen.project_root_path = None
    frozen.document_path = None
    atomic_write_json(frozen.json_path, project_manifest(frozen))
    save_shots_json(frozen.metadata_root, list(frozen.shots))
    save_settings(frozen)
    return frozen


def _target_project(
    source: Project,
    root: Path,
    document_name: str,
    *,
    source_document: Path,
    source_version: int,
    source_hash: str,
) -> Project:
    target = copy.deepcopy(source)
    target.layout = LAYOUT_2
    target.project_id = str(uuid.uuid4())
    target.storage_revision = 1
    target.project_root_path = root
    target.root_path = resolve_root_child(root, ".storyboarder", "work")
    target.document_path = resolve_root_child(root, document_name)
    target.converted_from = {
        "source_path": str(source_document),
        "timestamp": datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "source_version": source_version,
        "source_hash": source_hash,
    }
    return target


class _Planner:
    def __init__(
        self,
        source: Project,
        target: Project,
        source_inventory: TreeInventory,
        final_root: Path,
    ) -> None:
        self.source = source
        self.target = target
        self.source_inventory = source_inventory
        self.final_root = final_root
        self.claimed: set[str] = set()
        self.known_directories: set[str] = set()
        self.excluded: set[str] = set()
        self.source_to_target: dict[tuple[str, str], str] = {}
        self.target_to_source: dict[str, str] = {}
        self.scene2d_ids: dict[str, str] = {}
        self.scene2d_perspective_ids: dict[tuple[str, str], str] = {}
        self.scene2d_paths: dict[str, str] = {}
        self.scene3d_paths: dict[str, str] = {}
        self.target_names: list[str] = []
        self.classifications: list[dict[str, str]] = []

    def _source_relative(self, value: str, label: str) -> tuple[str, Path]:
        path = resolve_project_path(self.source, value, field_name=label)
        relative = path.relative_to(self.source.project_root).as_posix()
        return relative, path

    def _record_classification(self, source: str, kind: str, target: str = "") -> None:
        self.claimed.add(source)
        for parent in PurePosixPath(source).parents:
            if parent.as_posix() != ".":
                self.known_directories.add(parent.as_posix())
        row = {"source": source, "kind": kind}
        if target:
            row["target"] = target
        self.classifications.append(row)

    def discard(self, source: str, kind: str) -> None:
        if source in self.source_inventory.copy_files:
            self._record_classification(source, kind)
            if kind.startswith("excluded") or "excluded " in kind:
                self.excluded.add(source)

    def copy(self, source_value: str, target_relative: str, label: str, *, required: bool) -> str:
        if not source_value:
            if required:
                raise FileNotFoundError(f"Missing required {label} path.")
            return ""
        source_relative, source_path = self._source_relative(source_value, label)
        if not source_path.is_file():
            if required:
                raise FileNotFoundError(f"Missing required {label}: {source_relative}.")
            return ""
        target_relative = validate_project_relative_posix(
            target_relative,
            field_name=f"converted {label}",
        ).as_posix()
        mapping_key = (source_relative, target_relative)
        existing = self.source_to_target.get(mapping_key)
        if existing:
            self._record_classification(source_relative, label, existing)
            return existing
        folded = target_relative.casefold()
        occupied_source = self.target_to_source.get(folded)
        if occupied_source is not None and occupied_source != source_relative:
            raise ValueError(f"Converted target path collision: {target_relative}.")
        if occupied_source == source_relative:
            self.source_to_target[mapping_key] = target_relative
            self._record_classification(source_relative, label, target_relative)
            return target_relative
        destination = resolve_root_child(self.target.project_root, *PurePosixPath(target_relative).parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, destination)
        if _record(destination) != _record(source_path):
            raise OSError(f"Converted asset failed hash verification: {source_relative}.")
        self.source_to_target[mapping_key] = target_relative
        self.target_to_source[folded] = source_relative
        self.target_names.append(target_relative)
        self._record_classification(source_relative, label, target_relative)
        return target_relative

    def mapped_reference(self, value: str, label: str) -> str:
        if not value:
            return ""
        source_relative, source_path = self._source_relative(value, label)
        if not source_path.is_file():
            raise FileNotFoundError(f"Missing stored reference for {label}: {source_relative}.")
        asset_id = str(uuid.uuid5(uuid.NAMESPACE_URL, source_relative))
        target_relative = reference_asset_relative(self.target, asset_id, source_path.suffix)
        return self.copy(source_relative, target_relative, label, required=True)

    def copy_export_tree(self) -> None:
        for name in sorted(self.source_inventory.copy_files):
            if name.startswith("exports/"):
                target = f"Exports/{name[len('exports/') :]}"
                self.copy(name, target, "legacy export", required=True)

    def unknown_members(self) -> list[str]:
        ignored_prefixes = ("backups/",)
        for name in sorted(self.source_inventory.copy_files):
            if name.startswith(ignored_prefixes):
                self.discard(name, "excluded legacy backup")
        known_empty_roots = {
            "backups", "exports", "references", "scene3d", "scenes2d",
            "scenes3d", "scripts", "shots", "generation",
        }
        self.known_directories.update(known_empty_roots)
        unknown = [
            name for name in sorted(self.source_inventory.copy_files)
            if name not in self.claimed
        ]
        unknown.extend(
            f"{name}/" for name in self.source_inventory.copy_directories
            if (
                name not in self.known_directories
                and name != "backups"
                and not name.startswith("backups/")
            )
        )
        return sorted(set(unknown))


def _migrate_shots(planner: _Planner) -> None:
    planner.discard("project.json", "rewritten Layout 2 manifest")
    planner.discard("settings.json", "rewritten Layout 2 settings")
    planner.discard("shots.json", "rewritten Layout 2 shots")
    planner.discard("shots.csv", "discarded compatibility CSV")
    planner.discard("canvas_color.txt", "discarded runtime bridge")
    planner.discard("storyboard_bridge.json", "discarded runtime bridge")

    target_by_id = {shot.shot_id: shot for shot in planner.target.shots}
    for source_shot in planner.source.shots:
        target_shot = target_by_id[source_shot.shot_id]
        planner.known_directories.update({
            f"shots/{source_shot.shot_id}",
            f"shots/{source_shot.shot_id}/references",
        })
        history_prefix = f"shots/{source_shot.shot_id}/_history/"
        planner.known_directories.add(history_prefix.rstrip("/"))
        for name in sorted(planner.source_inventory.copy_files):
            if name.startswith(history_prefix):
                planner.discard(
                    name,
                    "excluded legacy PSD recovery backup",
                )
        source_path = source_shot.source_file_path
        if source_path and Path(source_path).suffix.lower() != ".psd":
            raise ValueError(f"Layout 2 conversion requires PSD shot sources: {source_path}.")
        target_shot.source_file_path = planner.copy(
            source_path,
            shot_asset_relative(planner.target, source_shot.shot_id, "source_psd"),
            f"shot {source_shot.shot_id} source",
            required=bool(source_path),
        )
        preview_source = source_shot.preview_image_path or source_shot.image_path
        preview = planner.copy(
            preview_source,
            shot_asset_relative(planner.target, source_shot.shot_id, "preview"),
            f"shot {source_shot.shot_id} preview",
            required=bool(preview_source),
        )
        target_shot.preview_image_path = preview
        target_shot.image_path = preview
        target_shot.thumbnail_path = planner.copy(
            source_shot.thumbnail_path,
            shot_asset_relative(planner.target, source_shot.shot_id, "thumbnail"),
            f"shot {source_shot.shot_id} thumbnail",
            required=False,
        )
        annotation_target = resolve_root_child(
            planner.target.metadata_root, "annotations", f"{source_shot.shot_id}.json"
        ).relative_to(planner.target.project_root).as_posix()
        target_shot.annotation_path = planner.copy(
            source_shot.annotation_path,
            annotation_target,
            f"shot {source_shot.shot_id} annotations",
            required=True,
        )
        notes_source = f"shots/{source_shot.shot_id}/{source_shot.shot_id}_notes.json"
        notes_target = resolve_root_child(
            planner.target.metadata_root, "notes", f"{source_shot.shot_id}.json"
        ).relative_to(planner.target.project_root).as_posix()
        planner.copy(notes_source, notes_target, f"shot {source_shot.shot_id} notes", required=True)
        for role in ("board_background", "codex"):
            source_role = shot_asset_relative(planner.source, source_shot.shot_id, role)
            planner.copy(
                source_role,
                shot_asset_relative(planner.target, source_shot.shot_id, role),
                f"shot {source_shot.shot_id} {role}",
                required=False,
            )
        for runtime_name in ("canvas_color.txt", "storyboard_bridge.json"):
            planner.discard(
                f"shots/{source_shot.shot_id}/{runtime_name}",
                "discarded shot runtime bridge",
            )


def _conversion_uuid(planner: _Planner, kind: str, *parts: str) -> str:
    seed = ":".join((str(planner.source.project_id or ""), kind, *parts))
    return str(uuid.uuid5(uuid.NAMESPACE_URL, seed))


def _load_scene2d_for_conversion(project: Project) -> list[dict[str, Any]]:
    """Read supported Layout 1 Scene2D metadata without invoking its disk migration."""
    index = scene2d._index_path(project)
    raw_scenes: Any
    if index.is_file():
        try:
            payload = json.loads(index.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Legacy Scene 2D index is unreadable.") from exc
        raw_scenes = payload.get("scenes") if isinstance(payload, dict) else payload
    else:
        raw_scenes = []
        for path in sorted(project.project_root.glob("scenes2d/*/*_meta.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError(
                    f"Legacy Scene 2D metadata is unreadable: {path.name}."
                ) from exc
            if not isinstance(payload, dict):
                raise ValueError(f"Legacy Scene 2D metadata is invalid: {path.name}.")
            raw_scenes.append(payload)
    if not isinstance(raw_scenes, list) or any(
        not isinstance(row, dict) for row in raw_scenes
    ):
        raise ValueError("Legacy Scene 2D index must contain a scenes list.")
    scenes: list[dict[str, Any]] = []
    scene_ids: set[str] = set()
    perspective_uuids: set[str] = set()
    for row in raw_scenes:
        scene = scene2d._normalize_scene(row, legacy=True, project=project)
        if scene["id"] in scene_ids:
            raise ValueError("Legacy Scene 2D contains duplicate scene IDs.")
        scene_ids.add(scene["id"])
        for perspective in scene.get("perspectives") or []:
            perspective_id = str(perspective["id"])
            if scene2d.is_uuid(perspective_id):
                if perspective_id in perspective_uuids:
                    raise ValueError(
                        "Legacy Scene 2D contains duplicate perspective UUIDs."
                    )
                perspective_uuids.add(perspective_id)
        scenes.append(scene)
    return scene2d._sort_scenes(scenes)


def _remap_scene2d_links(planner: _Planner) -> None:
    for shot in planner.target.shots:
        if not shot.scene_id:
            continue
        if shot.scene_id not in planner.scene2d_ids:
            raise ValueError(f"Shot references an unknown Scene 2D id: {shot.scene_id}.")
        shot.scene_id = planner.scene2d_ids[shot.scene_id]

    links = planner.target.settings.get("reference_links") or []
    if not isinstance(links, list):
        raise ValueError("Project reference links are invalid.")
    for link in links:
        if not isinstance(link, dict):
            raise ValueError("Project reference link is invalid.")
        old_scene_id = str(link.get("source_scene2d_id") or "")
        old_perspective_id = str(link.get("source_scene2d_perspective_id") or "")
        if not old_scene_id:
            continue
        new_scene_id = planner.scene2d_ids.get(old_scene_id)
        if not new_scene_id:
            raise ValueError(f"Reference link uses an unknown Scene 2D id: {old_scene_id}.")
        link["source_scene2d_id"] = new_scene_id
        if old_perspective_id:
            new_perspective_id = planner.scene2d_perspective_ids.get(
                (old_scene_id, old_perspective_id)
            )
            if not new_perspective_id:
                raise ValueError(
                    "Reference link uses an unknown Scene 2D perspective id: "
                    f"{old_perspective_id}."
                )
            link["source_scene2d_perspective_id"] = new_perspective_id
        old_path = str(link.get("path") or "")
        if old_path in planner.scene2d_paths:
            link["path"] = planner.scene2d_paths[old_path]


def _migrate_scenes(planner: _Planner) -> None:
    scenes2d = _load_scene2d_for_conversion(planner.source)
    converted2d: list[dict[str, Any]] = []
    planner.discard("scenes2d/scenes2d.json", "rewritten Scene 2D index")
    for source_scene in scenes2d:
        old_scene_id = str(source_scene["id"])
        new_scene_id = (
            old_scene_id
            if scene2d.is_uuid(old_scene_id)
            else _conversion_uuid(planner, "scene2d", old_scene_id)
        )
        planner.scene2d_ids[old_scene_id] = new_scene_id
        converted = copy.deepcopy(source_scene)
        converted["id"] = new_scene_id
        planner.discard(
            f"scenes2d/{old_scene_id}/{old_scene_id}_meta.json",
            "rewritten Scene 2D metadata",
        )
        for perspective in converted.get("perspectives") or []:
            old_perspective_id = str(perspective["id"])
            new_perspective_id = (
                old_perspective_id
                if scene2d.is_uuid(old_perspective_id)
                else _conversion_uuid(
                    planner,
                    "scene2d-perspective",
                    old_scene_id,
                    old_perspective_id,
                )
            )
            planner.scene2d_perspective_ids[(old_scene_id, old_perspective_id)] = (
                new_perspective_id
            )
            perspective["id"] = new_perspective_id
            source_value = str(perspective.get("source_file_path") or "")
            suffix = Path(source_value).suffix.lower()
            role = "source_psd" if suffix == ".psd" else "source_image"
            mapped_source = planner.copy(
                source_value,
                scene2d_asset_relative(
                    planner.target,
                    new_scene_id,
                    new_perspective_id,
                    role,
                    suffix,
                ),
                f"Scene 2D {old_perspective_id} source",
                required=True,
            )
            perspective["source_file_path"] = mapped_source
            planner.scene2d_paths[source_value] = mapped_source
            preview_value = str(perspective.get("preview_image_path") or "")
            mapped_preview = planner.copy(
                preview_value,
                scene2d_asset_relative(
                    planner.target, new_scene_id, new_perspective_id, "preview"
                ),
                f"Scene 2D {old_perspective_id} preview",
                required=bool(preview_value),
            ) or mapped_source
            perspective["preview_image_path"] = mapped_preview
            if preview_value:
                planner.scene2d_paths[preview_value] = mapped_preview
        old_primary_id = str(source_scene.get("primary_perspective_id") or "")
        converted["primary_perspective_id"] = planner.scene2d_perspective_ids.get(
            (old_scene_id, old_primary_id),
            "",
        )
        converted2d.append(converted)
    _remap_scene2d_links(planner)
    scene2d._save_scenes(planner.target, converted2d)

    loaded3d = scene3d._read_index(planner.source)
    if loaded3d is None:
        legacy3d = scene3d._legacy_scene(planner.source)
        payload3d = {
            "active_scene3d_id": legacy3d["id"] if legacy3d else "",
            "scenes": [legacy3d] if legacy3d else [],
        }
    else:
        payload3d = {"active_scene3d_id": loaded3d[0], "scenes": loaded3d[1]}
    planner.discard("scenes3d/scenes3d.json", "rewritten Scene 3D index")
    converted3d: list[dict[str, Any]] = []
    for source_scene in payload3d.get("scenes", []):
        converted = copy.deepcopy(source_scene)
        planner.discard(
            f"scenes3d/{source_scene['id']}/{source_scene['id']}_meta.json",
            "rewritten Scene 3D metadata",
        )
        source_type = str(converted.get("source_type") or "").lower()
        blend_value = str(converted.get("blend_file_path") or "")
        if source_type == "blender" or blend_value:
            converted["source_type"] = "blender"
            mapped_blend = planner.copy(
                blend_value,
                scene3d_asset_relative(planner.target, converted["id"], ".blend"),
                f"Scene 3D {converted['id']} blend_file_path",
                required=True,
            )
            converted["blend_file_path"] = mapped_blend
            planner.scene3d_paths[blend_value] = mapped_blend

            preview_value = str(converted.get("file_path") or "")
            preview_target = scene3d_preview_path(
                planner.target, converted["id"]
            ).relative_to(planner.target.project_root).as_posix()
            mapped_preview = planner.copy(
                preview_value,
                preview_target,
                f"Scene 3D {converted['id']} derived preview",
                required=bool(preview_value),
            )
            converted["file_path"] = mapped_preview
            if preview_value:
                planner.scene3d_paths[preview_value] = mapped_preview
        else:
            value = str(converted.get("file_path") or "")
            if value:
                mapped_file = planner.copy(
                    value,
                    scene3d_asset_relative(
                        planner.target, converted["id"], Path(value).suffix
                    ),
                    f"Scene 3D {converted['id']} file_path",
                    required=True,
                )
                converted["file_path"] = mapped_file
                planner.scene3d_paths[value] = mapped_file
            else:
                converted["file_path"] = ""
            if str(converted.get("blend_file_path") or ""):
                raise ValueError("Non-Blender Scene 3D cannot carry a Blend source.")
        converted3d.append(converted)
    scene3d._save(planner.target, str(payload3d.get("active_scene3d_id") or ""), converted3d)


def _migrate_references(planner: _Planner) -> None:
    for shot in planner.target.shots:
        shot.reference_image_paths = [
            planner.mapped_reference(value, f"shot {shot.shot_id} reference")
            for value in shot.reference_image_paths
        ]
        shot.ref_video_path = planner.mapped_reference(
            shot.ref_video_path,
            f"shot {shot.shot_id} reference video",
        )
        bindings = shot.prompt_config.get("reference_bindings", [])
        for index, binding in enumerate(bindings if isinstance(bindings, list) else []):
            if not isinstance(binding, dict):
                continue
            for field in ("path", "relative_path", "reference_path"):
                if binding.get(field):
                    binding[field] = planner.mapped_reference(
                        str(binding[field]),
                        f"shot {shot.shot_id} binding {index} {field}",
                    )
    for field in ("reference_image_path", "reference_video_path", "reference_model_path"):
        value = str(planner.target.settings.get(field) or "")
        if value:
            planner.target.settings[field] = planner.mapped_reference(value, f"settings {field}")
    for index, link in enumerate(planner.target.settings.get("reference_links") or []):
        if not isinstance(link, dict) or not link.get("path"):
            continue
        if str(link.get("source_scene2d_id") or "") in set(
            planner.scene2d_ids.values()
        ):
            continue
        link["path"] = planner.mapped_reference(
            str(link["path"]), f"reference link {index}"
        )
    for index, segment in enumerate(planner.target.settings.get("ref_segments") or []):
        if isinstance(segment, dict) and segment.get("reference_path"):
            segment["reference_path"] = planner.mapped_reference(
                str(segment["reference_path"]), f"reference segment {index}"
            )


def _remap_generation_path(planner: _Planner, row: dict, relative_field: str, absolute_field: str, label: str) -> None:
    value = str(row.get(relative_field) or "")
    if not value:
        if row.get(absolute_field):
            raise ValueError(f"{label} has an absolute path without a portable path.")
        return
    mapped = (
        planner.scene2d_paths.get(value)
        or planner.scene3d_paths.get(value)
        or planner.mapped_reference(value, label)
    )
    row[relative_field] = mapped
    row[absolute_field] = str(resolve_root_child(planner.final_root, *PurePosixPath(mapped).parts))
    for exists_field in ("exists", "file_exists", "blend_file_exists"):
        if exists_field in row:
            row[exists_field] = True


def _read_generation_object(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is unreadable: {path.name}.") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be an object: {path.name}.")
    if payload.get("schema_version") != generation_service.SCHEMA_VERSION:
        raise ValueError(f"Unsupported {label.lower()}: {path.name}.")
    return payload


def _require_generation_id(value: Any, expected: str, label: str) -> str:
    identifier = generation_service._validate_id(str(value or ""), label)
    if identifier != expected:
        raise ValueError(f"{label.capitalize()} does not match its storage path.")
    return identifier


def _mapped_scene2d_path(planner: _Planner, value: Any, label: str) -> str:
    relative = str(value or "")
    if not relative:
        return ""
    mapped = planner.scene2d_paths.get(relative)
    if not mapped:
        raise ValueError(f"{label} references an unknown Scene 2D asset: {relative}.")
    return mapped


def _remap_scene2d_snapshot(
    planner: _Planner,
    value: Any,
    label: str,
) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object or null.")
    snapshot = copy.deepcopy(value)
    old_scene_id = str(snapshot.get("id") or "")
    if old_scene_id:
        new_scene_id = planner.scene2d_ids.get(old_scene_id)
        if not new_scene_id:
            raise ValueError(f"{label} uses an unknown Scene 2D id: {old_scene_id}.")
        snapshot["id"] = new_scene_id
    for field in ("source_file_path", "preview_image_path", "primary_reference_path"):
        if snapshot.get(field):
            snapshot[field] = _mapped_scene2d_path(
                planner, snapshot[field], f"{label} {field}"
            )
    raw_perspectives = snapshot.get("perspectives")
    if raw_perspectives is not None:
        if not isinstance(raw_perspectives, list) or any(
            not isinstance(row, dict) for row in raw_perspectives
        ):
            raise ValueError(f"{label} perspectives are invalid.")
        for perspective in raw_perspectives:
            old_perspective_id = str(perspective.get("id") or "")
            if not old_scene_id or not old_perspective_id:
                raise ValueError(f"{label} perspective identity is incomplete.")
            new_perspective_id = planner.scene2d_perspective_ids.get(
                (old_scene_id, old_perspective_id)
            )
            if not new_perspective_id:
                raise ValueError(
                    f"{label} uses an unknown perspective id: {old_perspective_id}."
                )
            perspective["id"] = new_perspective_id
            for field in ("source_file_path", "preview_image_path"):
                if perspective.get(field):
                    perspective[field] = _mapped_scene2d_path(
                        planner,
                        perspective[field],
                        f"{label} perspective {field}",
                    )
    old_primary_id = str(snapshot.get("primary_perspective_id") or "")
    if old_primary_id:
        new_primary_id = planner.scene2d_perspective_ids.get(
            (old_scene_id, old_primary_id)
        )
        if not new_primary_id:
            raise ValueError(f"{label} primary perspective is invalid.")
        snapshot["primary_perspective_id"] = new_primary_id
    return snapshot


def _validate_request_schema(
    planner: _Planner,
    path: Path,
    payload: dict[str, Any],
) -> tuple[str, Shot]:
    request_id = _require_generation_id(
        payload.get("request_id"), path.stem, "request id"
    )
    required_dicts = (
        "shot",
        "character_bible",
        "prompt_config",
        "continuity",
        "canvas",
        "generation_plan",
        "prompt",
        "output_contract",
        "execution_constraints",
    )
    required_lists = ("references", "keyword_assets", "continuity_context")
    if any(not isinstance(payload.get(field), dict) for field in required_dicts):
        raise ValueError(f"Generation request object fields are invalid: {path.name}.")
    if any(not isinstance(payload.get(field), list) for field in required_lists):
        raise ValueError(f"Generation request list fields are invalid: {path.name}.")
    for field in ("scene_bible", "scene_context"):
        if payload.get(field) is not None and not isinstance(payload.get(field), dict):
            raise ValueError(f"Generation request {field} is invalid: {path.name}.")
    for field in (
        "project_name",
        "project_root",
        "shot_id",
        "destination",
        "provider",
        "mode",
        "status",
        "created_at",
        "updated_at",
        "input_revision",
        "consistency_revision",
    ):
        if not isinstance(payload.get(field), str):
            raise ValueError(f"Generation request {field} is invalid: {path.name}.")
    if isinstance(payload.get("shot_number"), bool) or not isinstance(
        payload.get("shot_number"), int
    ):
        raise ValueError(f"Generation request shot_number is invalid: {path.name}.")
    shot_id = generation_service._validate_id(payload["shot_id"], "shot id")
    target_shot = next(
        (shot for shot in planner.target.shots if shot.shot_id == shot_id),
        None,
    )
    if target_shot is None:
        raise ValueError(f"Generation request uses an unknown shot id: {shot_id}.")
    shot_snapshot = payload["shot"]
    if str(shot_snapshot.get("shot_id") or "") != shot_id:
        raise ValueError("Generation request shot snapshot id does not match shot_id.")
    request_shot = Shot.from_dict(shot_snapshot)
    request_shot.prompt_config = copy.deepcopy(payload["prompt_config"])
    request_shot.continuity = copy.deepcopy(payload["continuity"])
    return request_id, request_shot


def _rewrite_request_scene_context(
    planner: _Planner,
    payload: dict[str, Any],
    request_shot: Shot,
) -> None:
    shot_snapshot = payload["shot"]
    old_scene_id = str(shot_snapshot.get("scene_id") or "")
    if old_scene_id:
        mapped_scene_id = planner.scene2d_ids.get(old_scene_id)
        if not mapped_scene_id:
            raise ValueError(
                f"Generation request shot uses an unknown Scene 2D id: {old_scene_id}."
            )
        shot_snapshot["scene_id"] = mapped_scene_id
        request_shot.scene_id = mapped_scene_id
    payload["scene_bible"] = _remap_scene2d_snapshot(
        planner, payload.get("scene_bible"), "Generation scene_bible"
    )
    payload["scene_context"] = _remap_scene2d_snapshot(
        planner, payload.get("scene_context"), "Generation scene_context"
    )
    prompt = payload["prompt"]
    layers = prompt.get("layers")
    if not isinstance(layers, dict):
        raise ValueError("Generation request prompt layers are invalid.")
    scene_context = payload.get("scene_context")
    character_bible = payload["character_bible"]
    character_prompt = str(character_bible.get("prompt") or "")
    layers["scene"] = str((scene_context or {}).get("title") or request_shot.scene or "")
    layers["scene_context"] = copy.deepcopy(scene_context or {})
    layers["characters"] = character_prompt
    layers["shot"] = generation_service._compile_shot_override(request_shot)
    prompt["compiled_prompt"] = generation_service.compile_prompt(
        request_shot,
        scene_bible=scene_context,
        character_bible_prompt=character_prompt,
        keyword_assets=payload["keyword_assets"],
    )


def _migrate_generation(planner: _Planner) -> None:
    planner.known_directories.update({
        "generation",
        "generation/candidates",
        "generation/requests",
        "generation/results",
        "generation/state",
    })
    source_root = generation_metadata_path(planner.source)
    if not source_root.is_dir():
        return
    request_input_fields = (
        "shot", "scene_bible", "scene_context", "character_bible",
        "prompt_config", "continuity", "references", "keyword_assets",
        "continuity_context", "canvas",
    )
    request_payloads: dict[str, dict[str, Any]] = {}
    requests = generation_metadata_path(planner.source, "requests")
    if requests.is_dir():
        for path in sorted(requests.glob("*.json")):
            relative = path.relative_to(planner.source.project_root).as_posix()
            planner._record_classification(relative, "rewritten generation request")
            payload = _read_generation_object(path, "Generation request")
            request_id, request_shot = _validate_request_schema(planner, path, payload)
            payload["project_root"] = str(planner.final_root)
            references = payload["references"]
            for index, row in enumerate(references):
                if not isinstance(row, dict):
                    raise ValueError(f"Generation request reference is invalid: {path.name}.")
                _remap_generation_path(planner, row, "project_relative_path", "absolute_path", f"request reference {index}")
            keyword_assets = payload["keyword_assets"]
            for index, row in enumerate(keyword_assets):
                if not isinstance(row, dict):
                    raise ValueError(f"Generation request keyword asset is invalid: {path.name}.")
                _remap_generation_path(planner, row, "file_path", "absolute_path", f"request asset {index}")
                _remap_generation_path(planner, row, "blend_file_path", "blend_absolute_path", f"request Blend asset {index}")
            plan = payload.get("generation_plan")
            prior = plan.get("prior_frame")
            if prior is not None:
                if not isinstance(prior, dict):
                    raise ValueError(f"Generation request prior frame is invalid: {path.name}.")
                _remap_generation_path(planner, prior, "project_relative_path", "absolute_path", "request prior frame")
            prompt_config = payload["prompt_config"]
            bindings = prompt_config.get("reference_bindings") or []
            if not isinstance(bindings, list):
                raise ValueError(f"Generation request bindings are invalid: {path.name}.")
            for index, binding in enumerate(bindings):
                if not isinstance(binding, dict):
                    raise ValueError(f"Generation request binding is invalid: {path.name}.")
                for field in ("path", "relative_path", "reference_path"):
                    if binding.get(field):
                        binding[field] = planner.mapped_reference(str(binding[field]), f"request binding {index}")
            _rewrite_request_scene_context(planner, payload, request_shot)
            payload["input_revision"] = generation_service._canonical_hash(
                {field: payload[field] for field in request_input_fields}
            )
            payload["consistency_revision"] = generation_service._canonical_hash({
                "scene": payload.get("scene_context") or {"title": request_shot.scene},
                "character_bible": payload["character_bible"],
            })
            target = generation_metadata_path(planner.target, "requests", path.name)
            atomic_write_json(target, payload)
            request_payloads[request_id] = payload

    states = generation_metadata_path(planner.source, "state")
    if states.is_dir():
        for path in sorted(states.glob("*.json")):
            payload = _read_generation_object(path, "Generation state")
            request_id = _require_generation_id(
                payload.get("request_id"), path.stem, "state request id"
            )
            if request_id not in request_payloads:
                raise ValueError("Generation state has no matching request.")
            if not isinstance(payload.get("status"), str):
                raise ValueError(f"Generation state status is invalid: {path.name}.")
            relative = path.relative_to(planner.source.project_root).as_posix()
            planner._record_classification(relative, "rewritten generation state")
            atomic_write_json(
                generation_metadata_path(planner.target, "state", path.name),
                payload,
            )

    results = generation_metadata_path(planner.source, "results")
    if results.is_dir():
        for path in sorted(results.glob("*/*.json")):
            relative = path.relative_to(planner.source.project_root).as_posix()
            planner._record_classification(relative, "rewritten generation result")
            payload = _read_generation_object(path, "Generation result")
            request_id = _require_generation_id(
                payload.get("request_id"), path.parent.name, "result request id"
            )
            result_id = _require_generation_id(
                payload.get("result_id"), path.stem, "result id"
            )
            request_payload = request_payloads.get(request_id)
            if request_payload is None:
                raise ValueError("Generation result has no matching request.")
            if str(payload.get("shot_id") or "") != str(request_payload["shot_id"]):
                raise ValueError("Generation result shot_id does not match its request.")
            artifacts = payload.get("artifacts")
            if not isinstance(artifacts, list):
                raise ValueError(f"Generation result artifacts are invalid: {path.name}.")
            for index, artifact in enumerate(artifacts, start=1):
                if not isinstance(artifact, dict):
                    raise ValueError(f"Generation result artifact is invalid: {path.name}.")
                expected_output_id = result_id if index == 1 else f"{result_id}_{index:03d}"
                _require_generation_id(
                    artifact.get("output_id"), expected_output_id, "artifact output id"
                )
                source_value = str(artifact.get("project_relative_path") or "")
                suffix = Path(source_value).suffix.lower()
                if suffix not in generation_service.IMAGE_SUFFIXES:
                    raise ValueError("Generation artifact has an unsupported file type.")
                mapped = planner.copy(
                    source_value,
                    generation_asset_relative(
                        planner.target, request_id, result_id, suffix, index=index
                    ),
                    f"generation artifact {index}",
                    required=True,
                )
                artifact["project_relative_path"] = mapped
                artifact["absolute_path"] = str(
                    resolve_root_child(planner.final_root, *PurePosixPath(mapped).parts)
                )
            target = generation_metadata_path(
                planner.target, "results", request_id, path.name
            )
            atomic_write_json(target, payload)


def materialize_layout1_to_layout2(project: Project, requested: Path) -> Layout2ConvertResult:
    """Build and atomically publish a validated Layout 2 target without source writes."""
    if project.layout != LAYOUT_1:
        raise ValueError("Convert supports Layout 1 to Layout 2 only.")
    source_document = Path(project.document_path or "").expanduser().resolve()
    if not source_document.is_file() or source_document.suffix.lower() != ".sbd":
        raise ValueError("Convert requires an active Layout 1 .sbd document.")
    source_spec = project_document.inspect_document_layout(source_document)
    if source_spec.layout != LAYOUT_1:
        raise ValueError("Convert supports Layout 1 to Layout 2 only.")
    source_root = project.project_root.absolute()
    if _is_reparse(source_root):
        raise ValueError("Convert source root cannot be a reparse point.")
    source_root = source_root.resolve()
    destination_root, destination_document = _destination_paths(source_root, requested)
    source_document_record = _record(source_document)
    source_inventory = _scan_tree(source_root)
    required_bytes = sum(record.size for record in source_inventory.copy_files.values()) * 2
    required_bytes += source_document_record.size
    if shutil.disk_usage(destination_root.parent).free < required_bytes:
        raise OSError("Insufficient free space for the staged conversion.")

    operation = destination_root.parent / f".{destination_root.name}.convert-{uuid.uuid4().hex}"
    report_path = operation / "conversion-report.json"
    input_root = operation / "source-snapshot"
    target_root = operation / "target"
    stage = "snapshot"
    report: dict[str, Any] = {
        "version": 1,
        "status": "running",
        "stage": stage,
        "source_document": str(source_document),
        "source_hash": source_document_record.sha256,
        "source_file_count": len(source_inventory.files),
        "portable_source_file_count": len(source_inventory.copy_files),
        "source_size": source_document_record.size,
        "destination_root": str(destination_root),
        "classifications": [],
        "unknown_members": [],
    }
    try:
        operation.mkdir(parents=False, exist_ok=False)
        _write_report(report_path, report)
        _copy_inventory(source_root, input_root, _input_inventory(source_inventory))
        analysis = _analysis_project(project, input_root)
        target_root.mkdir(parents=False, exist_ok=False)
        target = _target_project(
            analysis,
            target_root,
            destination_document.name,
            source_document=source_document,
            source_version=source_spec.schema_version,
            source_hash=source_document_record.sha256,
        )
        target.metadata_root.mkdir(parents=True)
        planner = _Planner(analysis, target, source_inventory, destination_root)

        stage = "classification"
        report["stage"] = stage
        _write_report(report_path, report)
        _migrate_shots(planner)
        _migrate_scenes(planner)
        _migrate_references(planner)
        _migrate_generation(planner)
        planner.copy_export_tree()
        unknown = planner.unknown_members()
        report.update({
            "stage": stage,
            "classifications": planner.classifications,
            "unknown_members": unknown,
        })
        _write_report(report_path, report)
        if unknown:
            raise ValueError("Unknown legacy members prevent conversion: " + ", ".join(unknown))
        if planner.claimed != set(source_inventory.copy_files):
            raise ValueError("Legacy member classification did not reconcile.")
        report["classified_source_file_count"] = len(planner.claimed)
        report["excluded_source_file_count"] = (
            len(source_inventory.files) - len(source_inventory.copy_files)
            + len(planner.excluded)
        )
        _write_report(report_path, report)
        ensure_no_casefold_collisions(planner.target_names, field_name="converted target paths")

        stage = "metadata"
        report["stage"] = stage
        _write_report(report_path, report)
        atomic_write_json(target.json_path, project_manifest(target))
        save_shots_json(target.metadata_root, list(target.shots))
        save_settings(target)
        validate_layout2_stored_references(target)

        stage = "archive"
        report["stage"] = stage
        _write_report(report_path, report)
        project_document.commit_layout2_document(target_root)
        staged_document = resolve_root_child(target_root, f"{target_root.name}.sbd")
        final_staged_document = resolve_root_child(target_root, destination_document.name)
        if final_staged_document.exists():
            raise FileExistsError("Converted target document path is occupied.")
        os.replace(staged_document, final_staged_document)
        project_document.validate_layout2_document(final_staged_document)
        validate_layout2_stored_references(target)

        stage = "verification"
        report["stage"] = stage
        _write_report(report_path, report)
        if _record(source_document) != source_document_record:
            raise OSError("Source .sbd changed during conversion.")
        source_after = _scan_tree(source_root)
        if (
            source_after.files != source_inventory.files
            or source_after.copy_directories != source_inventory.copy_directories
        ):
            raise OSError("Expanded source changed during conversion.")
        final_inventory = _scan_tree(target_root)
        snapshot_hash = _snapshot_hash(final_inventory.files, None)

        stage = "rename"
        report.update({
            "stage": stage,
            "status": "ready_to_publish",
            "staged_target": str(target_root),
            "destination_file_count": len(final_inventory.files),
        })
        _write_report(report_path, report)
        destination_folded = destination_root.name.casefold()
        document_folded = destination_document.name.casefold()
        for child in destination_root.parent.iterdir():
            if child.name.casefold() == destination_folded:
                raise FileExistsError(
                    f"Conversion destination collided by case during staging: {child.name}."
                )
            if child.name.casefold() == document_folded:
                raise FileExistsError(
                    f"Conversion document collided by case during staging: {child.name}."
                )
        if destination_root.exists():
            raise FileExistsError("Conversion destination appeared during staging.")
        os.rename(target_root, destination_root)
        report.pop("staged_target", None)
        report.update({
            "status": "published",
            "stage": "published",
            "published_target": str(destination_root),
            "snapshot_hash": snapshot_hash,
            "destination_file_count": len(final_inventory.files),
        })
        _write_report(report_path, report)
        shutil.rmtree(operation, ignore_errors=True)
        return Layout2ConvertResult(
            destination_root=destination_root,
            document_path=destination_document,
            snapshot_hash=snapshot_hash,
            source_hash=source_document_record.sha256,
            source_file_count=len(source_inventory.files),
            destination_file_count=len(final_inventory.files),
            excluded_paths=tuple(sorted(
                set(source_inventory.excluded)
                .union(planner.excluded)
                .union(
                    name
                    for name in source_inventory.copy_files
                    if name.startswith("backups/")
                )
            )),
            report=report,
        )
    except BaseException as exc:
        original_exc = exc
        report.update({"status": "failed", "stage": stage, "error": str(exc)})
        report_write_error: BaseException | None = None
        if operation.exists():
            try:
                _write_report(report_path, report)
            except BaseException as write_exc:
                report_write_error = write_exc
        try:
            source_unchanged = _record(source_document) == source_document_record
        except OSError:
            source_unchanged = False
        if not source_unchanged:
            stage = "source_integrity"
            exc = OSError("Source .sbd changed during conversion failure handling.")
            if operation.exists():
                report.update({"stage": stage, "error": str(exc)})
                try:
                    _write_report(report_path, report)
                except BaseException as write_exc:
                    report_write_error = write_exc
        if report_write_error is not None:
            exc = OSError(
                f"{exc} Conversion report could not be persisted: "
                f"{report_write_error}"
            )
        raise Layout2ConvertError(
            stage,
            str(exc),
            operation_path=operation if operation.exists() else None,
            report_path=report_path if report_path.is_file() else None,
            destination_root=destination_root,
        ) from original_exc
