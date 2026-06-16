"""Recover a Photoshop-unopenable PSD by rebuilding it from its layers.

Photoshop is stricter than ``psd_tools`` about malformed PSDs, so a file that
triggers *"Could not open … because of a program error"* in Photoshop can often
still be read by ``psd_tools``. This module rasterises each leaf layer of such a
file to a full-canvas image and reassembles a clean PSD that Photoshop can open
again — the automated, no-Photoshop equivalent of the ``rebuild_temp`` scripts.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator

# Storyboarder / Photoshop plugin manage these layers from disk — recovering them
# from a broken PSD often duplicates or mis-orders the stack.
_PLUGIN_MANAGED_LAYER_NAMES = frozenset({"Background", "SB bg"})
_PLUGIN_MANAGED_LAYER_PREFIX = "SB ref:"


def can_open_with_psd_tools(psd_path: Path) -> bool:
    """True when ``psd_tools`` can read the file (so a rebuild is possible)."""
    from psd_tools import PSDImage

    try:
        PSDImage.open(psd_path)
        return True
    except Exception:
        return False


def _iter_leaf_layers(container) -> Iterator[Any]:
    """Yield leaf (non-group) layers in psd_tools' native order, flattening groups."""
    for layer in container:
        try:
            is_group = layer.is_group()
        except Exception:
            is_group = False
        if is_group:
            yield from _iter_leaf_layers(layer)
        else:
            yield layer


def _layer_to_canvas_image(layer, canvas_w: int, canvas_h: int):
    """Render a layer onto a transparent full-canvas RGBA image, or None if empty."""
    from PIL import Image

    try:
        image = layer.composite(force=True)
    except TypeError:
        image = layer.composite()
    if image is None:
        return None

    image = image.convert("RGBA")
    if image.size == (canvas_w, canvas_h):
        return image

    full = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    try:
        left, top = int(layer.bbox[0]), int(layer.bbox[1])
    except Exception:
        left, top = 0, 0
    full.paste(image, (left, top), image)
    return full


def _layer_own_image(layer, canvas_w: int, canvas_h: int):
    """The layer's own pixels (not blended with siblings) on a transparent canvas.

    Uses ``topil`` so blend mode / opacity can be re-applied as live properties;
    falls back to a per-layer composite when raw pixels are unavailable.
    """
    from PIL import Image

    image = None
    try:
        image = layer.topil()
    except Exception:
        image = None
    if image is None:
        try:
            image = layer.composite(force=True)
        except TypeError:
            image = layer.composite()
        except Exception:
            image = None
    if image is None:
        return None

    image = image.convert("RGBA")
    if image.size == (canvas_w, canvas_h):
        return image

    full = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    try:
        left, top = int(layer.offset[0]), int(layer.offset[1])
    except Exception:
        try:
            left, top = int(layer.bbox[0]), int(layer.bbox[1])
        except Exception:
            left, top = 0, 0
    full.paste(image, (left, top), image)
    return full


def _is_plugin_managed_layer_name(name: str) -> bool:
    text = str(name or "")
    if text in _PLUGIN_MANAGED_LAYER_NAMES:
        return True
    return text.startswith(_PLUGIN_MANAGED_LAYER_PREFIX)


def _recoverable_layer_image(layer, canvas_w: int, canvas_h: int):
    """Best-effort pixels for a drawing layer; None when nothing usable remains."""
    image = _layer_own_image(layer, canvas_w, canvas_h)
    if image is None:
        image = _layer_to_canvas_image(layer, canvas_w, canvas_h)
    if image is None:
        return None
    try:
        if image.getbbox() is None:
            return None
    except Exception:
        pass
    return image


def _copy_layer_properties(src_layer, dst_layer) -> None:
    try:
        dst_layer.visible = bool(getattr(src_layer, "visible", True))
    except Exception:
        pass
    try:
        blend_mode = getattr(src_layer, "blend_mode", None)
        if blend_mode is not None:
            dst_layer.blend_mode = blend_mode
    except Exception:
        pass
    try:
        opacity = getattr(src_layer, "opacity", None)
        if opacity is not None:
            dst_layer.opacity = int(opacity)
    except Exception:
        pass


def _rebuild_preserving_layers(broken_psd: Path, output_psd: Path) -> dict[str, Any]:
    """Reassemble a clean, openable PSD that keeps each layer's properties.

    Builds a brand-new file (so Photoshop can open it — a `psd_tools` round-trip
    of the original tends to keep whatever Photoshop choked on) while preserving
    every layer's own pixels, blend mode, opacity, and visibility. Editability of
    text / smart objects and masks is not retained (those rasterise to pixels).
    """
    from psd_tools import PSDImage

    source = PSDImage.open(broken_psd)
    width, height = source.size
    rebuilt = PSDImage.new("RGBA", (width, height))

    recovered = 0
    skipped: list[str] = []
    for layer in _iter_leaf_layers(source):
        name = str(getattr(layer, "name", "") or "Layer")[:255]
        if _is_plugin_managed_layer_name(name):
            skipped.append(name)
            continue
        image = _recoverable_layer_image(layer, width, height)
        if image is None:
            skipped.append(name)
            continue
        pixel_layer = rebuilt.create_pixel_layer(image, name=name)
        _copy_layer_properties(layer, pixel_layer)
        rebuilt.append(pixel_layer)
        recovered += 1

    if recovered == 0:
        raise ValueError("No recoverable layers were found in the PSD.")

    rebuilt.save(output_psd)
    return {
        "output": str(output_psd),
        "width": int(width),
        "height": int(height),
        "layers_recovered": recovered,
        "layers_skipped": skipped,
        "method": "layers",
    }


def _rebuild_flattened(broken_psd: Path, output_psd: Path) -> dict[str, Any]:
    """Reassemble a new PSD from each layer rasterised to a full-canvas image.

    Lossy (blend modes / effects / editability are baked into pixels) but the
    most robust path: every layer becomes a brand-new, simple pixel layer.
    """
    from psd_tools import PSDImage

    source = PSDImage.open(broken_psd)
    width, height = source.size
    rebuilt = PSDImage.new("RGBA", (width, height))

    recovered = 0
    skipped: list[str] = []
    for layer in _iter_leaf_layers(source):
        name = str(getattr(layer, "name", "") or "Layer")[:255]
        if _is_plugin_managed_layer_name(name):
            skipped.append(name)
            continue
        image = _recoverable_layer_image(layer, width, height)
        if image is None:
            skipped.append(name)
            continue
        pixel_layer = rebuilt.create_pixel_layer(image, name=name)
        try:
            pixel_layer.visible = bool(getattr(layer, "visible", True))
        except Exception:
            pass
        rebuilt.append(pixel_layer)
        recovered += 1

    if recovered == 0:
        raise ValueError("No recoverable layers were found in the PSD.")

    rebuilt.save(output_psd)
    return {
        "output": str(output_psd),
        "width": int(width),
        "height": int(height),
        "layers_recovered": recovered,
        "layers_skipped": skipped,
        "method": "flatten",
    }


def rebuild_psd(broken_psd: Path, output_psd: Path, *, preserve_layers: bool = True) -> dict[str, Any]:
    """Rebuild ``broken_psd`` into ``output_psd``.

    With ``preserve_layers`` (default) it keeps the original layer data via a
    psd_tools round-trip, falling back to a flattened rebuild only if that cannot
    be written. With ``preserve_layers=False`` it flattens directly — use this
    when a layer-preserving rebuild still won't open in Photoshop. The result dict
    reports which ``method`` was used.
    """
    broken_psd = Path(broken_psd)
    output_psd = Path(output_psd).with_suffix(".psd")
    output_psd.parent.mkdir(parents=True, exist_ok=True)

    if preserve_layers:
        try:
            return _rebuild_preserving_layers(broken_psd, output_psd)
        except Exception:
            # Round-trip could not be written cleanly — flatten instead.
            pass
    return _rebuild_flattened(broken_psd, output_psd)
