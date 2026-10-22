"""Agent-facing views of a project: board grid, outline, and the assembled cut.

These are the read endpoints an agent (through the MCP server) uses to *see* a
storyboard, plus the sequence render that concatenates a route's chosen video
takes into one MP4. Boards follow route order, the same order the app's story
view shows (``activeRouteShots``): the active route unless one is named, and a
board's ``number`` is its 1-based position in that route.
"""
from __future__ import annotations

import io
import math
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from . import comfy_cloud
from .models import Project, Shot
from .project_layout import ProjectPathError, project_relative_posix, resolve_project_path, resolve_root_child
from .shot_assets import render_shot_composite_image, resolve_shot_preview_path
from .story_graph import get_graph
from .video_export import _normalize_frame, duration_frames

SEQUENCE_FPS = comfy_cloud.FPS  # 16, the rate Wan takes are generated at
GRID_DEFAULT_MAX_EDGE = 1600
GRID_MAX_COLUMNS = 12
_GRID_MAX_CELL = 480  # px; a few boards should not blow up into a poster


class AgentViewError(ValueError):
    """A request the caller can fix (unknown route, empty selection, bad take)."""


# ── route order ─────────────────────────────────────────────────────────────

def resolve_route(project: Project, route_id: str = "") -> dict[str, Any]:
    graph = get_graph(project)
    wanted = str(route_id or "").strip() or graph["active_route_id"]
    route = next((item for item in graph["routes"] if item["id"] == wanted), None)
    if route is None:
        raise AgentViewError(f"Story route {wanted!r} not found.")
    return route


def route_boards(project: Project, route_id: str = "") -> tuple[dict[str, Any], list[tuple[int, Shot]]]:
    """(route, [(number, shot)]) in route order; number is the route position."""
    route = resolve_route(project, route_id)
    shots = {shot.shot_id: shot for shot in project.shots}
    ordered = [shots[shot_id] for shot_id in route["shot_ids"] if shot_id in shots]
    return route, list(enumerate(ordered, start=1))


def _safe_duration(shot: Shot) -> float:
    value = float(shot.duration_seconds or 0)
    return value if math.isfinite(value) and value > 0 else 3.0


def _canvas_size(project: Project) -> tuple[int, int]:
    return (
        max(1, int(project.settings.get("canvas_width") or 1920)),
        max(1, int(project.settings.get("canvas_height") or 1080)),
    )


# ── grid ────────────────────────────────────────────────────────────────────

def default_columns(count: int) -> int:
    if count <= 1:
        return 1
    return min(count, 6, max(2, math.ceil(math.sqrt(count))))


def render_grid_png(
    project: Project,
    boards: list[tuple[int, Shot]],
    *,
    columns: int | None = None,
    max_edge: int = GRID_DEFAULT_MAX_EDGE,
) -> bytes:
    """Numbered contact sheet: image, ``#NN`` badge, duration badge, title."""
    from .comic_lettering import lettering_font

    count = len(boards)
    cols = max(1, min(GRID_MAX_COLUMNS, int(columns or default_columns(count)), max(1, count)))
    rows = max(1, math.ceil(count / cols))
    canvas_w, canvas_h = _canvas_size(project)
    ratio = canvas_h / canvas_w
    gap_k, label_k = 0.04, 0.16
    width_units = cols + (cols + 1) * gap_k
    height_units = rows * (ratio + label_k) + (rows + 1) * gap_k
    cell = int(min(_GRID_MAX_CELL, max_edge / max(width_units, height_units)))
    cell = max(32, cell)
    gap = max(2, round(cell * gap_k))
    label_h = max(14, round(cell * label_k))
    image_h = max(1, round(cell * ratio))
    sheet_w = cols * cell + (cols + 1) * gap
    sheet_h = rows * (image_h + label_h) + (rows + 1) * gap
    sheet = Image.new("RGB", (sheet_w, sheet_h), (32, 34, 40))
    draw = ImageDraw.Draw(sheet)
    badge_font = lettering_font(max(9, round(cell * 0.075)))
    title_font = lettering_font(max(9, round(label_h * 0.55)))

    if not boards:
        draw.text((gap, gap), "No boards", fill=(200, 200, 200), font=title_font)

    for position, (number, shot) in enumerate(boards):
        x = gap + (position % cols) * (cell + gap)
        y = gap + (position // cols) * (image_h + label_h + gap)
        composite = render_shot_composite_image(project, shot)
        if composite is None:
            draw.rectangle((x, y, x + cell - 1, y + image_h - 1), fill=(236, 236, 236), outline=(160, 160, 160))
            text = "No image"
            tw = draw.textlength(text, font=title_font)
            draw.text((x + (cell - tw) / 2, y + image_h / 2 - label_h * 0.3), text, fill=(120, 120, 120), font=title_font)
        else:
            tile = Image.new("RGB", (cell, image_h), (255, 255, 255))
            frame = composite.copy()
            frame.thumbnail((cell, image_h), Image.LANCZOS)
            offset = ((cell - frame.width) // 2, (image_h - frame.height) // 2)
            tile.paste(frame, offset, frame if frame.mode == "RGBA" else None)
            sheet.paste(tile, (x, y))
        _badge(draw, (x + gap // 2 + 1, y + gap // 2 + 1), f"#{number:02d}", badge_font, (20, 20, 20), (255, 214, 64))
        duration_text = f"{_safe_duration(shot):g}s"
        dw = draw.textlength(duration_text, font=badge_font)
        pad = max(2, round(cell * 0.015))
        _badge(draw, (x + cell - gap // 2 - 1 - dw - 2 * pad, y + gap // 2 + 1), duration_text, badge_font, (255, 255, 255), (0, 0, 0))
        title = (shot.title or "Untitled").replace("\n", " ")
        draw.text((x + 2, y + image_h + label_h * 0.18), _fit_text(draw, title, title_font, cell - 4),
                  fill=(232, 232, 232), font=title_font)

    output = io.BytesIO()
    sheet.save(output, "PNG", optimize=True)
    return output.getvalue()


def _badge(draw: ImageDraw.ImageDraw, origin: tuple[float, float], text: str, font, fg, bg) -> None:
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    pad = max(2, round((bottom - top) * 0.3))
    x, y = origin
    draw.rectangle((x, y, x + (right - left) + 2 * pad, y + (bottom - top) + 2 * pad), fill=bg)
    draw.text((x + pad - left, y + pad - top), text, fill=fg, font=font)


def _fit_text(draw: ImageDraw.ImageDraw, text: str, font, width: float) -> str:
    if draw.textlength(text, font=font) <= width:
        return text
    while text and draw.textlength(text + "…", font=font) > width:
        text = text[:-1]
    return text + "…"


# ── outline ─────────────────────────────────────────────────────────────────

def _take_summary(take: dict[str, Any] | None) -> dict[str, Any] | None:
    if not take:
        return None
    return {
        key: take.get(key)
        for key in ("take_id", "status", "mode", "seconds", "width", "height", "end_shot_id", "error",
                    "created_at", "updated_at")
    }


def latest_image_job(app: Any, project: Project, shot_id: str) -> dict[str, Any] | None:
    """Merge hook for team A's ``comfy_images`` module (decision 4).

    Returns the newest image job for the board when ``storyboard_tool.comfy_images``
    exists and exposes ``list_jobs(app, project, shot_id)`` (the same shape as
    ``comfy_cloud.list_takes``); ``None`` until that module lands.
    """
    try:
        from . import comfy_images  # type: ignore[attr-defined]
    except ImportError:
        return None
    list_jobs = getattr(comfy_images, "list_jobs", None)
    if list_jobs is None:
        return None
    jobs = list(list_jobs(app, project, shot_id) or [])
    if not jobs:
        return None
    jobs.sort(key=lambda row: str(row.get("created_at") or ""), reverse=True)
    return jobs[0]


def build_outline(app: Any, project: Project, route_id: str = "") -> dict[str, Any]:
    graph = get_graph(project)
    route, boards = route_boards(project, route_id)
    canvas_w, canvas_h = _canvas_size(project)
    rows: list[dict[str, Any]] = []
    cursor = 0.0
    for number, shot in boards:
        takes = comfy_cloud.list_takes(app, project, shot.shot_id)
        duration = _safe_duration(shot)
        design = {key: value for key, value in (shot.shot_design or {}).items() if value not in ("", False, None)}
        prompt = shot.prompt_config or {}
        rows.append({
            "number": number,
            "shot_id": shot.shot_id,
            "title": shot.title,
            "description": shot.description,
            "dialogue": shot.dialogue,
            "duration_seconds": duration,
            "start_seconds": round(cursor, 3),
            "status": shot.status,
            "scene": shot.scene,
            "notes": {
                "action": shot.action_note,
                "camera": shot.camera_note,
                "character": shot.character_note,
                "lighting": shot.lighting_note,
                "transition": shot.transition_note,
            },
            "shot_design": design,
            "prompt": {
                "mode": str(prompt.get("mode") or "auto"),
                "manual_prompt": str(prompt.get("manual_prompt") or ""),
                "prompt_extra": str(prompt.get("prompt_extra") or ""),
                "negative_prompt": str(prompt.get("negative_prompt") or ""),
            },
            "video_prompt": comfy_cloud.compile_video_prompt(shot),
            "has_image": resolve_shot_preview_path(project, shot) is not None,
            "latest_image_job": latest_image_job(app, project, shot.shot_id),
            "latest_video_take": _take_summary(takes[0] if takes else None),
            "video_takes": {
                "total": len(takes),
                "succeeded": sum(1 for take in takes if take.get("status") == "succeeded"),
            },
        })
        cursor += duration
    return {
        "project": {"name": project.name, "canvas": {"width": canvas_w, "height": canvas_h}},
        "route": {"id": route["id"], "name": route["name"]},
        "routes": [
            {"id": item["id"], "name": item["name"], "board_count": len(item["shot_ids"]),
             "active": item["id"] == graph["active_route_id"]}
            for item in graph["routes"]
        ],
        "board_count": len(rows),
        "total_seconds": round(cursor, 3),
        "boards": rows,
    }


# ── sequence render ─────────────────────────────────────────────────────────

@dataclass
class _Segment:
    shot_id: str
    number: int
    source: str  # "take" | "still"
    path: Path
    seconds: float  # length used in the cut
    take_id: str = ""
    take_seconds: float = 0.0  # the take's own length (takes only)
    trim_frames: int = 0  # > 0: cut the take to this many frames at SEQUENCE_FPS


def _even(value: int) -> int:
    return max(2, int(value) - int(value) % 2)


def plan_sequence(
    app: Any,
    project: Project,
    boards: list[tuple[int, Shot]],
    takes: dict[str, str],
    still_dir: Path,
    *,
    trim_to_board: bool = True,
) -> tuple[list[_Segment], tuple[int, int]]:
    """Choose each board's source and snapshot stills; call under PROJECT_LOCK.

    With ``trim_to_board`` a take longer than its board is cut to the board's
    duration in whole frames at ``SEQUENCE_FPS``; a shorter take is never extended.
    """
    unknown = set(takes) - {shot.shot_id for _, shot in boards}
    if unknown:
        raise AgentViewError(f"Takes were chosen for boards outside this sequence: {', '.join(sorted(unknown))}.")
    segments: list[_Segment] = []
    size: tuple[int, int] | None = None
    canvas_w, canvas_h = _canvas_size(project)
    for number, shot in boards:
        records = comfy_cloud.list_takes(app, project, shot.shot_id)
        chosen_id = str(takes.get(shot.shot_id) or "")
        record: dict[str, Any] | None = None
        if chosen_id:
            record = next((row for row in records if row.get("take_id") == chosen_id), None)
            if record is None:
                raise AgentViewError(f"Take {chosen_id} does not belong to board #{number:02d}.")
            if record.get("status") != "succeeded":
                raise AgentViewError(f"Take {chosen_id} has not succeeded (status: {record.get('status')}).")
        else:
            record = next((row for row in records if row.get("status") == "succeeded" and row.get("video_path")), None)
        video = _take_video(project, record) if record else None
        if record and chosen_id and video is None:
            raise AgentViewError(f"The video file of take {chosen_id} is missing on disk.")
        if video is not None and record is not None:
            if size is None:
                size = (_even(int(record.get("width") or 0) or 832), _even(int(record.get("height") or 0) or 464))
            take_seconds = _probe_seconds(video) or float(record.get("seconds") or _safe_duration(shot))
            seconds, trim_frames = take_seconds, 0
            if trim_to_board:
                board_frames = duration_frames(_safe_duration(shot), SEQUENCE_FPS)
                take_frames = max(1, round(take_seconds * SEQUENCE_FPS))
                if board_frames < take_frames:
                    trim_frames = board_frames
                seconds = min(board_frames, take_frames) / SEQUENCE_FPS
            segments.append(_Segment(shot.shot_id, number, "take", video, seconds, str(record["take_id"]),
                                     take_seconds=take_seconds, trim_frames=trim_frames))
            continue
        still = still_dir / f"still_{number:04d}.png"
        _normalize_frame(render_shot_composite_image(project, shot), canvas_w, canvas_h).save(still, "PNG")
        seconds = duration_frames(_safe_duration(shot), SEQUENCE_FPS) / SEQUENCE_FPS
        segments.append(_Segment(shot.shot_id, number, "still", still, seconds))
    if size is None:
        size = comfy_cloud.frame_size(canvas_w, canvas_h)
    return segments, size


def _take_video(project: Project, record: dict[str, Any]) -> Path | None:
    relative = str(record.get("video_path") or "")
    if not relative:
        return None
    try:
        path = resolve_project_path(project, relative)
    except ValueError:
        return None
    return path if path.is_file() else None


def _probe_seconds(path: Path) -> float:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return 0.0
    result = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True, check=False,
    )
    try:
        return float(result.stdout.strip())
    except ValueError:
        return 0.0


def encode_sequence(segments: list[_Segment], size: tuple[int, int], output: Path) -> None:
    """One ffmpeg pass: scale/pad every source to ``size``, 16 fps, concat, H.264."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("Sequence render requires ffmpeg on PATH.")
    width, height = size
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y"]
    filters: list[str] = []
    for index, segment in enumerate(segments):
        if segment.source == "still":
            cmd += ["-loop", "1", "-framerate", str(SEQUENCE_FPS), "-t", f"{segment.seconds:.6f}", "-i", str(segment.path)]
        else:
            cmd += ["-i", str(segment.path)]
        filters.append(
            f"[{index}:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=0x111318,setsar=1,"
            f"fps={SEQUENCE_FPS},"
            + (f"trim=end_frame={segment.trim_frames},setpts=PTS-STARTPTS," if segment.trim_frames else "")
            + f"format=yuv420p[v{index}]"
        )
    joined = "".join(f"[v{index}]" for index in range(len(segments)))
    filters.append(f"{joined}concat=n={len(segments)}:v=1:a=0[out]")
    cmd += [
        "-filter_complex", ";".join(filters), "-map", "[out]", "-an",
        "-c:v", "libx264", "-preset", "medium", "-pix_fmt", "yuv420p", "-r", str(SEQUENCE_FPS),
        "-movflags", "+faststart", "-f", "mp4", str(output),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0 or not output.is_file() or output.stat().st_size <= 0:
        detail = (result.stderr or "").strip().splitlines()[-1:] or ["no output"]
        raise RuntimeError(f"ffmpeg could not render the sequence: {detail[0][:300]}")


def sequence_output_path(project: Project) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    candidate = resolve_root_child(project.exports_dir, f"sequence_{stamp}.mp4")
    counter = 2
    while candidate.exists():
        candidate = resolve_root_child(project.exports_dir, f"sequence_{stamp}_{counter}.mp4")
        counter += 1
    return candidate


def relative_export_path(project: Project, path: Path) -> str:
    try:
        return project_relative_posix(project, path)
    except (ValueError, ProjectPathError):
        return ""


def new_still_dir() -> tempfile.TemporaryDirectory:
    return tempfile.TemporaryDirectory(prefix="sequence-")
