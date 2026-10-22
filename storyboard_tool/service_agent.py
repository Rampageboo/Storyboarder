"""Agent-facing project views: board grid, outline, and sequence render."""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from . import agent_views, app_state, project_manager
from .errors import AppErrorCode, app_error
from .file_transactions import atomic_output_file

logger = logging.getLogger(__name__)


class AgentServiceMixin:
    def _agent_route_boards(self, route_id: str = ""):
        project = app_state._require_project(self.app)
        try:
            route, boards = agent_views.route_boards(project, route_id)
        except agent_views.AgentViewError as exc:
            raise app_error(AppErrorCode.INVALID_REQUEST, str(exc), status=404) from exc
        return project, route, boards

    def method_project_grid(self, route_id: str = "", columns: int | None = None,
                            max_edge: int = agent_views.GRID_DEFAULT_MAX_EDGE) -> bytes:
        project, _route, boards = self._agent_route_boards(route_id)
        return agent_views.render_grid_png(project, boards, columns=columns, max_edge=max_edge)

    def method_project_outline(self, route_id: str = "") -> dict[str, Any]:
        project = app_state._require_project(self.app)
        try:
            return agent_views.build_outline(self.app, project, route_id)
        except agent_views.AgentViewError as exc:
            raise app_error(AppErrorCode.INVALID_REQUEST, str(exc), status=404) from exc

    # Not a project_mutation: like the other exports it writes only a file under
    # Exports/ and no metadata. The board/take choice and still frames are
    # snapshotted under PROJECT_LOCK; the ffmpeg encode runs outside it so a long
    # cut never blocks edits or a finishing video take.
    def method_render_sequence(self, data: dict[str, Any]) -> dict[str, Any]:
        project = app_state._require_project(self.app)
        route_id = str(data.get("route_id") or "")
        shot_ids = [str(item) for item in (data.get("shot_ids") or [])]
        takes = {str(key): str(value) for key, value in (data.get("takes") or {}).items()}
        with agent_views.new_still_dir() as still_dir:
            try:
                with project_manager.PROJECT_LOCK:
                    boards = self._sequence_boards(project, route_id, shot_ids)
                    if not boards:
                        raise agent_views.AgentViewError("There are no boards to render.")
                    segments, size = agent_views.plan_sequence(self.app, project, boards, takes, Path(still_dir))
                    output_path = agent_views.sequence_output_path(project)
            except agent_views.AgentViewError as exc:
                raise app_error(AppErrorCode.INVALID_REQUEST, str(exc)) from exc
            try:
                with atomic_output_file(output_path) as staged:
                    agent_views.encode_sequence(segments, size, staged)
            except RuntimeError as exc:
                logger.exception("Sequence render failed")
                raise app_error(AppErrorCode.EXPORT_FAILED, str(exc), status=500) from exc
        duration = agent_views._probe_seconds(output_path) or round(sum(item.seconds for item in segments), 3)
        return {
            "path": str(output_path),
            "relative_path": agent_views.relative_export_path(project, output_path),
            "duration_seconds": round(duration, 3),
            "width": size[0],
            "height": size[1],
            "fps": agent_views.SEQUENCE_FPS,
            "bytes": os.path.getsize(output_path),
            "boards": [
                {
                    "shot_id": item.shot_id,
                    "number": item.number,
                    "source": item.source,
                    **({"take_id": item.take_id} if item.take_id else {}),
                    "seconds": round(item.seconds, 3),
                }
                for item in segments
            ],
        }

    def _sequence_boards(self, project, route_id: str, shot_ids: list[str]):
        """Route order by default; an explicit ``shot_ids`` list is used as given."""
        if not shot_ids:
            return agent_views.route_boards(project, route_id)[1]
        if route_id:
            raise agent_views.AgentViewError("Choose a route or a list of boards, not both.")
        if len(set(shot_ids)) != len(shot_ids):
            raise agent_views.AgentViewError("Each board may appear once in a sequence.")
        _route, ordered = agent_views.route_boards(project)
        numbers = {shot.shot_id: number for number, shot in ordered}
        positions = {shot.shot_id: index for index, shot in enumerate(project.shots, start=1)}
        shots = {shot.shot_id: shot for shot in project.shots}
        missing = [shot_id for shot_id in shot_ids if shot_id not in shots]
        if missing:
            raise agent_views.AgentViewError(f"Unknown boards: {', '.join(missing)}.")
        return [(numbers.get(shot_id, positions[shot_id]), shots[shot_id]) for shot_id in shot_ids]
