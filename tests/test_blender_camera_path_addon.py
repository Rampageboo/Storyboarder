from __future__ import annotations

from pathlib import Path

from storyboard_tool import project_manager
from storyboard_tool import external_tools


def test_bundled_camera_path_addon_sources_compile() -> None:
    addon_root = Path(external_tools.__file__).resolve().parent / "blender_addon"
    bootstrap = addon_root / "register_storyboarder_addon.py"
    sources = [
        bootstrap,
        addon_root / "storyboarder_bridge.py",
        addon_root / "storyboarder_camera_path" / "__init__.py",
    ]
    for source in sources:
        compile(source.read_text(encoding="utf-8"), str(source), "exec")


def test_open_blender_does_not_register_bundled_addon_by_default(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project = project_manager.create_project(tmp_path)
    fake_blender = tmp_path / "blender.exe"
    fake_blender.write_bytes(b"")
    project.settings["blender_path"] = str(fake_blender)

    launched: list[list[str]] = []
    monkeypatch.setattr(
        "storyboard_tool.external_tools.subprocess.Popen",
        lambda args: launched.append(list(args)),
    )

    blend_path = external_tools.open_blender_scene(project)

    assert blend_path.is_file()
    assert launched == [
        [
            str(fake_blender.resolve()),
            str(blend_path.resolve()),
        ]
    ]
