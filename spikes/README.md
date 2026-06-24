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
- **Test B (viewport offscreen)** — the real streaming primitive (`draw_view3d`).
  Reports PER-ENVIRONMENT and saves a proof PNG (`spike_testb_viewport.png`) so the
  "real pixels" claim is visually verifiable. On pip bpy + a GPU it WORKS (~0.6ms,
  windows=1). Run it across all four environments before generalizing — it depends on
  the GL context: (1) pip bpy headless, (2) `blender --background`, (3) real window,
  (4) hidden window / EGL.

> ⚠️ An earlier version of this spike wrongly concluded "draw_view3d unusable headless"
> — that was a self-inflicted bug (`offscreen.free()` before `texture_color.read()`).
> Always rule out test-harness errors before trusting a negative result.

Flags: `--inject-demo` forces demo geometry (Suzanne + cubes) even into a non-empty
scene. Without it, a real `.blend` is measured AS-IS (never silently mutated).

## render_server/ — plan-1 skeleton (progressive frame streaming)

A minimal, runnable skeleton of "route C, plan 1": a standalone bpy worker that
loads a `.blend` once (stays warm), and serves solid-shaded JPEG frames per camera
request. It is a SEPARATE process by necessity — bpy's `numpy<2` can never share the
app's `numpy>=2` env — talking plain HTTP.

```powershell
./spikes/render_server/run.ps1            # serves http://127.0.0.1:8765
# open the URL: drag to orbit (low-res, fast), release for a full-res frame
```

- `GET /`        — drag-to-orbit demo page (`index.html`)
- `GET /frame?w=&h=&yaw=&pitch=&dist=` — one solid JPEG; `X-Render-ms` header has render time
- `GET /healthz` — readiness probe

Measured on this machine: ~20ms @640×360 (interactive), ~53ms @1280×720 (full).
Not production: renders via `render.render` to a temp JPEG and serves one request at
a time (bpy isn't thread-safe). A real server would render to an in-memory buffer and
stream over a persistent socket, and the main FastAPI app would proxy/spawn this worker.
