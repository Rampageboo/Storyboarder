from __future__ import annotations

from pathlib import Path

import pytest

from storyboard_tool import export_service, project_manager, video_export


def _project_with_boards(tmp: Path, count: int = 3) -> object:
    project = project_manager.create_project(tmp, canvas_width=320, canvas_height=180)
    for _ in range(count):
        shot = project_manager.add_shot(project)
        shot.duration_seconds = 0.3
    return project


def test_export_animatic_produces_nonempty_mp4(tmp_path: Path) -> None:
    project = _project_with_boards(tmp_path)
    try:
        output = export_service.export_animatic(project, fps=8, captions=True)
    except RuntimeError as exc:  # no ffmpeg and no usable OpenCV writer in this environment
        pytest.skip(str(exc))
    assert output.exists()
    assert output.suffix == ".mp4"
    assert output.stat().st_size > 0


def test_export_animatic_rejects_empty_project(tmp_path: Path) -> None:
    project = project_manager.create_project(tmp_path, canvas_width=320, canvas_height=180)
    with pytest.raises(ValueError):
        video_export.export_animatic(project, tmp_path / "empty.mp4")
