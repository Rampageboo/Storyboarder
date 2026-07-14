"""PSD canvas pixel-budget guard (protects the psd_tools composite paths)."""
from __future__ import annotations

import pytest

from storyboard_tool.image_utils import MAX_PSD_PIXELS, _ensure_psd_pixel_budget


def test_normal_canvas_sizes_pass():
    for width, height in [(1920, 1080), (3840, 2160), (8192, 8192)]:
        _ensure_psd_pixel_budget(width, height)  # must not raise


def test_oversized_canvas_rejected():
    with pytest.raises(ValueError):
        _ensure_psd_pixel_budget(100_000, 100_000)  # 10 GP


def test_boundary_is_inclusive():
    # Exactly at the cap is allowed; one pixel over is not.
    _ensure_psd_pixel_budget(MAX_PSD_PIXELS, 1)
    with pytest.raises(ValueError):
        _ensure_psd_pixel_budget(MAX_PSD_PIXELS + 1, 1)


def test_non_numeric_dimensions_are_ignored():
    # Defensive: unexpected types must not raise from the guard itself.
    _ensure_psd_pixel_budget(None, None)  # type: ignore[arg-type]
