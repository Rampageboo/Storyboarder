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

from storyboard_tool import app_state, project_document, project_layout, project_manager, project_transaction, story_graph
from storyboard_tool.backend_service import StoryboardBackendService
from storyboard_tool.models import Project, Shot
from storyboard_tool.mutation_executor import MutationPolicy, project_mutation


def _app(project):
    return SimpleNamespace(state=SimpleNamespace(
        project=project, dirty=False, project_disk_mtime=12,
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


def test_metadata_transaction_historical_import_is_compatible():
    assert story_graph.metadata_transaction is project_transaction.metadata_transaction


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
    monkeypatch.setattr(project_transaction, "metadata_transaction", lambda app: scope("metadata"))
    monkeypatch.setattr(project_transaction, "mutate_project", lambda project: scope("memory"))
    monkeypatch.setattr(project_document, "layout2_mutation_transaction", lambda root: scope("disk"))
    return events


@pytest.mark.parametrize("policy", list(MutationPolicy))
@pytest.mark.parametrize("layout", [None, 1, 2])
@pytest.mark.parametrize("graph_present", [False, True])
def test_policy_selects_exact_lock_and_rollback_scope(execution_trace, policy, layout, graph_present):
    project = None if layout is None else Project(root_path=Path("unused"), layout=layout)
    if project is not None and graph_present:
        project.settings["story_graph"] = {}
    service = SimpleNamespace(app=_app(project))

    @project_mutation(policy)
    def arbitrary_name(self, value, *, extra):
        execution_trace.append("body")
        return value + extra

    assert arbitrary_name(service, 2, extra=3) == 5
    if policy is MutationPolicy.CONVERT:
        scopes = ["transition"]
    elif policy is MutationPolicy.SAVE_AS:
        scopes = ["transition"] + ([] if layout == 2 else ["project"])
    else:
        scopes = ["project"]
        if layout == 1 and (policy is MutationPolicy.METADATA or (policy is MutationPolicy.GRAPH_IF_PRESENT and graph_present)):
            scopes += ["metadata"]
        elif layout == 2 and policy is not MutationPolicy.SERIALIZED:
            scopes += ["disk", "memory"]
    assert execution_trace == [f"enter:{name}" for name in scopes] + ["body"] + [f"exit:{name}" for name in reversed(scopes)]


@pytest.mark.parametrize("policy,layout", [(MutationPolicy.CONVERT, 1), (MutationPolicy.SAVE_AS, 2)])
def test_lifecycle_coordinator_quiesces_before_project_lock(execution_trace, policy, layout):
    service = SimpleNamespace(app=_app(Project(root_path=Path("unused"), layout=layout)))

    @project_mutation(policy)
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


@pytest.mark.parametrize("policy,graph_present,rollback", [
    (MutationPolicy.METADATA, False, True),
    (MutationPolicy.GRAPH_IF_PRESENT, True, True),
    (MutationPolicy.GRAPH_IF_PRESENT, False, False),
    (MutationPolicy.SERIALIZED, True, False),
    (MutationPolicy.LAYOUT2, True, False),
])
def test_layout1_metadata_failure_preserves_conditional_rollback(tmp_path, policy, graph_present, rollback):
    project = Project(root_path=tmp_path, shots=[Shot(shot_id="a", title="before")])
    project.settings = {"nested": {"value": "before"}}
    if graph_present:
        project.settings["story_graph"] = {}
    app = _app(project)
    service = SimpleNamespace(app=app)
    metadata = [project.json_path, project.settings_path, project_manager.shots_json_path(tmp_path), project_manager.shots_csv_path(tmp_path)]
    # Cover restoring existing files and removing newly created metadata alike.
    for path in metadata[:-1]:
        path.write_bytes(b"before")
    artwork = tmp_path / "artwork.png"
    artwork.write_bytes(b"before")

    @project_mutation(policy)
    def edit(self):
        project.shots[0].title = "after"
        project.settings["nested"]["value"] = "after"
        for path in metadata:
            path.write_bytes(b"after")
        artwork.write_bytes(b"after")
        app.state.dirty = True
        app.state.project_disk_mtime = 99
        raise RuntimeError("save fault")

    with pytest.raises(RuntimeError, match="save fault"):
        edit(service)
    expected = "before" if rollback else "after"
    assert project.shots[0].title == expected
    assert project.settings["nested"]["value"] == expected
    assert [path.read_bytes() for path in metadata[:-1]] == [expected.encode()] * 3
    assert metadata[-1].exists() is (not rollback)
    assert app.state.dirty is (not rollback)
    assert app.state.project_disk_mtime == (12 if rollback else 99)
    assert artwork.read_bytes() == b"after", "Layout 1 metadata rollback must not rewrite artwork."


def _tree_bytes(root):
    return {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}


@pytest.mark.parametrize("policy", [MutationPolicy.METADATA, MutationPolicy.GRAPH_IF_PRESENT, MutationPolicy.LAYOUT2])
def test_layout2_failure_restores_disk_memory_revision_and_active_app(tmp_path, monkeypatch, policy):
    monkeypatch.setattr(project_layout, "LAYOUT_2_ENABLED", True)
    project = project_manager.create_layout2_document(tmp_path / "Story.sbd", canvas_width=64, canvas_height=64)
    project.shots = [Shot(shot_id="a", title="before")]
    project.settings["backup_on_save"] = False
    project_manager.save_project(project, flush_document=False)
    app = _app(project)
    service = SimpleNamespace(app=app)
    before_disk = _tree_bytes(project.project_root)
    before_settings = json.loads(json.dumps(project.settings))
    before_revision = project.storage_revision
    new_asset = project.project_root / "assets" / "new.bin"

    @project_mutation(policy)
    def edit(self):
        # Nested real transactions must compose with the method-wide boundary.
        with project_document.layout2_mutation_transaction(project.project_root):
            project_document.enlist_layout2_mutation_paths(project.project_root, [new_asset])
            new_asset.parent.mkdir(parents=True, exist_ok=True)
            new_asset.write_bytes(b"new")
            project.shots[0].title = "after"
            project.settings["mutation_probe"] = True
            app_state.persist_project_mutation(self.app)
        assert project.storage_revision > before_revision
        app.state.project = Project(root_path=tmp_path / "wrong")
        app.state.dirty = True
        app.state.project_disk_mtime = 99
        app.state.external_blender_context_revision = 100
        raise RuntimeError("after persistence")

    with pytest.raises(RuntimeError, match="after persistence"):
        edit(service)
    assert app.state.project is project
    assert project.shots[0].title == "before"
    assert project.settings == before_settings
    assert project.storage_revision == before_revision
    assert app.state.dirty is False
    assert app.state.project_disk_mtime == 12
    assert app.state.external_blender_context_revision == 34
    assert _tree_bytes(project.project_root) == before_disk
    assert not new_asset.exists()


def test_layout2_app_state_restoration_also_runs_on_base_exception(execution_trace):
    project = Project(root_path=Path("unused"), layout=2, storage_revision=5)
    app = _app(project)
    service = SimpleNamespace(app=app)

    class Abort(BaseException):
        pass

    @project_mutation(MutationPolicy.LAYOUT2)
    def edit(self):
        project.storage_revision = 6
        app.state.project = None
        app.state.dirty = True
        app.state.project_disk_mtime = 99
        app.state.external_blender_context_revision = 100
        raise Abort()

    with pytest.raises(Abort):
        edit(service)
    assert app.state.project is project
    assert project.storage_revision == 5
    assert app.state.dirty is False
    assert app.state.project_disk_mtime == 12
    assert app.state.external_blender_context_revision == 34
    assert execution_trace == ["enter:project", "enter:disk", "enter:memory", "exit:memory", "exit:disk", "exit:project"]
