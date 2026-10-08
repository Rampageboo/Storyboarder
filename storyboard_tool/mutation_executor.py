"""Execution boundary for declaration-local backend mutation policies.

The service chooses a policy at each method. This module knows no operation
names: it only serializes execution and coordinates the existing rollback
mechanisms. Lifecycle coordinators must quiesce writers before taking the
project lock, so their transition-lock-first paths are deliberately separate.
"""
from __future__ import annotations

from contextlib import contextmanager
from enum import Enum
from functools import wraps

from . import project_document, project_manager, project_transaction
from .project_layout import LAYOUT_2


class MutationPolicy(Enum):
    SERIALIZED = "serialized"  # Project lock; the operation owns any rollback.
    GRAPH_IF_PRESENT = "graph_if_present"  # Layout 1 metadata only for stored graphs.
    METADATA = "metadata"  # Layout 1 metadata even before a graph exists.
    LAYOUT2 = "layout2"  # Recoverable Layout 2 work, memory and app state.
    SAVE_AS = "save_as"  # Layout 2 delegates project locking to its coordinator.
    CONVERT = "convert"  # Coordinator owns quiescing and project locking.


def project_mutation(policy: MutationPolicy):
    """Declare the whole-method boundary, retaining its callable signature."""
    def decorate(method):
        @wraps(method)
        def wrapper(self, *args, **kwargs):
            with mutation_scope(self.app, policy):
                return method(self, *args, **kwargs)

        wrapper.mutation_policy = policy
        return wrapper

    return decorate


@contextmanager
def mutation_scope(app, policy: MutationPolicy):
    if policy is MutationPolicy.CONVERT:
        # The coordinator owns quiesce and the transition -> project lock order.
        with project_manager.PROJECT_TRANSITION_LOCK:
            yield
        return

    if policy is MutationPolicy.SAVE_AS:
        with project_manager.PROJECT_TRANSITION_LOCK:
            project = getattr(app.state, "project", None)
            if project is not None and project.layout == LAYOUT_2:
                # The Layout 2 coordinator quiesces before taking PROJECT_LOCK.
                yield
            else:
                # Layout 1 keeps its historical whole-method project lock.
                with project_manager.PROJECT_LOCK:
                    yield
        return

    # PROJECT_LOCK is reentrant: nested save/refresh calls compose with this
    # whole-method boundary. Ordinary mutations do not take a transition lock.
    with project_manager.PROJECT_LOCK:
        project = getattr(app.state, "project", None)
        if project is not None and project.layout != LAYOUT_2 and (
            policy is MutationPolicy.METADATA
            or (
                policy is MutationPolicy.GRAPH_IF_PRESENT
                and "story_graph" in project.settings
            )
        ):
            with project_transaction.metadata_transaction(app):
                yield
            return

        if (
            project is None
            or project.layout != LAYOUT_2
            or policy is MutationPolicy.SERIALIZED
        ):
            yield
            return

        # GRAPH_IF_PRESENT and METADATA also use the full Layout 2 boundary.
        revision_before = int(project.storage_revision)
        app_state_before = {
            name: getattr(app.state, name, None)
            for name in (
                "dirty",
                "project_disk_mtime",
                "external_blender_context_revision",
            )
        }
        try:
            with project_document.layout2_mutation_transaction(project.project_root):
                with project_transaction.mutate_project(project):
                    yield
        except BaseException:
            app.state.project = project
            project.storage_revision = revision_before
            for name, value in app_state_before.items():
                setattr(app.state, name, value)
            raise
