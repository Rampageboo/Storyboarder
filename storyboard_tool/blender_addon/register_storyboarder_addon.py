"""Register Storyboarder's bundled Blender tools for this Blender session."""

from __future__ import annotations

import sys
from pathlib import Path


ADDON_ROOT = Path(__file__).resolve().parent
if str(ADDON_ROOT) not in sys.path:
    sys.path.insert(0, str(ADDON_ROOT))

import storyboarder_camera_path  # noqa: E402
import storyboarder_bridge  # noqa: E402


if hasattr(storyboarder_camera_path, "unregister"):
    try:
        storyboarder_camera_path.unregister()
    except (RuntimeError, AttributeError):
        pass

storyboarder_camera_path.register()
storyboarder_bridge.register()
print("Storyboarder: external scene bridge and camera-path tools registered")
