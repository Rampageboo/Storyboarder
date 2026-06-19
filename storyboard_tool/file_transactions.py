"""Atomic file-copy helpers for cross-file transaction safety.

All helpers write to a temp file beside the destination and then
call os.replace() to commit atomically.  A crash or exception leaves
at most a stale .tmp file; the destination is never partially overwritten.

Usage pattern:
  atomic_copy_file(source, destination)

The existing image_utils helpers (copy_and_convert_image, save_png_data_url,
create_thumbnail, create_blank_psd) already follow this pattern.  This
module fills the remaining gap: plain binary-copy operations that otherwise
would use shutil.copy2 directly.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path


def atomic_copy_file(source: Path, destination: Path) -> Path:
    """Copy *source* to *destination* via a sibling temp file.

    Uses temp + os.replace() instead of shutil.copy2() so a crash mid-copy
    never leaves *destination* in a partial state.  If *source* and
    *destination* resolve to the same path this is a no-op.

    Raises the same exceptions as shutil.copy2 / os.replace.
    Returns *destination*.
    """
    if source.resolve() == destination.resolve():
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = destination.with_suffix(destination.suffix + ".tmp")
    try:
        shutil.copy2(source, tmp)
        os.replace(tmp, destination)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return destination
