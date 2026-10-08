"""Editable lettering rendering. Explicit newline/CJK wrapping matches the SVG preview."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def text_units(text: str) -> float:
    return sum(1 if ord(char) > 255 else .6 for char in text)


def lettering_lines(item: dict) -> list[str]:
    width = item["width"] * (.66 if item["kind"] == "speech" else 1) - 16
    height = item["height"] * (.78 if item["kind"] == "speech" else 1) - 16
    limit = max(1, (height if item["vertical"] else width) / item["font_size"])
    lines = []
    for paragraph in item["text"].split("\n"):
        line = ""
        for char in paragraph:
            units = len(line) + 1 if item["vertical"] else text_units(line + char)
            if line and units > limit:
                lines.append(line)
                line = ""
            line += char
        lines.append(line)
    return lines


@lru_cache(maxsize=160)
def lettering_font(size: int):
    import os
    candidates = [Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts/msyh.ttc",
                  Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc")]
    for path in candidates:
        if path.is_file():
            return ImageFont.truetype(str(path), size)
    try:
        return ImageFont.truetype("DejaVuSans.ttf", size)
    except OSError:
        return ImageFont.load_default(size=size)


def paint_lettering(canvas: Image.Image, item: dict) -> None:
    w, h, size = item["width"], item["height"], item["font_size"]
    border, color, fill = item["border"], item["color"], item["fill"]
    body = h * .82 if item["kind"] == "speech" else h
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    if item["kind"] == "speech":
        tail = [(w * .36, body * .8), (w * item["tail"], h - border / 2), (w * .6, body * .82)]
        draw.polygon(tail, fill=fill)
        if border:
            draw.line(tail, fill=color, width=border, joint="curve")
        draw.ellipse((border / 2, border / 2, w - border / 2 - 1, body - border / 2 - 1),
                     fill=fill, outline=color if border else None, width=max(1, border))
    elif item["kind"] == "caption":
        draw.rectangle((0, 0, w - 1, h - 1), fill=fill, outline=color if border else None, width=max(1, border))
    text = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    pen = ImageDraw.Draw(text)
    font = lettering_font(size)
    lines = lettering_lines(item)
    for i, line in enumerate(lines):
        if item["vertical"]:
            x = w / 2 + (len(lines) - 1) * size * .6 - i * size * 1.2
            for j, char in enumerate(line):
                pen.text((x, 16 + size + j * size), char, fill=color, font=font, anchor="ms")
        else:
            x = max(8, (w - text_units(line) * size) / 2)
            y = max(size + 8, (body - len(lines) * size * 1.2) / 2 + size) + i * size * 1.2
            pen.text((x, y), line, fill=color, font=font, anchor="ls")
    crop = (8, 8, max(8, w - 8), max(8, int(body) - 8))
    layer.alpha_composite(text.crop(crop), (8, 8))
    canvas.paste(layer, (item["x"], item["y"]), layer)
