"""Render a storyboard into an .mp4 animatic.

Each board is composited with :func:`render_shot_composite_image`, letterboxed to
the project canvas size, and held for its ``duration_seconds`` (or a global
override). Encoding prefers ffmpeg (H.264, universal playback) and falls back to
OpenCV's ``mp4v`` writer, mirroring the cv2/ffmpeg convention in ``video_utils``.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .export_utils import numbered_shots
from .models import Project, Shot
from .shot_assets import render_shot_composite_image

DEFAULT_FPS = 24
DEFAULT_MIN_SECONDS = 0.5
_CAPTION_BAR_HEIGHT = 30


def export_animatic(
    project: Project,
    output_path: Path,
    *,
    fps: int = DEFAULT_FPS,
    seconds_per_board: float | None = None,
    min_seconds: float = DEFAULT_MIN_SECONDS,
    captions: bool = False,
) -> Path:
    """Render each board held for its duration and encode an .mp4 animatic."""
    shots = list(project.shots)
    if not shots:
        raise ValueError("The project has no boards to export.")
    fps = max(1, min(60, int(fps)))
    min_seconds = max(0.05, float(min_seconds))
    width = int(project.settings.get("canvas_width") or 1920)
    height = int(project.settings.get("canvas_height") or 1080)
    # H.264 requires even dimensions.
    width = max(2, width - (width % 2))
    height = max(2, height - (height % 2))

    frames: list[tuple[Image.Image, float]] = []
    for number, shot in numbered_shots(project):
        composite = render_shot_composite_image(project, shot)
        frame = _normalize_frame(composite, width, height)
        if captions:
            _draw_caption(frame, number, shot)
        if seconds_per_board and seconds_per_board > 0:
            duration = float(seconds_per_board)
        else:
            duration = float(shot.duration_seconds or 0.0)
        frames.append((frame, max(min_seconds, duration)))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if _encode_ffmpeg(frames, output_path, fps):
        return output_path
    if _encode_cv2(frames, output_path, fps, width, height):
        return output_path
    raise RuntimeError(
        "Video export requires ffmpeg on PATH or opencv-python-headless. "
        "Install ffmpeg, or: pip install opencv-python-headless"
    )


def _normalize_frame(image: Image.Image | None, width: int, height: int) -> Image.Image:
    canvas = Image.new("RGB", (width, height), (17, 19, 24))
    if image is None:
        draw = ImageDraw.Draw(canvas)
        draw.text((max(0, width // 2 - 40), max(0, height // 2 - 8)), "No image", fill=(136, 136, 136))
        return canvas
    frame = image.convert("RGB") if image.mode != "RGB" else image.copy()
    frame.thumbnail((width, height), Image.LANCZOS)
    canvas.paste(frame, ((width - frame.width) // 2, (height - frame.height) // 2))
    return canvas


def _draw_caption(frame: Image.Image, number: int, shot: Shot) -> None:
    draw = ImageDraw.Draw(frame)
    font = ImageFont.load_default()
    # Board number, never the UUID — the caption is for a viewer, not a database.
    label = f"Board {number:03d}"
    if shot.title:
        label = f"{label}  {shot.title}"
    if shot.dialogue:
        label = f"{label}  —  {shot.dialogue}"
    bar_top = frame.height - _CAPTION_BAR_HEIGHT
    draw.rectangle((0, bar_top, frame.width, frame.height), fill=(0, 0, 0))
    draw.text((10, bar_top + 9), label[:140], fill=(232, 232, 232), font=font)


def _encode_ffmpeg(frames: list[tuple[Image.Image, float]], output_path: Path, fps: int) -> bool:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return False
    with tempfile.TemporaryDirectory(prefix="animatic-") as tmp:
        tmp_dir = Path(tmp)
        lines: list[str] = []
        for index, (frame, duration) in enumerate(frames):
            name = f"f{index:05d}.png"
            frame.save(tmp_dir / name, "PNG")
            # Relative names + cwd avoid Windows path-escaping issues in the concat demuxer.
            lines.append(f"file '{name}'")
            lines.append(f"duration {max(0.001, duration):.3f}")
        # The concat demuxer ignores the final entry's duration; repeat the last
        # frame so the last board stays visible, then trim the output to the exact
        # total with -t (the repeated frame otherwise over-holds the ending).
        lines.append(f"file 'f{len(frames) - 1:05d}.png'")
        (tmp_dir / "list.txt").write_text("\n".join(lines), encoding="utf-8")
        total_seconds = sum(max(0.001, duration) for _, duration in frames)
        cmd = [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "concat", "-safe", "0", "-i", "list.txt",
            "-vf", f"fps={fps},format=yuv420p",
            "-t", f"{total_seconds:.3f}",
            "-c:v", "libx264", "-preset", "medium", "-movflags", "+faststart",
            str(output_path.resolve()),
        ]
        result = subprocess.run(cmd, cwd=str(tmp_dir), capture_output=True, check=False)
        return result.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0


def _encode_cv2(frames: list[tuple[Image.Image, float]], output_path: Path, fps: int, width: int, height: int) -> bool:
    try:
        import cv2
        import numpy as np
    except ImportError:
        return False
    writer = cv2.VideoWriter(str(output_path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))
    if not writer.isOpened():
        writer.release()
        return False
    try:
        for frame, duration in frames:
            bgr = np.asarray(frame.convert("RGB"))[:, :, ::-1]
            for _ in range(max(1, round(duration * fps))):
                writer.write(bgr)
    finally:
        writer.release()
    return output_path.exists() and output_path.stat().st_size > 0
