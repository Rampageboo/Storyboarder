from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from storyboard_tool import api as api_module


def _client_with_shots(tmp_path: Path, count: int = 3) -> tuple[TestClient, list[str]]:
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    project_parent = tmp_path / "project"
    project_parent.mkdir()
    client = TestClient(api_module.create_app(app_dir), raise_server_exceptions=False)
    created = client.post("/api/project/new", json={"path": str(project_parent)})
    assert created.status_code == 200, created.text
    shot_ids: list[str] = []
    for _index in range(count):
        added = client.post("/api/shots", json={})
        assert added.status_code == 200, added.text
        shot_ids.append(added.json()["shot"]["shot_id"])
    return client, shot_ids


def test_batch_update_delete_restore_and_queue(tmp_path: Path) -> None:
    client, shot_ids = _client_with_shots(tmp_path)
    selected = shot_ids[:2]

    updated = client.patch(
        "/api/shots/batch",
        json={
            "updates": [
                {"shot_id": shot_id, "changes": {"scene_id": "scene-a", "scene": "Atrium"}}
                for shot_id in selected
            ],
        },
    )
    assert updated.status_code == 200, updated.text
    by_id = {shot["shot_id"]: shot for shot in updated.json()["shots"]}
    assert all(by_id[shot_id]["scene_id"] == "scene-a" for shot_id in selected)
    assert by_id[shot_ids[2]]["scene_id"] == ""

    queued = client.post(
        "/api/shots/batch/generation-requests",
        json={"shot_ids": selected},
    )
    assert queued.status_code == 200, queued.text
    assert len(queued.json()["created_request_ids"]) == 2
    assert {request["shot_id"] for request in queued.json()["requests"]} == set(selected)

    before_delete = updated.json()["shots"]
    snapshots = [
        {"shot": shot, "index": index}
        for index, shot in enumerate(before_delete)
        if shot["shot_id"] in selected
    ]
    deleted = client.request("DELETE", "/api/shots/batch", json={"shot_ids": selected})
    assert deleted.status_code == 200, deleted.text
    assert [shot["shot_id"] for shot in deleted.json()["shots"]] == [shot_ids[2]]

    restored = client.post("/api/shots/batch/restore", json={"items": snapshots})
    assert restored.status_code == 200, restored.text
    assert [shot["shot_id"] for shot in restored.json()["shots"]] == shot_ids


def test_batch_mutations_validate_all_shots_before_changing_any(tmp_path: Path) -> None:
    client, shot_ids = _client_with_shots(tmp_path, count=2)
    invalid_id = "missing-shot"

    update = client.patch(
        "/api/shots/batch",
        json={
            "updates": [
                {"shot_id": shot_ids[0], "changes": {"scene": "Should roll back"}},
                {"shot_id": invalid_id, "changes": {"scene": "Missing"}},
            ],
        },
    )
    assert update.status_code == 400
    current = client.get("/api/project").json()
    assert all(shot["scene"] == "" for shot in current["shots"])

    deleted = client.request(
        "DELETE",
        "/api/shots/batch",
        json={"shot_ids": [shot_ids[0], invalid_id]},
    )
    assert deleted.status_code == 400
    assert [shot["shot_id"] for shot in client.get("/api/project").json()["shots"]] == shot_ids
