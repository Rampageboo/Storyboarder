"""Generate raster app icons from the startup film-strip design."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parent
STATIC = ROOT.parent / "web" / "static"

BG_TOP = (11, 12, 15)
BG_MID = (6, 7, 8)
BG_BOTTOM = (3, 3, 4)
ACCENT = (232, 185, 35)
FRAME_FILL = (18, 20, 26)
PERF_FILL = (255, 255, 255, 36)
STRIP_BORDER = (30, 32, 36)


def _lerp(a: int, b: int, t: float) -> int:
    return int(a + (b - a) * t)


def _bg_color(y: int, size: int) -> tuple[int, int, int]:
    t = y / max(size - 1, 1)
    if t <= 0.55:
        local = t / 0.55
        return (
            _lerp(BG_TOP[0], BG_MID[0], local),
            _lerp(BG_TOP[1], BG_MID[1], local),
            _lerp(BG_TOP[2], BG_MID[2], local),
        )
    local = (t - 0.55) / 0.45
    return (
        _lerp(BG_MID[0], BG_BOTTOM[0], local),
        _lerp(BG_MID[1], BG_BOTTOM[1], local),
        _lerp(BG_MID[2], BG_BOTTOM[2], local),
    )


def _rounded_rect(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    radius: int,
    fill,
    outline=None,
    width: int = 1,
) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def render_icon(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    px = img.load()

    corner = max(4, round(size * 0.22))
    for y in range(size):
        color = _bg_color(y, size)
        for x in range(size):
            dx = min(x, size - 1 - x)
            dy = min(y, size - 1 - y)
            if dx < corner and dy < corner:
                cx = corner - dx if x < corner else size - corner - 1 + (size - 1 - x)
                cy = corner - dy if y < corner else size - corner - 1 + (size - 1 - y)
                dist_sq = (corner - cx) ** 2 + (corner - cy) ** 2
                if dist_sq > corner**2:
                    continue
            px[x, y] = (*color, 255)

    draw = ImageDraw.Draw(img)
    glow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    glow_draw.ellipse(
        (size * 0.08, -size * 0.12, size * 0.92, size * 0.52),
        fill=(232, 185, 35, int(size * 0.08)),
    )
    img = Image.alpha_composite(img, glow)
    draw = ImageDraw.Draw(img)

    margin = round(size * 0.156)
    strip_top = round(size * 0.188)
    strip_w = size - margin * 2
    strip_h = round(size * 0.625)
    strip_radius = max(2, round(size * 0.055))
    strip_box = (margin, strip_top, margin + strip_w, strip_top + strip_h)
    _rounded_rect(draw, strip_box, strip_radius, FRAME_FILL, outline=STRIP_BORDER, width=max(1, round(size * 0.012)))

    perf_h = max(2, round(size * 0.094))
    perf_step = max(4, round(size * 0.22))
    perf_w = max(2, round(size * 0.078))
    for band_y in (strip_top, strip_top + strip_h - perf_h):
        for x in range(margin, margin + strip_w, perf_step):
            hole_x1 = x + round(perf_step * 0.21)
            hole_x2 = hole_x1 + perf_w
            if hole_x2 > margin + strip_w:
                continue
            draw.rounded_rectangle(
                (hole_x1, band_y + max(1, perf_h // 5), hole_x2, band_y + perf_h - max(1, perf_h // 5)),
                radius=max(1, perf_h // 5),
                fill=PERF_FILL,
            )

    frame_top = strip_top + round(size * 0.156)
    frame_h = round(size * 0.312)
    frame_w = round(size * 0.156)
    frame_gap = round(size * 0.047)
    frame_x = margin + round(size * 0.062)
    frame_radius = max(1, round(size * 0.019))
    stroke = max(1, round(size * 0.02))
    for _ in range(3):
        _rounded_rect(
            draw,
            (frame_x, frame_top, frame_x + frame_w, frame_top + frame_h),
            frame_radius,
            (12, 14, 20, 255),
            outline=ACCENT,
            width=stroke,
        )
        frame_x += frame_w + frame_gap

    return img


def main() -> None:
    master = render_icon(256)
    ROOT.mkdir(parents=True, exist_ok=True)
    STATIC.mkdir(parents=True, exist_ok=True)

    master.save(ROOT / "icon.png", format="PNG")
    master.save(STATIC / "favicon.png", format="PNG")

    ico_sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    for target in (ROOT / "icon.ico", STATIC / "favicon.ico"):
        master.save(target, format="ICO", sizes=ico_sizes)
    print(f"Wrote icons to {ROOT} and {STATIC}")


if __name__ == "__main__":
    main()
