from __future__ import annotations

import base64
import os
import re
from io import BytesIO
from pathlib import Path
from typing import BinaryIO

from PIL import Image, ImageDraw, ImageFont


DEFAULT_CANVAS_COLOR = "#E8E8E8"
_HEX_COLOR_RE = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


def normalize_hex_color(value: str, default: str = DEFAULT_CANVAS_COLOR) -> str:
    candidate = (value or "").strip()
    if not _HEX_COLOR_RE.fullmatch(candidate):
        candidate = default
    if len(candidate) == 4:
        chars = candidate[1:]
        candidate = "#" + "".join(char * 2 for char in chars)
    return candidate.upper()


def hex_to_rgb(value: str, default: str = DEFAULT_CANVAS_COLOR) -> tuple[int, int, int]:
    normalized = normalize_hex_color(value, default)
    red = int(normalized[1:3], 16)
    green = int(normalized[3:5], 16)
    blue = int(normalized[5:7], 16)
    return red, green, blue


SUPPORTED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp"}
PSD_EXTENSIONS = {".psd", ".psb"}
THUMBNAIL_SIZE = (420, 260)
SB_BG_LAYER_NAME = "SB bg"
SB_REF_LAYER_PREFIX = "SB ref:"
CANVAS_BACKGROUND_LAYER_NAME = "Background"


def board_background_filename(shot_id: str) -> str:
    return f"{shot_id}_background.png"


def preview_export_layer_filter(layer) -> bool:
    # Mirror the plugin's preview export: drop the board background reference
    # (`SB bg`), the canvas-color fill (`Background`), and onion-skin overlays
    # (`SB ref:`) so the storyboard preview is the artist's strokes on transparency.
    name = str(getattr(layer, "name", "") or "")
    return (
        name != SB_BG_LAYER_NAME
        and name != CANVAS_BACKGROUND_LAYER_NAME
        and not name.startswith(SB_REF_LAYER_PREFIX)
    )


REFERENCE_FIT_MODES = frozenset({"fit", "fill", "stretch"})


def normalize_reference_fit_mode(value: str) -> str:
    mode = str(value or "fit").strip().lower()
    if mode in REFERENCE_FIT_MODES:
        return mode
    return "fit"


def fit_image_to_canvas(image: Image.Image, width: int, height: int) -> Image.Image:
    """Scale uniformly to fit inside the canvas, centered (matches in-app object-fit: contain)."""
    source = image.convert("RGBA")
    src_w, src_h = source.size
    if src_w <= 0 or src_h <= 0:
        return Image.new("RGBA", (width, height), (0, 0, 0, 0))
    scale = min(width / src_w, height / src_h)
    fitted_w = max(1, round(src_w * scale))
    fitted_h = max(1, round(src_h * scale))
    resized = source.resize((fitted_w, fitted_h), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    offset_x = (width - fitted_w) // 2
    offset_y = (height - fitted_h) // 2
    canvas.paste(resized, (offset_x, offset_y), resized)
    return canvas


def fill_image_to_canvas(image: Image.Image, width: int, height: int) -> Image.Image:
    """Scale uniformly to cover the canvas, centered (matches object-fit: cover)."""
    source = image.convert("RGBA")
    src_w, src_h = source.size
    if src_w <= 0 or src_h <= 0:
        return Image.new("RGBA", (width, height), (0, 0, 0, 0))
    scale = max(width / src_w, height / src_h)
    fitted_w = max(1, round(src_w * scale))
    fitted_h = max(1, round(src_h * scale))
    resized = source.resize((fitted_w, fitted_h), Image.Resampling.LANCZOS)
    left = max(0, (fitted_w - width) // 2)
    top = max(0, (fitted_h - height) // 2)
    return resized.crop((left, top, left + width, top + height))


def stretch_image_to_canvas(image: Image.Image, width: int, height: int) -> Image.Image:
    """Stretch to exact canvas size (matches object-fit: fill)."""
    source = image.convert("RGBA")
    if source.size == (width, height):
        return source
    return source.resize((width, height), Image.Resampling.LANCZOS)


def compose_image_to_canvas(
    image: Image.Image,
    width: int,
    height: int,
    fit_mode: str = "fit",
    background_color: str = DEFAULT_CANVAS_COLOR,
) -> Image.Image:
    mode = normalize_reference_fit_mode(fit_mode)
    if mode == "stretch":
        layer = stretch_image_to_canvas(image, width, height)
    elif mode == "fill":
        layer = fill_image_to_canvas(image, width, height)
    else:
        layer = fit_image_to_canvas(image, width, height)
    bg_rgb = hex_to_rgb(background_color)
    canvas = Image.new("RGB", (width, height), bg_rgb)
    if layer.mode == "RGBA":
        canvas.paste(layer, (0, 0), layer)
    else:
        canvas.paste(layer, (0, 0))
    return canvas


def is_psd_path(path: Path) -> bool:
    return path.suffix.lower() in PSD_EXTENSIONS


def export_psd_composite_to_png(psd_path: Path, destination_path: Path) -> Path:
    from psd_tools import PSDImage

    destination_path.parent.mkdir(parents=True, exist_ok=True)
    destination_path = destination_path.with_suffix(".png")
    psd = PSDImage.open(psd_path)
    image = psd.composite(layer_filter=preview_export_layer_filter)
    if image.mode not in ("RGB", "RGBA"):
        image = image.convert("RGBA")
    image.save(destination_path, "PNG")
    return destination_path


def ensure_psd_board_background_layer(psd_path: Path, background_path: Path) -> bool:
    """Insert or refresh the board reference image as the bottom art layer."""
    from psd_tools import PSDImage

    if not psd_path.is_file() or not background_path.is_file():
        return False

    psd = PSDImage.open(psd_path)
    for layer in list(psd.descendants()):
        if str(getattr(layer, "name", "") or "") == SB_BG_LAYER_NAME:
            psd.remove(layer)

    with Image.open(background_path) as image:
        fitted = fit_image_to_canvas(image, psd.width, psd.height)
        layer = psd.create_pixel_layer(fitted, name=SB_BG_LAYER_NAME)
        psd.insert(0, layer)

    psd.save(psd_path)
    return True


def is_solid_color_image(path: Path, sample_points: int = 12) -> bool:
    if not path.is_file():
        return False
    try:
        with Image.open(path) as image:
            rgba = image.convert("RGBA")
            width, height = rgba.size
            if width <= 0 or height <= 0:
                return False
            points = {
                (0, 0),
                (width - 1, 0),
                (0, height - 1),
                (width - 1, height - 1),
                (width // 2, height // 2),
            }
            step_x = max(1, width // 4)
            step_y = max(1, height // 4)
            for x in range(0, width, step_x):
                for y in range(0, height, step_y):
                    points.add((min(x, width - 1), min(y, height - 1)))
                    if len(points) >= sample_points:
                        break
                if len(points) >= sample_points:
                    break
            # Transparent/semi-transparent pixels mean this is an artwork export from
            # Photoshop, not a flat canvas plate.
            if any(rgba.getpixel(point)[3] < 255 for point in points):
                return False
            rgb = rgba.convert("RGB")
            reference = rgb.getpixel((0, 0))
            return all(rgb.getpixel(point) == reference for point in points)
    except OSError:
        return False


def image_has_transparency(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        with Image.open(path) as image:
            if image.mode in ("RGBA", "LA"):
                alpha = image.getchannel("A")
                extrema = alpha.getextrema()
                return bool(extrema and extrema[0] < 255)
            if image.mode == "P":
                transparency = image.info.get("transparency")
                return transparency is not None
            return False
    except OSError:
        return False


def create_solid_preview_png(
    destination_path: Path,
    width: int,
    height: int,
    background_color: str = DEFAULT_CANVAS_COLOR,
) -> Path:
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    destination_path = destination_path.with_suffix(".png")
    rgb = hex_to_rgb(background_color)
    Image.new("RGB", (width, height), rgb).save(destination_path, "PNG")
    return destination_path


def create_blank_psd(
    destination_path: Path,
    width: int = 1920,
    height: int = 1080,
    background_color: tuple[int, int, int] | str = DEFAULT_CANVAS_COLOR,
) -> Path:
    from psd_tools import PSDImage

    destination_path.parent.mkdir(parents=True, exist_ok=True)
    destination_path = destination_path.with_suffix(".psd")
    if isinstance(background_color, str):
        rgb = hex_to_rgb(background_color)
    else:
        rgb = background_color
    tmp_path = destination_path.with_suffix(".tmp.psd")
    try:
        psd = PSDImage.new("RGB", (width, height), color=rgb)
        psd.save(tmp_path)
        os.replace(tmp_path, destination_path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
    return destination_path


def copy_and_convert_image(source_path: Path, destination_path: Path) -> Path:
    if source_path.suffix.lower() not in SUPPORTED_IMAGE_EXTENSIONS:
        raise ValueError("Unsupported image format. Use PNG, JPG, JPEG, or TIFF.")

    destination_path.parent.mkdir(parents=True, exist_ok=True)
    final = destination_path.with_suffix(".png")
    tmp = final.with_suffix(".tmp.png")
    try:
        with Image.open(source_path) as image:
            if image.mode not in ("RGB", "RGBA"):
                image = image.convert("RGBA")
            image.save(tmp, "PNG")
        os.replace(tmp, final)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return final


def copy_and_convert_image_stream(
    source_stream: BinaryIO,
    source_suffix: str,
    destination_path: Path,
) -> Path:
    if source_suffix.lower() not in SUPPORTED_IMAGE_EXTENSIONS:
        raise ValueError("Unsupported image format. Use PNG, JPG, JPEG, or TIFF.")

    destination_path.parent.mkdir(parents=True, exist_ok=True)
    final = destination_path.with_suffix(".png")
    tmp = final.with_suffix(".tmp.png")
    try:
        with Image.open(source_stream) as image:
            if image.mode not in ("RGB", "RGBA"):
                image = image.convert("RGBA")
            image.save(tmp, "PNG")
        os.replace(tmp, final)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return final


def create_thumbnail(source_path: Path, thumbnail_path: Path) -> Path:
    thumbnail_path.parent.mkdir(parents=True, exist_ok=True)
    final = thumbnail_path.with_suffix(".png")
    tmp = final.with_suffix(".tmp.png")
    try:
        with Image.open(source_path) as image:
            image.thumbnail(THUMBNAIL_SIZE)
            if image.mode not in ("RGB", "RGBA"):
                image = image.convert("RGBA")
            image.save(tmp, "PNG")
        os.replace(tmp, final)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return final


def create_blank_canvas(
    destination_path: Path,
    width: int = 1920,
    height: int = 1080,
    background_color: str = DEFAULT_CANVAS_COLOR,
) -> Path:
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (width, height), normalize_hex_color(background_color))
    draw = ImageDraw.Draw(image)
    draw.rectangle((40, 40, width - 40, height - 40), outline="#d0d0d0", width=4)
    draw.text((72, 72), "Storyboard canvas", fill="#888888", font=ImageFont.load_default())
    image.save(destination_path.with_suffix(".png"), "PNG")
    return destination_path.with_suffix(".png")


def save_png_data_url(data_url: str, destination_path: Path) -> Path:
    prefix = "data:image/png;base64,"
    if not data_url.startswith(prefix):
        raise ValueError("Expected a PNG data URL.")
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    raw = base64.b64decode(data_url[len(prefix):])
    final = destination_path.with_suffix(".png")
    tmp = final.with_suffix(".tmp.png")
    try:
        with Image.open(BytesIO(raw)) as image:
            image.save(tmp, "PNG")
        os.replace(tmp, final)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return final


def create_placeholder_if_needed() -> str:
    return "No Image"
