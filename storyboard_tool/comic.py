"""Comic page composition; panel artwork and generation stay owned by shots."""
from __future__ import annotations

import copy
import io
import json
import os
import tempfile
import zipfile
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class ComicChapter(BaseModel):
    id: str = Field(min_length=1, max_length=96, pattern=r"^[A-Za-z0-9_-]+$")
    title: str = Field(max_length=120)
    prompt: str = Field(default="", max_length=20000)


class ComicPanel(BaseModel):
    id: str = Field(min_length=1, max_length=96, pattern=r"^[A-Za-z0-9_-]+$")
    shot_id: str = Field(min_length=1, max_length=96)
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    width: int = Field(ge=16, le=8192)
    height: int = Field(ge=16, le=32000)
    fit: Literal["contain", "cover"] = "contain"
    border: int = Field(default=2, ge=0, le=32)
    points: list[tuple[float, float]] | None = Field(default=None, min_length=3, max_length=8)
    locked: bool = False
    image_scale: float = Field(default=1, ge=0.25, le=8, allow_inf_nan=False)
    image_x: float = Field(default=0, ge=-2, le=2, allow_inf_nan=False)
    image_y: float = Field(default=0, ge=-2, le=2, allow_inf_nan=False)

    @model_validator(mode="after")
    def check_shape(self):
        if self.points is None:
            return self
        import math
        if any(not math.isfinite(value) or not 0 <= value <= 1 for point in self.points for value in point):
            raise ValueError("Panel vertices must be finite normalized coordinates between 0 and 1.")
        area = 0
        sign = 0
        for index, a in enumerate(self.points):
            b = self.points[(index + 1) % len(self.points)]
            c = self.points[(index + 2) % len(self.points)]
            area += a[0] * b[1] - b[0] * a[1]
            cross = (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])
            if abs(cross) > 1e-8:
                current = 1 if cross > 0 else -1
                if sign and current != sign:
                    raise ValueError("Panel shape must be convex and cannot cross itself.")
                sign = current
        if abs(area) / 2 < .01 or not sign:
            raise ValueError("Panel shape is too small.")
        # A regular star can have consistently turning edges; reject intersections explicitly.
        for i, a in enumerate(self.points):
            b = self.points[(i + 1) % len(self.points)]
            for j in range(i + 2, len(self.points)):
                if i == 0 and j == len(self.points) - 1:
                    continue
                c, d = self.points[j], self.points[(j + 1) % len(self.points)]
                def orientation(p, q, r):
                    return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
                if orientation(a, b, c) * orientation(a, b, d) < 0 and orientation(c, d, a) * orientation(c, d, b) < 0:
                    raise ValueError("Panel edges cannot intersect.")
        return self


class ComicLettering(BaseModel):
    id: str = Field(min_length=1, max_length=96, pattern=r"^[A-Za-z0-9_-]+$")
    kind: Literal["speech", "caption", "text"] = "speech"
    text: str = Field(default="", max_length=2000)
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    width: int = Field(ge=16, le=8192)
    height: int = Field(ge=16, le=32000)
    font_size: int = Field(default=32, ge=8, le=160)
    vertical: bool = False
    color: str = Field(default="#161616", pattern=r"^#[0-9a-fA-F]{6}$")
    fill: str = Field(default="#ffffff", pattern=r"^#[0-9a-fA-F]{6}$")
    border: int = Field(default=2, ge=0, le=12)
    tail: float = Field(default=.25, ge=0, le=1, allow_inf_nan=False)


class ComicPage(BaseModel):
    id: str = Field(min_length=1, max_length=96, pattern=r"^[A-Za-z0-9_-]+$")
    chapter_id: str
    title: str = Field(max_length=120)
    mode: Literal["page", "spread", "scroll"]
    width: int = Field(ge=64, le=8192)
    height: int = Field(ge=64, le=32000)
    gutter: int = Field(default=32, ge=0, le=512)
    prompt: str = Field(default="", max_length=20000)
    panels: list[ComicPanel] = Field(default_factory=list, max_length=500)
    lettering: list[ComicLettering] = Field(default_factory=list, max_length=500)
    background: str = Field(default="#ffffff", pattern=r"^#[0-9a-fA-F]{6}$")
    safe_margin: int = Field(default=32, ge=0, le=512)

    @model_validator(mode="after")
    def check_geometry(self):
        if self.width * self.height > 64_000_000:
            raise ValueError("Page exceeds 64 million pixels; split long scrolls into sections.")
        if self.gutter >= self.width:
            raise ValueError("Gutter must be narrower than the page.")
        for panel in [*self.panels, *self.lettering]:
            if panel.x + panel.width > self.width or panel.y + panel.height > self.height:
                raise ValueError("Panel must fit inside its page; increase page dimensions first.")
        if len({item.id for item in self.lettering}) != len(self.lettering):
            raise ValueError("Lettering IDs must be unique within a page.")
        return self


class ComicDocument(BaseModel):
    version: Literal[1] = 1
    revision: int = Field(default=0, ge=0)
    reading_direction: Literal["ltr", "rtl"] = "ltr"
    style_prompt: str = Field(default="", max_length=20000)
    chapters: list[ComicChapter] = Field(default_factory=list, max_length=500)
    pages: list[ComicPage] = Field(default_factory=list, max_length=2000)

    @model_validator(mode="after")
    def check_links(self):
        chapter_ids = [chapter.id for chapter in self.chapters]
        page_ids = [page.id for page in self.pages]
        panels = [panel for page in self.pages for panel in page.panels]
        for ids in (chapter_ids, page_ids, [panel.id for panel in panels], [panel.shot_id for panel in panels]):
            if len(ids) != len(set(ids)):
                raise ValueError("Chapter, page, panel, and placed board IDs must be unique.")
        if any(page.chapter_id not in chapter_ids for page in self.pages):
            raise ValueError("Page refers to a missing chapter.")
        return self


def get_document(project) -> dict:
    """Old projects have an empty comic. Deleted boards leave no ghost panels."""
    raw = copy.deepcopy(project.settings.get("comic_document") or {})
    ids = {shot.shot_id for shot in project.shots}
    for page in raw.get("pages", []):
        page["panels"] = [panel for panel in page.get("panels", []) if panel.get("shot_id") in ids]
    return ComicDocument.model_validate(raw).model_dump()


def _panel_contexts(document: dict) -> dict[str, dict]:
    chapters = {chapter["id"]: chapter for chapter in document["chapters"]}
    contexts = {}
    for page in document["pages"]:
        for index, panel in enumerate(page["panels"]):
            contexts[panel["shot_id"]] = {
                "style_prompt": document["style_prompt"],
                "reading_direction": document["reading_direction"],
                "chapter": chapters[page["chapter_id"]],
                "page": {key: value for key, value in page.items() if key != "panels"},
                "panel": panel,
                "reading_order": index + 1,
                "panel_count": len(page["panels"]),
            }
    return contexts


def panel_context(project, shot_id: str) -> dict | None:
    return _panel_contexts(get_document(project)).get(shot_id)


def update_document(project, value: dict) -> dict:
    current = get_document(project)
    document = ComicDocument.model_validate(value).model_dump()
    if document["revision"] != current["revision"]:
        raise RevisionConflict("Comic changed since it was loaded. Reload before saving.")
    ids = {shot.shot_id for shot in project.shots}
    if any(panel["shot_id"] not in ids for page in document["pages"] for panel in page["panels"]):
        raise ValueError("Panel refers to a missing board.")
    before = _panel_contexts(current)
    document["revision"] += 1
    project.settings["comic_document"] = document
    after = _panel_contexts(document)
    from .generation_service import has_generation_activity
    for shot in project.shots:
        if before.get(shot.shot_id) != after.get(shot.shot_id) and has_generation_activity(shot):
            shot.generation_state["freshness_status"] = "stale"
    return document


class RevisionConflict(ValueError):
    pass


def export_path(project, page_id: str = "", chapter_id: str = "", format: str = ""):
    from .project_layout import resolve_root_child
    document = get_document(project)
    if bool(page_id) == bool(chapter_id):
        raise ValueError("Choose one page or one chapter to export.")
    if page_id and not any(page["id"] == page_id for page in document["pages"]):
        raise ValueError("Comic page not found.")
    if chapter_id and not any(chapter["id"] == chapter_id for chapter in document["chapters"]):
        raise ValueError("Comic chapter not found.")
    chosen = format or ("png" if page_id else "zip")
    if chosen not in ({"png", "pdf"} if page_id else {"zip", "pdf", "cbz"}):
        raise ValueError("Choose PNG/PDF for a page or ZIP/PDF/CBZ for a chapter.")
    return resolve_root_child(project.exports_dir, f"Comic_{page_id or chapter_id}.{chosen}")


def export_comic(project, page_id: str = "", chapter_id: str = "", format: str = ""):
    target = export_path(project, page_id, chapter_id, format)
    if target.suffix == ".pdf":
        from reportlab.pdfgen.canvas import Canvas
        from reportlab.lib.utils import ImageReader
        document = get_document(project)
        pages = [page for page in document["pages"] if page["id"] == page_id] if page_id else [
            page for page in document["pages"] if page["chapter_id"] == chapter_id]
        if not pages:
            raise ValueError("Add pages to this chapter before exporting.")
        output = io.BytesIO()
        pdf = Canvas(output, pageCompression=1)
        for page in pages:
            scale = min(.75, 14400 / max(page["width"], page["height"]))
            width, height = page["width"] * scale, page["height"] * scale
            pdf.setPageSize((width, height))
            pdf.drawImage(ImageReader(io.BytesIO(render_page(project, page["id"]))), 0, 0, width, height)
            pdf.showPage()
        pdf.save()
        content = output.getvalue()
    elif page_id:
        content = render_page(project, page_id)
    else:
        document = get_document(project)
        pages = [page for page in document["pages"] if page["chapter_id"] == chapter_id]
        if not pages:
            raise ValueError("Add pages to this chapter before exporting.")
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for index, page in enumerate(pages):
                archive.writestr(f"{index + 1:03d}_{page['mode']}.png", render_page(project, page["id"]))
            placed = {panel["shot_id"] for page in pages for panel in page["panels"]}
            chapter_document = {**document, "pages": pages,
                                "chapters": [chapter for chapter in document["chapters"] if chapter["id"] == chapter_id]}
            manifest = {"comic_document": chapter_document, "exported_chapter_id": chapter_id,
                        "boards": [shot.to_dict() for shot in project.shots if shot.shot_id in placed]}
            if target.suffix != ".cbz":
                archive.writestr("comic-prompts.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        content = output.getvalue()
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=target.parent, suffix=target.suffix)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
        os.replace(temporary, target)
    except BaseException:
        if os.path.exists(temporary):
            os.unlink(temporary)
        raise
    return target


def compile_context(context: dict) -> str:
    page, panel = context["page"], context["panel"]
    return "\n".join([
        "COMIC PANEL — render this one panel; do not render a whole page or a panel grid.",
        f"Style: {context['style_prompt']}",
        f"Chapter: {context['chapter']['title']}; {context['chapter']['prompt']}",
        f"Page: {page['title']}; {page['mode']}; {page['prompt']}",
        f"Reading direction: {context['reading_direction']}; panel {context['reading_order']} of {context['panel_count']}",
        f"Panel artwork size: {panel['width']} x {panel['height']} pixels; layout position: {panel['x']}, {panel['y']}",
        "Keep lettering separate from artwork. Dialogue is planning context; do not invent speech bubbles or lettering.",
    ])


def render_page(project, page_id: str) -> bytes:
    """Composite the same background/generated/artwork stack as the board preview."""
    import io
    from PIL import Image, ImageDraw, ImageOps, ImageChops
    from . import project_manager, shot_assets
    from .image_utils import image_has_transparency, is_solid_color_image

    page = next((page for page in get_document(project)["pages"] if page["id"] == page_id), None)
    if page is None:
        raise ValueError("Comic page not found.")
    canvas = Image.new("RGB", (page["width"], page["height"]), page["background"])
    shots = {shot.shot_id: shot for shot in project.shots}
    for panel in page["panels"]:
        shot = shots[panel["shot_id"]]
        size = (panel["width"], panel["height"])
        vertices = panel["points"] or [(0, 0), (1, 0), (1, 1), (0, 1)]
        points = [(round(x * (size[0] - 1)), round(y * (size[1] - 1))) for x, y in vertices]
        mask = Image.new("L", size, 0)
        ImageDraw.Draw(mask).polygon(points, fill=255)
        canvas.paste("white", (panel["x"], panel["y"], panel["x"] + size[0], panel["y"] + size[1]), mask)
        paths = [
            shot_assets.get_shot_board_background_path(project, shot),
            shot_assets.get_shot_codex_layer_path(project, shot),
            project_manager.resolve_shot_preview_path(project, shot),
        ]
        newest_background = paths[0].stat().st_mtime if paths[0] and paths[0].is_file() else 0
        for index, path in enumerate(paths):
            if path is None or not path.is_file():
                continue
            if index == 2:
                if is_solid_color_image(path):
                    continue
                if newest_background > path.stat().st_mtime and not image_has_transparency(path):
                    continue
            with Image.open(path) as source:
                image = ImageOps.exif_transpose(source).convert("RGBA")
            choose = max if panel["fit"] == "cover" else min
            factor = choose(size[0] / image.width, size[1] / image.height) * panel["image_scale"]
            left = (size[0] - image.width * factor) / 2 + panel["image_x"] * size[0]
            top = (size[1] - image.height * factor) / 2 + panel["image_y"] * size[1]
            placed = image.transform(size, Image.Transform.AFFINE,
                                     (1 / factor, 0, -left / factor, 0, 1 / factor, -top / factor),
                                     resample=Image.Resampling.BICUBIC)
            canvas.paste(placed, (panel["x"], panel["y"]), ImageChops.multiply(placed.getchannel("A"), mask))
        if panel["border"]:
            border = Image.new("RGBA", size, (0, 0, 0, 0))
            ImageDraw.Draw(border).line([*points, points[0]], fill="black", width=panel["border"] * 2, joint="curve")
            canvas.paste(border, (panel["x"], panel["y"]), ImageChops.multiply(border.getchannel("A"), mask))
    from .comic_lettering import paint_lettering
    for item in page["lettering"]:
        paint_lettering(canvas, item)
    output = io.BytesIO()
    canvas.save(output, "PNG")
    return output.getvalue()
