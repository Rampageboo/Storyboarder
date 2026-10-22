"""Behavioral checks for the service's explicit mutation boundaries.

The fixture is a review inventory, not an execution registry. Null means the
operation was historically outside the generic boundary (including lifecycle
coordinators, runtime/session operations and methods with their own locks).
Every public method, including inherited mixin handlers, must have an explicit
policy decision in this inventory;
it cannot silently bypass review by being omitted from a runtime name list.
"""
from __future__ import annotations

import inspect
import json
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from conftest import make_project
from storyboard_tool import app_state, project_document, project_manager, project_transaction
from storyboard_tool.backend_service import StoryboardBackendService
from storyboard_tool.models import Project, Shot
from storyboard_tool.mutation_executor import MutationPolicy, project_mutation


def _app(project):
    return SimpleNamespace(state=SimpleNamespace(
        project=project, project_disk_mtime=12,
        external_blender_context_revision=34,
    ))


def test_every_service_operation_has_a_reviewed_policy():
    expected = json.loads((Path(__file__).parent / "fixtures/backend_mutation_policies.json").read_text(encoding="utf-8"))
    actual = {}
    for name, method in inspect.getmembers(StoryboardBackendService):
        if not name.startswith("method_") or not callable(method):
            continue
        policy = getattr(method, "mutation_policy", None)
        actual[name] = policy.name if policy is not None else None
        if policy is not None:
            assert inspect.signature(method) == inspect.signature(method.__wrapped__)
            assert method.__name__ == name
    assert actual == expected, "Review new/changed service operations and their declaration-local mutation policies."


def test_policies_are_serialized_transaction_and_save_as_only():
    assert {policy.name for policy in MutationPolicy} == {"SERIALIZED", "TRANSACTION", "SAVE_AS"}


@pytest.fixture
def execution_trace(monkeypatch):
    events = []

    @contextmanager
    def scope(name):
        events.append(f"enter:{name}")
        try:
            yield
        finally:
            events.append(f"exit:{name}")

    # Each lock must be reusable for nested lifecycle coordinator acquisition.
    class Lock:
        def __init__(self, name):
            self.name = name

        def __enter__(self):
            events.append(f"enter:{self.name}")

        def __exit__(self, *exc):
            events.append(f"exit:{self.name}")

    monkeypatch.setattr(project_manager, "PROJECT_LOCK", Lock("project"))
    monkeypatch.setattr(project_manager, "PROJECT_TRANSITION_LOCK", Lock("transition"))
    monkeypatch.setattr(project_transaction, "mutate_project", lambda project: scope("memory"))
    monkeypatch.setattr(project_document, "mutation_transaction", lambda root: scope("disk"))
    return events


@pytest.mark.parametrize("policy", list(MutationPolicy))
@pytest.mark.parametrize("project_open", [False, True])
def test_policy_selects_exact_lock_and_rollback_scope(execution_trace, policy, project_open):
    project = Project(root_path=Path("unused")) if project_open else None
    service = SimpleNamespace(app=_app(project))

    @project_mutation(policy)
    def arbitrary_name(self, value, *, extra):
        execution_trace.append("body")
        return value + extra

    assert arbitrary_name(service, 2, extra=3) == 5
    if policy is MutationPolicy.SAVE_AS:
        scopes = ["transition"]
    else:
        scopes = ["project"]
        if project_open and policy is MutationPolicy.TRANSACTION:
            scopes += ["disk", "memory"]
    assert execution_trace == [f"enter:{name}" for name in scopes] + ["body"] + [f"exit:{name}" for name in reversed(scopes)]


def test_lifecycle_coordinator_quiesces_before_project_lock(execution_trace):
    service = SimpleNamespace(app=_app(Project(root_path=Path("unused"))))

    @project_mutation(MutationPolicy.SAVE_AS)
    def coordinator(self):
        execution_trace.append("quiesce")
        with project_manager.PROJECT_TRANSITION_LOCK:
            with project_manager.PROJECT_LOCK:
                execution_trace.append("body")
                raise RuntimeError("coordinator failed")

    with pytest.raises(RuntimeError, match="coordinator failed"):
        coordinator(service)
    assert execution_trace == [
        "enter:transition", "quiesce", "enter:transition", "enter:project",
        "body", "exit:project", "exit:transition", "exit:transition",
    ]


def _tree_bytes(root):
    return {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def _saved_project(tmp_path):
    project = make_project(tmp_path, "Story", canvas_width=64, canvas_height=64)
    project.shots = [Shot(shot_id="a", title="before")]
    project.settings["backup_on_save"] = False
    project_manager.save_project(project)
    return project


def test_transaction_failure_restores_disk_memory_revision_and_active_app(tmp_path):
    project = _saved_project(tmp_path)
    app = _app(project)
    service = SimpleNamespace(app=app)
    before_disk = _tree_bytes(project.project_root)
    before_settings = json.loads(json.dumps(project.settings))
    before_revision = project.storage_revision
    new_asset = project.project_root / "assets" / "new.bin"

    @project_mutation(MutationPolicy.TRANSACTION)
    def edit(self):
        # Nested real transactions must compose with the method-wide boundary.
        with project_document.mutation_transaction(project.project_root):
            project_document.enlist_mutation_paths(project.project_root, [new_asset])
            new_asset.parent.mkdir(parents=True, exist_ok=True)
            new_asset.write_bytes(b"new")
            project.shots[0].title = "after"
            project.settings["mutation_probe"] = True
            app_state.persist_project_mutation(self.app)
        assert project.storage_revision > before_revision
        app.state.project = Project(root_path=tmp_path / "wrong")
        app.state.project_disk_mtime = 99
        raise RuntimeError("after persistence")

    with pytest.raises(RuntimeError, match="after persistence"):
        edit(service)
    assert app.state.project is project
    assert project.shots[0].title == "before"
    assert project.settings == before_settings
    assert project.storage_revision == before_revision
    assert app.state.project_disk_mtime == 12
    assert _tree_bytes(project.project_root) == before_disk
    assert not new_asset.exists()
    reopened = project_manager.open_project(project.document_path)
    assert reopened.shots[0].title == "before"
    assert reopened.storage_revision == before_revision


def test_serialized_failure_leaves_the_operation_to_own_rollback(tmp_path):
    project = _saved_project(tmp_path)
    app = _app(project)
    service = SimpleNamespace(app=app)
    before_revision = project.storage_revision

    @project_mutation(MutationPolicy.SERIALIZED)
    def edit(self):
        project.shots[0].title = "after"
        app_state.persist_project_mutation(self.app)
        raise RuntimeError("after persistence")

    with pytest.raises(RuntimeError, match="after persistence"):
        edit(service)
    assert project.shots[0].title == "after"
    assert project.storage_revision == before_revision + 1
    reopened = project_manager.open_project(project.document_path)
    assert reopened.shots[0].title == "after"


def test_transaction_app_state_restoration_also_runs_on_base_exception(execution_trace):
    project = Project(root_path=Path("unused"), storage_revision=5)
    app = _app(project)
    service = SimpleNamespace(app=app)

    class Abort(BaseException):
        pass

    @project_mutation(MutationPolicy.TRANSACTION)
    def edit(self):
        project.storage_revision = 6
        app.state.project = None
        app.state.project_disk_mtime = 99
        raise Abort()

    with pytest.raises(Abort):
        edit(service)
    assert app.state.project is project
    assert project.storage_revision == 5
    assert app.state.project_disk_mtime == 12
    assert execution_trace == ["enter:project", "enter:disk", "enter:memory", "exit:memory", "exit:disk", "exit:project"]
