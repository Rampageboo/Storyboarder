"""FastAPI boundary for the managed built-in Blender viewport."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from . import app_state, blender_bridge, bpy_viewport


class BpyCameraPathRequest(BaseModel):
    points: list[list[float]] = Field(default_factory=list)
    width: int = Field(default=960, ge=64, le=1920)
    height: int = Field(default=540, ge=64, le=1080)
    yaw: float = 0.6
    pitch: float = 0.5
    distance: float = Field(default=9.0, ge=0.1, le=100000.0)
    target: list[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0])
    duration_frames: int = Field(default=120, ge=2, le=100000)


def register_bpy_viewport_routes(app: FastAPI) -> None:
    def manager() -> bpy_viewport.BpyViewportManager:
        return bpy_viewport.manager_for_app(app)

    def project():
        return app_state._require_project(app)

    def translate_error(exc: bpy_viewport.BpyViewportError) -> HTTPException:
        return HTTPException(status_code=400, detail=str(exc))

    @app.get("/api/project/bpy-viewport/status")
    def bpy_viewport_status() -> dict[str, Any]:
        external = blender_bridge.status(app)
        built_in = manager().status()
        return {
            **built_in,
            **external,
            "owner": "external"
            if external["external_blender_owned"]
            else ("built-in" if built_in["running"] else "none"),
        }

    @app.post("/api/project/bpy-viewport/start")
    def start_bpy_viewport() -> dict[str, Any]:
        if blender_bridge.owns_scene(app):
            raise HTTPException(
                status_code=409,
                detail=(
                    "External Blender owns this scene. Close it before starting "
                    "the built-in Blender viewport."
                ),
            )
        try:
            result = manager().start(project())
            return {
                **result,
                **blender_bridge.status(app),
                "owner": "built-in",
            }
        except bpy_viewport.BpyViewportError as exc:
            raise translate_error(exc) from exc

    @app.post("/api/project/bpy-viewport/stop")
    def stop_bpy_viewport() -> dict[str, Any]:
        manager().stop()
        return {"running": False, "engine": "bpy"}

    @app.get("/api/project/bpy-viewport/frame")
    def render_bpy_viewport_frame(
        width: int = Query(960, ge=64, le=1920),
        height: int = Query(540, ge=64, le=1080),
        yaw: float = 0.6,
        pitch: float = 0.5,
        distance: float = Query(9.0, ge=0.1, le=100000.0),
        target_x: float = 0.0,
        target_y: float = 0.0,
        target_z: float = 0.0,
        camera: str = "orbit",
        frame: int | None = None,
    ) -> Response:
        try:
            body, headers = manager().frame(
                {
                    "w": width,
                    "h": height,
                    "yaw": yaw,
                    "pitch": pitch,
                    "dist": distance,
                    "target_x": target_x,
                    "target_y": target_y,
                    "target_z": target_z,
                    "camera": camera,
                    "frame": frame,
                }
            )
        except bpy_viewport.BpyViewportError as exc:
            raise translate_error(exc) from exc
        response = Response(content=body, media_type="image/jpeg")
        response.headers["Cache-Control"] = "no-store"
        if "X-Render-ms" in headers:
            response.headers["X-Render-ms"] = headers["X-Render-ms"]
        return response

    @app.post("/api/project/bpy-viewport/camera-path")
    def create_bpy_camera_path(request: BpyCameraPathRequest) -> dict[str, Any]:
        if len(request.points) < 2:
            raise HTTPException(status_code=400, detail="Draw at least two camera-path points.")
        try:
            result = manager().create_camera_path(request.model_dump())
        except bpy_viewport.BpyViewportError as exc:
            raise translate_error(exc) from exc
        app.state.dirty = True
        return result

    @app.post("/api/project/bpy-viewport/save")
    def save_bpy_scene() -> dict[str, Any]:
        try:
            result = manager().save()
        except bpy_viewport.BpyViewportError as exc:
            raise translate_error(exc) from exc
        app.state.dirty = True
        return result
