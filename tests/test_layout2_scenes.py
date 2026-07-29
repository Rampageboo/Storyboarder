from __future__ import annotations

import copy
import hashlib
import io
import json
import uuid
import subprocess
from pathlib import Path

import pytest
from fastapi import HTTPException

from storyboard_tool import (
    app_state,
    blender_bridge,
    external_tools,
    file_transactions,
    project_document,
    project_layout,
    project_manager,
    reference_segments,
    scene2d,
    system_utils,
    scene3d,
)
from storyboard_tool.api import create_app
from storyboard_tool.backend_service import StoryboardBackendService
from storyboard_tool.bpy_viewport import (
    BpyViewportError,
    BpyViewportManager,
    project_blend_path,
)
from storyboard_tool.models import Project
from storyboard_tool.plugin_service import (
    EXPLICIT_ASSET_PATHS_CAPABILITY,
    PLUGIN_PROTOCOL_VERSION,
    PluginBridgeService,
)


def _project(tmp_path: Path) -> Project:
    root = tmp_path / "Portable"
    work = root / ".storyboarder" / "work"
    work.mkdir(parents=True)
    project = Project(
        root_path=work,
        project_root_path=root,
        document_path=root / "Portable.sbd",
        layout=2,
        project_id=str(uuid.uuid4()),
        storage_revision=12,
        settings=dict(project_manager.DEFAULT_SETTINGS),
    )

    scene3d.initialize_layout2_metadata(project)
    scene2d.initialize_layout2_metadata(project)
    return project


def _v2_protocol(
    app,
    project: Project,
    *,
    work_key: str = "",
    asset_role: str = "",
    token: str = "",
) -> dict[str, object]:
    return {
        "version": PLUGIN_PROTOCOL_VERSION,
        "capabilities": [EXPLICIT_ASSET_PATHS_CAPABILITY],
        "project_session_id": app.state.project_session_id,
        "context_revision": project.storage_revision,
        "work_key": work_key,
        "asset_role": asset_role,
        "write_intent": token,
    }


def test_layout2_scene2d_assets_are_flat_and_metadata_stays_in_work(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)

    scene, _scenes = scene2d.create_scene(project, "Board")
    perspective = scene["perspectives"][0]

    assert perspective["source_file_path"] == (
        f"PSD/Scene2D/{perspective['id']}.psd"
    )
    assert perspective["preview_image_path"] == (
        f"Images/Scene2D/{perspective['id']}_preview.png"
    )
    assert (project.project_root / perspective["source_file_path"]).is_file()
    assert (project.metadata_root / "scenes2d" / "scenes2d.json").is_file()
    assert (
        project.metadata_root
        / "scenes2d"
        / scene["id"]
        / f"{scene['id']}_meta.json"
    ).is_file()
    assert not (project.project_root / "scenes2d").exists()


def test_layout2_scene2d_import_and_duplicate_use_exact_uuid_paths(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    scene, _scenes = scene2d.create_scene(project, "Board")
    scene, imported, _scenes = scene2d.import_perspective(
        project,
        scene["id"],
        "reference.webp",
        b"webp-data",
    )

    assert imported["source_file_path"] == f"Images/Scene2D/{imported['id']}.webp"
    assert imported["preview_image_path"] == imported["source_file_path"]
    scene, duplicate, _scenes = scene2d.duplicate_perspective(
        project, scene["id"], imported["id"]
    )

    assert duplicate["source_file_path"] == (
        f"Images/Scene2D/{duplicate['id']}.webp"
    )
    assert (project.project_root / duplicate["source_file_path"]).read_bytes() == b"webp-data"
    assert not (project.project_root / "Images" / "Scene2D" / scene["id"]).exists()


def test_layout2_scene2d_move_is_metadata_only_and_preserves_paths(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    source, _scenes = scene2d.create_scene(project, "Source")
    target, _scenes = scene2d.create_scene(project, "Target")
    perspective = source["perspectives"][0]
    source_path = project.project_root / perspective["source_file_path"]
    before = source_path.read_bytes()
    original_source_rel = perspective["source_file_path"]
    original_preview_rel = perspective["preview_image_path"]
    preview_path = project.project_root / original_preview_rel
    preview_path.parent.mkdir(parents=True, exist_ok=True)
    preview_path.write_bytes(b"preview")
    reference, _scenes = scene2d.add_perspective_to_references(
        project, source["id"], perspective["id"]
    )

    _source, moved_target, moved, _scenes = scene2d.move_perspective(
        project, source["id"], perspective["id"], target["id"]
    )

    assert moved["source_file_path"] == original_source_rel
    assert moved["preview_image_path"] == original_preview_rel
    assert source_path.read_bytes() == before
    assert perspective["id"] in {
        item["id"] for item in moved_target["perspectives"]
    }
    moved_reference = next(
        item
        for item in project.settings["reference_links"]
        if item["id"] == reference["id"]
    )
    assert moved_reference["source_scene2d_id"] == target["id"]
    assert moved_reference["path"] == original_preview_rel


def test_layout2_scene2d_move_failure_restores_metadata_without_touching_assets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path)
    source, _scenes = scene2d.create_scene(project, "Source")
    target, _scenes = scene2d.create_scene(project, "Target")
    perspective = source["perspectives"][0]
    asset = project.project_root / perspective["source_file_path"]
    before_asset = asset.read_bytes()
    project_manager.save_settings(project)
    paths = (
        project.metadata_root / "scenes2d" / "scenes2d.json",
        project.metadata_root
        / "scenes2d"
        / source["id"]
        / f"{source['id']}_meta.json",
        project.metadata_root
        / "scenes2d"
        / target["id"]
        / f"{target['id']}_meta.json",
        project.settings_path,
    )
    before_metadata = {path: path.read_bytes() for path in paths}

    monkeypatch.setattr(
        scene2d,
        "_save_scenes",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            OSError("injected metadata failure")
        ),
    )
    with pytest.raises(OSError, match="injected"):
        scene2d.move_perspective(
            project, source["id"], perspective["id"], target["id"]
        )

    assert asset.read_bytes() == before_asset
    assert {path: path.read_bytes() for path in paths} == before_metadata
    assert perspective["source_file_path"].startswith("PSD/Scene2D/")
    assert not (
        project.metadata_root / "scenes2d" / scene2d.PERSPECTIVE_MOVE_ROOT
    ).exists()


def test_layout2_scene2d_valid_stored_paths_are_not_rebound(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    scene, _scenes = scene2d.create_scene(project, "Stored")
    custom = "PSD/Scene2D/user-preserved.psd"
    custom_path = project.project_root / custom
    custom_path.write_bytes(b"custom")
    scene["perspectives"][0]["source_file_path"] = custom
    scene2d._save_scenes(project, [scene])

    reloaded = scene2d.list_scenes(project)

    assert reloaded[0]["perspectives"][0]["source_file_path"] == custom
    paths = PluginBridgeService(create_app(tmp_path)).asset_paths(
        project,
        f"scene2d:{scene['id']}:{scene['perspectives'][0]['id']}",
    )
    assert paths["source_psd"]["project_relative_path"] == custom
    assert custom_path.read_bytes() == b"custom"
    custom_path.unlink()
    with pytest.raises(FileNotFoundError, match="user-preserved"):
        scene2d._ensure_perspective_source(
            project, reloaded[0]["perspectives"][0]
        )
    assert not custom_path.exists()


def test_layout2_scene3d_paths_and_blend_creation_are_lazy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path)
    created = scene3d.create_scene(project, title="Stage")["scene"]
    blend_path = project.project_root / "Blender" / f"{created['id']}.blend"

    assert not blend_path.exists()
    assert (project.metadata_root / "scenes3d" / "scenes3d.json").is_file()
    imported = scene3d.import_scene_file(
        project, created["id"], "stage.glb", b"glb"
    )["scene"]
    assert imported["file_path"] == f"Blender/{created['id']}.glb"
    assert (project.project_root / imported["file_path"]).read_bytes() == b"glb"
    assert not (project.project_root / "scenes3d").exists()

    template = tmp_path / "template.blend"
    template.write_bytes(b"blend-template")
    monkeypatch.setattr(external_tools, "BLEND_TEMPLATE_PATH", template)
    created_blend = external_tools.ensure_project_blend_file(
        project, scene_id=created["id"]
    )
    configured = scene3d.configure_blend_preview(
        project, created["id"], created_blend
    )

    assert created_blend == blend_path
    assert created_blend.read_bytes() == b"blend-template"
    assert configured["blend_file_path"] == f"Blender/{created['id']}.blend"
    assert configured["file_path"] == (
        f".storyboarder/cache/scene3d/{created['id']}/storyboarder_preview.glb"
    )


def test_layout2_blender_references_use_portable_double_slash_paths(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    scene = scene3d.create_scene(project, title="Stage")["scene"]
    blend = project.project_root / "Blender" / f"{scene['id']}.blend"
    blend.parent.mkdir(parents=True)
    blend.write_bytes(b"blend")
    reference = reference_segments.import_project_reference_stream(
        project, io.BytesIO(b"glb-reference"), "prop.glb"
    )
    asset = project.project_root / reference["path"]

    assert reference["path"].startswith("Blender/References/")
    assert external_tools.blender_portable_reference(project, blend, asset) == (
        f"//References/{asset.name}"
    )


def test_layout2_external_blender_rejects_stale_writer_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path)
    scene = scene3d.create_scene(project, title="Stage")["scene"]
    blend = project.project_root / "Blender" / f"{scene['id']}.blend"
    blend.parent.mkdir(parents=True)
    blend.write_bytes(b"blend")
    scene = scene3d.configure_blend_preview(project, scene["id"], blend)
    bridge_path = tmp_path / "bridge.json"
    heartbeat_path = tmp_path / "heartbeat.json"
    monkeypatch.setattr(blender_bridge, "bridge_file_path", lambda: bridge_path)
    monkeypatch.setattr(blender_bridge, "heartbeat_file_path", lambda: heartbeat_path)
    app = create_app(tmp_path)
    app.state.project = project

    session = blender_bridge.begin_session(app, project, scene, blend)
    launch = Path(session["launch_path"])
    assert launch != blend
    assert launch.parent == blend.parent
    assert launch.read_bytes() == blend.read_bytes()
    context = json.loads(bridge_path.read_text(encoding="utf-8"))
    assert context["version"] == 2
    assert context["path_mode"] == "explicit-assets"
    assert context["offline_write_allowed"] is False
    assert context["write_enabled"] is True
    assert context["project_session_id"] == app.state.project_session_id
    assert context["context_revision"] == project.storage_revision
    assert context["blend_path"] == str(launch)
    assert context["canonical_blend_path"] == str(blend.resolve())

    blender_bridge._write_json(
        heartbeat_path,
        {"session_id": session["session_id"], "blend_path": str(blend.resolve())},
    )
    heartbeat, _age = blender_bridge._validated_heartbeat(app, project)
    assert heartbeat == {}

    blender_bridge._write_json(
        heartbeat_path,
        {
            "session_id": session["session_id"],
            "project_session_id": app.state.project_session_id,
            "context_revision": project.storage_revision,
            "blend_path": str(launch),
        },
    )
    heartbeat, _age = blender_bridge._validated_heartbeat(app, project)
    assert heartbeat["session_id"] == session["session_id"]

    project.storage_revision += 1
    heartbeat_path.write_text(
        json.dumps(heartbeat),
        encoding="utf-8",
    )
    rejected, _age = blender_bridge._validated_heartbeat(app, project)
    assert rejected == {}


def test_layout2_external_blender_brokers_only_save_authorized_session_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(project_layout, "LAYOUT_2_ENABLED", True)
    project = _project(tmp_path)
    project.settings["backup_on_save"] = False
    scene = scene3d.create_scene(project, title="Brokered")["scene"]
    canonical = project.project_root / "Blender" / f"{scene['id']}.blend"
    canonical.parent.mkdir(parents=True)
    canonical.write_bytes(b"canonical-v1")
    scene = scene3d.configure_blend_preview(
        project, scene["id"], canonical
    )
    project_manager.save_project(project, flush_document=False)
    project_document.commit_layout2_document(project.project_root)

    bridge_path = tmp_path / "broker-bridge.json"
    heartbeat_path = tmp_path / "broker-heartbeat.json"
    monkeypatch.setattr(blender_bridge, "bridge_file_path", lambda: bridge_path)
    monkeypatch.setattr(blender_bridge, "heartbeat_file_path", lambda: heartbeat_path)
    app_root = tmp_path / "broker-app"
    app_root.mkdir()
    app = create_app(app_root)
    app.state.project = project
    session = blender_bridge.begin_session(app, project, scene, canonical)
    working = Path(session["launch_path"])
    before_revision = project.storage_revision

    working.write_bytes(b"authorized-v2")
    blender_bridge._write_json(
        heartbeat_path,
        {
            "session_id": session["session_id"],
            "project_session_id": app.state.project_session_id,
            "context_revision": before_revision,
            "blend_path": str(working),
            "dirty": False,
            "saved_mtime_ns": working.stat().st_mtime_ns,
            "save_authorized": True,
        },
    )

    status = blender_bridge.status(app)

    assert status["external_blender_canonical_path"] == str(canonical)
    assert canonical.read_bytes() == b"authorized-v2"
    assert project.storage_revision == before_revision + 1
    renewed = json.loads(bridge_path.read_text(encoding="utf-8"))
    assert renewed["context_revision"] == project.storage_revision
    assert renewed["write_enabled"] is True

    canonical_before_stale = canonical.read_bytes()
    working.write_bytes(b"offline-stale-v3")
    renewed["lease_expires_at"] = 0.0
    blender_bridge._write_json(bridge_path, renewed)
    blender_bridge._write_json(
        heartbeat_path,
        {
            "session_id": session["session_id"],
            "project_session_id": app.state.project_session_id,
            "context_revision": project.storage_revision,
            "blend_path": str(working),
            "dirty": False,
            "saved_mtime_ns": working.stat().st_mtime_ns,
            "save_authorized": False,
        },
    )

    stale_status = blender_bridge.status(app, refresh_context=False)

    assert stale_status["external_blender_connected"] is False
    assert canonical.read_bytes() == canonical_before_stale
    assert project.storage_revision == before_revision + 1


def test_layout2_real_blender_native_save_cannot_bypass_broker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidates = system_utils.detect_blender_paths()
    if not candidates:
        pytest.skip("Blender executable is unavailable for native-save integration.")
    blender = Path(candidates[0])
    template = Path(external_tools.BLEND_TEMPLATE_PATH)
    if not template.is_file():
        pytest.skip("Storyboarder Blender template is unavailable.")

    monkeypatch.setattr(project_layout, "LAYOUT_2_ENABLED", True)
    project = _project(tmp_path)
    project.settings["backup_on_save"] = False
    scene = scene3d.create_scene(project, title="Real Blender")["scene"]
    canonical = project.project_root / "Blender" / f"{scene['id']}.blend"
    canonical.parent.mkdir(parents=True)
    file_transactions.atomic_copy_file(template, canonical)
    scene = scene3d.configure_blend_preview(project, scene["id"], canonical)
    project_manager.save_project(project, flush_document=False)
    project_document.commit_layout2_document(project.project_root)

    bridge_path = tmp_path / "real-blender-bridge.json"
    heartbeat_path = tmp_path / "real-blender-heartbeat.json"
    monkeypatch.setattr(blender_bridge, "bridge_file_path", lambda: bridge_path)
    monkeypatch.setattr(blender_bridge, "heartbeat_file_path", lambda: heartbeat_path)
    app_root = tmp_path / "real-blender-app"
    app_root.mkdir()
    app = create_app(app_root)
    app.state.project = project
    session = blender_bridge.begin_session(app, project, scene, canonical)
    working = Path(session["launch_path"])
    bootstrap = (
        Path(__file__).parents[1]
        / "storyboard_tool"
        / "blender_addon"
        / "register_storyboarder_addon.py"
    )

    def native_save(marker: str) -> subprocess.CompletedProcess[str]:
        expression = (
            "import bpy, storyboarder_bridge; "
            f"bpy.context.scene['storyboarder_test_marker']={marker!r}; "
            "bpy.ops.wm.save_as_mainfile(filepath=bpy.data.filepath); "
            "storyboarder_bridge._heartbeat()"
        )
        return subprocess.run(
            [
                str(blender),
                "--background",
                str(working),
                "--python",
                str(bootstrap),
                "--python-expr",
                expression,
                "--",
                "--storyboarder-bridge",
                str(bridge_path),
                "--storyboarder-heartbeat",
                str(heartbeat_path),
                "--storyboarder-session",
                str(session["session_id"]),
            ],
            cwd=Path(__file__).parents[1],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=90,
            check=False,
        )

    canonical_before = canonical.read_bytes()
    authorized = native_save("authorized")
    assert authorized.returncode == 0, authorized.stdout + authorized.stderr
    authorized_heartbeat = json.loads(
        heartbeat_path.read_text(encoding="utf-8")
    )
    assert authorized_heartbeat["save_authorized"] is True
    assert authorized_heartbeat["blend_path"] == str(working.resolve())

    blender_bridge.status(app)

    canonical_after_authorized = canonical.read_bytes()
    assert canonical_after_authorized != canonical_before
    authorized_revision = project.storage_revision

    stale_context = json.loads(bridge_path.read_text(encoding="utf-8"))
    stale_context["lease_expires_at"] = 0.0
    blender_bridge._write_json(bridge_path, stale_context)
    stale = native_save("stale-offline")
    assert stale.returncode == 0, stale.stdout + stale.stderr
    stale_heartbeat = json.loads(heartbeat_path.read_text(encoding="utf-8"))
    assert stale_heartbeat["save_authorized"] is False
    assert working.read_bytes() != canonical_after_authorized

    blender_bridge.status(app, refresh_context=False)

    assert canonical.read_bytes() == canonical_after_authorized
    assert project.storage_revision == authorized_revision


def test_layout2_builtin_blender_rejects_stale_writer_context(tmp_path: Path) -> None:
    project = _project(tmp_path)
    app = create_app(tmp_path)
    manager = BpyViewportManager()
    manager.bind_context(
        project,
        project_session_id=app.state.project_session_id,
        context_revision=project.storage_revision,
    )
    manager.require_context(
        project,
        project_session_id=app.state.project_session_id,
        context_revision=project.storage_revision,
    )

    with pytest.raises(BpyViewportError, match="stale"):
        manager.require_context(
            project,
            project_session_id=app.state.project_session_id,
            context_revision=project.storage_revision + 1,
        )


def test_layout2_builtin_blender_uses_valid_persisted_path(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    scene = scene3d.create_scene(project, title="Stage")["scene"]
    stale = project.project_root / "Blender" / "stale.blend"
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_bytes(b"stale")
    scene["blend_file_path"] = "Blender/stale.blend"
    scene3d._save(project, scene["id"], [scene])

    configured = scene3d.configure_blend_preview(project, scene["id"], stale)
    assert configured["blend_file_path"] == "Blender/stale.blend"
    assert project_blend_path(project) == stale.resolve()


def test_blender_addon_guards_explicit_asset_writes() -> None:
    source = (
        Path(__file__).parents[1]
        / "storyboard_tool"
        / "blender_addon"
        / "storyboarder_bridge.py"
    ).read_text(encoding="utf-8")

    assert "def _context_allows_write" in source
    assert 'CONTEXT.get("offline_write_allowed") is False' in source
    assert 'CONTEXT.get("write_enabled") is True' in source
    assert '"project_session_id"' in source
    assert '"context_revision"' in source
    assert 'CONTEXT.get("lease_expires_at")' in source
    assert "def _on_save_pre" in source
    assert "bpy.app.handlers.save_pre.append(_on_save_pre)" in source


def _tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_layout2_scene_mutation_advances_once_and_invalidates_blender_lease(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(project_layout, "LAYOUT_2_ENABLED", True)
    project = _project(tmp_path)
    project.settings["backup_on_save"] = False
    scene = scene3d.create_scene(project, title="Leased")["scene"]
    blend = project.project_root / "Blender" / "preserved-name.blend"
    blend.parent.mkdir(parents=True, exist_ok=True)
    blend.write_bytes(b"blend")
    scene["blend_file_path"] = "Blender/preserved-name.blend"
    scene3d._save(project, scene["id"], [scene])
    project_manager.save_project(project, flush_document=False)
    project_document.commit_layout2_document(project.project_root)

    bridge_path = tmp_path / "bridge.json"
    heartbeat_path = tmp_path / "heartbeat.json"
    monkeypatch.setattr(blender_bridge, "bridge_file_path", lambda: bridge_path)
    monkeypatch.setattr(blender_bridge, "heartbeat_file_path", lambda: heartbeat_path)
    app_root = tmp_path / "app"
    app_root.mkdir()
    app = create_app(app_root)
    app.state.project = project
    service = StoryboardBackendService(app)
    before = project.storage_revision
    blender_bridge.begin_session(app, project, scene, blend)

    service.method_update_scene3d(scene["id"], {"title": "Revision changed"})

    assert project.storage_revision == before + 1
    manifest = project_manager.parse_project_manifest(
        json.loads(project.json_path.read_text(encoding="utf-8"))
    )
    assert manifest.storage_revision == before + 1
    state = json.loads(
        (project.project_root / ".storyboarder" / "state.json").read_text(
            encoding="utf-8"
        )
    )
    assert state["global_revision"] == before + 1
    assert state["committed_revision"] == before
    assert project_document.validate_layout2_document(project.document_path).revision == before
    context = json.loads(bridge_path.read_text(encoding="utf-8"))
    assert context["write_enabled"] is False
    assert context["lease_expires_at"] > context["updated_at"]

    project_manager.sync_document(project)

    assert project_document.validate_layout2_document(project.document_path).revision == before + 1
    assert not (project.metadata_root / "shots.csv").exists()
    blender_bridge.cancel_session(app)
    cancelled = json.loads(bridge_path.read_text(encoding="utf-8"))
    assert cancelled["write_enabled"] is False
    assert cancelled["session_id"] == ""
    assert cancelled["lease_expires_at"] == 0.0


@pytest.mark.parametrize("fault_file", ["project.json", "state.json"])
@pytest.mark.parametrize("fault_timing", ["before", "after"])
def test_layout2_scene_mutation_rolls_back_split_revision_faults(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault_file: str,
    fault_timing: str,
) -> None:
    monkeypatch.setattr(project_layout, "LAYOUT_2_ENABLED", True)
    project = _project(tmp_path)
    project.settings["backup_on_save"] = False
    scene = scene3d.create_scene(project, title="Before fault")["scene"]
    project_manager.save_project(project, flush_document=False)
    project_document.commit_layout2_document(project.project_root)
    app_root = tmp_path / f"fault-app-{fault_file}-{fault_timing}"
    app_root.mkdir()
    app = create_app(app_root)
    app.state.project = project
    app.state.project_disk_mtime = project_manager.project_disk_mtime(project)
    app.state.dirty = False
    service = StoryboardBackendService(app)
    before_tree = _tree_bytes(project.project_root)
    before_revision = project.storage_revision
    before_disk_mtime = app.state.project_disk_mtime
    real_write = project_document._atomic_write_json

    def fail_revision_write(path, payload):
        target = Path(path)
        is_target = (
            target.name == fault_file
            and (
                fault_file == "state.json"
                or target.parent == project.metadata_root
            )
        )
        if not is_target:
            return real_write(path, payload)
        if fault_timing == "after":
            real_write(path, payload)
        raise OSError(f"injected {fault_file} {fault_timing} write fault")

    monkeypatch.setattr(
        project_document, "_atomic_write_json", fail_revision_write
    )

    with pytest.raises(OSError, match="injected"):
        service.method_update_scene3d(
            scene["id"], {"title": "Must roll back"}
        )

    assert project.storage_revision == before_revision
    assert app.state.dirty is False
    assert app.state.project_disk_mtime == before_disk_mtime
    assert _tree_bytes(project.project_root) == before_tree
    restored = next(
        item
        for item in scene3d.list_scenes(project)["scenes"]
        if item["id"] == scene["id"]
    )
    assert restored["title"] == "Before fault"
    transactions = project.project_root / ".storyboarder" / "transactions"
    assert not transactions.exists() or not any(
        path.name.startswith("mutation-") for path in transactions.iterdir()
    )


def test_layout2_scene2d_open_uses_persisted_psd_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project(tmp_path)
    scene, _scenes = scene2d.create_scene(project, "Stored path")
    perspective = scene["perspectives"][0]
    custom_relative = "PSD/Scene2D/user-preserved.psd"
    custom = project.project_root / custom_relative
    custom.write_bytes(b"custom")
    perspective["source_file_path"] = custom_relative
    scene2d._save_scenes(project, [scene])
    app_root = tmp_path / "app-open"
    app_root.mkdir()
    app = create_app(app_root)
    app.state.project = project
    work_key = f"scene2d:{scene['id']}:{perspective['id']}"
    monkeypatch.setattr(
        app_state,
        "plugin_work_key_state",
        lambda _app: (work_key, {work_key}),
    )
    monkeypatch.setattr(app_state, "_touch_live_bridge", lambda *_args, **_kwargs: {})

    payload = StoryboardBackendService(app).method_open_scene2d_perspective(
        scene["id"], perspective["id"]
    )

    assert payload["relative_path"] == custom_relative
    custom.unlink()
    with pytest.raises(HTTPException, match="Source PSD not found"):
        StoryboardBackendService(app).method_open_scene2d_perspective(
            scene["id"], perspective["id"]
        )
    assert not custom.exists()


def test_layout2_scene2d_plugin_ingests_preview_and_validates_psd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(project_layout, "LAYOUT_2_ENABLED", True)
    project = _project(tmp_path)
    project.settings["backup_on_save"] = False
    scene, _scenes = scene2d.create_scene(project, "Plugin")
    perspective = scene["perspectives"][0]
    project_manager.save_project(project, flush_document=False)
    project_document.commit_layout2_document(project.project_root)

    app_root = tmp_path / "plugin-app"
    app_root.mkdir()
    app = create_app(app_root)
    app.state.project = project
    app.state.project_disk_mtime = project_manager.project_disk_mtime(project)
    service = StoryboardBackendService(app)
    plugin = PluginBridgeService(app)
    work_key = f"scene2d:{scene['id']}:{perspective['id']}"
    canonical_preview = project_manager.resolve_project_path(
        project, perspective["preview_image_path"]
    )
    canonical_preview.parent.mkdir(parents=True, exist_ok=True)
    canonical_preview.write_bytes(b"stale-preview")
    issued = plugin.issue_write_intent(
        work_key,
        "preview",
        _v2_protocol(app, project),
    )
    inbox = Path(issued["write_path"])
    preview_bytes = b"\x89PNG\r\n\x1a\nnew-scene2d-preview"
    inbox.write_bytes(preview_bytes)
    before_preview_revision = project.storage_revision

    preview_result = service.method_plugin_scene2d_export_preview(
        scene["id"],
        perspective["id"],
        _v2_protocol(
            app,
            project,
            work_key=work_key,
            asset_role="preview",
            token=str(issued["token"]),
        ),
    )

    assert canonical_preview.read_bytes() == preview_bytes
    assert not inbox.parent.parent.exists()
    assert preview_result["preview_sha256"] == hashlib.sha256(
        preview_bytes
    ).hexdigest()
    assert project.storage_revision == before_preview_revision + 1

    source = project_manager.resolve_project_path(
        project, perspective["source_file_path"]
    )
    source.write_bytes(b"invalid-psd")
    rejected_intent = plugin.issue_write_intent(
        work_key,
        "source_psd",
        _v2_protocol(app, project),
    )
    with pytest.raises(HTTPException, match="missing or invalid"):
        service.method_plugin_scene2d_psd_saved(
            scene["id"],
            perspective["id"],
            _v2_protocol(
                app,
                project,
                work_key=work_key,
                asset_role="source_psd",
                token=str(rejected_intent["token"]),
            ),
        )
    revision_after_rejection = project.storage_revision
    source_bytes = b"8BPSvalidated-scene2d-source"
    source.write_bytes(source_bytes)
    accepted_intent = plugin.issue_write_intent(
        work_key,
        "source_psd",
        _v2_protocol(app, project),
    )

    source_result = service.method_plugin_scene2d_psd_saved(
        scene["id"],
        perspective["id"],
        _v2_protocol(
            app,
            project,
            work_key=work_key,
            asset_role="source_psd",
            token=str(accepted_intent["token"]),
        ),
    )

    assert source_result["source_sha256"] == hashlib.sha256(source_bytes).hexdigest()
    assert project.storage_revision == revision_after_rejection + 1


@pytest.mark.parametrize("fault_stage", ["metadata", "settings", "rename"])
def test_layout2_scene2d_delete_rolls_back_every_fault(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault_stage: str,
) -> None:
    project = _project(tmp_path)
    scene, _scenes = scene2d.create_scene(project, "Delete rollback")
    perspective = scene["perspectives"][0]
    preview = project.project_root / perspective["preview_image_path"]
    preview.parent.mkdir(parents=True, exist_ok=True)
    preview.write_bytes(b"preview")
    scene2d.add_perspective_to_references(
        project, scene["id"], perspective["id"]
    )
    before_files = _tree_bytes(project.project_root)
    before_settings = copy.deepcopy(project.settings)

    if fault_stage == "metadata":
        monkeypatch.setattr(
            scene2d,
            "_save_scenes",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                OSError("injected Scene2D metadata fault")
            ),
        )
    elif fault_stage == "settings":
        monkeypatch.setattr(
            project_manager,
            "save_settings",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                OSError("injected Scene2D settings fault")
            ),
        )
    else:
        real_replace = file_transactions.os.replace
        move_count = 0

        def fail_second_quarantine_move(source, destination):
            nonlocal move_count
            destination_path = Path(destination)
            if "transactions" in destination_path.parts:
                move_count += 1
                if move_count == 2:
                    raise OSError("injected Scene2D rename fault")
            return real_replace(source, destination)

        monkeypatch.setattr(file_transactions.os, "replace", fail_second_quarantine_move)

    with pytest.raises(OSError, match="injected Scene2D"):
        scene2d.delete_perspective(project, scene["id"], perspective["id"])

    assert _tree_bytes(project.project_root) == before_files
    assert project.settings == before_settings
    transactions = project.project_root / ".storyboarder" / "transactions"
    assert not transactions.exists() or not any(transactions.rglob("*"))


@pytest.mark.parametrize("fault_stage", ["metadata", "settings", "rename"])
def test_layout2_whole_scene2d_delete_rolls_back_every_fault(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault_stage: str,
) -> None:
    project = _project(tmp_path)
    scene, _scenes = scene2d.create_scene(project, "Whole delete rollback")
    perspective = scene["perspectives"][0]
    preview = project.project_root / perspective["preview_image_path"]
    preview.parent.mkdir(parents=True, exist_ok=True)
    preview.write_bytes(b"preview")
    scene2d.add_perspective_to_references(
        project, scene["id"], perspective["id"]
    )
    before_files = _tree_bytes(project.project_root)
    before_settings = copy.deepcopy(project.settings)

    if fault_stage == "metadata":
        monkeypatch.setattr(
            scene2d,
            "_save_scenes",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                OSError("injected whole Scene2D metadata fault")
            ),
        )
    elif fault_stage == "settings":
        monkeypatch.setattr(
            project_manager,
            "save_settings",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                OSError("injected whole Scene2D settings fault")
            ),
        )
    else:
        real_replace = file_transactions.os.replace
        move_count = 0

        def fail_second_quarantine_move(source, destination):
            nonlocal move_count
            destination_path = Path(destination)
            if "transactions" in destination_path.parts:
                move_count += 1
                if move_count == 2:
                    raise OSError("injected whole Scene2D rename fault")
            return real_replace(source, destination)

        monkeypatch.setattr(
            file_transactions.os, "replace", fail_second_quarantine_move
        )

    with pytest.raises(OSError, match="injected whole Scene2D"):
        scene2d.delete_scene(project, scene["id"])

    assert _tree_bytes(project.project_root) == before_files
    assert project.settings == before_settings
    assert scene["id"] in {item["id"] for item in scene2d.list_scenes(project)}
    transactions = project.project_root / ".storyboarder" / "transactions"
    assert not transactions.exists() or not any(transactions.rglob("*"))


@pytest.mark.parametrize("fault_stage", ["metadata", "settings", "rename"])
def test_layout2_scene3d_delete_rolls_back_every_fault(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault_stage: str,
) -> None:
    project = _project(tmp_path)
    target = scene3d.create_scene(project, title="Delete target")["scene"]
    scene3d.create_scene(project, title="Survivor")
    target = scene3d.import_scene_file(
        project, target["id"], "target.glb", b"glb"
    )["scene"]
    preview = scene3d.preview_file_path(project, target["id"])
    preview.parent.mkdir(parents=True, exist_ok=True)
    preview.write_bytes(b"preview")
    linked, _scenes = scene2d.create_scene(project, "Linked")
    scene2d.update_scene(
        project, linked["id"], {"linked_scene3d_id": target["id"]}
    )
    before_files = _tree_bytes(project.project_root)
    before_settings = copy.deepcopy(project.settings)

    if fault_stage == "metadata":
        monkeypatch.setattr(
            scene3d,
            "_save",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                OSError("injected Scene3D metadata fault")
            ),
        )
    elif fault_stage == "settings":
        monkeypatch.setattr(
            project_manager,
            "save_settings",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                OSError("injected Scene3D settings fault")
            ),
        )
    else:
        real_replace = file_transactions.os.replace
        move_count = 0

        def fail_second_quarantine_move(source, destination):
            nonlocal move_count
            destination_path = Path(destination)
            if "transactions" in destination_path.parts:
                move_count += 1
                if move_count == 2:
                    raise OSError("injected Scene3D rename fault")
            return real_replace(source, destination)

        monkeypatch.setattr(file_transactions.os, "replace", fail_second_quarantine_move)

    with pytest.raises(OSError, match="injected Scene3D"):
        scene3d.delete_scene(project, target["id"])

    assert _tree_bytes(project.project_root) == before_files
    assert project.settings == before_settings
    reloaded = scene3d.list_scenes(project)
    assert target["id"] in {scene["id"] for scene in reloaded["scenes"]}
    restored_scene = next(
        scene for scene in scene2d.list_scenes(project) if scene["id"] == linked["id"]
    )
    assert restored_scene["linked_scene3d_id"] == target["id"]


def test_layout2_scene3d_index_corruption_never_uses_settings_mirror(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    scene = scene3d.create_scene(project, title="Canonical")["scene"]
    index = project.metadata_root / "scenes3d" / "scenes3d.json"
    canonical = index.read_bytes()
    project.settings["scene3d"] = {"id": scene["id"], "title": "Mirror only"}

    index.unlink()
    with pytest.raises(FileNotFoundError, match="index is missing"):
        scene3d.list_scenes(project)
    assert not index.exists()

    index.write_bytes(b"{broken")
    with pytest.raises(ValueError, match="unreadable"):
        scene3d.list_scenes(project)

    index.write_bytes(canonical)
    payload = json.loads(canonical)
    payload["scenes"].append(dict(payload["scenes"][0]))
    index.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        scene3d.list_scenes(project)

    payload = json.loads(canonical)
    payload["scenes"][0]["blend_file_path"] = "Blender\\invalid.blend"
    index.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="POSIX"):
        scene3d.list_scenes(project)


def test_layout2_scene2d_index_is_canonical_strict_and_posix_only(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    scene, _scenes = scene2d.create_scene(project, "Canonical")
    index = project.metadata_root / "scenes2d" / "scenes2d.json"
    meta = (
        project.metadata_root
        / "scenes2d"
        / scene["id"]
        / f"{scene['id']}_meta.json"
    )
    canonical_index = index.read_bytes()
    canonical_meta = meta.read_bytes()

    index.unlink()
    with pytest.raises(FileNotFoundError, match="index is missing"):
        scene2d.list_scenes(project)
    assert not index.exists()

    index.write_bytes(b"{broken")
    with pytest.raises(ValueError, match="unreadable"):
        scene2d.list_scenes(project)

    index.write_bytes(canonical_index)
    payload = json.loads(canonical_index)
    payload["scenes"].append(dict(payload["scenes"][0]))
    index.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate scene"):
        scene2d.list_scenes(project)

    index.write_bytes(canonical_index)
    meta.unlink()
    with pytest.raises(FileNotFoundError, match="mirror metadata is missing"):
        scene2d.list_scenes(project)

    meta.write_bytes(canonical_meta)
    meta_payload = json.loads(canonical_meta)
    meta_payload["title"] = "Stale mirror"
    meta.write_text(json.dumps(meta_payload), encoding="utf-8")
    with pytest.raises(ValueError, match="mirror metadata differ"):
        scene2d.list_scenes(project)

    meta.write_bytes(canonical_meta)
    payload = json.loads(canonical_index)
    payload["scenes"][0]["perspectives"][0][
        "source_file_path"
    ] = "PSD\\Scene2D\\invalid.psd"
    index.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="POSIX"):
        scene2d.list_scenes(project)


@pytest.mark.parametrize("suffix", [".blend", ".glb"])
def test_layout2_scene3d_import_preserves_stored_path_and_rolls_back(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    suffix: str,
) -> None:
    project = _project(tmp_path)
    scene = scene3d.create_scene(project, title="Import rollback")["scene"]
    custom_relative = f"Blender/user-preserved{suffix}"
    custom = project.project_root / custom_relative
    custom.parent.mkdir(parents=True, exist_ok=True)
    custom.write_bytes(b"original-binary")
    if suffix == ".blend":
        scene["blend_file_path"] = custom_relative
    else:
        scene.update(
            {
                "source_type": "glb",
                "file_path": custom_relative,
                "file_name": custom.name,
            }
        )
    scene3d._save(project, scene["id"], [scene])
    metadata_before = _tree_bytes(project.metadata_root / "scenes3d")
    settings_before = copy.deepcopy(project.settings)

    with monkeypatch.context() as failure:
        failure.setattr(
            scene3d,
            "_save",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                OSError("injected Scene3D import metadata fault")
            ),
        )
        with pytest.raises(OSError, match="injected Scene3D import"):
            scene3d.import_scene_file(
                project,
                scene["id"],
                f"replacement{suffix}",
                b"replacement-binary",
            )

    assert custom.read_bytes() == b"original-binary"
    assert _tree_bytes(project.metadata_root / "scenes3d") == metadata_before
    assert project.settings == settings_before

    result = scene3d.import_scene_file(
        project,
        scene["id"],
        f"replacement{suffix}",
        b"replacement-binary",
    )["scene"]

    field = "blend_file_path" if suffix == ".blend" else "file_path"
    assert result[field] == custom_relative
    assert custom.read_bytes() == b"replacement-binary"


def test_layout2_transactional_deletes_commit_assets_and_metadata(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    scene, _scenes = scene2d.create_scene(project, "Delete success")
    perspective = scene["perspectives"][0]
    perspective_assets = {
        project.project_root / perspective["source_file_path"],
        project.project_root / perspective["preview_image_path"],
    }
    preview = project.project_root / perspective["preview_image_path"]
    preview.parent.mkdir(parents=True, exist_ok=True)
    preview.write_bytes(b"preview")

    scene2d.delete_perspective(project, scene["id"], perspective["id"])

    assert not any(path.exists() for path in perspective_assets)
    reloaded_scene = next(
        item for item in scene2d.list_scenes(project) if item["id"] == scene["id"]
    )
    assert perspective["id"] not in {
        item["id"] for item in reloaded_scene["perspectives"]
    }

    whole, _scenes = scene2d.create_scene(project, "Whole delete success")
    whole_perspective = whole["perspectives"][0]
    whole_assets = {
        project.project_root / whole_perspective["source_file_path"],
        project.project_root / whole_perspective["preview_image_path"],
    }
    whole_preview = project.project_root / whole_perspective["preview_image_path"]
    whole_preview.parent.mkdir(parents=True, exist_ok=True)
    whole_preview.write_bytes(b"whole-preview")

    scene2d.delete_scene(project, whole["id"])

    assert not any(path.exists() for path in whole_assets)
    assert whole["id"] not in {
        item["id"] for item in scene2d.list_scenes(project)
    }

    target = scene3d.create_scene(project, title="Delete target")["scene"]
    survivor = scene3d.create_scene(project, title="Survivor")["scene"]
    target = scene3d.import_scene_file(
        project, target["id"], "target.glb", b"glb"
    )["scene"]
    target_assets = {
        project.project_root / target["file_path"],
        scene3d.preview_file_path(project, target["id"]),
    }
    target_preview = scene3d.preview_file_path(project, target["id"])
    target_preview.parent.mkdir(parents=True, exist_ok=True)
    target_preview.write_bytes(b"preview")

    scene3d.delete_scene(project, target["id"])

    assert not any(path.exists() for path in target_assets)
    remaining = scene3d.list_scenes(project)
    assert {item["id"] for item in remaining["scenes"]} == {survivor["id"]}
    transactions = project.project_root / ".storyboarder" / "transactions"
    assert not transactions.exists() or not any(transactions.rglob("*"))
