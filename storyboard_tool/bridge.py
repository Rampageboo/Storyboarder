from __future__ import annotations

import json
from typing import Any

from starlette.testclient import TestClient


class DesktopBridge:
    """Expose the FastAPI app to the desktop UI via pywebview js_api."""

    def __init__(self, asgi_app) -> None:
        self._app = asgi_app
        self._client = TestClient(asgi_app, raise_server_exceptions=False)
        self._ref_video_window = None

    def ping(self) -> str:
        return "python-backend-ready"

    def api_call(self, method: str, args_json: str = "[]") -> Any:
        try:
            raw_args = json.loads(args_json or "[]")
            if not isinstance(raw_args, list):
                raise ValueError("Args must be a JSON array.")
        except Exception as exc:
            raise RuntimeError(str(exc)) from exc
        response = self._client.post("/api", json={"method": method, "args": raw_args})
        payload = self._parse(response)
        if isinstance(payload, dict) and payload.get("ok") is False:
            raise RuntimeError(str(payload.get("error") or "API call failed"))
        if isinstance(payload, dict) and "result" in payload:
            return payload["result"]
        return payload

    def apiCall(self, method: str, args_json: str = "[]") -> Any:
        return self.api_call(method, args_json)

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

    def uploadMultipart(self, path: str, filename: str, content_type: str, data: list[int]) -> Any:
        return self.upload_multipart(path, filename, content_type, data)

    def open_ref_video_window(self, segment_id: str = "") -> bool:
        try:
            import webview
        except ImportError:
            return False
        port = int(getattr(self._app.state, "bridge_port", 8000) or 8000)
        query = f"?segment={segment_id}" if str(segment_id or "").strip() else ""
        url = f"http://127.0.0.1:{port}/ref-video{query}"
        if self._ref_video_window is not None:
            try:
                if hasattr(self._ref_video_window, "load_url"):
                    self._ref_video_window.load_url(url)
                self._ref_video_window.show()
                return True
            except Exception:
                self._ref_video_window = None
        try:
            self._ref_video_window = webview.create_window(
                "Video",
                url,
                width=980,
                height=720,
                min_size=(720, 520),
                resizable=True,
                js_api=self,
            )
            return True
        except Exception:
            self._ref_video_window = None
            return False

    def openRefVideoWindow(self, segment_id: str = "") -> bool:
        return self.open_ref_video_window(segment_id)

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
