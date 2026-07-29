from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException

from . import app_state, project_manager, runtime_state, scene2d, shot_service
from .errors import AppErrorCode, app_error
from .models import Shot
from .project_layout import LAYOUT_2, resolve_metadata_path


PLUGIN_PROTOCOL_VERSION = 2
EXPLICIT_ASSET_PATHS_CAPABILITY = "explicit_asset_paths_v2"
WRITE_INTENT_TTL_SECONDS = 30.0
_WRITABLE_ASSET_ROLES = frozenset({"source_psd", "preview"})
_INBOX_ASSET_ROLES = frozenset({"preview"})
_MAX_PLUGIN_IMAGE_BYTES = 256 * 1024 * 1024


def _file_header(path: Path, size: int) -> bytes:
    try:
        with path.open("rb") as stream:
            return stream.read(size)
    except OSError:
        return b""


def _stable_sha256(path: Path) -> str:
    before = path.stat()
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    after = path.stat()
    if (
        before.st_size != after.st_size
        or before.st_mtime_ns != after.st_mtime_ns
        or before.st_ino != after.st_ino
    ):
        raise OSError("File changed while its hash was being validated.")
    return digest.hexdigest()


class PluginBridgeService:
    """Photoshop plugin and live bridge workflow logic."""

    def __init__(self, app: FastAPI) -> None:
        self.app = app

    def _context_revision(self, project) -> int:
        if project.layout == LAYOUT_2:
            return int(project.storage_revision)
        return runtime_state.plugin_project_revision(self.app)

    def _protocol_is_v2(self, protocol: dict[str, Any] | None) -> bool:
        data = protocol if isinstance(protocol, dict) else {}
        capabilities = {
            str(item).strip()
            for item in data.get("capabilities", [])
            if str(item).strip()
        }
        return (
            data.get("version") == PLUGIN_PROTOCOL_VERSION
            and EXPLICIT_ASSET_PATHS_CAPABILITY in capabilities
        )

    def _upgrade_required(self) -> HTTPException:
        return app_error(
            AppErrorCode.PLUGIN_UPGRADE_REQUIRED,
            "This project requires Photoshop plugin protocol v2 with "
            "explicit_asset_paths_v2. Upgrade the Storyboarder plugin.",
            status=426,
        )

    def _require_layout_protocol(
        self,
        project,
        protocol: dict[str, Any] | None,
    ) -> None:
        if project.layout == LAYOUT_2 and not self._protocol_is_v2(protocol):
            raise self._upgrade_required()

    def _require_fresh_protocol(
        self,
        project,
        protocol: dict[str, Any] | None,
    ) -> None:
        self._require_layout_protocol(project, protocol)
        if not self._protocol_is_v2(protocol):
            raise app_error(
                AppErrorCode.PLUGIN_PROTOCOL_REJECTED,
                "Plugin protocol v2 with explicit_asset_paths_v2 is required.",
                status=400,
            )
        data = protocol if isinstance(protocol, dict) else {}
        expected_session = str(getattr(self.app.state, "project_session_id", "") or "")
        if not expected_session or data.get("project_session_id") != expected_session:
            raise app_error(
                AppErrorCode.PLUGIN_PROTOCOL_REJECTED,
                "Plugin project session is stale.",
                status=409,
            )
        if data.get("context_revision") != self._context_revision(project):
            raise app_error(
                AppErrorCode.PLUGIN_PROTOCOL_REJECTED,
                "Plugin context revision is stale.",
                status=409,
            )

    def _require_mutation_protocol(
        self,
        project,
        protocol: dict[str, Any] | None,
    ) -> None:
        self._require_layout_protocol(project, protocol)
        if project.layout == LAYOUT_2:
            self._require_fresh_protocol(project, protocol)

    def _scene_records(self, project) -> list[dict[str, Any]]:
        if project.layout != LAYOUT_2:
            return scene2d.list_scenes(project)
        index = resolve_metadata_path(project, "scenes2d/scenes2d.json")
        if not index.is_file():
            return []
        try:
            payload = json.loads(index.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        scenes = payload.get("scenes") if isinstance(payload, dict) else None
        return [item for item in scenes if isinstance(item, dict)] if isinstance(scenes, list) else []

    def _scene_perspective(self, project, scene_id: str, perspective_id: str) -> dict[str, Any] | None:
        for scene in self._scene_records(project):
            if str(scene.get("id") or "") != scene_id:
                continue
            for perspective in scene.get("perspectives") or []:
                if (
                    isinstance(perspective, dict)
                    and str(perspective.get("id") or "") == perspective_id
                ):
                    return perspective
        return None

    def _safe_work_context(self, project) -> dict[str, Any]:
        context = dict(runtime_state.active_work_context(self.app))
        if project.layout != LAYOUT_2:
            return context
        key = str(context.get("key") or "")
        safe = {
            field: context[field]
            for field in (
                "kind",
                "key",
                "shot_id",
                "scene_id",
                "perspective_id",
            )
            if field in context
        }
        try:
            source = self.asset_paths(project, key)["source_psd"]
        except (HTTPException, KeyError, ValueError):
            return safe
        safe["source_file_path"] = source["project_relative_path"]
        safe["source_native_path"] = source["native_path"]
        return safe

    def asset_paths(self, project, work_key: str) -> dict[str, dict[str, Any]]:
        """Backend-owned exact role paths; client-supplied paths are never authority."""
        key = str(work_key or "").strip()
        relative: dict[str, str]
        if key.startswith("shot:"):
            shot_id = key.removeprefix("shot:")
            shot = next((item for item in project.shots if item.shot_id == shot_id), None)
            if shot is None:
                raise HTTPException(status_code=404, detail="Plugin work item not found.")
            if project.layout == LAYOUT_2:
                relative = {
                    "source_psd": f"PSD/Shots/{shot_id}.psd",
                    "preview": f"Images/Shots/{shot_id}_preview.png",
                    "thumbnail": f".storyboarder/cache/thumbnails/{shot_id}.png",
                    "board_background": f"Images/Shots/{shot_id}_background.png",
                }
            else:
                relative = {
                    "source_psd": shot.source_file_path
                    or f"shots/{shot_id}/{shot_id}.psd",
                    "preview": shot.preview_image_path
                    or f"shots/{shot_id}/{shot_id}_preview.png",
                    "thumbnail": shot.thumbnail_path
                    or f"shots/{shot_id}/{shot_id}_thumb.png",
                    "board_background": f"shots/{shot_id}/{shot_id}_background.png",
                }
        elif key.startswith("scene2d:"):
            parts = key.split(":")
            if len(parts) != 3:
                raise HTTPException(status_code=404, detail="Plugin work item not found.")
            scene_id, perspective_id = parts[1], parts[2]
            perspective = self._scene_perspective(project, scene_id, perspective_id)
            if perspective is None or perspective.get("type") != "psd":
                raise HTTPException(status_code=404, detail="Plugin work item not found.")
            if project.layout == LAYOUT_2:
                relative = {
                    "source_psd": f"PSD/Scene2D/{perspective_id}.psd",
                    "preview": f"Images/Scene2D/{perspective_id}_preview.png",
                }
            else:
                relative = {
                    "source_psd": str(perspective.get("source_file_path") or ""),
                    "preview": str(perspective.get("preview_image_path") or ""),
                }
        else:
            raise HTTPException(status_code=404, detail="Plugin work item not found.")

        result: dict[str, dict[str, Any]] = {}
        for role, stored in relative.items():
            if not stored:
                continue
            path = project_manager.resolve_project_path(project, stored)
            result[role] = {
                "project_relative_path": stored,
                "native_path": str(path),
                "writable": role in _WRITABLE_ASSET_ROLES,
            }
        return result

    def issue_write_intent(
        self,
        work_key: str,
        asset_role: str,
        protocol: dict[str, Any] | None,
    ) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        self._require_fresh_protocol(project, protocol)
        key = str(work_key or "").strip()
        role = str(asset_role or "").strip()
        paths = self.asset_paths(project, key)
        if role not in _WRITABLE_ASSET_ROLES or role not in paths:
            raise app_error(
                AppErrorCode.PLUGIN_WRITE_INTENT_REJECTED,
                "Asset role is not writable for this work item.",
                status=400,
            )
        token = secrets.token_urlsafe(32)
        target = Path(paths[role]["native_path"])
        inbox_path: Path | None = None
        if project.layout == LAYOUT_2 and role in _INBOX_ASSET_ROLES:
            inbox_path = project_manager.resolve_project_child(
                project,
                ".storyboarder",
                "transactions",
                token,
                "plugin-inbox",
                target.name,
            )
            inbox_path.parent.mkdir(parents=True, exist_ok=False)
        intents = getattr(self.app.state, "plugin_write_intents", None)
        if not isinstance(intents, dict):
            intents = {}
            self.app.state.plugin_write_intents = intents
        now = time.monotonic()
        for stale_token, stale_record in list(intents.items()):
            if (
                not isinstance(stale_record, dict)
                or stale_record.get("used")
                or float(stale_record.get("expires_at") or 0.0) < now
            ):
                intents.pop(stale_token, None)
                self._cleanup_intent_record(stale_record)
        intents[token] = {
            "expires_at": now + WRITE_INTENT_TTL_SECONDS,
            "project_session_id": str(self.app.state.project_session_id),
            "context_revision": self._context_revision(project),
            "work_key": key,
            "asset_role": role,
            "target_path": str(target),
            "project_relative_path": paths[role]["project_relative_path"],
            "inbox_path": str(inbox_path) if inbox_path is not None else "",
            "used": False,
        }
        return {
            "token": token,
            "expires_in_seconds": WRITE_INTENT_TTL_SECONDS,
            "work_key": key,
            "asset_role": role,
            "write_path": str(inbox_path or target),
            "canonical_path": str(target),
            "project_relative_path": paths[role]["project_relative_path"],
        }

    def _cleanup_intent_record(self, record: Any) -> None:
        if not isinstance(record, dict):
            return
        inbox_text = str(record.get("inbox_path") or "")
        if not inbox_text:
            return
        inbox = Path(inbox_text)
        try:
            transaction_dir = inbox.parents[1]
            transactions_root = inbox.parents[2]
        except IndexError:
            return
        if (
            transactions_root.name == "transactions"
            and transactions_root.parent.name == ".storyboarder"
        ):
            shutil.rmtree(transaction_dir, ignore_errors=True)

    def _consume_write_intent(
        self,
        project,
        protocol: dict[str, Any] | None,
        *,
        expected_work_key: str,
        expected_role: str,
    ) -> dict[str, Any]:
        self._require_fresh_protocol(project, protocol)
        data = protocol if isinstance(protocol, dict) else {}
        if data.get("work_key") != expected_work_key or data.get("asset_role") != expected_role:
            raise app_error(
                AppErrorCode.PLUGIN_WRITE_INTENT_REJECTED,
                "Plugin write role or work key does not match the endpoint.",
                status=409,
            )
        token = str(data.get("write_intent") or "")
        intents = getattr(self.app.state, "plugin_write_intents", None)
        record = intents.get(token) if isinstance(intents, dict) and token else None
        if not isinstance(record, dict):
            raise app_error(
                AppErrorCode.PLUGIN_WRITE_INTENT_REJECTED,
                "Plugin write intent is missing or unknown.",
                status=403,
            )
        if record.get("used") or float(record.get("expires_at") or 0.0) < time.monotonic():
            intents.pop(token, None)
            self._cleanup_intent_record(record)
            raise app_error(
                AppErrorCode.PLUGIN_WRITE_INTENT_REJECTED,
                "Plugin write intent is expired or already used.",
                status=409,
            )
        expected = {
            "project_session_id": str(self.app.state.project_session_id),
            "context_revision": self._context_revision(project),
            "work_key": expected_work_key,
            "asset_role": expected_role,
        }
        if any(record.get(field) != value for field, value in expected.items()):
            raise app_error(
                AppErrorCode.PLUGIN_WRITE_INTENT_REJECTED,
                "Plugin write intent is stale or has the wrong scope.",
                status=409,
            )
        record["used"] = True
        return record

    def mark_project_changed(self) -> None:
        runtime_state.mark_plugin_project_changed(self.app)

    def heartbeat(self, payload: dict[str, Any] | None = None) -> dict[str, str]:
        project = getattr(self.app.state, "project", None)
        valid_work_keys = {item["key"] for item in self.work_items(project) if item.get("key")} if project else set()
        runtime_state.record_plugin_heartbeat(
            self.app,
            payload,
            valid_work_keys=valid_work_keys,
        )
        return {"ok": "true"}

    def context(self, protocol: dict[str, Any] | None = None) -> dict[str, Any]:
        current = app_state._require_project(self.app)
        self._require_layout_protocol(current, protocol)
        project = app_state._refresh_project_from_disk(self.app)
        self._require_layout_protocol(project, protocol)
        return self.context_payload(project, protocol)

    def context_payload(
        self,
        project,
        protocol: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._require_layout_protocol(project, protocol)
        canvas_width, canvas_height = project_manager.get_canvas_size(project)
        selected_shot_id = str(
            app_state._plugin_selected_shot_id(self.app)
            or runtime_state.live_selected_shot_id(self.app)
            or ""
        )
        if selected_shot_id and all(shot.shot_id != selected_shot_id for shot in project.shots):
            selected_shot_id = ""
        focused_shot_id = runtime_state.live_focus_shot_id(self.app)
        shots = [
            shot.to_dict() if project.layout == LAYOUT_2 else self.shot_payload(project, shot)
            for shot in project.shots
        ]
        selected_index = next(
            (index for index, shot in enumerate(project.shots) if shot.shot_id == selected_shot_id),
            -1,
        )
        next_shot_id = ""
        if selected_index >= 0 and selected_index + 1 < len(project.shots):
            next_shot_id = project.shots[selected_index + 1].shot_id
        selected_shot = project.shots[selected_index] if selected_index >= 0 else None
        layout2 = project.layout == LAYOUT_2
        bridge = app_state._bridge_status_payload(self.app)
        safe_work_context = self._safe_work_context(project)
        if layout2:
            bridge["work_context"] = safe_work_context
        payload = {
            "work_context": safe_work_context,
            "work_items": self.work_items(project),
            "project_name": project.name,
            "project_root": "" if layout2 else str(project.project_root),
            "project_json_path": "" if layout2 else str(project.json_path),
            "selected_shot_id": selected_shot_id,
            "focused_shot_id": focused_shot_id,
            "canvas": {
                "width": canvas_width,
                "height": canvas_height,
                "background_color": project_manager.get_canvas_color(project),
            },
            "shots": shots,
            "previous_shots": shots[:selected_index] if selected_index > 0 else [],
            "next_shot_id": next_shot_id,
            "paths": self.shot_paths(project, selected_shot) if selected_shot else {},
            "bridge": bridge,
            "protocol_version": PLUGIN_PROTOCOL_VERSION if self._protocol_is_v2(protocol) else 1,
            "required_capabilities": (
                [EXPLICIT_ASSET_PATHS_CAPABILITY] if layout2 else []
            ),
            "project_session_id": str(getattr(self.app.state, "project_session_id", "") or ""),
            "context_revision": self._context_revision(project),
            "path_mode": "explicit-assets" if self._protocol_is_v2(protocol) else "legacy",
            "offline_write_allowed": not layout2,
        }
        return payload

    def work_items(self, project) -> list[dict[str, Any]]:
        """Return all editable PSD work items: shots + Scene 2D PSD Perspectives."""
        items: list[dict[str, Any]] = []
        shots = list(project.shots)
        total_shots = len(shots)
        for index, shot in enumerate(shots):
            role_paths = self.asset_paths(project, f"shot:{shot.shot_id}")
            source_rel = role_paths["source_psd"]["project_relative_path"]
            preview_rel = role_paths["preview"]["project_relative_path"]
            previous_key = f"shot:{shots[index - 1].shot_id}" if index > 0 else ""
            next_key = f"shot:{shots[index + 1].shot_id}" if index + 1 < total_shots else ""
            items.append({
                "kind": "shot",
                "key": f"shot:{shot.shot_id}",
                "shot_id": shot.shot_id,
                "shot_title": str(shot.title or "").strip(),
                "label": shot.title or shot.shot_id,
                "index": index + 1,
                "count": total_shots,
                "previous_key": previous_key,
                "next_key": next_key,
                "source_file_path": source_rel,
                "source_native_path": role_paths["source_psd"]["native_path"],
                "preview_image_path": preview_rel,
                "asset_paths": role_paths,
            })
        try:
            scenes = self._scene_records(project)
        except Exception:
            scenes = []
        for sc in scenes:
            scene_id = sc.get("id", "")
            scene_title = str(sc.get("title") or "")
            psd_perspectives = [p for p in (sc.get("perspectives") or []) if p.get("type") == "psd"]
            count = len(psd_perspectives)
            for index, persp in enumerate(psd_perspectives):
                if persp.get("type") != "psd":
                    continue
                persp_id = persp.get("id", "")
                source_rel = str(persp.get("source_file_path") or "")
                preview_rel = str(persp.get("preview_image_path") or "")
                role_paths = self.asset_paths(
                    project,
                    f"scene2d:{scene_id}:{persp_id}",
                )
                source_rel = role_paths["source_psd"]["project_relative_path"]
                preview_rel = role_paths["preview"]["project_relative_path"]
                items.append({
                    "kind": "scene2d",
                    "key": f"scene2d:{scene_id}:{persp_id}",
                    "scene_id": scene_id,
                    "perspective_id": persp_id,
                    "scene_title": scene_title,
                    "perspective_title": str(persp.get("title") or "Untitled Perspective"),
                    "perspective_type": "psd",
                    "label": f"{scene_title} / {persp.get('title') or 'Untitled Perspective'}",
                    "source_file_path": source_rel,
                    "source_native_path": role_paths["source_psd"]["native_path"],
                    "preview_image_path": preview_rel,
                    "asset_paths": role_paths,
                    "index": index + 1,
                    "count": count,
                    "previous_key": f"scene2d:{scene_id}:{psd_perspectives[index - 1]['id']}" if index > 0 else "",
                    "next_key": f"scene2d:{scene_id}:{psd_perspectives[index + 1]['id']}" if index + 1 < count else "",
                })
        return items

    def _native_project_path(self, project, relative_path: str) -> str:
        rel = str(relative_path or "").strip()
        if not rel:
            return ""
        try:
            return str(project_manager.resolve_project_path(project, rel)).replace("\\", "/")
        except (OSError, ValueError):
            return ""

    def work_item_by_key(self, project, key: str) -> dict[str, Any] | None:
        key = str(key or "").strip()
        if not key:
            return None
        return next((item for item in self.work_items(project) if item.get("key") == key), None)

    def export_preview(
        self,
        shot_id: str,
        payload: dict[str, Any] | None = None,
        protocol: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        current = app_state._require_project(self.app)
        self._require_layout_protocol(current, protocol)
        project = app_state._refresh_project_from_disk(self.app)
        shot = app_state._find_shot(project, shot_id)
        if project.layout == LAYOUT_2:
            record = self._consume_write_intent(
                project,
                protocol,
                expected_work_key=f"shot:{shot_id}",
                expected_role="preview",
            )
            canonical = Path(
                self.asset_paths(project, f"shot:{shot_id}")["preview"]["native_path"]
            )
            if Path(record["target_path"]) != canonical:
                self._cleanup_intent_record(record)
                raise app_error(
                    AppErrorCode.PLUGIN_WRITE_INTENT_REJECTED,
                    "Plugin write intent target is no longer canonical.",
                    status=409,
                )
            inbox = Path(record["inbox_path"])
            if (
                not inbox.is_file()
                or inbox.is_symlink()
                or inbox.stat().st_size > _MAX_PLUGIN_IMAGE_BYTES
                or _file_header(inbox, 8) != b"\x89PNG\r\n\x1a\n"
            ):
                self._cleanup_intent_record(record)
                raise app_error(
                    AppErrorCode.PLUGIN_WRITE_INTENT_REJECTED,
                    "Plugin preview inbox file is missing or invalid.",
                    status=400,
                )
            canonical.parent.mkdir(parents=True, exist_ok=True)
            os.replace(inbox, canonical)
            shutil.rmtree(inbox.parents[1], ignore_errors=True)
            relative = project_manager.project_relative_posix(project, canonical)
            shot.image_path = relative
            shot.preview_image_path = relative
            app_state._autosave(self.app)
            runtime_state.mark_plugin_preview_exported(self.app, shot.shot_id)
            self.mark_project_changed()
            return {
                "shot": shot.to_dict(),
                "context": self.context(protocol),
            }
        data = payload if isinstance(payload, dict) else {}
        preview_rel = str(data.get("preview_image_path") or f"shots/{shot.shot_id}/{shot.shot_id}_preview.png")
        source_rel = str(data.get("source_file_path") or "").strip()
        if source_rel:
            try:
                source_path = project_manager.resolve_project_relative_path(project, source_rel, required_suffixes=(".psd",))
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            if not source_path.is_file():
                raise HTTPException(status_code=400, detail=f"PSD not found: {source_rel}")
            shot.source_file_path = project_manager.project_relative_posix(project, source_path)
            shot.source_sync_mtime = source_path.stat().st_mtime
        else:
            fallback_source = project_manager.resolve_project_child(
                project,
                "shots",
                shot.shot_id,
                f"{shot.shot_id}.psd",
            )
            if fallback_source.is_file():
                shot.source_file_path = project_manager.project_relative_posix(
                    project,
                    fallback_source,
                )
                shot.source_sync_mtime = fallback_source.stat().st_mtime
        try:
            project_manager.relink_preview_image(project, shot, preview_rel)
        except (ValueError, FileNotFoundError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        runtime_state.mark_plugin_preview_exported(self.app, shot.shot_id)
        app_state._autosave(self.app)
        self.mark_project_changed()
        return {
            "shot": self.shot_payload(project, shot),
            "context": self.context(),
        }

    def psd_saved(
        self,
        shot_id: str,
        payload: dict[str, Any] | None = None,
        protocol: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        current = app_state._require_project(self.app)
        self._require_layout_protocol(current, protocol)
        project = app_state._refresh_project_from_disk(self.app)
        shot = app_state._find_shot(project, shot_id)
        if project.layout == LAYOUT_2:
            record = self._consume_write_intent(
                project,
                protocol,
                expected_work_key=f"shot:{shot_id}",
                expected_role="source_psd",
            )
            canonical = Path(
                self.asset_paths(project, f"shot:{shot_id}")["source_psd"]["native_path"]
            )
            if Path(record["target_path"]) != canonical:
                raise app_error(
                    AppErrorCode.PLUGIN_WRITE_INTENT_REJECTED,
                    "Plugin write intent target is no longer canonical.",
                    status=409,
                )
            if (
                not canonical.is_file()
                or canonical.is_symlink()
                or canonical.stat().st_size < 4
                or _file_header(canonical, 4) != b"8BPS"
            ):
                raise app_error(
                    AppErrorCode.PLUGIN_WRITE_INTENT_REJECTED,
                    "Canonical Photoshop file is missing or invalid.",
                    status=400,
                )
            try:
                source_sha256 = _stable_sha256(canonical)
            except OSError as exc:
                raise app_error(
                    AppErrorCode.PLUGIN_WRITE_INTENT_REJECTED,
                    "Canonical Photoshop file changed during hash validation.",
                    status=409,
                ) from exc
            record["committed_sha256"] = source_sha256
            shot.source_file_path = project_manager.project_relative_posix(project, canonical)
            shot.source_sync_mtime = canonical.stat().st_mtime
            app_state._autosave(self.app)
            self.mark_project_changed()
            return {
                "shot": shot.to_dict(),
                "source_sha256": source_sha256,
                "context": self.context(protocol),
            }
        data = payload if isinstance(payload, dict) else {}
        source_rel = str(data.get("source_file_path") or shot.source_file_path or f"shots/{shot.shot_id}/{shot.shot_id}.psd")
        try:
            source_path = project_manager.resolve_project_relative_path(project, source_rel, required_suffixes=(".psd",))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not source_path.is_file():
            raise HTTPException(status_code=400, detail=f"PSD not found: {source_rel}")
        shot.source_file_path = project_manager.project_relative_posix(project, source_path)
        shot.source_sync_mtime = source_path.stat().st_mtime
        app_state._autosave(self.app)
        self.mark_project_changed()
        return {"shot": self.shot_payload(project, shot), "context": self.context()}

    def focus_shot(
        self,
        shot_id: str,
        protocol: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        self._require_mutation_protocol(project, protocol)
        app_state._find_shot(project, shot_id)
        runtime_state.set_plugin_and_live_selected_shot_id(self.app, shot_id)
        app_state._persist_app_session(self.app, selected_shot_id=shot_id)
        app_state._touch_live_bridge(self.app, selected_shot_id=shot_id)
        return self.context(protocol)

    def next_shot(
        self,
        current_shot_id: str | None = None,
        auto_add: bool = False,
        protocol: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        self._require_mutation_protocol(project, protocol)
        current = str(current_shot_id or runtime_state.plugin_selected_shot_id(self.app) or "").strip()
        index = app_state._find_shot_index(project, current) if current else -1
        created = None
        if index >= 0 and index + 1 < len(project.shots):
            next_shot = project.shots[index + 1]
        elif auto_add:
            next_shot = shot_service.create_shot(
                project,
                after_shot_id=project.shots[index].shot_id if index >= 0 else None,
            )
            created = next_shot
            app_state._autosave(self.app)
            self.mark_project_changed()
        else:
            return {"shot": None, "created": False, "context": self.context(protocol)}
        runtime_state.set_plugin_and_live_selected_shot_id(self.app, next_shot.shot_id)
        app_state._touch_live_bridge(self.app, selected_shot_id=next_shot.shot_id)
        return {
            "shot": self.shot_payload(project, next_shot),
            "created": created is not None,
            "context": self.context(protocol),
        }

    def shot_payload(self, project, shot: Shot) -> dict[str, Any]:
        data = app_state._shot_payload(project, shot)
        data.update(self.shot_health(project, shot))
        return data

    def shot_paths(self, project, shot: Shot | None) -> dict[str, str]:
        if shot is None:
            return {}
        if project.layout == LAYOUT_2:
            roles = self.asset_paths(project, f"shot:{shot.shot_id}")
            return {
                "psd": roles["source_psd"]["native_path"],
                "preview": roles["preview"]["native_path"],
                "thumbnail": roles["thumbnail"]["native_path"],
                "board_background": roles["board_background"]["native_path"],
            }
        preview = project_manager.resolve_shot_preview_path(project, shot)
        thumb = project_manager.resolve_shot_thumbnail_path(project, shot)
        background = project_manager.get_shot_board_background_path(project, shot)
        psd = self.shot_psd_path(project, shot)
        return {
            "psd": str(psd) if psd else str(
                project_manager.resolve_project_child(
                    project, "shots", shot.shot_id, f"{shot.shot_id}.psd"
                )
            ),
            "preview": str(preview) if preview else str(
                project_manager.resolve_project_child(
                    project, "shots", shot.shot_id, f"{shot.shot_id}_preview.png"
                )
            ),
            "thumbnail": str(thumb) if thumb else str(
                project_manager.resolve_project_child(
                    project, "shots", shot.shot_id, f"{shot.shot_id}_thumb.png"
                )
            ),
            "board_background": str(background) if background else str(
                project_manager.resolve_project_child(
                    project, "shots", shot.shot_id, f"{shot.shot_id}_background.png"
                )
            ),
        }

    def shot_psd_path(self, project, shot: Shot) -> Path | None:
        candidates: list[Path] = []
        if shot.source_file_path:
            candidates.append(
                project_manager.resolve_project_path(project, shot.source_file_path)
            )
        candidates.append(
            project_manager.resolve_project_child(
                project,
                "shots",
                shot.shot_id,
                f"{shot.shot_id}.psd",
            )
        )
        for candidate in candidates:
            if candidate.is_file():
                return candidate
        return None

    # ── Scene 2D plugin methods ───────────────────────────────────────────

    def scene2d_export_preview(
        self,
        scene_id: str,
        perspective_id: str,
        protocol: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Called after the plugin exports a Scene 2D preview PNG."""
        current = app_state._require_project(self.app)
        self._require_layout_protocol(current, protocol)
        project = app_state._refresh_project_from_disk(self.app)
        if project.layout == LAYOUT_2:
            self._consume_write_intent(
                project,
                protocol,
                expected_work_key=f"scene2d:{scene_id}:{perspective_id}",
                expected_role="preview",
            )
        try:
            sc, scenes = scene2d._find_scene(project, scene_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        try:
            perspective = scene2d._find_perspective(sc, perspective_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        if perspective.get("type") != "psd":
            raise HTTPException(status_code=400, detail="Perspective is not a PSD — export not allowed.")

        source_rel = str(perspective.get("source_file_path") or "")
        canonical_source_rel = scene2d._source_rel(scene_id, perspective_id)
        if source_rel != canonical_source_rel:
            raise HTTPException(status_code=400, detail="Perspective source path is not canonical.")
        source_path = project_manager.resolve_project_path(project, source_rel)
        if not source_path.is_file():
            raise HTTPException(status_code=400, detail=f"Source PSD not found: {source_rel}")

        preview_rel = perspective.get("preview_image_path", "")
        if not preview_rel:
            raise HTTPException(status_code=400, detail="Perspective has no preview_image_path.")
        canonical_preview_rel = scene2d._preview_rel(scene_id, perspective_id)
        if preview_rel != canonical_preview_rel:
            raise HTTPException(status_code=400, detail="Perspective preview path is not canonical.")

        try:
            preview_path = project_manager.resolve_project_path(project, preview_rel)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Preview path escapes project root.") from exc

        if not preview_path.is_file():
            raise HTTPException(status_code=400, detail="Exported preview PNG not found — did the plugin save it?")

        # Update timestamps atomically
        timestamp = scene2d._now_iso()
        perspective["updated_at"] = timestamp
        sc["updated_at"] = timestamp
        updated_scenes = scene2d._replace_scene(scenes, scene2d._with_legacy_aliases(sc))
        scene2d._save_scenes(project, updated_scenes)
        project_manager.sync_document(project)

        runtime_state.mark_scene2d_changed(self.app, scene_id, perspective_id)
        app_state._touch_live_bridge(self.app)

        work_ctx = runtime_state.active_work_context(self.app)
        return {
            "work_context": work_ctx,
            "scene": scene2d._with_legacy_aliases(sc),
            "perspective": perspective,
            "preview_image_path": preview_rel,
        }

    def scene2d_psd_saved(
        self,
        scene_id: str,
        perspective_id: str,
        protocol: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Called when the artist saves the Scene 2D PSD (Ctrl+S in Photoshop)."""
        current = app_state._require_project(self.app)
        self._require_layout_protocol(current, protocol)
        project = app_state._refresh_project_from_disk(self.app)
        if project.layout == LAYOUT_2:
            self._consume_write_intent(
                project,
                protocol,
                expected_work_key=f"scene2d:{scene_id}:{perspective_id}",
                expected_role="source_psd",
            )
        try:
            sc, scenes = scene2d._find_scene(project, scene_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        try:
            perspective = scene2d._find_perspective(sc, perspective_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        source_path = project_manager.resolve_project_path(
            project,
            perspective["source_file_path"],
        )
        if not source_path.is_file():
            raise HTTPException(status_code=400, detail=f"Source PSD not found: {perspective['source_file_path']}")

        timestamp = scene2d._now_iso()
        perspective["updated_at"] = timestamp
        sc["updated_at"] = timestamp
        updated_scenes = scene2d._replace_scene(scenes, scene2d._with_legacy_aliases(sc))
        scene2d._save_scenes(project, updated_scenes)
        project_manager.sync_document(project)

        work_ctx = runtime_state.active_work_context(self.app)
        return {"work_context": work_ctx, "scene": scene2d._with_legacy_aliases(sc), "perspective": perspective}

    def scene2d_next_perspective(
        self,
        scene_id: str,
        perspective_id: str,
        protocol: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return the next PSD Perspective in the same Scene group."""
        current = app_state._require_project(self.app)
        self._require_mutation_protocol(current, protocol)
        project = app_state._refresh_project_from_disk(self.app)
        try:
            sc, _scenes = scene2d._find_scene(project, scene_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        psd_perspectives = [p for p in (sc.get("perspectives") or []) if p.get("type") == "psd"]
        index = next((i for i, p in enumerate(psd_perspectives) if p.get("id") == perspective_id), -1)
        if index < 0:
            raise HTTPException(status_code=404, detail="Perspective not found in scene.")

        if index >= len(psd_perspectives) - 1:
            return {"next_perspective": None, "at_end": True}

        next_persp = psd_perspectives[index + 1]
        return {"next_perspective": next_persp, "scene": scene2d._with_legacy_aliases(sc), "at_end": False}

    def shot_health(self, project, shot: Shot) -> dict[str, Any]:
        psd = self.shot_psd_path(project, shot)
        preview = project_manager.resolve_shot_preview_path(project, shot)
        thumb = project_manager.resolve_shot_thumbnail_path(project, shot)
        background = project_manager.get_shot_board_background_path(project, shot)
        try:
            source_missing = bool(shot.source_file_path) and not project_manager.resolve_project_path(
                project,
                shot.source_file_path,
            ).is_file()
        except ValueError:
            source_missing = bool(shot.source_file_path)
        psd_size = psd.stat().st_size if psd and psd.is_file() else 0
        psd_mtime = psd.stat().st_mtime if psd and psd.is_file() else 0.0
        preview_mtime = preview.stat().st_mtime if preview and preview.is_file() else 0.0
        last_exported = runtime_state.plugin_last_exported_preview(self.app)
        return {
            "psd_exists": bool(psd and psd.is_file()),
            "preview_exists": bool(preview and preview.is_file()),
            "thumbnail_exists": bool(thumb and thumb.is_file()),
            "source_path_missing": source_missing,
            "preview_out_of_date": bool(psd_mtime and (not preview_mtime or preview_mtime + 1.0 < psd_mtime)),
            "broken_or_zero_byte_psd": bool(psd and psd.is_file() and psd_size < 26),
            "last_exported_preview_time": last_exported.get(shot.shot_id),
            "paths": self.shot_paths(project, shot),
            "ref_video_path": shot.ref_video_path,
            "ref_video_time": shot.ref_video_time,
            "ref_segment_time": shot.ref_segment_time,
        }
