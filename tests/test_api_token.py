"""CORS restriction, per-launch API token gate, and request-size rejection."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from storyboard_tool import api as api_module

_TOKEN = "launchtoken_ABC-123"


def _app(monkeypatch, *, token: str | None = None):
    if token:
        monkeypatch.setenv("STORYBOARDER_LAUNCH_TOKEN", token)
    else:
        monkeypatch.delenv("STORYBOARDER_LAUNCH_TOKEN", raising=False)
    tmp = tempfile.mkdtemp()
    app = api_module.create_app(Path(tmp))
    return app, TestClient(app, raise_server_exceptions=False), tmp


# ── CORS ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "origin,allowed",
    [
        ("https://evil.example.com", False),
        ("null", False),
        ("http://127.0.0.1:8000", True),
        ("http://localhost:5173", True),
        ("https://127.0.0.1:8443", True),
    ],
)
def test_cors_only_reflects_localhost(monkeypatch, origin, allowed):
    _app_obj, client, _tmp = _app(monkeypatch)
    resp = client.get("/api/app/session", headers={"Origin": origin})
    acao = resp.headers.get("access-control-allow-origin")
    if allowed:
        assert acao == origin
    else:
        assert acao is None


# ── Token gate ────────────────────────────────────────────────────────────────


def test_no_token_configured_leaves_api_open(monkeypatch):
    app, client, tmp = _app(monkeypatch, token=None)
    assert app.state.api_token == ""
    resp = client.post("/api/project/new", json={"path": tmp})
    assert resp.status_code == 200


def test_mutation_without_token_is_rejected(monkeypatch):
    _app_obj, client, tmp = _app(monkeypatch, token=_TOKEN)
    resp = client.post("/api/project/new", json={"path": tmp})
    assert resp.status_code == 403
    assert resp.json().get("code") == "UNAUTHORIZED"


def test_mutation_with_wrong_token_is_rejected(monkeypatch):
    _app_obj, client, tmp = _app(monkeypatch, token=_TOKEN)
    resp = client.post(
        "/api/project/new", json={"path": tmp}, headers={"X-Storyboarder-Token": "wrong"}
    )
    assert resp.status_code == 403


def test_mutation_with_correct_token_succeeds(monkeypatch):
    _app_obj, client, tmp = _app(monkeypatch, token=_TOKEN)
    resp = client.post(
        "/api/project/new", json={"path": tmp}, headers={"X-Storyboarder-Token": _TOKEN}
    )
    assert resp.status_code == 200


def test_get_requests_do_not_require_token(monkeypatch):
    # GET/media routes must stay open: <img>/<a> loads cannot send custom headers.
    _app_obj, client, _tmp = _app(monkeypatch, token=_TOKEN)
    resp = client.get("/api/app/session")
    assert resp.status_code == 200


def test_cross_origin_post_without_token_does_not_mutate(monkeypatch):
    app, client, tmp = _app(monkeypatch, token=_TOKEN)
    # Open a project (authenticated) and record the shot count.
    client.post("/api/project/new", json={"path": tmp}, headers={"X-Storyboarder-Token": _TOKEN})
    before = len(app.state.project.shots)
    # Simulate a hostile cross-origin page firing a preflight-exempt POST with no token.
    resp = client.post("/api/shots", headers={"Origin": "https://evil.example.com"})
    assert resp.status_code == 403
    assert len(app.state.project.shots) == before


def test_index_injects_token_meta(monkeypatch):
    _app_obj, client, _tmp = _app(monkeypatch, token=_TOKEN)
    resp = client.get("/")
    # The dist build may or may not exist in CI; only assert injection when served.
    if resp.status_code == 200 and "text/html" in resp.headers.get("content-type", ""):
        assert f'content="{_TOKEN}"' in resp.text


def test_index_has_no_token_meta_when_unset(monkeypatch):
    _app_obj, client, _tmp = _app(monkeypatch, token=None)
    resp = client.get("/")
    if resp.status_code == 200:
        assert "storyboarder-token" not in resp.text


# ── Request-size rejection (ASGI level, before multipart parsing) ─────────────


def test_oversized_content_length_rejected(monkeypatch):
    monkeypatch.setattr(api_module, "_MAX_UPLOAD_BYTES", 100)
    _app_obj, client, _tmp = _app(monkeypatch, token=None)
    resp = client.post("/api/project/new", json={"path": "x" * 500})
    assert resp.status_code == 413
    assert resp.json().get("code") == "PAYLOAD_TOO_LARGE"
