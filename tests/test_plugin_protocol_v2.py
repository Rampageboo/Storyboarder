from __future__ import annotations

import hashlib
import json
import time
import uuid
from pathlib import Path
from unittest import mock

import pytest
from fastapi.testclient import TestClient

from storyboard_tool import api as api_module
from storyboard_tool import live_bridge, project_manager
from storyboard_tool.models import Project, Shot
from storyboard_tool.plugin_service import (
    EXPLICIT_ASSET_PATHS_CAPABILITY,
    PLUGIN_PROTOCOL_VERSION,
)

MINI_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082"
)


def _layout2_client(tmp_path: Path) -> tuple[TestClient, object, Project, str]:
    project_root = tmp_path / "Portable"
    work_root = project_root / ".storyboarder" / "work"
    work_root.mkdir(parents=True)
    shot_id = "shot-protocol"
    project = Project(
        root_path=work_root,
        project_root_path=project_root,
        document_path=project_root / "Portable.sbd",
        layout=2,
        project_id=str(uuid.uuid4()),
        storage_revision=7,
        shots=[Shot(shot_id=shot_id, title="Protocol shot")],
        settings=dict(project_manager.DEFAULT_SETTINGS),
    )
    app = api_module.create_app(tmp_path / "app")
    app.state.project = project
    app.state.project_disk_mtime = 0.0
    app.state.dirty = True
    bridge_dir = tmp_path / "bridge"
    bridge_dir.mkdir()
    patchers = [
        mock.patch.object(live_bridge, "global_bridge_dir", return_value=bridge_dir),
        mock.patch.object(live_bridge, "shared_bridge_dir", return_value=bridge_dir),
    ]
    for patcher in patchers:
        patcher.start()
    client = TestClient(app, raise_server_exceptions=False)
    client._storyboarder_patchers = patchers  # type: ignore[attr-defined]
    return client, app, project, shot_id


def _close_client(client: TestClient) -> None:
    client.close()
    for patcher in getattr(client, "_storyboarder_patchers", []):
        patcher.stop()


def _v2_headers(
    app,
    *,
    session: str | None = None,
    revision: int | None = None,
    work_key: str = "",
    asset_role: str = "",
    token: str = "",
) -> dict[str, str]:
    headers = {
        "x-storyboarder-protocol": str(PLUGIN_PROTOCOL_VERSION),
        "x-storyboarder-capabilities": EXPLICIT_ASSET_PATHS_CAPABILITY,
        "x-storyboarder-project-session": (
            str(app.state.project_session_id) if session is None else session
        ),
        "x-storyboarder-context-revision": str(7 if revision is None else revision),
    }
    if work_key:
        headers["x-storyboarder-work-key"] = work_key
    if asset_role:
        headers["x-storyboarder-asset-role"] = asset_role
    if token:
        headers["x-storyboarder-write-intent"] = token
    return headers


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("get", "/api/plugin/context", None),
        (
            "post",
            "/api/plugin/shots/shot-protocol/export-preview",
            {"preview_image_path": "C:/attacker.png"},
        ),
        (
            "post",
            "/api/plugin/shots/shot-protocol/psd-saved",
            {"source_file_path": "C:/attacker.psd"},
        ),
        ("post", "/api/plugin/shots/shot-protocol/focus", None),
        (
            "post",
            "/api/plugin/shots/next",
            {"current_shot_id": "shot-protocol", "auto_add": False},
        ),
        (
            "post",
            "/api/plugin/scenes2d/scene-x/perspectives/perspective-x/export-preview",
            None,
        ),
    ],
)
def test_layout2_old_protocol_is_426_before_any_path_disclosure(
    tmp_path: Path,
    method: str,
    path: str,
    body: dict | None,
) -> None:
    client, _app, project, _shot_id = _layout2_client(tmp_path)
    try:
        response = getattr(client, method)(path, json=body) if body is not None else getattr(client, method)(path)
    finally:
        _close_client(client)

    assert response.status_code == 426
    assert response.json()["code"] == "PLUGIN_UPGRADE_REQUIRED"
    text = response.text
    assert str(project.project_root) not in text
    assert str(project.metadata_root) not in text
    for forbidden in (
        "project_root",
        "project_json_path",
        "shot_folder",
        "source_file_path",
    ):
        assert forbidden not in response.json()


def test_layout2_v2_context_exposes_only_explicit_role_paths(tmp_path: Path) -> None:
    client, app, project, shot_id = _layout2_client(tmp_path)
    app.state.active_work_context = {
        "kind": "shot",
        "key": f"shot:{shot_id}",
        "shot_id": shot_id,
        "source_file_path": "../../attacker.psd",
        "source_native_path": "C:/attacker.psd",
    }
    try:
        response = client.get("/api/plugin/context", headers=_v2_headers(app))
    finally:
        _close_client(client)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["protocol_version"] == 2
    assert body["path_mode"] == "explicit-assets"
    assert body["offline_write_allowed"] is False
    assert body["project_root"] == ""
    assert body["project_json_path"] == ""
    assert body["project_session_id"] == app.state.project_session_id
    assert body["context_revision"] == 7
    assert body["work_context"]["source_file_path"] == f"PSD/Shots/{shot_id}.psd"
    assert "attacker" not in response.text
    item = next(entry for entry in body["work_items"] if entry["key"] == f"shot:{shot_id}")
    paths = item["asset_paths"]
    assert paths["source_psd"]["project_relative_path"] == f"PSD/Shots/{shot_id}.psd"
    assert paths["preview"]["project_relative_path"] == f"Images/Shots/{shot_id}_preview.png"
    assert paths["thumbnail"]["project_relative_path"] == (
        f".storyboarder/cache/thumbnails/{shot_id}.png"
    )
    assert paths["board_background"]["project_relative_path"] == (
        f"Images/Shots/{shot_id}_background.png"
    )
    for details in paths.values():
        assert str(project.project_root) in details["native_path"]
    live = body["bridge"]["live"]
    assert live["project_root"] == ""
    assert live["project_json_path"] == ""
    assert live["shot_folder"] == ""
    assert live["source_file_path"] == ""
    assert live["plugin_protocol_required"] == 2
    assert not (project.project_root / "storyboard_live_bridge.json").exists()


@pytest.mark.parametrize(
    ("headers", "message"),
    [
        ({"session": "stale-session"}, "session is stale"),
        ({"revision": 6}, "revision is stale"),
    ],
)
def test_layout2_write_intent_rejects_stale_context(
    tmp_path: Path,
    headers: dict[str, object],
    message: str,
) -> None:
    client, app, project, shot_id = _layout2_client(tmp_path)
    try:
        response = client.post(
            "/api/plugin/write-intents",
            headers=_v2_headers(app, **headers),
            json={"work_key": f"shot:{shot_id}", "asset_role": "preview"},
        )
    finally:
        _close_client(client)

    assert response.status_code == 409
    assert response.json()["code"] == "PLUGIN_PROTOCOL_REJECTED"
    assert message in response.json()["detail"]
    assert not (project.project_root / ".storyboarder" / "transactions").exists()


def test_layout2_write_intent_returns_scoped_inbox_not_client_path(tmp_path: Path) -> None:
    client, app, project, shot_id = _layout2_client(tmp_path)
    key = f"shot:{shot_id}"
    try:
        response = client.post(
            "/api/plugin/write-intents",
            headers=_v2_headers(app),
            json={"work_key": key, "asset_role": "preview"},
        )
    finally:
        _close_client(client)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["work_key"] == key
    assert body["asset_role"] == "preview"
    assert body["canonical_path"] == str(
        project.project_root / "Images" / "Shots" / f"{shot_id}_preview.png"
    )
    assert body["write_path"].endswith(
        f"plugin-inbox{Path('/').anchor}{shot_id}_preview.png"
    ) or body["write_path"].replace("\\", "/").endswith(
        f"plugin-inbox/{shot_id}_preview.png"
    )
    assert ".storyboarder" in body["write_path"]
    assert "transactions" in body["write_path"]
    assert body["token"] in app.state.plugin_write_intents


@pytest.mark.parametrize("token_state", ["unknown", "expired", "used"])
def test_layout2_preview_write_rejects_invalid_or_stale_intent(
    tmp_path: Path,
    token_state: str,
) -> None:
    client, app, project, shot_id = _layout2_client(tmp_path)
    key = f"shot:{shot_id}"
    try:
        issued = client.post(
            "/api/plugin/write-intents",
            headers=_v2_headers(app),
            json={"work_key": key, "asset_role": "preview"},
        ).json()
        token = "unknown-token" if token_state == "unknown" else issued["token"]
        if token_state == "expired":
            app.state.plugin_write_intents[token]["expires_at"] = time.monotonic() - 1.0
        elif token_state == "used":
            app.state.plugin_write_intents[token]["used"] = True
        response = client.post(
            f"/api/plugin/shots/{shot_id}/export-preview",
            headers=_v2_headers(
                app,
                work_key=key,
                asset_role="preview",
                token=token,
            ),
            json={"preview_image_path": "C:/must-not-be-used.png"},
        )
    finally:
        _close_client(client)

    assert response.status_code in {403, 409}
    assert response.json()["code"] == "PLUGIN_WRITE_INTENT_REJECTED"
    assert not (project.project_root / "C:" / "must-not-be-used.png").exists()


def test_layout2_preview_write_rejects_wrong_role_without_consuming_token(
    tmp_path: Path,
) -> None:
    client, app, _project, shot_id = _layout2_client(tmp_path)
    key = f"shot:{shot_id}"
    try:
        issued = client.post(
            "/api/plugin/write-intents",
            headers=_v2_headers(app),
            json={"work_key": key, "asset_role": "preview"},
        ).json()
        response = client.post(
            f"/api/plugin/shots/{shot_id}/export-preview",
            headers=_v2_headers(
                app,
                work_key=key,
                asset_role="source_psd",
                token=issued["token"],
            ),
            json={"preview_image_path": "C:/must-not-be-used.png"},
        )
        used = app.state.plugin_write_intents[issued["token"]]["used"]
    finally:
        _close_client(client)

    assert response.status_code == 409
    assert response.json()["code"] == "PLUGIN_WRITE_INTENT_REJECTED"
    assert used is False


def test_layout2_preview_commit_uses_inbox_and_ignores_client_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, app, project, shot_id = _layout2_client(tmp_path)
    key = f"shot:{shot_id}"
    monkeypatch.setattr(
        "storyboard_tool.plugin_service.app_state._autosave",
        lambda _app: None,
    )
    try:
        issued = client.post(
            "/api/plugin/write-intents",
            headers=_v2_headers(app),
            json={"work_key": key, "asset_role": "preview"},
        ).json()
        inbox = Path(issued["write_path"])
        inbox.write_bytes(MINI_PNG)
        malicious = tmp_path / "client-selected.png"
        response = client.post(
            f"/api/plugin/shots/{shot_id}/export-preview",
            headers=_v2_headers(
                app,
                work_key=key,
                asset_role="preview",
                token=issued["token"],
            ),
            json={"preview_image_path": str(malicious)},
        )
        replay = client.post(
            f"/api/plugin/shots/{shot_id}/export-preview",
            headers=_v2_headers(
                app,
                work_key=key,
                asset_role="preview",
                token=issued["token"],
            ),
            json={"preview_image_path": str(malicious)},
        )
    finally:
        _close_client(client)

    canonical = project.project_root / "Images" / "Shots" / f"{shot_id}_preview.png"
    assert response.status_code == 200, response.text
    assert canonical.read_bytes() == MINI_PNG
    assert project.shots[0].preview_image_path == f"Images/Shots/{shot_id}_preview.png"
    assert not malicious.exists()
    assert not inbox.parent.parent.exists()
    assert replay.status_code == 409
    assert replay.json()["code"] == "PLUGIN_WRITE_INTENT_REJECTED"


def test_layout2_native_psd_reconnect_validates_canonical_role_and_hash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, app, project, shot_id = _layout2_client(tmp_path)
    key = f"shot:{shot_id}"
    monkeypatch.setattr(
        "storyboard_tool.plugin_service.app_state._autosave",
        lambda _app: None,
    )
    try:
        issued = client.post(
            "/api/plugin/write-intents",
            headers=_v2_headers(app),
            json={"work_key": key, "asset_role": "source_psd"},
        ).json()
        canonical = Path(issued["canonical_path"])
        assert canonical.parent.is_dir()
        raw = b"8BPS" + b"\0" * 64
        canonical.write_bytes(raw)
        response = client.post(
            f"/api/plugin/shots/{shot_id}/psd-saved",
            headers=_v2_headers(
                app,
                work_key=key,
                asset_role="source_psd",
                token=issued["token"],
            ),
            json={"source_file_path": str(tmp_path / "attacker.psd")},
        )
    finally:
        _close_client(client)

    assert response.status_code == 200, response.text
    assert response.json()["source_sha256"] == hashlib.sha256(raw).hexdigest()
    assert project.shots[0].source_file_path == f"PSD/Shots/{shot_id}.psd"
    assert not (tmp_path / "attacker.psd").exists()


def test_layout2_live_bridge_scrubs_legacy_and_focus_paths(tmp_path: Path) -> None:
    client, app, project, shot_id = _layout2_client(tmp_path)
    app.state.active_work_context = {
        "kind": "shot",
        "key": f"shot:{shot_id}",
        "source_file_path": "PSD/Shots/secret.psd",
        "source_native_path": str(project.project_root / "PSD" / "Shots" / "secret.psd"),
    }
    try:
        payload = live_bridge.build_payload(
            project=project,
            selected_shot_id=shot_id,
            work_context={
                "kind": "shot",
                "key": f"shot:{shot_id}",
                "source_file_path": "PSD/Shots/secret.psd",
                "source_native_path": str(project.project_root / "PSD" / "Shots" / "secret.psd"),
            },
            focus_work_context={
                "kind": "shot",
                "key": f"shot:{shot_id}",
                "source_file_path": "PSD/Shots/secret.psd",
                "source_native_path": str(project.project_root / "PSD" / "Shots" / "secret.psd"),
            },
        )
        status = client.get("/api/bridge/status")
    finally:
        _close_client(client)

    assert payload["project_root"] == ""
    assert payload["project_json_path"] == ""
    assert payload["shot_folder"] == ""
    assert payload["source_file_path"] == ""
    assert "source_file_path" not in payload["work_context"]
    assert "source_native_path" not in payload["work_context"]
    assert payload["focus_request"]["source_file_path"] == ""
    assert payload["focus_request"]["source_native_path"] == ""
    assert status.status_code == 200
    assert "source_file_path" not in status.json()["work_context"]
    assert "source_native_path" not in status.json()["work_context"]
    assert str(project.project_root) not in status.text
