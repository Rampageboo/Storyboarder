"""Transactional Layout 2 Save As materialization."""
from __future__ import annotations

import copy
import hashlib
import os
import shutil
import stat
import tempfile
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from . import project_document
from .models import Project
from .project_layout import (
    LAYOUT_2,
    ProjectPathError,
    ensure_no_casefold_collisions,
    project_manifest,
    resolve_project_path,
    resolve_root_child,
    validate_project_relative_posix,
)
from .project_storage import atomic_write_json, save_settings
from .shot_store import save_shots_json


_REPARSE_POINT_ATTRIBUTE = 0x400
_RUNTIME_DIRS = frozenset({"locks", "runtime", "session", "sessions", "transactions"})
_PRIMARY_MUTABLE_MEMBERS = frozenset(
    {
        ".storyboarder/state.json",
        ".storyboarder/work/project.json",
        ".storyboarder/work/settings.json",
        ".storyboarder/work/shots.json",
    }
)


class Layout2SaveAsError(RuntimeError):
    """A failed stage, including its recoverable staging path when retained."""

    def __init__(
        self,
        stage: str,
        message: str,
        *,
        staging_path: Path | None = None,
        destination_root: Path | None = None,
    ) -> None:
        self.stage = stage
        self.staging_path = staging_path
        self.destination_root = destination_root
        suffix = f" Staging preserved at: {staging_path}." if staging_path else ""
        super().__init__(f"Layout 2 Save As failed during {stage}: {message}.{suffix}")


@dataclass(frozen=True)
class FileRecord:
    size: int
    sha256: str


@dataclass(frozen=True)
class TreeInventory:
    files: dict[str, FileRecord]
    copy_files: dict[str, FileRecord]
    copy_directories: tuple[str, ...]
    excluded: tuple[str, ...]


@dataclass(frozen=True)
class Layout2SaveAsResult:
    destination_root: Path
    document_path: Path
    snapshot_hash: str
    source_file_count: int
    destination_file_count: int
    excluded_paths: tuple[str, ...]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _record(path: Path) -> FileRecord:
    before = path.stat()
    digest = _sha256(path)
    after = path.stat()
    if (
        before.st_size != after.st_size
        or before.st_mtime_ns != after.st_mtime_ns
        or before.st_ino != after.st_ino
    ):
        raise OSError(f"File changed while it was inventoried: {path}")
    return FileRecord(size=int(after.st_size), sha256=digest)


def _is_reparse(path: Path) -> bool:
    info = path.lstat()
    return path.is_symlink() or bool(
        int(getattr(info, "st_file_attributes", 0)) & _REPARSE_POINT_ATTRIBUTE
    )


def _runtime_excluded(relative: PurePosixPath) -> bool:
    parts = relative.parts
    if relative.as_posix() == project_document.SESSION_MARKER:
        return True
    return bool(
        len(parts) >= 2
        and parts[0] == ".storyboarder"
        and (parts[1] in _RUNTIME_DIRS or parts[-1].casefold().endswith(".lock"))
    )


def _scan_tree(root: Path, *, source_document: Path | None = None) -> TreeInventory:
    raw_root = Path(root).expanduser().absolute()
    if not raw_root.is_dir() or _is_reparse(raw_root):
        raise ValueError("Layout 2 source root must be a regular directory.")
    root = raw_root.resolve()
    document = Path(source_document).resolve() if source_document is not None else None
    files: dict[str, FileRecord] = {}
    copy_files: dict[str, FileRecord] = {}
    copy_directories: list[str] = []
    excluded: list[str] = []
    path_names: list[str] = []

    def walk(directory: Path, parent: PurePosixPath | None = None) -> None:
        with os.scandir(directory) as entries:
            children = sorted(entries, key=lambda item: item.name.casefold())
        for entry in children:
            relative = PurePosixPath(entry.name) if parent is None else parent / entry.name
            name = validate_project_relative_posix(
                relative.as_posix(), field_name="Save As inventory path"
            ).as_posix()
            path_names.append(name)
            path = Path(entry.path)
            if _is_reparse(path):
                raise ValueError(f"Save As refuses links or reparse points: {name}.")
            entry_stat = entry.stat(follow_symlinks=False)
            skip = _runtime_excluded(relative) or (
                document is not None and path.resolve() == document
            )
            if stat.S_ISDIR(entry_stat.st_mode):
                if skip:
                    excluded.append(name)
                    continue
                copy_directories.append(name)
                walk(path, relative)
                continue
            if not stat.S_ISREG(entry_stat.st_mode):
                raise ValueError(f"Save As found an unsupported entry: {name}.")
            record = _record(path)
            files[name] = record
            if skip:
                excluded.append(name)
            else:
                copy_files[name] = record

    walk(root)
    ensure_no_casefold_collisions(path_names, field_name="Save As inventory paths")
    return TreeInventory(
        files=files,
        copy_files=copy_files,
        copy_directories=tuple(sorted(copy_directories)),
        excluded=tuple(sorted(excluded)),
    )


def _destination_paths(source_root: Path, requested: Path) -> tuple[Path, Path]:
    requested_document = Path(requested).expanduser().absolute()
    if requested_document.suffix.lower() != project_document.DOCUMENT_SUFFIX:
        requested_document = requested_document.with_suffix(project_document.DOCUMENT_SUFFIX)
    if not requested_document.parent.is_dir():
        raise FileNotFoundError(f"Save As parent folder not found: {requested_document.parent}")
    if _is_reparse(requested_document.parent):
        raise ValueError("Save As destination parent cannot be a reparse point.")
    requested_document = requested_document.resolve()
    destination_root = requested_document.parent / requested_document.stem
    destination_document = destination_root / f"{destination_root.name}.sbd"
    source = Path(source_root).resolve()
    destination = destination_root.resolve()
    if destination == source or source in destination.parents:
        raise ValueError("Save As destination cannot be the source or nested inside it.")
    if destination_root.exists() or requested_document.exists() or destination_document.exists():
        raise FileExistsError("Save As destination already exists; projects are never merged.")
    folded = destination_root.name.casefold()
    document_folded = requested_document.name.casefold()
    for child in requested_document.parent.iterdir():
        if child.name.casefold() == folded:
            raise FileExistsError(
                f"Save As destination collides by case with an existing path: {child.name}."
            )
        if child.name.casefold() == document_folded:
            raise FileExistsError(
                f"Save As document collides by case with an existing path: {child.name}."
            )
    return destination_root, destination_document


def _source_cover(document: Path) -> bytes | None:
    project_document.validate_layout2_document(document)
    with zipfile.ZipFile(document, "r") as archive:
        try:
            return archive.read("cover.png")
        except KeyError:
            return None


def _snapshot_hash(records: dict[str, FileRecord], cover: bytes | None) -> str:
    digest = hashlib.sha256()
    for name, record in sorted(records.items()):
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(record.size).encode("ascii"))
        digest.update(b"\0")
        digest.update(bytes.fromhex(record.sha256))
    if cover is not None:
        digest.update(b"@cover.png\0")
        digest.update(hashlib.sha256(cover).digest())
    return digest.hexdigest()


def _copy_inventory(source: Path, stage: Path, inventory: TreeInventory) -> None:
    stage.mkdir(parents=False, exist_ok=False)
    for name in inventory.copy_directories:
        resolve_root_child(stage, *PurePosixPath(name).parts).mkdir(parents=True, exist_ok=True)
    for name, expected in inventory.copy_files.items():
        parts = PurePosixPath(name).parts
        source_path = resolve_root_child(source, *parts)
        destination = resolve_root_child(stage, *parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, destination)
        if _record(destination) != expected:
            raise OSError(f"Copied file failed hash verification: {name}.")


def _snapshot_project(project: Project, root: Path) -> Project:
    frozen = copy.deepcopy(project)
    frozen.project_root_path = root
    frozen.root_path = resolve_root_child(root, ".storyboarder", "work")
    frozen.document_path = resolve_root_child(root, f"{root.name}.sbd")
    return frozen


def _write_frozen_primary_metadata(project: Project) -> None:
    atomic_write_json(project.json_path, project_manifest(project))
    save_shots_json(project.metadata_root, list(project.shots))
    save_settings(project)


def _stored_asset_paths(project: Project) -> list[tuple[str, str]]:
    values: list[tuple[str, str]] = []
    for shot in project.shots:
        for field in (
            "image_path", "preview_image_path", "thumbnail_path",
            "source_file_path", "annotation_path", "ref_video_path",
        ):
            value = str(getattr(shot, field, "") or "")
            if value:
                values.append((f"shot {shot.shot_id} {field}", value))
        for value in shot.reference_image_paths:
            if value:
                values.append((f"shot {shot.shot_id} reference", str(value)))
    for link in project.settings.get("reference_links") or []:
        if isinstance(link, dict) and str(link.get("path") or ""):
            values.append((f"reference {link.get('id') or ''}", str(link["path"])))
    for field in (
        "reference_image_path",
        "reference_video_path",
        "reference_model_path",
    ):
        value = str(project.settings.get(field) or "")
        if value:
            values.append((f"settings {field}", value))
    for segment in project.settings.get("ref_segments") or []:
        if isinstance(segment, dict) and str(segment.get("reference_path") or ""):
            values.append(
                (
                    f"reference segment {segment.get('id') or ''}",
                    str(segment["reference_path"]),
                )
            )

    from . import scene2d, scene3d

    for scene in scene2d.list_scenes(project):
        for perspective in scene.get("perspectives") or []:
            for field in ("source_file_path", "preview_image_path"):
                value = str(perspective.get(field) or "")
                if value:
                    values.append((f"Scene 2D {perspective.get('id')} {field}", value))
    for scene in scene3d.list_scenes(project).get("scenes", []):
        for field in ("file_path", "blend_file_path"):
            value = str(scene.get(field) or "")
            if value:
                values.append((f"Scene 3D {scene.get('id')} {field}", value))
    return values


def validate_layout2_stored_references(project: Project) -> None:
    for label, relative in _stored_asset_paths(project):
        try:
            path = resolve_project_path(project, relative, field_name=label)
        except (ProjectPathError, OSError) as exc:
            raise ValueError(f"Invalid stored reference for {label}: {relative}.") from exc
        if relative.startswith(".storyboarder/cache/"):
            continue
        if not path.is_file():
            raise FileNotFoundError(f"Stored reference is missing for {label}: {relative}.")


def materialize_layout2_save_as(project: Project, requested: Path) -> Layout2SaveAsResult:
    """Publish a complete validated snapshot with one directory rename."""
    if project.layout != LAYOUT_2:
        raise ValueError("Transactional folder Save As requires Layout 2.")
    source_root = Path(project.project_root).absolute()
    if _is_reparse(source_root):
        raise ValueError("Layout 2 source root cannot be a reparse point.")
    source_root = source_root.resolve()
    source_document = Path(project.document_path or "").resolve()
    if not source_document.is_file() or source_document.parent != source_root:
        raise ValueError("Layout 2 Save As requires its canonical source .sbd.")
    destination_root, destination_document = _destination_paths(source_root, requested)
    validate_layout2_stored_references(project)
    source_before = _scan_tree(source_root, source_document=source_document)
    cover = _source_cover(source_document)
    if source_before.files.get(source_document.name) != _record(source_document):
        raise OSError("Source project changed during Save As preflight.")
    required_bytes = sum(record.size for record in source_before.copy_files.values())
    required_bytes += sum(
        record.size for name, record in source_before.copy_files.items()
        if name.startswith(".storyboarder/work/")
    )
    required_bytes += len(cover or b"")
    if shutil.disk_usage(destination_root.parent).free < required_bytes:
        raise OSError("Insufficient free space for the staged Save As snapshot.")

    stage = destination_root.parent / f".{destination_root.name}.save-as-{uuid.uuid4().hex}"
    current_stage = "copy"
    try:
        _copy_inventory(source_root, stage, source_before)
        current_stage = "snapshot"
        staged_project = _snapshot_project(project, stage)
        _write_frozen_primary_metadata(staged_project)
        validate_layout2_stored_references(staged_project)
        staged_before_commit = _scan_tree(stage)
        for name, expected in source_before.copy_files.items():
            if name not in _PRIMARY_MUTABLE_MEMBERS and staged_before_commit.files.get(name) != expected:
                raise OSError(f"Staged source member differs from its source: {name}.")
        snapshot_hash = _snapshot_hash(staged_before_commit.files, cover)

        current_stage = "archive"
        if cover is not None:
            descriptor, cover_name = tempfile.mkstemp(
                dir=str(destination_root.parent),
                prefix=f".{destination_root.name}.cover-",
                suffix=".png",
            )
            cover_path = Path(cover_name)
            try:
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(cover)
                    stream.flush()
                    os.fsync(stream.fileno())
                project_document.commit_layout2_document(stage, cover_path=cover_path)
            finally:
                cover_path.unlink(missing_ok=True)
        else:
            project_document.commit_layout2_document(stage)
        staged_document = resolve_root_child(stage, f"{stage.name}.sbd")
        final_staged_document = resolve_root_child(stage, destination_document.name)
        os.replace(staged_document, final_staged_document)
        project_document.validate_layout2_document(final_staged_document)

        current_stage = "verification"
        source_after = _scan_tree(source_root, source_document=source_document)
        if source_after.files != source_before.files:
            raise OSError("Source project changed during Save As snapshotting.")
        final_inventory = _scan_tree(stage)
        expected_names = set(staged_before_commit.files)
        expected_names.update({".storyboarder/state.json", destination_document.name})
        if set(final_inventory.files) != expected_names:
            raise OSError("Staged Save As file counts do not reconcile.")

        current_stage = "rename"
        sibling_document = destination_root.parent / f"{destination_root.name}.sbd"
        folded_targets = {
            destination_root.name.casefold(),
            sibling_document.name.casefold(),
        }
        for child in destination_root.parent.iterdir():
            if child == stage:
                continue
            if child.name.casefold() in folded_targets:
                raise FileExistsError(
                    "Save As destination appeared during staging; it was not replaced."
                )
        # On Windows, os.rename is an atomic same-volume move that refuses an
        # existing destination. The immediate collision recheck also produces
        # a recoverable staging report if another process races publication.
        os.rename(stage, destination_root)
        return Layout2SaveAsResult(
            destination_root=destination_root,
            document_path=destination_document,
            snapshot_hash=snapshot_hash,
            source_file_count=len(source_before.files),
            destination_file_count=len(final_inventory.files),
            excluded_paths=source_before.excluded,
        )
    except BaseException as exc:
        preserve = current_stage == "rename" and stage.exists()
        if stage.exists() and not preserve:
            shutil.rmtree(stage, ignore_errors=True)
        retained_stage = stage if stage.exists() else None
        raise Layout2SaveAsError(
            current_stage,
            str(exc),
            staging_path=retained_stage,
            destination_root=destination_root,
        ) from exc
