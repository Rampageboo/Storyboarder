"""Pydantic models for API response shapes.

Used for documentation, typing, and test assertions.  Request models live in
``api.py`` alongside the route definitions that consume them.
"""

from __future__ import annotations

from pydantic import BaseModel


class ErrorBody(BaseModel):
    """Structured error response body returned by all app-level errors.

    ``detail`` is the human-readable message (preserved for backward
    compatibility — existing frontend and bridge code reads this field).
    ``code`` is a machine-readable constant from ``errors.AppErrorCode`` that
    callers can use for branching without string-matching the message.
    """

    detail: str
    code: str | None = None
