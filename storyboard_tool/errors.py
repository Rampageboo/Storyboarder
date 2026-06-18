"""Structured application error codes and factory.

Every app-level error has a machine-readable code so callers (frontend, logs)
can branch without parsing the human-readable message string.

Usage::

    from .errors import AppErrorCode, app_error
    raise app_error(AppErrorCode.SHOT_NOT_FOUND, f"Shot not found: {shot_id}", status=404)

The custom exception handler in ``api.create_app`` flattens the response body
so existing frontend code that reads ``payload.detail`` still works, and new
code can additionally branch on ``payload.code``.
"""

from __future__ import annotations

from fastapi import HTTPException


class AppErrorCode:
    PROJECT_NOT_OPEN = "PROJECT_NOT_OPEN"
    PROJECT_OPEN_FAILED = "PROJECT_OPEN_FAILED"
    PROJECT_SAVE_FAILED = "PROJECT_SAVE_FAILED"
    SHOT_NOT_FOUND = "SHOT_NOT_FOUND"
    MEDIA_NOT_FOUND = "MEDIA_NOT_FOUND"
    REF_APPLY_FAILED = "REF_APPLY_FAILED"
    EXPORT_FAILED = "EXPORT_FAILED"
    INVALID_REQUEST = "INVALID_REQUEST"


def app_error(code: str, message: str, *, status: int = 400) -> HTTPException:
    """Return an HTTPException carrying a structured body.

    The ``api.create_app`` exception handler sees ``detail`` as a dict and
    returns it directly, producing ``{"detail": message, "code": code}``
    instead of FastAPI's default ``{"detail": {...}}``.  This keeps the
    ``detail`` key at the top level so existing frontend and bridge code
    that reads ``payload.detail`` continues to work unchanged.
    """
    return HTTPException(status_code=status, detail={"detail": message, "code": code})
