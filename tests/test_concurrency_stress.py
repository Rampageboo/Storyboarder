"""Concurrency stress: PROJECT_LOCK must make each mutation an atomic transaction.

Drives the service layer from many threads (the production model: FastAPI runs sync
endpoints on a threadpool and the plugin is a second client). Asserts no corruption:
no unexpected exceptions, no duplicate shot IDs, shots.json and shots.csv agree, and
the persisted state matches memory after a reload.
"""
from __future__ import annotations

import random
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import HTTPException

from storyboard_tool import project_manager
from storyboard_tool.api import create_app
from storyboard_tool.backend_service import StoryboardBackendService
from storyboard_tool.shot_store import (
    load_shots_csv,
    load_shots_json,
    shots_csv_path,
    shots_json_path,
)


def test_concurrent_mutations_keep_project_consistent():
    tmp = tempfile.mkdtemp()
    app = create_app(Path(tmp))
    svc = StoryboardBackendService(app)
    svc.method_new_project(path=tmp)
    for _ in range(5):
        svc.method_add_shot()

    errors: list[Exception] = []
    rng = random.Random(1234)

    def worker(i: int) -> None:
        try:
            op = i % 4
            if op == 0:
                svc.method_add_shot()
            elif op == 1:
                shots = list(app.state.project.shots)  # snapshot to avoid harness races
                if shots:
                    svc.method_delete_shot(rng.choice(shots).shot_id)
            elif op == 2:
                ids = [s.shot_id for s in list(app.state.project.shots)]
                rng.shuffle(ids)
                svc.method_reorder_shots(ids)
            else:
                svc.method_get_project()
        except HTTPException:
            # Racing delete (404) or reorder mismatch (400) are clean app-level
            # outcomes, not corruption — exactly what the lock should produce.
            pass
        except Exception as exc:  # noqa: BLE001 - any other exception is a real failure
            errors.append(exc)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(worker, range(64)))

    assert not errors, f"Unexpected exceptions under concurrency: {errors!r}"

    project = app.state.project
    mem_ids = [s.shot_id for s in project.shots]
    assert len(mem_ids) == len(set(mem_ids)), "duplicate shot IDs in memory"

    root = project.root_path
    json_ids = [s.shot_id for s in (load_shots_json(shots_json_path(root)) or [])]
    csv_ids = [s.shot_id for s in load_shots_csv(shots_csv_path(root))]
    assert json_ids == csv_ids, "shots.json and shots.csv disagree"

    reloaded = project_manager.open_project(project.json_path)
    assert [s.shot_id for s in reloaded.shots] == mem_ids, "disk state != memory after reload"
