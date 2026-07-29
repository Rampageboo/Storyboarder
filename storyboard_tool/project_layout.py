"""Project layout schema and portable path authority.

All persisted filesystem paths are project-root-relative POSIX strings.  This
module owns their validation and resolution so layout-specific storage never
leaks into domain consumers.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Protocol


PROJECT_JSON_VERSION = 4
SUPPORTED_PROJECT_JSON_VERSIONS = frozenset({1, 2, 3, PROJECT_JSON_VERSION})

LAYOUT_1 = 1
LAYOUT_2 = 2
SUPPORTED_LAYOUTS = frozenset({LAYOUT_1, LAYOUT_2})
LAYOUT_2_ENABLED = False

MAX_STORAGE_REVISION = (1 << 63) - 1
_DRIVE_PATH_RE = re.compile(r"^[A-Za-z]:")


class ProjectLayoutError(ValueError):
    """Base error for an invalid project layout contract."""


class ProjectSchemaError(ProjectLayoutError):
    """The project manifest has an unsupported or malformed schema."""


class ProjectPathError(ProjectLayoutError):
    """A persisted project path is unsafe or non-portable."""


class ProjectIntegrityError(ProjectLayoutError):
    """Persisted project data points at a missing or ambiguous target."""


class LayoutDisabledError(ProjectLayoutError):
    """A valid layout is not enabled for application use yet."""


class ProjectPathContext(Protocol):
    @property
    def project_root(self) -> Path: ...


@dataclass(frozen=True)
class ProjectLayoutSpec:
    """Validated layout-bearing fields from ``project.json``."""

    schema_version: int
    layout: int
    project_id: str = ""
    storage_revision: int = 0


def parse_project_manifest(payload: Any) -> ProjectLayoutSpec:
    """Validate the schema/layout fields in a project manifest.

    Versions 1-3 remain readable for Layout 1 compatibility. A missing
    ``layout`` is explicitly Layout 1; every other missing or unknown schema
    discriminator fails closed.
    """
    if not isinstance(payload, dict):
        raise ProjectSchemaError("project.json must contain a JSON object.")

    version = payload.get("version")
    if isinstance(version, bool) or not isinstance(version, int):
        raise ProjectSchemaError("project.json requires an integer version.")
    if version not in SUPPORTED_PROJECT_JSON_VERSIONS:
        raise ProjectSchemaError(f"Unsupported project.json version: {version!r}.")

    layout = payload.get("layout", LAYOUT_1)
    if isinstance(layout, bool) or not isinstance(layout, int) or layout not in SUPPORTED_LAYOUTS:
        raise ProjectSchemaError(f"Unsupported project layout: {layout!r}.")

    if layout == LAYOUT_1:
        return ProjectLayoutSpec(schema_version=version, layout=LAYOUT_1)

    project_id = payload.get("project_id")
    if not isinstance(project_id, str) or not project_id or project_id != project_id.strip():
        raise ProjectSchemaError("Layout 2 requires a non-empty stable project_id.")

    storage_revision = payload.get("storage_revision")
    if (
        isinstance(storage_revision, bool)
        or not isinstance(storage_revision, int)
        or storage_revision < 0
        or storage_revision > MAX_STORAGE_REVISION
    ):
        raise ProjectSchemaError(
            f"Layout 2 storage_revision must be an integer from 0 to {MAX_STORAGE_REVISION}."
        )

    return ProjectLayoutSpec(
        schema_version=version,
        layout=LAYOUT_2,
        project_id=project_id,
        storage_revision=storage_revision,
    )


def ensure_layout_enabled(layout: int) -> None:
    """Reject valid-but-disabled layouts before any project mutation."""
    if isinstance(layout, bool) or not isinstance(layout, int) or layout not in SUPPORTED_LAYOUTS:
        raise ProjectSchemaError(f"Unsupported project layout: {layout!r}.")
    if layout == LAYOUT_2 and not LAYOUT_2_ENABLED:
        raise LayoutDisabledError("Layout 2 projects are not enabled in this build.")


def project_manifest(project: Any) -> dict[str, Any]:
    """Build the canonical manifest for a project model."""
    layout = getattr(project, "layout", LAYOUT_1)
    if isinstance(layout, bool) or not isinstance(layout, int) or layout not in SUPPORTED_LAYOUTS:
        raise ProjectSchemaError(f"Unsupported project layout: {layout!r}.")
    if layout == LAYOUT_1:
        return {"version": PROJECT_JSON_VERSION}
    spec = parse_project_manifest(
        {
            "version": PROJECT_JSON_VERSION,
            "layout": layout,
            "project_id": getattr(project, "project_id", ""),
            "storage_revision": getattr(project, "storage_revision", None),
        }
    )
    return {
        "version": spec.schema_version,
        "layout": spec.layout,
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


def _reject_casefold_disk_collision(root: Path, relative: PurePosixPath) -> None:
    current = root
    for part in relative.parts:
        if not current.is_dir():
            return
        try:
            matches = [child for child in current.iterdir() if child.name.casefold() == part.casefold()]
        except OSError as exc:
            raise ProjectPathError(f"Cannot inspect project path component {current}: {exc}") from exc
        distinct_names = {child.name for child in matches}
        if len(distinct_names) > 1:
            names = ", ".join(sorted(repr(name) for name in distinct_names))
            raise ProjectPathError(f"Case-fold collision under {current}: {names}.")
        current = matches[0] if matches else current / part


def _reject_reparse_escape(root: Path, relative: PurePosixPath) -> Path:
    root_resolved = root.resolve(strict=False)
    current = root
    for part in relative.parts:
        current = current / part
        if current.exists() or current.is_symlink():
            resolved_component = current.resolve(strict=False)
            if not _is_within(resolved_component, root_resolved):
                raise ProjectPathError(f"Project path escapes through a reparse point: {relative}.")

    resolved = current.resolve(strict=False)
    if not _is_within(resolved, root_resolved):
        raise ProjectPathError(f"Project path escapes the project root: {relative}.")
    return resolved


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
    rebound to a layout default.
    """
    stored = "" if persisted_path is None else persisted_path
    if not isinstance(stored, str):
        raise ProjectPathError(f"{field_name} must be a string.")
    using_default = stored == ""
    chosen = default if using_default else stored
    if chosen is None or chosen == "":
        raise ProjectPathError(f"{field_name} is required.")

    relative = validate_project_relative_posix(chosen, field_name=field_name)
    root = Path(project.project_root).absolute()
    _reject_casefold_disk_collision(root, relative)
    resolved = _reject_reparse_escape(root, relative)

    if required_suffixes is not None:
        suffixes = tuple(str(suffix).lower() for suffix in required_suffixes)
        if resolved.suffix.lower() not in suffixes:
            raise ProjectPathError(
                f"{field_name} must use one of these extensions: {', '.join(required_suffixes)}"
            )

    if must_exist and not resolved.exists():
        source = "default" if using_default else "stored"
        raise ProjectIntegrityError(f"{source.capitalize()} {field_name} target is missing: {chosen}.")
    return resolved


def project_relative_posix(project: ProjectPathContext, path: Path) -> str:
    """Convert an existing path under ``project_root`` into portable storage."""
    root = Path(project.project_root).resolve(strict=False)
    resolved = Path(path).resolve(strict=False)
    if not _is_within(resolved, root) or resolved == root:
        raise ProjectPathError("Path must identify an item inside the project root.")
    relative = resolved.relative_to(root).as_posix()
    validate_project_relative_posix(relative)
    return relative
