r"""Create an isolated, reopenable comic QA project and real export evidence.

Run: .venv\Scripts\python.exe -m scripts.qa_comic <new-project-directory>
The destination must not exist; no user project is overwritten.
"""
from __future__ import annotations

import argparse
import io
import json
from pathlib import Path

from PIL import Image, ImageDraw

from storyboard_tool import comic, generation_service, project_manager
from storyboard_tool.project_layout import project_relative_posix, resolve_shot_asset


def create_evidence(destination: Path) -> dict:
    destination = destination.resolve()
    if destination.exists():
        raise FileExistsError(f"QA destination already exists: {destination}")
    project = project_manager.create_project(destination, canvas_width=640, canvas_height=360)
    project.settings["backup_on_save"] = False
    colors = ["#e34b42", "#2a75d3", "#35a37a", "#9a51c4", "#e99d31", "#327589"]
    for index, color in enumerate(colors, start=1):
        shot = project_manager.add_shot(project)
        shot.title = f"QA Panel {index}"
        shot.description = f"Character arrives at station; beat {index}"
        shot.dialogue = f"Dialogue plan {index}"
        shot.prompt_config.update(negative_prompt="lettering, watermark", prompt_extra="Consistent character silhouette")
        if index == 1:
            shot.prompt_config.update(mode="manual", manual_prompt="One detective with a red umbrella")
        preview = resolve_shot_asset(project, shot.shot_id, "preview")
        preview.parent.mkdir(parents=True, exist_ok=True)
        art = Image.new("RGB", (600, 400), color)
        draw = ImageDraw.Draw(art)
        draw.rectangle((15, 15, 584, 384), outline="white", width=6)
        draw.ellipse((220, 70, 380, 230), fill="#171d2b")
        draw.rectangle((245, 205, 355, 370), fill="#171d2b")
        draw.text((30, 30), f"PANEL {index} - artwork fixture", fill="white")
        art.save(preview)
        shot.preview_image_path = shot.image_path = project_relative_posix(project, preview)
    doc = comic.ComicDocument().model_dump()
    doc.update(style_prompt="Graphic ink with limited colors", reading_direction="ltr", chapters=[{
        "id": "chapter_qa", "title": "Station arrival", "prompt": "Rainy coastal station, consistent cast",
    }])
    specs = [
        ("page_qa", "page", 640, 960, [(32, 32, 576, 416), (32, 496, 576, 416)]),
        ("spread_qa", "spread", 1280, 960, [(32, 32, 576, 896), (672, 32, 576, 896)]),
        ("scroll_qa", "scroll", 640, 3200, [(32, 64, 576, 576), (32, 2100, 576, 900)]),
    ]
    for page_index, (page_id, mode, width, height, rects) in enumerate(specs):
        panels = []
        for local, (x, y, panel_width, panel_height) in enumerate(rects):
            index = page_index * 2 + local
            panels.append({"id": f"panel_{index + 1}", "shot_id": project.shots[index].shot_id,
                           "x": x, "y": y, "width": panel_width, "height": panel_height,
                           "fit": "contain" if local == 0 else "cover", "border": 4})
        doc["pages"].append({"id": page_id, "chapter_id": "chapter_qa", "title": f"QA {mode}",
                             "mode": mode, "width": width, "height": height, "gutter": 32,
                             "prompt": f"Composition context for {mode}", "panels": panels})
    accepted = comic.update_document(project, doc)
    project_manager.save_project(project)
    evidence = destination / "comic-qa-evidence"
    evidence.mkdir()
    exports = []
    for page in accepted["pages"]:
        pixels = comic.render_page(project, page["id"])
        export_path = evidence / f"{page['mode']}.png"
        export_path.write_bytes(pixels)
        image = Image.open(io.BytesIO(pixels))
        assert image.size == (page["width"], page["height"])
        for panel in page["panels"]:
            assert image.getpixel((panel["x"], panel["y"])) == (0, 0, 0)
        exports.append({"mode": page["mode"], "path": str(export_path), "size": list(image.size)})
    request = generation_service.build_request_snapshot(project, project.shots[0], "queue")
    (evidence / "generation-request.json").write_text(json.dumps(request, ensure_ascii=False, indent=2), encoding="utf-8")
    reopened = project_manager.open_project(project.reopen_path)
    assert comic.get_document(reopened) == accepted
    manifest = {"project_path": str(project.reopen_path), "comic_document": accepted,
                "exports": exports, "reopen_verified": True, "shot_count": len(project.shots)}
    (evidence / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--serve", action="store_true", help="Serve an already generated QA project on localhost")
    parser.add_argument("--port", type=int, default=8123)
    args = parser.parse_args()
    if args.serve:
        import uvicorn
        from storyboard_tool.api import create_app
        manifest = json.loads((args.destination / "comic-qa-evidence" / "manifest.json").read_text(encoding="utf-8"))
        runtime = args.destination.resolve() / "qa-server-runtime"
        runtime.mkdir(exist_ok=True)
        app = create_app(runtime, bridge_port=args.port)
        app.state.project = project_manager.open_project(Path(manifest["project_path"]))
        app.state.project_disk_mtime = project_manager.project_disk_mtime(app.state.project)
        uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
    else:
        print(json.dumps(create_evidence(args.destination), ensure_ascii=False, indent=2))
