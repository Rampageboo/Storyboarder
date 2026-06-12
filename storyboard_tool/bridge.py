from __future__ import annotations

import json
from typing import Any

from starlette.testclient import TestClient


class DesktopBridge:
    """Expose the FastAPI app to the desktop UI via pywebview js_api."""

    def __init__(self, asgi_app) -> None:
        self._client = TestClient(asgi_app, raise_server_exceptions=False)

    def ping(self) -> str:
        return "python-backend-ready"

    def request(self, method: str, path: str, body: str | None = None) -> Any:
        method = method.upper()
        kwargs: dict[str, Any] = {}
        if body:
            kwargs["content"] = body.encode("utf-8")
            kwargs["headers"] = {"Content-Type": "application/json"}
        response = self._client.request(method, path, **kwargs)
        return self._parse(response)

    def upload_multipart(self, path: str, filename: str, content_type: str, data: list[int]) -> Any:
        files = {"file": (filename, bytes(data), content_type or "application/octet-stream")}
        response = self._client.post(path, files=files)
        return self._parse(response)

    def _parse(self, response) -> Any:
        if response.status_code >= 400:
            message = response.reason_phrase or "Request failed"
            try:
                payload = response.json()
                detail = payload.get("detail")
                if detail is not None:
                    message = detail if isinstance(detail, str) else json.dumps(detail)
            except Exception:
                if response.text:
                    message = response.text
            raise RuntimeError(message)
        if not response.content:
            return {}
        try:
            return response.json()
        except Exception:
            return {"text": response.text}
