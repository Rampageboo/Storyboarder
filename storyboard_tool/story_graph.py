"""Canonical route graph stored in project.settings; edges are derived only.

Legacy projects remain unmodified: their graph is a read-only linear projection
until the first explicit graph edit. Shot CRUD reconciles an existing graph.
"""
from __future__ import annotations

import copy
import math
import uuid
from typing import Any

from .models import Project, Shot
# Preserve the historical import for callers; execution belongs to transactions.
from .project_transaction import metadata_transaction as metadata_transaction


class RevisionConflict(ValueError):
    pass


def validate(graph: Any, shot_ids: list[str]) -> dict[str, Any]:
    if not isinstance(graph, dict) or set(graph) != {
        "version", "revision", "active_route_id", "routes", "positions"
    }:
        raise ValueError("Story graph must contain version, revision, active_route_id, routes and positions.")
    if type(graph["version"]) is not int or graph["version"] != 1:
        raise ValueError("Unsupported story graph version.")
    if type(graph["revision"]) is not int or graph["revision"] < 0:
        raise ValueError("Story graph revision must be a non-negative integer.")
    known = set(shot_ids)
    if len(known) != len(shot_ids):
        raise ValueError("Project shot IDs must be unique.")
    routes = graph["routes"]
    if not isinstance(routes, list) or not routes:
        raise ValueError("Story graph must contain at least one route.")
    route_ids: set[str] = set()
    covered: set[str] = set()
    adjacency: dict[str, set[str]] = {shot_id: set() for shot_id in shot_ids}
    for route in routes:
        if not isinstance(route, dict) or set(route) != {"id", "name", "shot_ids"}:
            raise ValueError("Each route must contain id, name and shot_ids.")
        route_id, name, ids = route["id"], route["name"], route["shot_ids"]
        if not isinstance(route_id, str) or not route_id.strip() or route_id in route_ids:
            raise ValueError("Route IDs must be non-empty and unique.")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Route names must be non-empty.")
        if not isinstance(ids, list) or any(not isinstance(item, str) for item in ids):
            raise ValueError("Route shot_ids must be an array of shot IDs.")
        if len(set(ids)) != len(ids) or not set(ids).issubset(known):
            raise ValueError("Route shot IDs must be unique and refer to existing shots.")
        route_ids.add(route_id)
        covered.update(ids)
        for source, target in zip(ids, ids[1:]):
            adjacency[source].add(target)
    if not isinstance(graph["active_route_id"], str) or graph["active_route_id"] not in route_ids:
        raise ValueError("Active route does not exist.")
    if covered != known:
        raise ValueError("Every shot must belong to at least one route.")
    positions = graph["positions"]
    if not isinstance(positions, dict) or not set(positions).issubset(known):
        raise ValueError("Positions must refer to existing shots.")
    for position in positions.values():
        if not isinstance(position, dict) or set(position) != {"x", "y"}:
            raise ValueError("Each position requires x and y.")
        try:
            finite = all(type(value) in (int, float) and math.isfinite(value) for value in position.values())
        except OverflowError:
            finite = False
        if not finite:
            raise ValueError("Position coordinates must be finite numbers.")
    indegree = dict.fromkeys(shot_ids, 0)
    for targets in adjacency.values():
        for target in targets:
            indegree[target] += 1
    pending = [shot_id for shot_id, degree in indegree.items() if degree == 0]
    visited = 0
    while pending:
        source = pending.pop()
        visited += 1
        for target in adjacency[source]:
            indegree[target] -= 1
            if indegree[target] == 0:
                pending.append(target)
    if visited != len(shot_ids):
        raise ValueError("Story routes must not form a cycle.")
    return copy.deepcopy(graph)


def get_graph(project: Project) -> dict[str, Any]:
    shot_ids = [shot.shot_id for shot in project.shots]
    if "story_graph" in project.settings:
        return validate(project.settings["story_graph"], shot_ids)
    return {
        "version": 1,
        "revision": 0,
        "active_route_id": "main",
        "routes": [{"id": "main", "name": "主线", "shot_ids": shot_ids}],
        "positions": {shot_id: {"x": 0, "y": index * 150} for index, shot_id in enumerate(shot_ids)},
    }


def update_graph(project: Project, graph: dict[str, Any]) -> None:
    current = get_graph(project)
    # A stale client may legitimately contain shots deleted since its read.
    # Report the revision conflict before validating those outdated references.
    if isinstance(graph, dict) and type(graph.get("revision")) is int and graph["revision"] >= 0 and graph["revision"] != current["revision"]:
        raise RevisionConflict("Story graph changed; reload the project before retrying.")
    accepted = validate(graph, [shot.shot_id for shot in project.shots])
    accepted["revision"] += 1
    project.settings["story_graph"] = accepted


def prepare_restore(project: Project, graph: dict[str, Any] | None, restored_ids: list[str]) -> dict[str, Any] | None:
    """Validate an undo snapshot against post-restore IDs before mutating anything."""
    if graph is None:
        return None
    current = get_graph(project)
    if isinstance(graph, dict) and type(graph.get("revision")) is int and graph["revision"] >= 0 and graph["revision"] != current["revision"]:
        raise RevisionConflict("Story graph changed; reload the project before retrying undo.")
    accepted = validate(graph, [shot.shot_id for shot in project.shots] + restored_ids)
    accepted["revision"] = current["revision"] + 1
    return accepted


def reconcile_shots(project: Project, previous_ids: list[str], after_id: str | None = None) -> None:
    """Maintain custom routes after one existing shot operation; never reorder them."""
    if "story_graph" not in project.settings:
        return
    graph = validate(project.settings["story_graph"], previous_ids)
    current_ids = [shot.shot_id for shot in project.shots]
    known = set(current_ids)
    for route in graph["routes"]:
        route["shot_ids"] = [shot_id for shot_id in route["shot_ids"] if shot_id in known]
    graph["positions"] = {key: value for key, value in graph["positions"].items() if key in known}
    active = next(route for route in graph["routes"] if route["id"] == graph["active_route_id"])
    for shot_id in current_ids:
        if shot_id in previous_ids:
            continue
        ids = active["shot_ids"]
        index = ids.index(after_id) + 1 if after_id in ids else len(ids)
        ids.insert(index, shot_id)
        parent = graph["positions"].get(after_id, {"x": 0, "y": -150})
        x, y = parent["x"], parent["y"] + 150
        while {"x": x, "y": y} in graph["positions"].values():
            x += 220
        graph["positions"][shot_id] = {"x": x, "y": y}
        after_id = shot_id
    graph["revision"] += 1
    project.settings["story_graph"] = validate(graph, current_ids)


def add_branch(project: Project, shot: Shot, route_id: str, from_shot_id: str, title: str) -> None:
    graph = get_graph(project)
    if not isinstance(title, str) or not title.strip():
        raise ValueError("Branch title is required.")
    route = next((item for item in graph["routes"] if item["id"] == route_id), None)
    if route is None or from_shot_id not in route["shot_ids"]:
        raise ValueError("The branch parent must belong to the selected route.")
    if any(item.shot_id == shot.shot_id for item in project.shots):
        raise ValueError("New branch shot ID already exists.")
    new_route_id = "route-" + uuid.uuid4().hex
    shot.title = title.strip()
    prefix = route["shot_ids"][:route["shot_ids"].index(from_shot_id) + 1]
    graph["routes"].append({"id": new_route_id, "name": title.strip(), "shot_ids": prefix + [shot.shot_id]})
    graph["active_route_id"] = new_route_id
    parent = graph["positions"].get(from_shot_id, {"x": 0, "y": 0})
    x, y = parent["x"] + 220, parent["y"] + 150
    while {"x": x, "y": y} in graph["positions"].values():
        x += 220
    graph["positions"][shot.shot_id] = {"x": x, "y": y}
    graph["revision"] += 1
    ids = [item.shot_id for item in project.shots]
    accepted = validate(graph, ids + [shot.shot_id])
    project.shots.insert(ids.index(from_shot_id) + 1, shot)
    project.settings["story_graph"] = accepted
