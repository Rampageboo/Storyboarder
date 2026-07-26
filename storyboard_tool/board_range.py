"""Board range specs for exports — the "Pages: 1-5, 8, 11-13" field.

Boards are addressed the way the user sees them in the strip: 1-based positions,
not shot ids. Parsing lives here (and only here) so the export routes, the
filename suffix, and the range field in the UI all agree on what a spec means.

Domain module: no FastAPI imports, no app state.
"""
from __future__ import annotations

import re

# Accept the dashes a user actually types, including what Word/Docs autocorrects
# a hyphen into.
_DASHES = "-‐‑‒–—"
_SEPARATORS = re.compile(r"[,;\s]+")
_TOKEN = re.compile(rf"^(\d*)\s*(?:([{_DASHES}])\s*(\d*))?$")

# Keeps a generated filename readable when the selection is long.
_MAX_SUFFIX_BOARDS = 3


def parse(spec: str, total: int) -> list[int]:
    """Resolve a range spec to ascending, de-duplicated 0-based board indexes.

    Accepts ``3``, ``1-5``, ``8-`` (to the end), ``-4`` (from the start), and any
    comma-separated mix. Raises ``ValueError`` with a message meant for the user.
    """
    if total <= 0:
        raise ValueError("This storyboard has no boards to export.")
    text = str(spec or "").strip()
    if not text:
        raise ValueError("Enter a board range, for example 1-5, 8.")

    selected: set[int] = set()
    for token in _SEPARATORS.split(text):
        if not token:
            continue
        match = _TOKEN.match(token)
        if match is None:
            raise ValueError(f"{token!r} is not a board number or range.")
        start_text, dash, end_text = match.groups()
        if dash:
            # Open-ended on either side: "8-" runs to the last board, "-4" from the first.
            start = _board_number(start_text, 1, token, total)
            end = _board_number(end_text, total, token, total)
            if start > end:
                start, end = end, start
            selected.update(range(start - 1, end))
        else:
            number = _board_number(start_text, None, token, total)
            selected.add(number - 1)

    if not selected:
        raise ValueError("Enter a board range, for example 1-5, 8.")
    return sorted(selected)


def _board_number(text: str, default: int | None, token: str, total: int) -> int:
    if not text:
        if default is None:
            raise ValueError(f"{token!r} is not a board number or range.")
        return default
    number = int(text)
    if number < 1 or number > total:
        raise ValueError(f"Board {number} does not exist — this storyboard has {total}.")
    return number


def is_contiguous(indexes: list[int]) -> bool:
    return bool(indexes) and indexes[-1] - indexes[0] == len(indexes) - 1


def filename_suffix(indexes: list[int], total: int) -> str:
    """Name an export after the boards in it, so ranges never overwrite each other.

    Empty when the selection is the whole storyboard — that output keeps its
    plain name.
    """
    if not indexes or len(indexes) == total:
        return ""
    if len(indexes) == 1:
        return f"_board-{indexes[0] + 1:03d}"
    if is_contiguous(indexes):
        return f"_boards-{indexes[0] + 1:03d}-{indexes[-1] + 1:03d}"
    if len(indexes) <= _MAX_SUFFIX_BOARDS:
        return "_boards-" + "+".join(f"{index + 1:03d}" for index in indexes)
    return f"_boards-{indexes[0] + 1:03d}-{indexes[-1] + 1:03d}-selection"


def describe(indexes: list[int], total: int) -> str:
    """Short human summary for the export dialog."""
    if not indexes:
        return "No boards selected"
    if len(indexes) == total:
        return f"All {total} boards"
    if len(indexes) == 1:
        return f"Board {indexes[0] + 1}"
    if is_contiguous(indexes):
        return f"Boards {indexes[0] + 1}-{indexes[-1] + 1} ({len(indexes)} of {total})"
    return f"{len(indexes)} of {total} boards"
