# Spikes

Throwaway scripts that validate a single risky assumption before committing to an
architecture. Not part of the app; safe to delete.

## bpy_solid_viewport_spike.py

Validates the core assumption behind **route C** (backend reads `.blend` directly via
the `bpy` module and streams a **solid-shading** viewport to the frontend, deleting the
current manual *export-GLB → import* round-trip).

It measures the only number that decides feasibility:

> How many milliseconds to render one solid frame at viewport resolution, headless?

…and probes the one historically fragile part — whether a true offscreen *viewport*
draw (`gpu.GPUOffScreen.draw_view3d`) works without a window.

### Run (isolated venv — required)

> ⚠️ **Never `pip install bpy` into the global or project environment.** bpy pins
> `numpy<2`, but the app's `opencv-python` requires `numpy>=2`. Installing bpy
> globally silently downgrades numpy and breaks opencv. The runner scripts below
> provision a dedicated `spikes/.venv-bpy` (gitignored) and keep bpy quarantined.

```powershell
# PowerShell (creates spikes/.venv-bpy on first run, then reuses it)
./spikes/run.ps1
./spikes/run.ps1 path/to/file.blend 1920x1080 60   # args forwarded to the spike
```

```bash
# Git Bash / POSIX
./spikes/run.sh
./spikes/run.sh path/to/file.blend 1920x1080 60
```

Optional args: `[file.blend] [WIDTHxHEIGHT] [frames]`.

Alternatively, run against a real Blender install (representative of a true
viewport-streaming server with a GL context — see Test B notes below):

```bash
blender --background storyboard_tool/assets/scene_template.blend \
        --python spikes/bpy_solid_viewport_spike.py
```

### Reading the result

- **Test A (Workbench render)** — robust headless path; `p50 < 33ms` means solid frames
  stream smoothly over loopback.
- **Test B (viewport offscreen)** — the real streaming primitive; if it `[FAIL]`s with
  "no window", a fully-headless `bpy` can't drive `draw_view3d`, so the streaming server
  must run Blender with a hidden window / EGL context (or fall back to Test A's path).
