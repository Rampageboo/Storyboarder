"""Transactional, source-preserving Layout 1 to Layout 2 conversion."""
from __future__ import annotations

import copy
import json
import os
import shutil
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from . import generation_service, project_document, project_manager, scene2d, scene3d
from .models import Project
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
    try:
        atomic_write_json(path, report)
    except OSError:
        pass


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
        self.source_to_target: dict[str, str] = {}
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
        existing = self.source_to_target.get(source_relative)
        if existing:
            self._record_classification(source_relative, label, existing)
            return existing
        folded = target_relative.casefold()
        if folded in {name.casefold() for name in self.target_names}:
            raise ValueError(f"Converted target path collision: {target_relative}.")
        destination = resolve_root_child(self.target.project_root, *PurePosixPath(target_relative).parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, destination)
        if _record(destination) != _record(source_path):
            raise OSError(f"Converted asset failed hash verification: {source_relative}.")
        self.source_to_target[source_relative] = target_relative
        self.target_names.append(target_relative)
        self._record_classification(source_relative, label, target_relative)
        return target_relative

    def mapped_reference(self, value: str, label: str) -> str:
        if not value:
            return ""
        source_relative, source_path = self._source_relative(value, label)
        mapped = self.source_to_target.get(source_relative)
        if mapped:
            self._record_classification(source_relative, label, mapped)
            return mapped
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
                self._record_classification(name, "excluded legacy backup")
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


def _migrate_scenes(planner: _Planner) -> None:
    scenes2d = scene2d.list_scenes(planner.source)
    converted2d: list[dict[str, Any]] = []
    planner.discard("scenes2d/scenes2d.json", "rewritten Scene 2D index")
    for source_scene in scenes2d:
        converted = copy.deepcopy(source_scene)
        planner.discard(
            f"scenes2d/{source_scene['id']}/{source_scene['id']}_meta.json",
            "rewritten Scene 2D metadata",
        )
        for perspective in converted.get("perspectives") or []:
            source_value = str(perspective.get("source_file_path") or "")
            suffix = Path(source_value).suffix.lower()
            role = "source_psd" if suffix == ".psd" else "source_image"
            perspective["source_file_path"] = planner.copy(
                source_value,
                scene2d_asset_relative(
                    planner.target,
                    converted["id"],
                    perspective["id"],
                    role,
                    suffix,
                ),
                f"Scene 2D {perspective['id']} source",
                required=True,
            )
            preview_value = str(perspective.get("preview_image_path") or "")
            perspective["preview_image_path"] = planner.copy(
                preview_value,
                scene2d_asset_relative(
                    planner.target, converted["id"], perspective["id"], "preview"
                ),
                f"Scene 2D {perspective['id']} preview",
                required=bool(preview_value),
            ) or perspective["source_file_path"]
        converted2d.append(converted)
    scene2d._save_scenes(planner.target, converted2d)

    payload3d = scene3d.list_scenes(planner.source)
    planner.discard("scenes3d/scenes3d.json", "rewritten Scene 3D index")
    converted3d: list[dict[str, Any]] = []
    for source_scene in payload3d.get("scenes", []):
        converted = copy.deepcopy(source_scene)
        planner.discard(
            f"scenes3d/{source_scene['id']}/{source_scene['id']}_meta.json",
            "rewritten Scene 3D metadata",
        )
        for field in ("file_path", "blend_file_path"):
            value = str(converted.get(field) or "")
            if not value:
                continue
            converted[field] = planner.copy(
                value,
                scene3d_asset_relative(planner.target, converted["id"], Path(value).suffix),
                f"Scene 3D {converted['id']} {field}",
                required=True,
            )
        preview = f"scenes3d/{source_scene['id']}/.preview/storyboarder_preview.glb"
        planner.discard(preview, "discarded derived Scene 3D preview")
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
        if isinstance(link, dict) and link.get("path"):
            link["path"] = planner.mapped_reference(str(link["path"]), f"reference link {index}")
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
    mapped = planner.mapped_reference(value, label)
    row[relative_field] = mapped
    row[absolute_field] = str(resolve_root_child(planner.final_root, *PurePosixPath(mapped).parts))
    for exists_field in ("exists", "file_exists", "blend_file_exists"):
        if exists_field in row:
            row[exists_field] = True


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
        "shot", "scene_bible", "scene_context", "character_bible", "prompt_config",
        "continuity", "references", "keyword_assets", "continuity_context", "canvas",
    )
    requests = generation_metadata_path(planner.source, "requests")
    if requests.is_dir():
        for path in sorted(requests.glob("*.json")):
            relative = path.relative_to(planner.source.project_root).as_posix()
            planner._record_classification(relative, "rewritten generation request")
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or payload.get("schema_version") != generation_service.SCHEMA_VERSION:
                raise ValueError(f"Unsupported generation request: {path.name}.")
            if any(field not in payload for field in request_input_fields):
                raise ValueError(f"Incomplete generation request: {path.name}.")
            payload["project_root"] = str(planner.final_root)
            references = payload["references"]
            if not isinstance(references, list):
                raise ValueError(f"Generation request references are invalid: {path.name}.")
            for index, row in enumerate(references):
                if not isinstance(row, dict):
                    raise ValueError(f"Generation request reference is invalid: {path.name}.")
                _remap_generation_path(planner, row, "project_relative_path", "absolute_path", f"request reference {index}")
            keyword_assets = payload["keyword_assets"]
            if not isinstance(keyword_assets, list):
                raise ValueError(f"Generation request keyword assets are invalid: {path.name}.")
            for index, row in enumerate(keyword_assets):
                if not isinstance(row, dict):
                    raise ValueError(f"Generation request keyword asset is invalid: {path.name}.")
                _remap_generation_path(planner, row, "file_path", "absolute_path", f"request asset {index}")
                _remap_generation_path(planner, row, "blend_file_path", "blend_absolute_path", f"request Blend asset {index}")
            plan = payload.get("generation_plan")
            if plan is not None and not isinstance(plan, dict):
                raise ValueError(f"Generation request plan is invalid: {path.name}.")
            prior = plan.get("prior_frame") if isinstance(plan, dict) else None
            if prior is not None:
                if not isinstance(prior, dict):
                    raise ValueError(f"Generation request prior frame is invalid: {path.name}.")
                _remap_generation_path(planner, prior, "project_relative_path", "absolute_path", "request prior frame")
            prompt_config = payload["prompt_config"]
            if not isinstance(prompt_config, dict):
                raise ValueError(f"Generation request prompt config is invalid: {path.name}.")
            bindings = prompt_config.get("reference_bindings") or []
            if not isinstance(bindings, list):
                raise ValueError(f"Generation request bindings are invalid: {path.name}.")
            for index, binding in enumerate(bindings):
                if not isinstance(binding, dict):
                    raise ValueError(f"Generation request binding is invalid: {path.name}.")
                for field in ("path", "relative_path", "reference_path"):
                    if binding.get(field):
                        binding[field] = planner.mapped_reference(str(binding[field]), f"request binding {index}")
            payload["input_revision"] = generation_service._canonical_hash(
                {field: payload[field] for field in request_input_fields}
            )
            target = generation_metadata_path(planner.target, "requests", path.name)
            atomic_write_json(target, payload)

    states = generation_metadata_path(planner.source, "state")
    if states.is_dir():
        for path in sorted(states.glob("*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or payload.get("schema_version") != generation_service.SCHEMA_VERSION:
                raise ValueError(f"Unsupported generation state: {path.name}.")
            relative = path.relative_to(planner.source.project_root).as_posix()
            target_relative = generation_metadata_path(
                planner.target, "state", path.name
            ).relative_to(planner.target.project_root).as_posix()
            planner.copy(relative, target_relative, "generation state", required=True)

    results = generation_metadata_path(planner.source, "results")
    if results.is_dir():
        for path in sorted(results.glob("*/*.json")):
            relative = path.relative_to(planner.source.project_root).as_posix()
            planner._record_classification(relative, "rewritten generation result")
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or payload.get("schema_version") != generation_service.SCHEMA_VERSION:
                raise ValueError(f"Unsupported generation result: {path.name}.")
            request_id = str(payload.get("request_id") or path.parent.name)
            result_id = str(payload.get("result_id") or path.stem)
            artifacts = payload.get("artifacts")
            if not isinstance(artifacts, list):
                raise ValueError(f"Generation result artifacts are invalid: {path.name}.")
            for index, artifact in enumerate(artifacts, start=1):
                if not isinstance(artifact, dict):
                    raise ValueError(f"Generation result artifact is invalid: {path.name}.")
                source_value = str(artifact.get("project_relative_path") or "")
                suffix = Path(source_value).suffix
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
            excluded_paths=tuple(sorted(set(source_inventory.excluded).union(
                name for name in source_inventory.copy_files if name.startswith("backups/")
            ))),
            report=report,
        )
    except BaseException as exc:
        report.update({"status": "failed", "stage": stage, "error": str(exc)})
        if operation.exists():
            _write_report(report_path, report)
        try:
            source_unchanged = _record(source_document) == source_document_record
        except OSError:
            source_unchanged = False
        if not source_unchanged:
            stage = "source_integrity"
            exc = OSError("Source .sbd changed during conversion failure handling.")
            if operation.exists():
                report.update({"stage": stage, "error": str(exc)})
                _write_report(report_path, report)
        raise Layout2ConvertError(
            stage,
            str(exc),
            operation_path=operation if operation.exists() else None,
            report_path=report_path if report_path.is_file() else None,
            destination_root=destination_root,
        ) from exc
