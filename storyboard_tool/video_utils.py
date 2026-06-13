from __future__ import annotations

import shutil
import subprocess
from io import BytesIO
from pathlib import Path

from PIL import Image


def get_video_duration(path: Path) -> float:
    path = path.expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"Video not found: {path}")
    try:
        import cv2

        cap = cv2.VideoCapture(str(path))
        try:
            if not cap.isOpened():
                raise ValueError(f"Cannot open video: {path}")
            fps = float(cap.get(cv2.CAP_PROP_FPS) or 0)
            frames = float(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        finally:
            cap.release()
        if fps > 0 and frames > 0:
            return frames / fps
    except ImportError:
        pass
    duration = _probe_duration_ffmpeg(path)
    if duration > 0:
        return duration
    raise RuntimeError(
        "Video frame extraction requires opencv-python-headless or ffmpeg on PATH. "
        "Install with: pip install opencv-python-headless"
    )


def extract_video_frame_to_png(source: Path, seconds: float, destination: Path) -> Path:
    source = source.expanduser()
    destination = destination.with_suffix(".png")
    destination.parent.mkdir(parents=True, exist_ok=True)
    target_seconds = max(0.0, float(seconds))
    try:
        import cv2

        frame = _read_frame_cv2(source, target_seconds)
        image = Image.fromarray(frame[:, :, ::-1])
        image.save(destination, "PNG")
        return destination
    except ImportError:
        pass
    if _extract_frame_ffmpeg(source, target_seconds, destination):
        return destination
    raise RuntimeError(
        "Video frame extraction requires opencv-python-headless or ffmpeg on PATH. "
        "Install with: pip install opencv-python-headless"
    )


def _read_frame_cv2(path: Path, seconds: float):
    import cv2

    cap = cv2.VideoCapture(str(path))
    try:
        if not cap.isOpened():
            raise ValueError(f"Cannot open video: {path}")
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 30)
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        target = seconds
        if frame_count > 0 and fps > 0:
            target = min(target, max(0.0, (frame_count - 1) / fps))
        for delta in (0.0, -0.05, 0.05, -0.2, 0.2):
            seek = max(0.0, target + delta)
            cap.set(cv2.CAP_PROP_POS_MSEC, seek * 1000.0)
            ok, frame = cap.read()
            if ok and frame is not None:
                return frame
            frame_index = max(0, int(round(seek * fps)))
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
            ok, frame = cap.read()
            if ok and frame is not None:
                return frame
    finally:
        cap.release()
    raise ValueError(f"Cannot read frame at {seconds:.3f}s from {path.name}")


def _extract_frame_ffmpeg(source: Path, seconds: float, destination: Path) -> bool:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return False
    cmd = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{max(0.0, seconds):.3f}",
        "-i",
        str(source),
        "-frames:v",
        "1",
        "-f",
        "image2pipe",
        "-vcodec",
        "png",
        "-",
    ]
    result = subprocess.run(cmd, capture_output=True, check=False)
    if result.returncode != 0 or not result.stdout:
        return False
    with Image.open(BytesIO(result.stdout)) as image:
        rgb = image.convert("RGB")
        rgb.save(destination, "PNG")
    return True


def _probe_duration_ffmpeg(path: Path) -> float:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return 0.0
    cmd = [
        ffprobe,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        return 0.0
    try:
        return max(0.0, float(result.stdout.strip()))
    except ValueError:
        return 0.0
