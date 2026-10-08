"""Byte conversion shared by shot, reference and scene upload adapters."""
from __future__ import annotations

import io
from typing import BinaryIO

from fastapi import HTTPException


def normalize_upload_bytes(data: list[int] | bytes | bytearray) -> bytes:
    if isinstance(data, (bytes, bytearray)):
        return bytes(data)
    if isinstance(data, list):
        return bytes(int(value) & 0xFF for value in data)
    raise HTTPException(status_code=400, detail="Upload payload must be bytes.")


def upload_stream(data: list[int] | bytes | bytearray) -> BinaryIO:
    return io.BytesIO(normalize_upload_bytes(data))
