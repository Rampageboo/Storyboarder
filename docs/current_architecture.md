# Storyboarder — Current Architecture

> Last updated: 2026-06-18
> Reflects the codebase after the desktop-only refactor, architecture cleanup,
> Photoshop plugin API, shot-service extraction, and project-transaction safety
> commits. For earlier history see [code-review-and-refactor.md](code-review-and-refactor.md).

---

## Table of Contents

1. [Overview](#1-overview)
2. [Desktop Launch Flow](#2-desktop-launch-flow)
3. [Internal Server Flow](#3-internal-server-flow)
4. [pywebview Shell](#4-pywebview-shell)
5. [React / Vite UI Bundle](#5-react--vite-ui-bundle)
6. [FastAPI Route Layer](#6-fastapi-route-layer)
7. [backend_service Role](#7-backend_service-role)
8. [app_state Helpers](#8-app_state-helpers)
9. [shot_service Role](#9-shot_service-role)
10. [project_manager Role](#10-project_manager-role)
11. [project_transaction: Snapshot and Rollback](#11-project_transaction-snapshot-and-rollback)
12. [reference_segments Role](#12-reference_segments-role)
13. [Photoshop Plugin API](#13-photoshop-plugin-api)
14. [Scene3D TypeScript Source and Generated Runtime Bundle](#14-scene3d-typescript-source-and-generated-runtime-bundle)
15. [Generated Files Policy](#15-generated-files-policy)
16. [Kept Routes](#16-kept-routes)
17. [Deleted Legacy Artifacts](#17-deleted-legacy-artifacts)
18. [Non-Goals](#18-non-goals)

---

## 1. Overview

Storyboarder is a **desktop-only** storyboarding application. There is no hosted server, no cloud sync, and no browser-accessible URL.

```
┌──────────────────────────────────────────────────────────────────┐
│                          Desktop process                          │
│                                                                   │
│  main.py                                                          │
│    └─ storyboard_tool/main.py                                     │
│         ├─ create_app()   →  FastAPI app                          │
│         └─ open_desktop_window()  →  pywebview window             │
│                                          │                        │
│                           http://127.0.0.1:PORT/                  │
│                                          │                        │
│  ┌───────────────────────────────────────┴───────────────────┐   │
│  │                     FastAPI (uvicorn)                      │   │
│  │  GET /              →  React SPA (dist/index.html)        │   │
│  │  GET /react/*       →  Vite assets                        │   │
│  │  GET /static/*      →  vendor + runtime bundle            │   │
│  │  /api/*             →  StoryboardBackendService           │   │
│  │  /api/plugin/*      →  Photoshop UXP plugin API           │   │
│  │  /api/bridge/*      →  Photoshop live-bridge polling      │   │
│  └────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────┘
```

**Runtime stack**

| Layer | Technology |
|---|---|
| Desktop shell | pywebview (Chromium WebView on Windows) |
| App server | FastAPI + uvicorn, loopback-only (`127.0.0.1`) |
| Frontend | React 18 + TypeScript, built with Vite |
| 3D engine | Three.js (vendor bundle) + Scene3D workspace (compiled TypeScript) |
| Backend language | Python 3.11+ |
| Image/media | Pillow, OpenCV-Python, psd-tools |

---

## 2. Desktop Launch Flow

```
python main.py
  └─ storyboard_tool.main.main()
       ├─ create_app(base_dir)          # storyboard_tool/api.py
       │    ├─ FastAPI instance
       │    ├─ CORS + no-store middleware
       │    ├─ Mount /static  (vendor & runtime)
       │    ├─ Register all /api/* routes
       │    └─ Start live-bridge refresh thread (1.5 s heartbeat)
       │
       └─ open_desktop_window(app)      # storyboard_tool/desktop.py
            ├─ Set Windows AppUserModelID (taskbar identity)
            ├─ Patch asyncio for Windows connection-reset noise
            ├─ Start uvicorn on 127.0.0.1:PORT (background thread)
            ├─ Wait for server ready (health-check poll)
            ├─ webview.create_window("Storyboard Tool", "http://127.0.0.1:PORT/")
            └─ webview.start()  →  blocks until window closes
```

There is no `--browser` mode. The internal server starts unconditionally and is never exposed outside loopback.

---

## 3. Internal Server Flow

`storyboard_tool/api.py` wires the FastAPI app.

**Route categories**

| Prefix | What it serves |
|---|---|
| `GET /` | `storyboard_tool/web/dist/index.html` (React SPA entry) |
| `GET /react/{path}` | Vite-generated JS/CSS assets |
| `GET /static/{path}` | Vendor Three.js + `scene3d_workspace.js` runtime bundle |
| `POST /api/project/*` | Project CRUD, settings, references, exports |
| `/api/shots/{id}/*` | Shot CRUD, images, canvas, annotations, sync, source |
| `/api/bridge/*` | Photoshop live-bridge polling and relink |
| `/api/plugin/*` | Photoshop UXP plugin API (heartbeat, context, export, PSD save) |
| `/api/export/*` | PDF, contact sheet, timing JSON, image sequence |
| `/api/system/*` | Native file/folder dialogs (via pywebview) |
| `/api/app/session` | UI session state (last project, selected shot, theme) |

All `/api/*` handlers delegate immediately to `StoryboardBackendService`. No business logic lives in `api.py`.

**Photoshop live-bridge thread**

A background daemon thread in `api.py` wakes every 1.5 seconds and refreshes `storyboard_live_bridge.json` in the Sessions directory. The Photoshop UXP plugin and `LiveBridgeContext.tsx` both poll this file.

---

## 4. pywebview Shell

`storyboard_tool/desktop.py` manages the native window lifecycle.

- Uses `webview.create_window()` with `http://127.0.0.1:PORT/` as the URL.
- The WebView is Chromium-based on Windows (EdgeWebView2); it runs the same React code as a browser would.
- System file dialogs (`/api/system/browse-*` routes) call back into pywebview's `create_file_dialog()` API from the server thread. This is the only place pywebview is called outside of window creation.
- `desktop.py` does not expose any JavaScript bridge; all communication goes through the HTTP API.

---

## 5. React / Vite UI Bundle

**Source:** `frontend/src/`
**Build output:** `storyboard_tool/web/dist/` (committed to git)
**Build command:** `cd frontend && npm run build`

### Entry point

`frontend/index.html` → `src/main.tsx` → `src/App.tsx`

The HTML file also carries an import map that resolves `/static/vendor/three/three.module.js` and related Three.js modules, so the workspace bundle can import them at runtime without a bundler.

### Vite configuration

| Config file | Role |
|---|---|
| `frontend/vite.config.ts` | Main React build; `base: '/react/'`; output → `storyboard_tool/web/dist` |
| `frontend/vite.workspace.config.ts` | Scene3D workspace-only build; output → `storyboard_tool/web/static/runtime/scene3d_workspace.js` |

The `base: '/react/'` setting means all Vite-generated asset paths are prefixed with `/react/assets/…`. FastAPI serves those under `GET /react/{path}`.

### Key components

| Component | Purpose |
|---|---|
| `App.tsx` | Root layout: left sidebar, center canvas, right inspector |
| `Topbar.tsx` | Menu bar (File, View, Tools, Help) and status |
| `BoardStrip.tsx` | Timeline film strip; shot thumbnails, duration scrubber |
| `CanvasBoard.tsx` | Main drawing canvas |
| `ShotInspector.tsx` | Metadata editor (title, scene, status, camera, dialogue) |
| `ReferencePanel.tsx` | Per-shot reference images |
| `ReferenceSidebar.tsx` | Project-level reference library, import controls |
| `ReferenceAssignmentPopover.tsx` | Shot-range apply modal for image/video references |
| `ReferenceAssignmentPopover3dApply.tsx` | Shot-range apply modal for 3D captures |
| `Scene3DPanel.tsx` | 3D workspace (import GLB, edit scene, capture frames) |

### State and API client

| Module | Role |
|---|---|
| `state/ProjectContext.tsx` | Global project and shot state; wraps all API calls |
| `state/LiveBridgeContext.tsx` | Polls `/api/bridge/live` every 2–3 s for Photoshop sync |
| `api/client.ts` | Thin `fetch` wrapper; `ApiError` class carries HTTP status |
| `api/project.ts`, `api/shots.ts`, `api/references.ts`, … | Domain-specific HTTP methods |

---

## 6. FastAPI Route Layer

`storyboard_tool/api.py` — approximately 90 route handlers.

Each handler follows the same pattern:

```python
@app.post("/api/shots/{shot_id}/image")
async def import_shot_image(shot_id: str, file: UploadFile = File(...)):
    data = await file.read()
    return _svc().method_import_shot_image(shot_id, file.filename or "", data)
```

`api.py` owns:
- Route registration and URL structure
- Request/response Pydantic models (defined in `api.py`)
- HTTP error mapping via a custom `HTTPException` handler

`api.py` does **not** own:
- Business logic (delegated to `backend_service.py`)
- File I/O (delegated to `project_manager.py`)
- Media processing (delegated to `image_utils.py`, `video_utils.py`)

---

## 7. backend_service Role

`storyboard_tool/backend_service.py` — `StoryboardBackendService` class.

This is the single business-logic entry point. Every `method_*` handler corresponds to one or more REST endpoints.

**Responsibilities**

- Validates inputs and raises `HTTPException` on bad requests
- Reads/writes project state via `project_manager` and `shot_service`
- Calls specialized modules for non-trivial operations
- Returns serialisable dicts that `api.py` returns as JSON

**Key delegations**

| Task | Delegated to |
|---|---|
| Shot domain operations | `shot_service.py` |
| Project/file CRUD | `project_manager.py` |
| Reference workflows | `reference_segments.py` |
| Auto-sync (PSD/PNG) | `linked_sync.py` |
| Export generation | `service_exports.py` + `export_utils.py` |
| Photoshop bridge | `live_bridge.py`, `bridge.py` |
| Image processing | `image_utils.py` |
| Video processing | `video_utils.py` |
| File dialogs | `system_utils.py` |
| App/project state helpers | `app_state.py` |

`StoryboardBackendService` inherits from `ExportServiceMixin` (`service_exports.py`), which provides all `method_export_*` and `method_download_*` handlers.

---

## 8. app_state Helpers

`storyboard_tool/app_state.py` — transport-agnostic project and app-state utilities.

These functions were extracted from `api.py` so they are available to both the HTTP route layer and the desktop bridge (`bridge.py`) without circular imports.

**Key helpers**

| Function | Purpose |
|---|---|
| `_require_project(app)` | Raises 400 if no project is open |
| `_find_shot(project, shot_id)` | Looks up a shot or raises 404 |
| `_track_project(app, project)` | Stores project in `app.state` and records its disk mtime |
| `_refresh_project_from_disk(app)` | Reloads `shots.json` if changed on disk (skipped when dirty) |
| `_autosave(app)` | Saves project and clears the dirty flag |
| `_touch_live_bridge(app, ...)` | Writes `storyboard_live_bridge.json` with current project + selection |
| `_bridge_status_payload(app)` | Builds the full `/api/bridge/status` response dict |
| `_project_payload(project, dirty)` | Serialises the project + all shots for the frontend |
| `_shot_payload(project, shot)` | Serialises one shot with disk mtimes and artwork flags |
| `_plugin_link_state(app)` | Returns `(linked, age, open_shot_ids)` from heartbeat file + HTTP |

---

## 9. shot_service Role

`storyboard_tool/shot_service.py` — canonical shot domain module.

All shot business logic lives here. **No FastAPI or HTTP imports** — errors are raised as `ValueError` so callers at the HTTP boundary can convert them to the appropriate status code.

| Function | Description |
|---|---|
| `find_shot_index(project, shot_id)` | Returns list index or raises `ValueError` |
| `find_shot(project, shot_id)` | Returns the `Shot` object or raises `ValueError` |
| `create_shot(project, after_shot_id)` | Wraps `project_manager.add_shot`; resolves optional after-ID |
| `duplicate_shot(project, shot_id)` | Wraps `project_manager.duplicate_shot` with lookup |
| `delete_shot(project, shot_id)` | Wraps `project_manager.delete_shot` with lookup |
| `reorder_shots(project, shot_ids)` | Delegates to `project_manager.reorder_shots` |
| `update_shot(shot, data)` | Updates all editable shot fields in-place |
| `update_shot_duration(shot, seconds)` | Sets duration with a minimum of 0.1 s |

`app_state._find_shot` and `app_state._find_shot_index` delegate to this module and convert `ValueError` to `HTTPException(404)`.

---

## 10. project_manager Role

`storyboard_tool/project_manager.py`

**Responsibilities**

- Project lifecycle: `create_project()`, `open_project()`, `save_project()`
- Shot list CRUD: `add_shot()`, `duplicate_shot()`, `delete_shot()`, `restore_shot()`, `reorder_shots()`
- Canonical file paths: `get_shot_dir()`, `resolve_shot_preview_path()`, `resolve_shot_thumbnail_path()`
- Canvas management: `get_canvas_color()`, `create_canvas_for_shot()`
- Change detection: `project_disk_mtime()` (combines mtime of `project.json`, `settings.json`, `shots.json`)
- Atomic JSON writes: `_atomic_write_json()` — writes to a temp file in the same directory, then calls `os.replace()` to overwrite atomically (crash-safe)

**Atomic save**

`save_project()` and `save_settings()` use `_atomic_write_json()` so a crash or write error during save never leaves a partial or empty JSON file.

**On-disk project structure**

```
Storyboard_Project/
  project.json          — manifest: name, created date
  settings.json         — canvas size, canvas color, Photoshop/Blender paths, ref segments
  shots.json            — canonical shot store
  backups/
    ref_undo/           — per-apply snapshots for reference segment undo
  shots/
    shot_001/
      shot_001_preview.png
      shot_001_thumb.png
      shot_001_annotations.json
      references/       — per-shot reference images
  references/           — project-level reference files (images, video, GLB)
  exports/              — PDF, contact sheets, timing JSON
```

---

## 11. project_transaction: Snapshot and Rollback

`storyboard_tool/project_transaction.py`

Provides a context manager, `mutate_project(project)`, that:

1. Deep-copies `project.shots` and `project.settings` before the guarded block runs.
2. Restores the snapshot if the block raises any exception.
3. Does nothing extra on success.

```python
with project_transaction.mutate_project(project):
    shot_service.delete_shot(project, shot_id)
# If delete_shot raises, project.shots is automatically restored.
```

**Operations wrapped with `mutate_project`**

- `method_delete_shot`
- `method_restore_shot`
- `method_reorder_shots`
- `method_apply_ref_segment` (all variants)
- `method_restore_ref_apply`
- `method_delete_ref_segment`
- `method_create_shot_canvas`
- `method_save_shot_drawing`

This is an in-memory guard only. It does not protect against failures that occur *during the subsequent `_autosave()`* — those are protected by the atomic file write.

---

## 12. reference_segments Role

`storyboard_tool/reference_segments.py`

Handles all workflows for applying reference material to shot ranges.

**Apply modes**

| Mode | Input | Process |
|---|---|---|
| Image | PNG / JPG uploaded to `references/` | Scale / tile image over board range |
| Video | MP4 / MOV in `references/` | Extract frame at timestamp; scale to board |
| 3D capture | GLB in `references/` | Render camera view from Scene3DEditor; bake PNG |
| Model captures | Pre-rendered PNGs from 3D panel | Apply existing capture set to shot range |

**Undo mechanism**

Before any apply, `snapshot_boards_for_undo()` copies the affected preview PNGs to `backups/ref_undo/<token>/`. `restore_boards_from_undo(token)` copies them back and deletes the snapshot.

**Provenance stamping**

Each applied shot's `camera_data` field receives:
- `ref_segment_id` — which segment was applied
- `ref_source_type` — `"image"`, `"video"`, `"3d"`, or `"builtin"`
- `ref_applied_at` — ISO timestamp
- `ref_frame_time` — source frame time (video/3D only)

---

## 13. Photoshop Plugin API

`/api/plugin/*` — endpoints consumed exclusively by the Photoshop UXP plugin (`photoshop_uxp_plugin/`).

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/plugin/heartbeat` | POST | Plugin reports it is alive; carries `selected_shot_id` and `open_shot_ids` |
| `/api/plugin/context` | GET | Full project context for the plugin panel (shots, canvas, selected shot, bridge status) |
| `/api/plugin/shots/{shot_id}/export-preview` | POST | Plugin has exported a preview PNG; update shot's preview path and autosave |
| `/api/plugin/shots/{shot_id}/psd-saved` | POST | Plugin has saved a PSD; update shot's `source_file_path` and autosave |
| `/api/plugin/shots/{shot_id}/focus` | POST | Switch the selected shot to `shot_id` in both the app and live bridge |
| `/api/plugin/shots/next` | POST | Advance to the next shot (optionally creating one if `auto_add=true`) |

**Plugin link detection**

`app_state._plugin_link_state(app)` returns `(linked, age_seconds, open_shot_ids)`.
A plugin is considered linked if its last heartbeat (file or HTTP) is ≤12 seconds old.

When the plugin is linked and has a shot open as a tab, `method_open_source` switches focus in the plugin instead of re-launching Photoshop (avoids duplicate documents).

---

## 14. Scene3D TypeScript Source and Generated Runtime Bundle

### Source

`frontend/src/scene3d/` — TypeScript, part of the `frontend/` project.

The canonical implementation of the 3D workspace lives in `frontend/src/scene3d/workspace/`. It is compiled separately from the main React bundle.

Key source files:

| File | Role |
|---|---|
| `workspace/staticEntry.ts` | Bundle entry; re-exports all public API |
| `workspace/workspaceEditor.ts` | `Scene3DEditor` class — the main public object |
| `workspace/workspaceBridge.ts` | Three.js renderer and scene setup |
| `workspace/workspaceCamera.ts` | Camera helpers, focal-length conversion |
| `workspace/workspaceCapture.ts` | PNG rendering (`captureRendererPng`) |
| `workspace/workspaceGlb.ts` / `workspaceGlbLoad.ts` | GLB parsing and Three.js loading |
| `workspace/workspacePrimitives.ts` | Primitive mesh factory |
| `workspace/workspaceState.ts` | Scene serialisation / deserialisation |
| `workspace/workspaceAnimation.ts` | Timeline playback |
| `workspace/workspaceLighting.ts` | Light creation and calibration |
| `workspace/workspaceMaterials.ts` | Material system |
| `scene3d/previewStyle.ts` | Canonical wireframe / preview-color logic (imported directly by React components) |

### Build

```bash
cd frontend
npm run build:workspace
# → storyboard_tool/web/static/runtime/scene3d_workspace.js
```

Uses `vite.workspace.config.ts`. Output format is ESM. Three.js imports resolve through the import map in `frontend/index.html` at runtime and are kept external to the bundle.

### Runtime usage

`Scene3DPanel.tsx` loads the workspace bundle lazily:

```typescript
const workspace = await import('/static/runtime/scene3d_workspace.js');
const editor = await workspace.initWorkspaceEditorThree(container, glbUrl, sceneData);
```

The bundle is served by FastAPI at `GET /static/runtime/scene3d_workspace.js`.

### Vendor Three.js

Location: `storyboard_tool/web/static/vendor/three/`

Files: `three.module.js`, `GLTFLoader.js`, `OrbitControls.js`, `TransformControls.js`, `RoomEnvironment.js`

These are never modified and are not rebuilt. They are referenced by the import map in `frontend/index.html`.

---

## 15. Generated Files Policy

The following files are compiled artefacts committed to git. They must be regenerated (not hand-edited) after changing their TypeScript source.

| File | Source | Rebuild command |
|---|---|---|
| `storyboard_tool/web/dist/` | `frontend/src/` | `cd frontend && npm run build` |
| `storyboard_tool/web/static/runtime/scene3d_workspace.js` | `frontend/src/scene3d/workspace/staticEntry.ts` | `cd frontend && npm run build:workspace` |

**Why committed?** The Python desktop app is deployed without Node.js. Bundles are pre-built so the app can run with only `pip install -r requirements.txt && python main.py`.

**Hand-edit policy**

| Path | Rule |
|---|---|
| `frontend/src/**` | Edit freely — TypeScript/React source |
| `storyboard_tool/api.py` and all Python modules | Edit freely |
| `storyboard_tool/web/dist/**` | Never hand-edit; regenerate with `npm run build` |
| `storyboard_tool/web/static/runtime/scene3d_workspace.js` | Never hand-edit; regenerate with `npm run build:workspace` |
| `storyboard_tool/web/static/vendor/three/**` | Never modify; these are pinned vendor copies |

---

## 16. Kept Routes

A small number of routes exist for compatibility reasons that are not obvious from their names.

| Route | Reason kept |
|---|---|
| `GET /react` and `GET /react/{path}` | Vite's `base: '/react/'` setting makes all generated asset paths start with `/react/assets/…`. Changing the base would require rebuilding and re-auditing all asset references. |
| `GET /ref-video` → redirect to `/` | The Photoshop UXP bridge originally opened a second window at this URL. The route is kept so that any plugin versions still sending heartbeats to `/ref-video` are silently redirected rather than 404-ing. |

---

## 17. Deleted Legacy Artifacts

The following were removed in the desktop-only and architecture-cleanup refactors. They are documented here so future readers understand why they are absent.

**Legacy HTML/CSS (pre-React)**

- `storyboard_tool/web/index.html` (main page, replaced by `web/dist/index.html`)
- `storyboard_tool/web/ref_segment.html` (standalone reference-segment window)
- `web/static/styles.css`, `themes.css`, `reference_media.css`, `ref_segment_window.css`

**Legacy JavaScript (pre-TypeScript migration)**

- `web/static/app/` — all classic JS modules (`app.js`, `annotations.js`, `sync_polling.js`, etc.)
- `web/static/core/` — all classic JS core modules
- `web/static/scene3d.js` — one-line re-export shim (callers now import from workspace bundle directly)
- `web/static/scene3d_preview_style.js` — logic moved to `frontend/src/scene3d/previewStyle.ts`

**Deleted routes**

- `GET /legacy` — old HTML entry point
- `GET /ref-segment` — standalone reference-segment window
- `GET /ref-scene3d` — standalone Scene3D window

**Deleted Python back-compat alias**

- `desktop.start_server()` — use `start_internal_server()` from `storyboard_tool/desktop.py`

**Deleted CLI mode**

- `--browser` / `--host` startup flags — the internal server no longer has a browsable mode

---

## 18. Non-Goals

The following are explicitly out of scope and not implemented:

- Network-accessible server (all traffic is loopback only)
- Browser-accessible UI (pywebview is the only supported client)
- Cloud sync or remote collaboration
- Audio features or video export
- Blender or Unreal live capture (Blender scene files can be opened; capture is not automated)
- Mobile or tablet support
- Multi-window layout (second windows redirect to the main SPA)
