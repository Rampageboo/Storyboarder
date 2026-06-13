from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .models import Project, Shot


def export_shot_list_csv(project: Project, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(
            [
                "shot_id",
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
            ]
        )
        for shot in project.shots:
            writer.writerow(
                [
                    shot.shot_id,
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
                ]
            )
    return output_path


def export_timing_json(project: Project, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cursor = 0.0
    rows = []
    for shot in project.shots:
        duration = max(0.1, float(shot.duration_seconds))
        rows.append(
            {
                "shot_id": shot.shot_id,
                "title": shot.title,
                "start_seconds": round(cursor, 3),
                "duration_seconds": round(duration, 3),
                "end_seconds": round(cursor + duration, 3),
                "camera_data": shot.camera_data,
            }
        )
        cursor += duration
    output_path.write_text(json.dumps({"total_seconds": round(cursor, 3), "shots": rows}, indent=2), encoding="utf-8")
    return output_path


def export_image_sequence(project: Project, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    for index, shot in enumerate(project.shots, start=1):
        source = _shot_image_path(project, shot)
        target = output_dir / f"{index:04d}_{shot.shot_id}.png"
        if source and source.exists():
            shutil.copy2(source, target)
        else:
            _placeholder_image(target, shot.shot_id)
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

    for index, shot in enumerate(project.shots):
        col = index % columns
        row = index // columns
        x = col * tile_w
        y = row * (tile_h + label_h)
        draw.rectangle((x, y, x + tile_w - 1, y + tile_h + label_h - 1), outline="#999999")
        source = _shot_image_path(project, shot)
        if source and source.exists():
            with Image.open(source) as image:
                image.thumbnail((tile_w - 20, tile_h - 20))
                paste_x = x + (tile_w - image.width) // 2
                paste_y = y + 10 + (tile_h - 20 - image.height) // 2
                if image.mode in ("RGBA", "LA"):
                    sheet.paste(image, (paste_x, paste_y), image)
                else:
                    sheet.paste(image.convert("RGB"), (paste_x, paste_y))
        else:
            draw.rectangle((x + 20, y + 20, x + tile_w - 20, y + tile_h - 20), outline="#bbbbbb")
            draw.text((x + 130, y + 120), "No Image", fill="#777777", font=font)
        label = f"{shot.shot_id} | {shot.title or 'Untitled'} | {shot.duration_seconds:.1f}s"
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
            if rel_path and not (project.root_path / rel_path).exists():
                rows.append({"shot_id": shot.shot_id, "field": field, "path": rel_path})
        for rel_path in shot.reference_image_paths:
            if rel_path and not (project.root_path / rel_path).exists():
                rows.append({"shot_id": shot.shot_id, "field": "reference_image_paths", "path": rel_path})
    return rows


def _shot_image_path(project: Project, shot: Shot) -> Path | None:
    rel_path = shot.preview_image_path or shot.image_path
    if not rel_path:
        return None
    return project.root_path / rel_path


def _placeholder_image(target: Path, shot_id: str) -> None:
    image = Image.new("RGB", (1280, 720), "#f4f5f6")
    draw = ImageDraw.Draw(image)
    draw.rectangle((80, 80, 1200, 640), outline="#999999", width=4)
    draw.text((540, 330), f"{shot_id}\nNo Image", fill="#666666", font=ImageFont.load_default())
    image.save(target, "PNG")
