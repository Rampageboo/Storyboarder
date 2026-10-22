"""Project manifest schema and portable path authority.

All persisted filesystem paths are project-root-relative POSIX strings.  This
module owns their validation and resolution so storage paths never leak into
domain consumers.
"""
from __future__ import annotations

import re
import stat
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Protocol


PROJECT_JSON_VERSION = 5

MAX_STORAGE_REVISION = (1 << 63) - 1
_DRIVE_PATH_RE = re.compile(r"^[A-Za-z]:")

_PROJECT_PATHS = {
    "images_dir": "Images",
    "references_dir": "Images/References",
    "exports_dir": "Exports",
    "backups_dir": ".storyboarder/backups",
}
_METADATA_PATHS = {
    "manifest": "project.json",
    "settings": "settings.json",
}


class ProjectLayoutError(ValueError):
    """Base error for an invalid project format contract."""


class ProjectSchemaError(ProjectLayoutError):
    """The project manifest has an unsupported or malformed schema."""


class ProjectPathError(ProjectLayoutError):
    """A persisted project path is unsafe or non-portable."""


class ProjectIntegrityError(ProjectLayoutError):
    """Persisted project data points at a missing or ambiguous target."""


class ProjectPathContext(Protocol):
    @property
    def project_root(self) -> Path: ...

    @property
    def metadata_root(self) -> Path: ...


@dataclass(frozen=True)
class ProjectManifest:
    """Validated fields from ``.storyboarder/data/project.json``."""

    project_id: str
    storage_revision: int


def parse_project_manifest(payload: Any) -> ProjectManifest:
    """Validate a project manifest; anything but the current schema fails closed."""
    if not isinstance(payload, dict):
        raise ProjectSchemaError("project.json must contain a JSON object.")
    version = payload.get("version")
    if isinstance(version, bool) or version != PROJECT_JSON_VERSION:
        raise ProjectSchemaError(f"Unsupported project.json version: {version!r}.")
    project_id = payload.get("project_id")
    if not isinstance(project_id, str) or not project_id or project_id != project_id.strip():
        raise ProjectSchemaError("project.json requires a non-empty project_id.")
    storage_revision = payload.get("storage_revision")
    if (
        isinstance(storage_revision, bool)
        or not isinstance(storage_revision, int)
        or storage_revision < 0
        or storage_revision > MAX_STORAGE_REVISION
    ):
        raise ProjectSchemaError(
            f"storage_revision must be an integer from 0 to {MAX_STORAGE_REVISION}."
        )
    return ProjectManifest(project_id=project_id, storage_revision=storage_revision)


def project_manifest(project: Any) -> dict[str, Any]:
    """Build the canonical manifest for a project model."""
    spec = parse_project_manifest(
        {
            "version": PROJECT_JSON_VERSION,
            "project_id": getattr(project, "project_id", ""),
            "storage_revision": getattr(project, "storage_revision", None),
        }
    )
    return {
        "version": PROJECT_JSON_VERSION,
        "project_id": spec.project_id,
        "storage_revision": spec.storage_revision,
    }


def validate_project_relative_posix(
    value: str,
    *,
    field_name: str = "project path",
) -> PurePosixPath:
    """Return a validated project-relative POSIX path without normalizing it."""
    if not isinstance(value, str) or not value:
        raise ProjectPathError(f"{field_name} is required.")
    if value != value.strip():
        raise ProjectPathError(f"{field_name} cannot have leading or trailing whitespace.")
    if "\x00" in value:
        raise ProjectPathError(f"{field_name} cannot contain a NUL byte.")
    if "\\" in value:
        raise ProjectPathError(f"{field_name} must use POSIX '/' separators.")
    if value.startswith("/") or _DRIVE_PATH_RE.match(value):
        raise ProjectPathError(f"{field_name} must be relative to the project root.")
    if value.endswith("/") or "//" in value:
        raise ProjectPathError(f"{field_name} must be a normalized POSIX path.")

    raw_parts = value.split("/")
    if any(part in {"", ".", ".."} for part in raw_parts):
        raise ProjectPathError(f"{field_name} cannot contain '.', '..', or empty components.")
    if any(":" in part for part in raw_parts):
        raise ProjectPathError(f"{field_name} cannot contain drive or stream syntax.")

    path = PurePosixPath(value)
    if path.is_absolute() or str(path) != value:
        raise ProjectPathError(f"{field_name} must be a normalized relative POSIX path.")
    return path


def ensure_no_casefold_collisions(
    values: Iterable[str],
    *,
    field_name: str = "project paths",
) -> None:
    """Reject distinct persisted paths that collide on case-insensitive hosts."""
    seen: dict[str, str] = {}
    for value in values:
        normalized = validate_project_relative_posix(value, field_name=field_name).as_posix()
        folded = normalized.casefold()
        previous = seen.get(folded)
        if previous is not None and previous != normalized:
            raise ProjectPathError(
                f"{field_name} contain a case-fold collision: {previous!r} and {normalized!r}."
            )
        seen[folded] = normalized


def _is_within(candidate: Path, root: Path) -> bool:
    return candidate == root or root in candidate.parents


def _stat_signature(value: Any) -> tuple[int, ...]:
    return (
        int(value.st_dev),
        int(value.st_ino),
        int(value.st_mode),
        int(value.st_size),
        int(value.st_mtime_ns),
        int(getattr(value, "st_file_attributes", 0)),
    )


@lru_cache(maxsize=4096)
def _casefold_directory_inventory(
    directory: str,
    signature: tuple[int, ...],
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Cache a directory's case-fold table until its filesystem mtime changes."""
    del signature  # Part of the cache key; contents are read from ``directory``.
    names: dict[str, list[str]] = {}
    for child in Path(directory).iterdir():
        names.setdefault(child.name.casefold(), []).append(child.name)
    return tuple(
        (folded, tuple(sorted(entries)))
        for folded, entries in sorted(names.items())
    )


def _reject_casefold_disk_collision(root: Path, relative: PurePosixPath) -> None:
    current = root
    for part in relative.parts:
        try:
            current_stat = current.stat()
        except FileNotFoundError:
            return
        except OSError as exc:
            raise ProjectPathError(f"Cannot inspect project path component {current}: {exc}") from exc
        if not stat.S_ISDIR(current_stat.st_mode):
            return
        try:
            inventory = dict(
                _casefold_directory_inventory(
                    str(current),
                    _stat_signature(current_stat),
                )
            )
        except OSError as exc:
            raise ProjectPathError(f"Cannot inspect project path component {current}: {exc}") from exc
        matches = inventory.get(part.casefold(), ())
        if len(matches) > 1:
            names = ", ".join(repr(name) for name in matches)
            raise ProjectPathError(f"Case-fold collision under {current}: {names}.")
        current = current / matches[0] if matches else current / part


@lru_cache(maxsize=16384)
def _resolve_signed_path(path: str, signature: tuple[int, ...]) -> Path:
    """Cache expensive Windows reparse resolution until the entry changes."""
    del signature
    return Path(path).resolve(strict=False)


def _reject_reparse_escape(root: Path, relative: PurePosixPath) -> Path:
    try:
        root_resolved = _resolve_signed_path(str(root), _stat_signature(root.lstat()))
    except FileNotFoundError:
        root_resolved = root.resolve(strict=False)
    except OSError as exc:
        raise ProjectPathError(f"Cannot inspect project root {root}: {exc}") from exc

    current = root
    resolved = root_resolved
    parts = relative.parts
    for index, part in enumerate(parts):
        current = current / part
        try:
            signature = _stat_signature(current.lstat())
        except FileNotFoundError:
            resolved = resolved.joinpath(*parts[index:])
            break
        except OSError as exc:
            raise ProjectPathError(f"Cannot inspect project path component {current}: {exc}") from exc
        resolved = _resolve_signed_path(str(current), signature)
        if not _is_within(resolved, root_resolved):
            raise ProjectPathError(f"Project path escapes through a reparse point: {relative}.")

    if not _is_within(resolved, root_resolved):
        raise ProjectPathError(f"Project path escapes the project root: {relative}.")
    return resolved


def _resolve_under_root(
    root: Path,
    relative: PurePosixPath,
    *,
    must_exist: bool,
    required_suffixes: tuple[str, ...] | None,
    field_name: str,
    missing_source: str,
) -> Path:
    absolute_root = Path(root).absolute()
    _reject_casefold_disk_collision(absolute_root, relative)
    resolved = _reject_reparse_escape(absolute_root, relative)

    if required_suffixes is not None:
        suffixes = tuple(str(suffix).lower() for suffix in required_suffixes)
        if resolved.suffix.lower() not in suffixes:
            raise ProjectPathError(
                f"{field_name} must use one of these extensions: {', '.join(required_suffixes)}"
            )

    if must_exist and not resolved.exists():
        raise ProjectIntegrityError(
            f"{missing_source.capitalize()} {field_name} target is missing: {relative.as_posix()}."
        )
    return resolved


def _resolve_generated_child(root: Path, *parts: str, field_name: str) -> Path:
    relative = validate_project_relative_posix(
        "/".join(str(part) for part in parts),
        field_name=field_name,
    )
    return _reject_reparse_escape(Path(root).absolute(), relative)


def resolve_project_path(
    project: ProjectPathContext,
    persisted_path: str | None,
    *,
    default: str | None = None,
    must_exist: bool = False,
    required_suffixes: tuple[str, ...] | None = None,
    field_name: str = "project path",
) -> Path:
    """Resolve a persisted path, using a default only when the field is empty.

    A non-empty stored path always wins. If it no longer exists and the caller
    requires an existing target, the project is corrupt rather than silently
    rebound to a default.
    """
    stored = "" if persisted_path is None else persisted_path
    if not isinstance(stored, str):
        raise ProjectPathError(f"{field_name} must be a string.")
    using_default = stored == ""
    chosen = default if using_default else stored
    if chosen is None or chosen == "":
        raise ProjectPathError(f"{field_name} is required.")

    relative = validate_project_relative_posix(chosen, field_name=field_name)
    return _resolve_under_root(
        project.project_root,
        relative,
        must_exist=must_exist,
        required_suffixes=required_suffixes,
        field_name=field_name,
        missing_source="default" if using_default else "stored",
    )


def resolve_project_child(
    project: ProjectPathContext,
    *parts: str,
    required_suffixes: tuple[str, ...] | None = None,
) -> Path:
    """Resolve a generated Layout path from validated POSIX components."""
    resolved = _resolve_generated_child(
        project.project_root,
        *parts,
        field_name="generated project path",
    )
    if required_suffixes is not None:
        suffixes = tuple(str(suffix).lower() for suffix in required_suffixes)
        if resolved.suffix.lower() not in suffixes:
            raise ProjectPathError(
                "generated project path must use one of these extensions: "
                f"{', '.join(required_suffixes)}"
            )
    return resolved


def resolve_project_sibling(
    project: ProjectPathContext,
    path: Path,
    sibling_name: str,
) -> Path:
    """Resolve a generated sibling of an already project-contained path."""
    candidate = Path(path).parent / sibling_name
    return resolve_project_path(project, project_relative_posix(project, candidate))


def resolve_root_child(root: Path, *parts: str) -> Path:
    """Resolve a safe relative child below an explicit internal root."""
    return _resolve_generated_child(Path(root), *parts, field_name="internal path")


def resolve_metadata_path(
    project: ProjectPathContext,
    relative_path: str,
    *,
    must_exist: bool = False,
) -> Path:
    """Resolve an internal metadata/work path under ``metadata_root``."""
    relative = validate_project_relative_posix(relative_path, field_name="metadata path")
    return _resolve_under_root(
        project.metadata_root,
        relative,
        must_exist=must_exist,
        required_suffixes=None,
        field_name="metadata path",
        missing_source="stored",
    )


def project_path_for(project: ProjectPathContext, role: str) -> Path:
    """Return a canonical project path for a static role."""
    try:
        relative = _PROJECT_PATHS[role]
    except KeyError as exc:
        raise ProjectSchemaError(f"Unknown project path role: {role!r}.") from exc
    return _resolve_generated_child(
        project.project_root,
        relative,
        field_name=f"{role} path",
    )


def _validated_component(value: str, field_name: str) -> str:
    component = validate_project_relative_posix(str(value), field_name=field_name).as_posix()
    if "/" in component:
        raise ProjectPathError(f"{field_name} must be a single path component.")
    return component


_SHOT_ASSET_PATHS = {
    "source_psd": "PSD/Shots/{id}.psd",
    "preview": "Images/Shots/{id}_preview.png",
    "board_background": "Images/Shots/{id}_background.png",
    "codex": "Images/Shots/{id}_codex.png",
    "thumbnail": ".storyboarder/cache/thumbnails/{id}.png",
}


def shot_asset_relative(project: ProjectPathContext, shot_id: str, role: str) -> str:
    """Return the exact project-relative path for one persisted shot asset."""
    shot_id = _validated_component(shot_id, "shot id")
    try:
        return _SHOT_ASSET_PATHS[role].format(id=shot_id)
    except KeyError as exc:
        raise ProjectSchemaError(f"Unknown shot asset role: {role!r}.") from exc


def resolve_shot_asset(project: ProjectPathContext, shot_id: str, role: str) -> Path:
    """Resolve an exact shot asset role."""
    return resolve_project_path(project, shot_asset_relative(project, shot_id, role))


def shot_metadata_relative(project: ProjectPathContext, shot_id: str, role: str) -> str:
    """Return the metadata-root-relative path for per-shot JSON."""
    shot_id = _validated_component(shot_id, "shot id")
    try:
        directory = {"annotations": "annotations", "drawing": "drawings", "notes": "notes"}[role]
    except KeyError as exc:
        raise ProjectSchemaError(f"Unknown shot metadata role: {role!r}.") from exc
    return f"{directory}/{shot_id}.json"


def resolve_shot_metadata(project: ProjectPathContext, shot_id: str, role: str) -> Path:
    """Resolve per-shot JSON below the metadata root."""
    return resolve_metadata_path(project, shot_metadata_relative(project, shot_id, role))


def reference_asset_relative(project: ProjectPathContext, asset_id: str, suffix: str) -> str:
    """Return the canonical path for an immutable reference asset id."""
    asset_id = _validated_component(asset_id, "reference asset id")
    extension = str(suffix or "").lower()
    if not extension.startswith(".") or "/" in extension or "\\" in extension:
        raise ProjectPathError("reference asset extension is invalid.")
    if extension in {".blend", ".glb", ".gltf"}:
        return f"Blender/References/{asset_id}{extension}"
    if extension in {".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v"}:
        return f".storyboarder/media/references/{asset_id}{extension}"
    return f"Images/References/{asset_id}{extension}"


def resolve_reference_asset(project: ProjectPathContext, asset_id: str, suffix: str) -> Path:
    """Resolve a canonical project reference asset."""
    return resolve_project_path(project, reference_asset_relative(project, asset_id, suffix))


def _validated_extension(suffix: str, field_name: str) -> str:
    extension = str(suffix or "").lower()
    if (
        not extension.startswith(".")
        or len(extension) < 2
        or "/" in extension
        or "\\" in extension
    ):
        raise ProjectPathError(f"{field_name} is invalid.")
    return extension


def scene2d_metadata_path(project: ProjectPathContext, *parts: str) -> Path:
    """Resolve Scene 2D JSON below the metadata root."""
    return resolve_metadata_path(project, "/".join(("scenes2d", *parts)))


def scene2d_asset_relative(
    project: ProjectPathContext,
    scene_id: str,
    perspective_id: str,
    role: str,
    suffix: str = "",
) -> str:
    """Return the canonical path for a Scene 2D perspective asset."""
    _validated_component(scene_id, "Scene 2D id")
    perspective_id = _validated_component(perspective_id, "Scene 2D perspective id")
    if role == "source_psd":
        return f"PSD/Scene2D/{perspective_id}.psd"
    if role == "source_image":
        extension = _validated_extension(suffix, "Scene 2D image extension")
        return f"Images/Scene2D/{perspective_id}{extension}"
    if role == "preview":
        return f"Images/Scene2D/{perspective_id}_preview.png"
    raise ProjectSchemaError(f"Unknown Scene 2D asset role: {role!r}.")


def resolve_scene2d_asset(
    project: ProjectPathContext,
    scene_id: str,
    perspective_id: str,
    role: str,
    suffix: str = "",
) -> Path:
    return resolve_project_path(
        project,
        scene2d_asset_relative(project, scene_id, perspective_id, role, suffix),
    )


def scene3d_metadata_path(project: ProjectPathContext, *parts: str) -> Path:
    """Resolve Scene 3D JSON below the metadata root."""
    return resolve_metadata_path(project, "/".join(("scenes3d", *parts)))


def scene3d_asset_relative(
    project: ProjectPathContext,
    scene_id: str,
    suffix: str,
) -> str:
    """Return the canonical project-relative Scene 3D asset path."""
    scene_id = _validated_component(scene_id, "Scene 3D id")
    extension = _validated_extension(suffix, "Scene 3D asset extension")
    if extension not in {".blend", ".glb", ".gltf"}:
        raise ProjectPathError("Scene 3D assets must be .blend, .glb, or .gltf files.")
    return f"Blender/{scene_id}{extension}"


def resolve_scene3d_asset(
    project: ProjectPathContext,
    scene_id: str,
    suffix: str,
) -> Path:
    return resolve_project_path(project, scene3d_asset_relative(project, scene_id, suffix))


def scene3d_preview_path(project: ProjectPathContext, scene_id: str) -> Path:
    """Resolve the disposable GLB preview for a Scene 3D record."""
    scene_id = _validated_component(scene_id, "Scene 3D id")
    return resolve_project_path(
        project, f".storyboarder/cache/scene3d/{scene_id}/storyboarder_preview.glb"
    )


def generation_metadata_path(project: ProjectPathContext, *parts: str) -> Path:
    """Resolve generation JSON/state below the metadata root."""
    return resolve_metadata_path(project, "/".join(("generation", *parts)))


def generation_asset_relative(
    project: ProjectPathContext,
    request_id: str,
    output_id: str,
    suffix: str,
    *,
    index: int,
) -> str:
    """Return the canonical path for a generated image artifact."""
    request_id = _validated_component(request_id, "request id")
    output_id = _validated_component(output_id, "output id")
    extension = str(suffix or "").lower()
    if not extension.startswith(".") or "/" in extension or "\\" in extension:
        raise ProjectPathError("generation artifact extension is invalid.")
    ordinal = "" if index == 1 else f"_{index:03d}"
    return f"Images/Generated/{request_id}_{output_id}{ordinal}{extension}"


def resolve_generation_asset(
    project: ProjectPathContext,
    request_id: str,
    output_id: str,
    suffix: str,
    *,
    index: int,
) -> Path:
    """Resolve a canonical generated image artifact."""
    return resolve_project_path(
        project,
        generation_asset_relative(project, request_id, output_id, suffix, index=index),
    )


def generation_video_relative(project: ProjectPathContext, take_id: str) -> str:
    """Return the canonical path for a generated video take."""
    take_id = _validated_component(take_id, "video take id")
    return f"Videos/Generated/{take_id}.mp4"


def metadata_path_for(project: ProjectPathContext, role: str) -> Path:
    """Return a canonical metadata path for a static role."""
    try:
        relative = _METADATA_PATHS[role]
    except KeyError as exc:
        raise ProjectSchemaError(f"Unknown metadata path role: {role!r}.") from exc
    return _resolve_generated_child(
        project.metadata_root,
        relative,
        field_name=f"{role} metadata path",
    )


def project_relative_posix(project: ProjectPathContext, path: Path) -> str:
    """Convert an existing path under ``project_root`` into portable storage."""
    root = Path(project.project_root).resolve(strict=False)
    resolved = Path(path).resolve(strict=False)
    if not _is_within(resolved, root) or resolved == root:
        raise ProjectPathError("Path must identify an item inside the project root.")
    relative = resolved.relative_to(root).as_posix()
    validate_project_relative_posix(relative)
    return relative
