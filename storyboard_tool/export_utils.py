from __future__ import annotations

import csv
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .models import Project, Shot
from .project_layout import project_relative_posix, resolve_project_child, resolve_project_path
from .shot_assets import render_shot_composite_image


def numbered_shots(project: Project) -> list[tuple[int, Shot]]:
    """Pair each shot with the board number the user sees in the strip.

    A partial export narrows `project.shots` to a selection, so counting the
    list would renumber boards 5-7 as 1-3. `board_numbers` carries the real
    positions when it is set; a whole project is simply 1..N.
    """
    if project.board_numbers and len(project.board_numbers) == len(project.shots):
        return list(zip(project.board_numbers, project.shots))
    return list(enumerate(project.shots, start=1))


def board_label(number: int, shot: Shot) -> str:
    """How a board is named in printed and rendered output — never its UUID."""
    title = shot.title.strip()
    return f"Board {number:03d} - {title}" if title else f"Board {number:03d}"


def export_shot_list_csv(project: Project, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(
            [
                "board",
                "title",
                "scene",
                "sequence",
                "status",
                "duration_seconds",
                "description",
                "action_note",
                "camera_note",
                "dialogue",
                "camera_angle",
                "camera_focal_length",
                "camera_location",
                "camera_rotation",
                "tags",
                "reference_image_paths",
                "ref_video_path",
                "ref_video_time",
                "ref_segment_time",
                # Trailing, not leading: the board number is the identity a
                # reader works from. The id stays available for tooling.
                "shot_id",
            ]
        )
        for number, shot in numbered_shots(project):
            writer.writerow(
                [
                    number,
                    shot.title,
                    shot.scene,
                    shot.sequence,
                    shot.status,
                    shot.duration_seconds,
                    shot.description,
                    shot.action_note,
                    shot.camera_note,
                    shot.dialogue,
                    shot.camera_data.get("angle", ""),
                    shot.camera_data.get("focal_length", ""),
                    shot.camera_data.get("location", ""),
                    shot.camera_data.get("rotation", ""),
                    ", ".join(shot.tags),
                    "; ".join(shot.reference_image_paths),
                    shot.ref_video_path,
                    shot.ref_video_time if shot.ref_video_path else "",
                    shot.ref_segment_time if shot.ref_video_path else "",
                    shot.shot_id,
                ]
            )
    return output_path


def export_timing_json(project: Project, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cursor = 0.0
    rows = []
    for number, shot in numbered_shots(project):
        duration = max(0.1, float(shot.duration_seconds))
        rows.append(
            {
                "board": number,
                "title": shot.title,
                "start_seconds": round(cursor, 3),
                "duration_seconds": round(duration, 3),
                "end_seconds": round(cursor + duration, 3),
                "camera_data": shot.camera_data,
                # Trailing: the board number is the identity; the id is for tooling.
                "shot_id": shot.shot_id,
            }
        )
        cursor += duration
    output_path.write_text(json.dumps({"total_seconds": round(cursor, 3), "shots": rows}, indent=2), encoding="utf-8")
    return output_path


def export_image_sequence(project: Project, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    for number, shot in numbered_shots(project):
        target = resolve_project_child(
            project,
            project_relative_posix(project, output_dir),
            f"board_{number:04d}.png",
        )
        composite = render_shot_composite_image(project, shot)
        if composite is not None:
            composite.save(target, "PNG")
        else:
            _placeholder_image(target, board_label(number, shot))
    return output_dir


def export_contact_sheet(project: Project, output_path: Path, columns: int = 3) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    columns = max(1, columns)
    tile_w, tile_h = 360, 270
    label_h = 46
    rows = max(1, (len(project.shots) + columns - 1) // columns)
    sheet = Image.new("RGB", (columns * tile_w, rows * (tile_h + label_h)), "white")
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()

    for position, (number, shot) in enumerate(numbered_shots(project)):
        col = position % columns
        row = position // columns
        x = col * tile_w
        y = row * (tile_h + label_h)
        draw.rectangle((x, y, x + tile_w - 1, y + tile_h + label_h - 1), outline="#999999")
        image = render_shot_composite_image(project, shot)
        if image is not None:
            image.thumbnail((tile_w - 20, tile_h - 20))
            paste_x = x + (tile_w - image.width) // 2
            paste_y = y + 10 + (tile_h - 20 - image.height) // 2
            sheet.paste(image, (paste_x, paste_y), image)
        else:
            draw.rectangle((x + 20, y + 20, x + tile_w - 20, y + tile_h - 20), outline="#bbbbbb")
            draw.text((x + 130, y + 120), "No Image", fill="#777777", font=font)
        # A UUID here used to eat the 58-char budget and truncate the real title.
        label = f"Board {number:03d} | {shot.title or 'Untitled'} | {shot.duration_seconds:.1f}s"
        draw.text((x + 10, y + tile_h + 12), label[:58], fill="#222222", font=font)

    sheet.save(output_path, "PNG")
    return output_path


def missing_files(project: Project) -> list[dict]:
    rows = []
    for shot in project.shots:
        checks = {
            "preview_image_path": shot.preview_image_path,
            "thumbnail_path": shot.thumbnail_path,
            "source_file_path": shot.source_file_path,
            "annotation_path": shot.annotation_path,
        }
        for field, rel_path in checks.items():
            if rel_path and not resolve_project_path(project, rel_path).exists():
                rows.append({"shot_id": shot.shot_id, "field": field, "path": rel_path})
        for rel_path in shot.reference_image_paths:
            if rel_path and not resolve_project_path(project, rel_path).exists():
                rows.append({"shot_id": shot.shot_id, "field": "reference_image_paths", "path": rel_path})
    return rows


def _shot_image_path(project: Project, shot: Shot) -> Path | None:
    rel_path = shot.preview_image_path or shot.image_path
    if not rel_path:
        return None
    return resolve_project_path(project, rel_path)


def _placeholder_image(target: Path, label: str) -> None:
    image = Image.new("RGB", (1280, 720), "#f4f5f6")
    draw = ImageDraw.Draw(image)
    draw.rectangle((80, 80, 1200, 640), outline="#999999", width=4)
    draw.text((540, 330), f"{label}\nNo Image", fill="#666666", font=ImageFont.load_default())
    image.save(target, "PNG")
