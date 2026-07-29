from __future__ import annotations

import io
import json
import uuid
from pathlib import Path

import pytest

from storyboard_tool import (
    blender_bridge,
    external_tools,
    project_manager,
    reference_segments,
    scene2d,
    scene3d,
)
from storyboard_tool.api import create_app
from storyboard_tool.bpy_viewport import (
    BpyViewportError,
    BpyViewportManager,
    project_blend_path,
)
from storyboard_tool.models import Project
from storyboard_tool.plugin_service import PluginBridgeService


def _project(tmp_path: Path) -> Project:
    root = tmp_path / "Portable"
    work = root / ".storyboarder" / "work"
    work.mkdir(parents=True)
    return Project(
        root_path=work,
        project_root_path=root,
        document_path=root / "Portable.sbd",
        layout=2,
        project_id=str(uuid.uuid4()),
        storage_revision=12,
        settings=dict(project_manager.DEFAULT_SETTINGS),
    )


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
    context = json.loads(bridge_path.read_text(encoding="utf-8"))
    assert context["version"] == 2
    assert context["path_mode"] == "explicit-assets"
    assert context["offline_write_allowed"] is False
    assert context["write_enabled"] is True
    assert context["project_session_id"] == app.state.project_session_id
    assert context["context_revision"] == project.storage_revision

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
            "blend_path": str(blend.resolve()),
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


def test_layout2_builtin_blender_rejects_noncanonical_stored_path(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    scene = scene3d.create_scene(project, title="Stage")["scene"]
    stale = project.project_root / "Blender" / "stale.blend"
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_bytes(b"stale")
    scene["blend_file_path"] = "Blender/stale.blend"
    scene3d._save(project, scene["id"], [scene])

    with pytest.raises(BpyViewportError, match="not canonical"):
        project_blend_path(project)


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
