# Storyboarder Blender Camera Path MVP

The same camera-path scene builder used by Storyboarder's built-in Blender
worker is also available in external Blender. Clicking **Open Blender** in
Storyboarder injects it for that Blender session only. It is not installed into
the user's Blender profile and does not change the user's normal add-ons or
settings.

## Use

1. Click **Open Blender** in Storyboarder's Scene 3D workspace. For standalone
   testing, `register_storyboarder_addon.py` can still be run manually.
2. In Blender's 3D View, open the right sidebar (`N`) and select **Storyboarder**.
3. Put the 3D Cursor where the camera should look.
4. Set the camera-path duration and click **Draw Camera Path**.
5. Drag with the left mouse button. Release to create the rig.

The tool creates:

- `SB_CameraPath`: a green, editable Bezier curve;
- `SB_PathCamera`: an animated camera with a Follow Path constraint;
- `SB_CameraTarget`: an Empty tracked by the camera.

The path is drawn on the horizontal plane at the 3D Cursor's Z position. Move
`SB_CameraTarget` to change where the camera points. The generated objects are
stored in the `Storyboarder Camera Paths` collection and saved normally with the
project's `.blend` file.

The external session also shows a **Storyboarder Link** panel with the active
project, Scene 3D, selected shot, active camera, and boards associated with that
camera. Blender writes a short-lived heartbeat while the scene is open. On
launch and after every Blender save, the session plugin atomically regenerates
Storyboarder's disposable GLB preview cache. There is no manual GLB export,
import, or reload step.

Storyboarder remains read-only: its preview can orbit, pan, zoom, switch between
free view and Blender cameras, scrub animation, and capture a board. The external
Blender process remains the only editor of the `.blend`.

This MVP intentionally does not install itself permanently, draw onto arbitrary
mesh surfaces, or control camera roll.
