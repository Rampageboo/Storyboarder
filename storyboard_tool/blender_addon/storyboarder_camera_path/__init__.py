"""Storyboarder camera-path drawing tool for Blender."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from math import hypot
from typing import Any

import bpy
import gpu
from bpy.props import IntProperty
from bpy_extras import view3d_utils
from gpu_extras.batch import batch_for_shader
from mathutils import Vector


bl_info = {
    "name": "Storyboarder Camera Path",
    "author": "Storyboarder",
    "version": (0, 1, 0),
    "blender": (4, 5, 0),
    "location": "3D View > Sidebar > Storyboarder",
    "description": "Draw a Bezier camera path with a camera and target Empty",
    "category": "Animation",
}

COLLECTION_NAME = "Storyboarder Camera Paths"
PATH_MATERIAL_NAME = "Storyboarder Camera Path Green"
PATH_COLOR = (0.03, 1.0, 0.12, 1.0)
POINT_SAMPLE_DISTANCE_PX = 6.0
SIMPLIFY_TOLERANCE_PX = 5.0


def _ensure_collection(scene: bpy.types.Scene) -> bpy.types.Collection:
    collection = bpy.data.collections.get(COLLECTION_NAME)
    if collection is None:
        collection = bpy.data.collections.new(COLLECTION_NAME)
    if collection.name not in {child.name for child in scene.collection.children}:
        scene.collection.children.link(collection)
    return collection


def _ensure_green_material() -> bpy.types.Material:
    material = bpy.data.materials.get(PATH_MATERIAL_NAME)
    if material is None:
        material = bpy.data.materials.new(PATH_MATERIAL_NAME)
    material.diffuse_color = PATH_COLOR
    material.use_nodes = True
    principled = material.node_tree.nodes.get("Principled BSDF") if material.node_tree else None
    if principled is not None:
        base_color = principled.inputs.get("Base Color")
        roughness = principled.inputs.get("Roughness")
        if base_color is not None:
            base_color.default_value = PATH_COLOR
        if roughness is not None:
            roughness.default_value = 0.65
    return material


def _tag(obj: bpy.types.Object, role: str) -> None:
    obj["storyboarder_camera_path"] = True
    obj["storyboarder_role"] = role


def create_camera_path(
    context: bpy.types.Context,
    points: Iterable[Sequence[float]],
    *,
    duration_frames: int = 120,
    target_location: Sequence[float] | None = None,
) -> dict[str, bpy.types.Object]:
    """Create an editable Bezier path, animated camera, and look-at Empty."""
    coordinates = [Vector(point).to_3d() for point in points]
    if len(coordinates) < 2:
        raise ValueError("A camera path needs at least two points.")
    duration = max(2, int(duration_frames))
    scene = context.scene
    collection = _ensure_collection(scene)

    curve_data = bpy.data.curves.new("Storyboarder Camera Path", type="CURVE")
    curve_data.dimensions = "3D"
    curve_data.resolution_u = 12
    curve_data.render_resolution_u = 16
    curve_data.bevel_depth = 0.025
    curve_data.bevel_resolution = 3
    curve_data.materials.append(_ensure_green_material())

    spline = curve_data.splines.new(type="BEZIER")
    spline.bezier_points.add(len(coordinates) - 1)
    for bezier_point, coordinate in zip(spline.bezier_points, coordinates, strict=True):
        bezier_point.co = coordinate
        bezier_point.handle_left_type = "AUTO"
        bezier_point.handle_right_type = "AUTO"

    path_object = bpy.data.objects.new("SB_CameraPath", curve_data)
    path_object.color = PATH_COLOR
    path_object.show_in_front = True
    _tag(path_object, "camera_path")
    collection.objects.link(path_object)

    if target_location is None:
        target_location = scene.cursor.location
    target_object = bpy.data.objects.new("SB_CameraTarget", None)
    target_object.location = Vector(target_location).to_3d()
    target_object.empty_display_type = "SPHERE"
    target_object.empty_display_size = 0.5
    target_object.show_in_front = True
    _tag(target_object, "camera_target")
    collection.objects.link(target_object)

    camera_data = bpy.data.cameras.new("SB_PathCamera")
    camera_object = bpy.data.objects.new("SB_PathCamera", camera_data)
    camera_object.location = (0.0, 0.0, 0.0)
    camera_object.rotation_euler = (0.0, 0.0, 0.0)
    camera_object.show_in_front = True
    _tag(camera_object, "path_camera")
    collection.objects.link(camera_object)

    follow_path = camera_object.constraints.new(type="FOLLOW_PATH")
    follow_path.name = "Storyboarder Follow Path"
    follow_path.target = path_object
    follow_path.use_fixed_location = True
    follow_path.use_curve_follow = False
    follow_path.offset_factor = 0.0
    follow_path.keyframe_insert(data_path="offset_factor", frame=scene.frame_start)
    follow_path.offset_factor = 1.0
    follow_path.keyframe_insert(
        data_path="offset_factor",
        frame=scene.frame_start + duration - 1,
    )

    look_at = camera_object.constraints.new(type="DAMPED_TRACK")
    look_at.name = "Storyboarder Track Target"
    look_at.target = target_object
    look_at.track_axis = "TRACK_NEGATIVE_Z"

    scene.frame_end = max(scene.frame_end, scene.frame_start + duration - 1)
    scene.camera = camera_object
    scene.frame_set(scene.frame_start)

    for selected in context.selected_objects:
        selected.select_set(False)
    path_object.select_set(True)
    context.view_layer.objects.active = path_object

    return {
        "path": path_object,
        "camera": camera_object,
        "target": target_object,
    }


def _point_segment_distance(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
) -> float:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    if dx == 0.0 and dy == 0.0:
        return hypot(point[0] - start[0], point[1] - start[1])
    t = ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    closest = (start[0] + t * dx, start[1] + t * dy)
    return hypot(point[0] - closest[0], point[1] - closest[1])


def _simplify_indices(points: Sequence[tuple[float, float]], tolerance: float) -> list[int]:
    if len(points) <= 2:
        return list(range(len(points)))
    max_distance = 0.0
    split_index = 0
    for index in range(1, len(points) - 1):
        distance = _point_segment_distance(points[index], points[0], points[-1])
        if distance > max_distance:
            max_distance = distance
            split_index = index
    if max_distance <= tolerance:
        return [0, len(points) - 1]
    left = _simplify_indices(points[: split_index + 1], tolerance)
    right = _simplify_indices(points[split_index:], tolerance)
    return left[:-1] + [split_index + index for index in right]


class STORYBOARDER_OT_draw_camera_path(bpy.types.Operator):
    """Draw on the 3D cursor's horizontal plane to create a camera rig."""

    bl_idname = "storyboarder.draw_camera_path"
    bl_label = "Draw Camera Path"
    bl_description = "Draw a green camera path on the 3D cursor's horizontal plane"
    bl_options = {"REGISTER", "UNDO", "BLOCKING"}

    duration_frames: IntProperty(
        name="Duration",
        description="Frames used to move the camera from the path start to end",
        default=120,
        min=2,
        max=100000,
    )

    _drawing: bool
    _screen_points: list[tuple[float, float]]
    _world_points: list[Vector]
    _draw_handle: Any
    _area: bpy.types.Area | None
    _window_region: bpy.types.Region | None

    @classmethod
    def poll(cls, context: bpy.types.Context) -> bool:
        return context.area is not None and context.area.type == "VIEW_3D"

    def invoke(self, context: bpy.types.Context, _event: bpy.types.Event) -> set[str]:
        self._drawing = False
        self._screen_points = []
        self._world_points = []
        self._area = context.area
        self._window_region = next(
            (region for region in context.area.regions if region.type == "WINDOW"),
            None,
        )
        if self._window_region is None:
            self.report({"ERROR"}, "Could not find the 3D viewport drawing region.")
            return {"CANCELLED"}
        self._draw_handle = bpy.types.SpaceView3D.draw_handler_add(
            self._draw_preview,
            (),
            "WINDOW",
            "POST_PIXEL",
        )
        context.window_manager.modal_handler_add(self)
        context.area.header_text_set("Storyboarder Camera Path: drag LMB to draw, Esc to cancel")
        context.area.tag_redraw()
        return {"RUNNING_MODAL"}

    def modal(self, context: bpy.types.Context, event: bpy.types.Event) -> set[str]:
        if event.type in {"ESC", "RIGHTMOUSE"}:
            self._finish(context)
            return {"CANCELLED"}

        if event.type == "LEFTMOUSE" and event.value == "PRESS":
            self._drawing = True
            self._screen_points = []
            self._world_points = []
            self._append_point(context, event)
            return {"RUNNING_MODAL"}

        if event.type == "MOUSEMOVE" and self._drawing:
            self._append_point(context, event)
            return {"RUNNING_MODAL"}

        if event.type == "LEFTMOUSE" and event.value == "RELEASE" and self._drawing:
            self._append_point(context, event, force=True)
            self._drawing = False
            if len(self._world_points) < 2:
                self.report({"WARNING"}, "Draw a longer path.")
                return {"RUNNING_MODAL"}
            indices = _simplify_indices(self._screen_points, SIMPLIFY_TOLERANCE_PX)
            points = [self._world_points[index] for index in indices]
            create_camera_path(context, points, duration_frames=self.duration_frames)
            self._finish(context)
            self.report(
                {"INFO"},
                "Created camera path, camera, and target. Move SB_CameraTarget to aim.",
            )
            return {"FINISHED"}

        return {"RUNNING_MODAL"}

    def _append_point(
        self,
        context: bpy.types.Context,
        event: bpy.types.Event,
        *,
        force: bool = False,
    ) -> None:
        if self._window_region is None:
            return
        screen = (
            float(event.mouse_x - self._window_region.x),
            float(event.mouse_y - self._window_region.y),
        )
        if not (
            0.0 <= screen[0] <= self._window_region.width
            and 0.0 <= screen[1] <= self._window_region.height
        ):
            return
        if self._screen_points and not force:
            previous = self._screen_points[-1]
            if hypot(screen[0] - previous[0], screen[1] - previous[1]) < POINT_SAMPLE_DISTANCE_PX:
                return
        world = self._screen_to_ground(context, self._window_region, screen)
        if world is None:
            return
        self._screen_points.append(screen)
        self._world_points.append(world)
        if context.area is not None:
            context.area.tag_redraw()

    @staticmethod
    def _screen_to_ground(
        context: bpy.types.Context,
        region: bpy.types.Region,
        screen: tuple[float, float],
    ) -> Vector | None:
        region_3d = context.space_data.region_3d
        origin = view3d_utils.region_2d_to_origin_3d(region, region_3d, screen)
        direction = view3d_utils.region_2d_to_vector_3d(region, region_3d, screen)
        ground_z = float(context.scene.cursor.location.z)
        if abs(direction.z) < 1e-7:
            return view3d_utils.region_2d_to_location_3d(
                region,
                region_3d,
                screen,
                context.scene.cursor.location,
            )
        distance = (ground_z - origin.z) / direction.z
        if distance < 0.0:
            return None
        return origin + direction * distance

    def _draw_preview(self) -> None:
        if len(self._screen_points) < 2:
            return
        shader = gpu.shader.from_builtin("UNIFORM_COLOR")
        batch = batch_for_shader(shader, "LINE_STRIP", {"pos": self._screen_points})
        shader.bind()
        shader.uniform_float("color", PATH_COLOR)
        batch.draw(shader)

    def _finish(self, context: bpy.types.Context) -> None:
        if self._draw_handle is not None:
            bpy.types.SpaceView3D.draw_handler_remove(self._draw_handle, "WINDOW")
            self._draw_handle = None
        if self._area is not None:
            self._area.header_text_set(None)
            self._area.tag_redraw()


class STORYBOARDER_PT_camera_path(bpy.types.Panel):
    bl_label = "Camera Path"
    bl_idname = "STORYBOARDER_PT_camera_path"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Storyboarder"

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        layout.label(text="Draw on the 3D Cursor Z plane.")
        layout.prop(context.scene, "storyboarder_camera_path_duration")
        operator = layout.operator(
            STORYBOARDER_OT_draw_camera_path.bl_idname,
            icon="CURVE_BEZCURVE",
        )
        operator.duration_frames = context.scene.storyboarder_camera_path_duration
        layout.separator()
        layout.label(text="The target starts at the 3D Cursor.", icon="EMPTY_AXIS")


CLASSES = (
    STORYBOARDER_OT_draw_camera_path,
    STORYBOARDER_PT_camera_path,
)


def register() -> None:
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.storyboarder_camera_path_duration = IntProperty(
        name="Duration",
        description="Frames used to move along a newly drawn camera path",
        default=120,
        min=2,
        max=100000,
    )


def unregister() -> None:
    if hasattr(bpy.types.Scene, "storyboarder_camera_path_duration"):
        del bpy.types.Scene.storyboarder_camera_path_duration
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
