# Storyboarder — Current Architecture

> Last updated: 2026-06-19 (asset lifecycle boundaries)
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
19. [Asset Lifecycle Boundaries](#19-asset-lifecycle-boundaries)
20. [Generation Queue and Codex MCP Handoffs](#20-generation-queue-and-codex-mcp-handoffs)
21. [Scene and Character Prompt Bibles](#21-scene-and-character-prompt-bibles)

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
| Frontend | React 19 + TypeScript, built with Vite |
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
- `desktop.py` does not expose any JavaScript bridge; all communication goes through the HTTP API. (The legacy pywebview `js_api` bridge — `DesktopBridge` in `bridge.py` — was unused by the React frontend and has been removed.)

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
| `state/ProjectContext.tsx` | Project server state, selected shot, dirty shot drafts, project busy/error flags, and central project actions that replace the project payload |
| `state/useProject.ts` | Public hook for reading project state and calling ProjectContext actions |
| `state/LiveBridgeContext.tsx` | Bridge heartbeat/status polling; delegates project refreshes caused by plugin revisions back to ProjectContext |
| `state/liveBridgeUtils.ts` | Bridge-specific context hook and display helpers |
| `api/client.ts` | Thin `fetch` wrapper; `ApiError` class carries HTTP status |
| `api/project.ts`, `api/shots.ts`, `api/references.ts`, … | Domain-specific HTTP methods |

Frontend state ownership is intentionally narrow:

- `ProjectContext` owns server-backed project payloads, selected-shot behavior, dirty/saving shot drafts, project fetch/save busy state, and project-level actions such as add/delete/sync/open selected shot.
- `LiveBridgeContext` owns bridge status, heartbeat publication, plugin revision polling, and Photoshop connection metadata. It delegates project refreshes back to `ProjectContext`.
- Component-local state stays local when it is only needed by one component: text input drafts, annotation editor rows, image load failures, popover form fields, lightboxes, upload notes, relink paths, and per-panel open/closed state.
- Derived state should be computed from `project`, `selectedShotId`, or component props with `useMemo` or pure helpers rather than stored globally.
- There is no UI layout context today; shared layout state has not crossed enough unrelated components to justify one.

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
| Export generation | `export_service.py` + `export_utils.py` |
| Photoshop bridge | `live_bridge.py` |
| Image processing | `image_utils.py` |
| Video processing | `video_utils.py` |
| File dialogs | `system_utils.py` |
| App/project state helpers | `app_state.py` |

`StoryboardBackendService` inherits from `ExportServiceMixin` (`service_exports.py`), which adapts backend `method_export_*` and `method_download_*` handlers to the canonical export logic in `export_service.py`.

---

## 8. app_state Helpers

`storyboard_tool/app_state.py` — transport-agnostic project and app-state utilities.

These functions were extracted from `api.py` so the service layer can use them without reaching "up" into the route module, avoiding circular imports.

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
- `method_apply_ref_segment` (all variants — video, image, 3D, model captures)
- `method_restore_ref_apply`
- `method_delete_ref_segment`
- `method_delete_project_reference` (modifies shots + settings when clearing segment references)
- `method_import_scene3d` (settings only — reverts `settings.scene3d` if file write or save fails)
- `method_create_shot_canvas`
- `method_save_shot_drawing`

This is an in-memory guard only. It does not protect against failures that occur *during the subsequent `_autosave()`* — those are protected by the atomic file write.

---

## 12. reference_segments Role

`storyboard_tool/reference_segments.py`

Owns all reference domain business logic. `project_manager.py` re-exports every public function from this module so callers can import from either name.

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
- `ref_source_type` — `"image"`, `"video"`, or `"model"`
- `ref_applied_at` — ISO timestamp
- `ref_frame_time` — source frame time (video/3D only)

`delete_ref_segment` reads and clears this provenance to determine which boards to reset.

**Active reference helpers**

| Function | Purpose |
|---|---|
| `set_active_reference_video(project, path)` | Set active video + update legacy fields; saves settings |
| `clear_active_reference_video(project)` | Clear video path + per-shot ref fields; saves settings |
| `set_active_reference_model(project, path)` | Set active model + scene3d metadata; saves settings |
| `clear_active_reference_model(project)` | Clear model path; reset mode to `"video"` if needed; saves settings |
| `set_active_reference_image(project, path)` | Set active image; saves settings |
| `clear_active_reference_image(project)` | Clear image path; reset mode to `"video"` if needed; saves settings |

**Reference library helpers**

| Function | Purpose |
|---|---|
| `normalize_reference_links(value)` | Parse and deduplicate `reference_links` list |
| `ensure_reference_library(settings)` | Promote legacy path fields into `reference_links` |
| `import_project_reference_stream(project, stream, name)` | Write file to `references/`, append to library |
| `remove_project_reference(project, ref_id)` | Delete file + clear segment references that pointed to it |

**Segment helpers**

| Function | Purpose |
|---|---|
| `normalize_ref_segments(settings)` | Parse modern `ref_segments` list or migrate legacy single-segment format |
| `find_ref_segment(project, segment_id)` | Look up segment by id, fall back to active, then to first |
| `sync_ref_segment_settings(project)` | Keep legacy `ref_segment` / `ref_segment_video` keys in sync with `ref_segments` list |
| `resolve_segment_reference(project, segment)` | Return `(rel_path, source_type)` for a segment, resolving by `reference_id` or `reference_path` |
| `_segment_board_range(shots, anchor_idx, end_idx)` | Clamp and normalise an index pair; raises if shots is empty |
| `_segment_board_range_by_shot_id(shots, anchor_id, end_id)` | Like above but looks up by shot id |

**What this module does NOT own**

- Generic project persistence (`project_manager.save_project`, `save_shots`) — called as side effects only
- HTTP route parsing (no FastAPI imports)
- Photoshop plugin bridge logic
- Frontend display calculation (see `frontend/src/utils/refSegmentDisplay.ts`)
- Board image compositing primitives (`_apply_reference_frame_to_shot`, `_apply_model_capture_to_shot` live in `project_manager.py` because they depend on canvas geometry helpers)

**Frontend reference helpers**

`frontend/src/utils/refSegmentDisplay.ts` — pure TypeScript display helpers.

| Export | Purpose |
|---|---|
| `resolveVisibleSegmentMarkerSpans` | Compute filmstrip marker spans (applied vs pending) for a shot array |
| `findRefSegment` | Look up a segment record by id |
| `segmentBoardIndexRange` | Resolve anchor/end shot ids to `{lo, hi}` indices |
| `segmentsOverlapBoardRange` | Test whether two segment records overlap |
| `isShotAppliedToSegment` | Test whether a shot has provenance from a given segment |
| `segmentHasPendingBoards` | True if any board in the segment range is not yet applied |
| `refSegmentsWithoutOverlap` | Optimistic client-side dedup before a new apply (mirrors backend delete logic) |
| `segmentTypeLabel`, `segmentCssType` | Display label / CSS class for a source type |
| `segmentMarkerTooltip` | Tooltip string for a marker span |

These helpers are pure functions with no side effects and are safe to call in `useMemo`.

---

## 13. Photoshop Plugin API

The Photoshop bridge has two related surfaces:

- `/api/bridge/*` is the desktop app and live-link status surface. The React app uses it for heartbeat and status polling; older plugin builds can also use it for heartbeat compatibility.
- `/api/plugin/*` is the UXP plugin contract. The plugin uses it for project context, shot focus, preview export, PSD-saved notifications, and next-shot navigation.

### Bridge endpoint map

| Endpoint | Backend method | Primary caller | Request | Response | Side effects |
|---|---|---|---|---|---|
| `GET /api/bridge/live` | `method_touch_live_bridge()` | Plugin discovery / compatibility | none | Live bridge JSON file payload | Refreshes `storyboard_live_bridge.json` |
| `PUT /api/bridge/live` | `method_touch_live_bridge(selected_shot_id)` | `LiveBridgeContext.tsx` | `LiveBridgeUpdateRequest` (`selected_shot_id`) | Live bridge JSON file payload | Updates `app.state.live_selected_shot_id`; refreshes live bridge file |
| `POST /api/bridge/relink` | `method_bridge_relink()` | Frontend advanced tools | none | Bridge status payload | Requires open project; refreshes live bridge file |
| `GET /api/bridge/status` | `method_bridge_status()` | `LiveBridgeContext.tsx`, Topbar, Advanced panel | none | `BridgeStatusResponse` fields plus `live` payload | Refreshes live bridge file; reports current plugin heartbeat state |
| `POST /api/bridge/plugin-heartbeat` | `method_plugin_heartbeat()` | Older UXP fallback | `PluginHeartbeatRequest` | `{ "ok": "true" }` | Updates transient plugin heartbeat state |
| `POST /api/plugin/heartbeat` | `method_plugin_heartbeat()` | Current UXP plugin | `PluginHeartbeatRequest` | `{ "ok": "true" }` | Updates transient plugin heartbeat state |
| `GET /api/plugin/context` | `method_plugin_context()` | UXP plugin | none | `PluginContextResponse` shape | Refreshes project from disk when safe; embeds bridge status |
| `POST /api/plugin/shots/{shot_id}/export-preview` | `method_plugin_export_preview()` | UXP plugin | `PluginShotEventRequest` (`preview_image_path`, optional `source_file_path`) | `{ shot, context }` | Validates project-relative paths; relinks preview; autosaves; increments `plugin_project_revision`; records `plugin_last_exported_preview[shot_id]` |
| `POST /api/plugin/shots/{shot_id}/psd-saved` | `method_plugin_psd_saved()` | UXP plugin | `PluginShotEventRequest` (`source_file_path`) | `{ shot, context }` | Validates PSD path; updates `source_file_path` metadata; autosaves; increments `plugin_project_revision` |
| `POST /api/plugin/shots/{shot_id}/focus` | `method_plugin_focus_shot()` | UXP plugin | none | Plugin context payload | Validates shot; updates plugin/app selected shot; persists app session; refreshes live bridge file |
| `POST /api/plugin/shots/next` | `method_plugin_next_shot()` | UXP plugin | `PluginNextShotRequest` (`current_shot_id`, `auto_add`) | `{ shot, created, context }` | Selects next shot; optionally creates/autosaves a shot; increments revision only when a shot is created |

### Bridge ownership

| Area | Owner | Notes |
|---|---|---|
| Route parsing and request models | `api.py`, bridge request models in `schemas.py` | Routes should only parse Pydantic inputs and call `StoryboardBackendService`. |
| Project-changing bridge behavior | `backend_service.py` | Preview export, PSD-saved, focus, next-shot, and revision increments live here. |
| Transient app/bridge state payloads | `app_state.py` | Owns `_touch_live_bridge()`, `_bridge_status_payload()`, `_plugin_link_state()`, heartbeat source precedence, and app session persistence. |
| File/project persistence | `project_manager.py` | Owns project-relative path resolution, preview relinking, thumbnail generation, and disk saves. |
| Frontend polling | `LiveBridgeContext.tsx` | Publishes app heartbeat and polls `/api/bridge/status`; it does not rebuild project payloads itself. |
| Frontend project replacement | `ProjectContext.tsx` | Owns `refreshProjectFromBridge()`, including selection fallback when the plugin-selected shot is stale. |
| Bridge display helpers | `liveBridgeUtils.ts` | Owns the bridge status hook and label helpers only. |

### Key fields

| Field | Owner | Meaning |
|---|---|---|
| `plugin_selected_shot_id` | Plugin heartbeat / focus endpoints, exposed by `app_state._bridge_status_payload()` | Shot the plugin currently reports as selected. Frontend should use it only if it exists in the refreshed project payload. |
| `plugin_open_shot_ids` | Plugin heartbeat, normalized in `app_state._plugin_open_shot_ids()` | Shot ids for open Photoshop tabs; used to focus existing plugin tabs instead of launching Photoshop again. |
| `plugin_last_exported_preview` | `method_plugin_export_preview()` | Per-shot timestamp for the latest plugin preview export. |
| `plugin_project_revision` | Backend plugin mutation methods | Monotonic in-memory counter telling `LiveBridgeContext.tsx` to ask `ProjectContext` for a project refresh. |
| `focus_request` in live bridge payload | `method_open_source()` / `_request_plugin_focus()` | One-shot request for the plugin to focus an already-open tab; includes a monotonic token so polling does not repeatedly switch tabs. |

### UXP linked mode and local fallback

When the plugin can reach the backend, it is in backend-linked mode:

- it reads `/api/plugin/context` for project, canvas, selected shot, paths, and bridge status;
- it sends `/api/plugin/heartbeat` with selected/open shot ids;
- it reports preview and PSD metadata through plugin endpoints;
- `panel_storage_adapter.js` avoids writing canonical project metadata files directly and refreshes from the backend instead.

When no backend is reachable, the plugin falls back to local project files (`project.json`, `shots.json`, `shots.csv`, `storyboard_bridge.json`) for compatibility. Do not casually change the linked-mode endpoints, field names, heartbeat file names, or local fallback behavior; older plugin sessions and saved projects depend on them.

**Plugin link detection**

`app_state._plugin_link_state(app)` returns `(linked, age_seconds, open_shot_ids)`.
A plugin is considered linked if its last heartbeat (file or HTTP) is ≤12 seconds old.

When the plugin is linked and has a shot open as a tab, `method_open_source` switches focus in the plugin instead of re-launching Photoshop (avoids duplicate documents).

---

## 14. Scene3D TypeScript Source and Generated Runtime Bundle

### Pipeline overview

```
User imports GLB   → /api/project/scene3d/import  → external_tools.import_scene3d_stream()
                                                     → writes scene3d/scene.glb
                                                     → updates settings.scene3d
User opens Blender → /api/project/scene3d/open-blender → external_tools.open_blender_scene()
                                                          → launches blender.exe

 ┌── Scene3DPanel.tsx ──────────────────────────────────────────────────────┐
 │  Loads workspace bundle lazily via                                        │
 │    import('/static/runtime/scene3d_workspace.js')                        │
 │  Scene3DEditor (workspace) ← user interacts → camera/view state          │
 │  captureToBoard()          → captureFrameDataUrl()  → PNG data URL        │
 │    → uploadShotImage()     → /api/shots/{id}/image  → persists preview   │
 │    → updateShot()          → /api/shots/{id}        → saves camera_data  │
 └──────────────────────────────────────────────────────────────────────────┘

 ┌── ReferenceAssignmentPopover3dApply.tsx ─────────────────────────────────┐
 │  applyModelCaptures()                                                     │
 │    ReferenceModelPreview.captureFrame()  → one PNG per board             │
 │    → /api/project/ref-segment/apply-model-captures                       │
 │         → reference_segments.apply_model_captures_to_boards()            │
 │              → validates PNG data URLs, stamps provenance, saves images  │
 └──────────────────────────────────────────────────────────────────────────┘
```

**Key constraint: all 3D rendering is TypeScript-only.** Python never drives Three.js. The backend
`apply_model_captures_to_boards` receives pre-rendered PNG data URLs from the frontend and stamps
provenance/metadata, applies compositing, and persists board images. It does not render GLBs.

### Source

`frontend/src/scene3d/` — TypeScript, part of the `frontend/` project.

The canonical implementation of the 3D workspace lives in `frontend/src/scene3d/workspace/`. It is compiled separately from the main React bundle.

**Top-level scene3d modules** (imported directly by React components)

| File | Role |
|---|---|
| `scene3dTypes.ts` | Shared types: `Scene3dReferenceView`, `Scene3dCaptureRequest`, `RefSegmentModelCapture` |
| `threeRuntime.ts` | Singleton loader for the Three.js vendor bundle; single source of truth for dynamic import URLs |
| `previewStyle.ts` | Canonical wireframe / object-color preview logic shared between React and workspace bundle |
| `scenePreviewSettings.ts` | Thin wrapper: resolves `Scene3dPreviewSettings` from `ProjectSettings` |
| `glbScene.ts` | GLB scene loading helper (used by `referenceGlbRenderer.ts`) |
| `referenceGlbRenderer.ts` | Self-contained WebGL renderer for the reference model preview canvas |
| `capture.ts` | Canvas readback helpers (`captureCanvasPng`, `isBlankCanvas`) |
| `applyModelCaptures.ts` | Render one GLB frame per board in range; pure function, no project writes |

**Workspace bundle modules** (compiled to `scene3d_workspace.js`)

| File | Role |
|---|---|
| `workspace/staticEntry.ts` | Bundle entry; re-exports all public API |
| `workspace/workspaceEditor.ts` | `Scene3DEditor` class — the main public object constructed by `Scene3DPanel` |
| `workspace/workspaceBridge.ts` | Three.js renderer and scene setup |
| `workspace/workspaceCamera.ts` | Camera helpers, focal-length conversion |
| `workspace/workspaceCapture.ts` | PNG rendering (`captureRendererPng`); re-exports `capture.ts` helpers |
| `workspace/workspaceGlb.ts` / `workspaceGlbLoad.ts` | GLB parsing and Three.js loading |
| `workspace/workspacePrimitives.ts` | Primitive mesh factory |
| `workspace/workspaceState.ts` | Scene serialisation / deserialisation |
| `workspace/workspaceAnimation.ts` | Timeline playback |
| `workspace/workspaceLighting.ts` | Light creation and calibration |
| `workspace/workspaceMaterials.ts` | Material system |

**React integration components**

| Component | Role |
|---|---|
| `Scene3DPanel.tsx` | Panel UI: import GLB, open workspace overlay, capture to board, save scene settings. Owns the `Scene3DEditor` instance lifecycle. |
| `ReferenceModelPreview.tsx` | Inline 3D preview canvas using `ReferenceGlbRenderer`. Also exposes `captureFrame()` via ref handle for the assignment popover. |
| `ReferenceAssignmentPopover3dApply.tsx` | Assignment popover; orchestrates per-board captures via `applyModelCaptures` and calls the backend apply endpoint. |

**Utility helper**

| File | Role |
|---|---|
| `utils/scene3dView.ts` | Pure helpers: `resolveScene3dReferenceView` (workspace view → shot/settings priority chain), `describeScene3dView` |

### Backend Scene3D endpoints

| Endpoint | Handler | What it does |
|---|---|---|
| `POST /api/project/scene3d/import` | `method_import_scene3d` | Write GLB to `scene3d/`, update `settings.scene3d`; wrapped in `mutate_project` |
| `POST /api/project/scene3d/open-blender` | `method_open_blender_scene` | Launch Blender with `scene3d/scene.blend`; copies template if missing |
| `GET /api/project/scene3d/file` | `method_get_scene3d_file` | Serve the linked GLB file for the workspace renderer |
| `POST /api/project/ref-segment/apply-model-captures` | `method_apply_ref_segment_model_captures` | Accept pre-rendered PNG data URLs; stamp provenance, composite board images |

`method_import_scene3d` is wrapped in `project_transaction.mutate_project` so an invalid import (bad extension, file write error) leaves `settings.scene3d` unchanged.

The backend module that owns 3D-specific file paths and Blender launch logic is `storyboard_tool/external_tools.py`. It is re-exported through `project_manager.py`.

### On-disk Scene3D structure

```
Storyboard_Project/
  scene3d/
    scene.glb     (or scene.gltf) — linked GLB imported by the user
    scene.blend   — Blender project file (copied from assets/scene_template.blend on first open)
```

### Build

```bash
cd frontend
npm run build:workspace
# → storyboard_tool/web/static/runtime/scene3d_workspace.js
```

Uses `vite.workspace.config.ts`. Output format is ESM. `/static/vendor/three/` imports are kept external (resolved via the import map in `frontend/index.html` at runtime).

### Runtime usage

`Scene3DPanel.tsx` loads the workspace bundle lazily via `loadScene3DEditorClass()` in `workspace/loadScene3DEditor.ts`:

```typescript
const Scene3DEditor = await loadScene3DEditorClass()
const editor = new Scene3DEditor(rootEl, { onApplyShotCamera, onCaptureToBoard, … })
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

---

## 19. Asset Lifecycle Boundaries

This section maps each asset type to its on-disk location, the module that owns it, and the deletion/rollback behaviour.

### 19.1 On-disk directory layout

```
<root>/                        ← project.root_path
  project.json                 ← lightweight version manifest
  settings.json                ← all project settings (atomic write via temp + replace)
  shots.json                   ← canonical shot list
  shots.csv                    ← read-only compatibility snapshot (written on save, never read back)
  shots/
    <shot_id>/
      <shot_id>_preview.png    ← artist artwork export (from Photoshop, drawing tool, or image import)
      <shot_id>_background.png ← reference / background plate (owned by reference apply flows)
      <shot_id>_codex.png      ← accepted generated image (never artist artwork)
      <shot_id>_thumb.png      ← thumbnail for filmstrip / timeline display
      <shot_id>.psd            ← Photoshop canvas (optional)
      <shot_id>_annotations.json
      _history/                ← PSD recovery backups
  references/
    ref_<uuid>.<ext>           ← imported video/image/model references
  scene3d/
    <filename>.glb / .gltf     ← imported 3D scene files
  exports/                     ← PDF, CSV, contact-sheet output (never input)
  backups/                     ← rolling project.json + shots.json copies on save
  backups/ref_undo/<token>/    ← pre-apply board snapshot (preview + bg + thumb copies)
  scripts/                     ← Blender .blend template
```

### 19.2 Board asset model

Four per-shot files serve distinct roles and must not be conflated:

| File | Owner | Written by | Must NOT be written by |
|---|---|---|---|
| `<id>_preview.png` | Artist / Photoshop | PSD export, drawing save, image import | Reference apply (video / image / model) |
| `<id>_background.png` | Reference system | `_apply_reference_frame_to_shot`, `_apply_model_capture_to_shot`, `import_image_for_shot` | Never by Photoshop sync |
| `<id>_codex.png` | Generation review | Explicit candidate acceptance | Never by Photoshop sync or drawing save |
| `<id>_thumb.png` | Display system | `_refresh_thumbnail_for_shot` (called by apply / import flows) | Never written as a primary operation |

**Display composite rule**: the fixed order is `_background.png` (bottom) + `_codex.png` + `_preview.png` (top, on transparency). The UI can temporarily hide individual layers; thumbnails and exports render the complete fixed-order composite. Neither composite generation nor thumbnail refresh may destroy the originals.

**Legacy boards**: projects created before this separation may have a `_preview.png` that IS a baked reference (the old model wrote the reference directly into the preview). Such shots are identified as "legacy-baked" — they have reference provenance (`camera_data["ref_segment_id"]` set) and no linked PSD or `source_file_path`. On `delete_ref_segment` their preview is cleared along with the background (since both represent the same baked reference). Shots that have a PSD or a `source_file_path` are never treated as legacy-baked.

### 19.3 Lifecycle flows and owning modules

| Flow | Files touched | Module | Transaction-safe? |
|---|---|---|---|
| `create_project` | root dirs, project.json, settings.json | `project_manager` | atomic JSON writes only |
| `add_shot` | `shots/<id>/` dir, optional blank canvas PSD | `project_manager` | no rollback needed — shot ID is new |
| `delete_shot` | removes Shot from `project.shots`; files are NOT deleted | `shot_service` → `project_manager` | `mutate_project` in `backend_service` |
| `import_image_for_shot` | writes `<id>_preview.png` + `<id>_background.png`, sets shot fields | `project_manager` | file write before metadata; `_autosave` commits |
| `remove_image_for_shot` | deletes `<id>_background.png`, clears shot preview fields | `project_manager` | no settings involved; shot-level only |
| `import_project_reference_stream` | writes `references/ref_<uuid>.<ext>`, appends to `reference_links` | `reference_segments` | `mutate_project` in `backend_service` |
| `remove_project_reference` | deletes reference file (if inside root), clears `reference_links` + any segments | `reference_segments` | `mutate_project` in `backend_service` |
| `import_scene3d_stream` | writes `scene3d/<name>.glb`, updates `settings["scene3d"]` | `external_tools` | `mutate_project` in `backend_service` |
| `apply_ref_segment_to_boards` | writes **only** `<id>_background.png` + `<id>_thumb.png`; stamps provenance metadata; does NOT touch `<id>_preview.png` or `source_file_path` | `reference_segments` | `mutate_project` in `backend_service`; undo snapshot taken first |
| `apply_model_captures_to_boards` | writes **only** `<id>_background.png` + `<id>_thumb.png`; stamps provenance metadata; does NOT touch `<id>_preview.png` or `source_file_path` | `reference_segments` | `mutate_project` in `backend_service`; undo snapshot taken first |
| Accept generation candidate | writes `<id>_codex.png` + `<id>_thumb.png`; updates approval state; does NOT touch preview/background/PSD | `generation_service` → `shot_assets` | `mutate_project` in `backend_service` |
| `delete_ref_segment` | deletes `<id>_background.png` + `<id>_thumb.png`; for legacy-baked shots (no PSD, has provenance) also deletes `<id>_preview.png`; clears shot metadata; removes segment from settings | `reference_segments` | `mutate_project` in `backend_service` |
| `snapshot_boards_for_undo` | copies preview/bg/thumb to `backups/ref_undo/<token>/` | `reference_segments` | snapshot is write-only; original files untouched |
| `restore_boards_from_undo` | copies snapshot PNGs back over current board files, restores shot metadata | `reference_segments` | `mutate_project` in `backend_service` |
| Export (PDF/CSV/contact sheet) | writes files under `exports/` only | `export_service` | no project metadata mutation |

**Atomic file safety**: `_apply_reference_frame_to_shot` and `_apply_model_capture_to_shot` write to a `.tmp.png` staging file, validate it can be opened, then `os.replace()` atomically into the final path. A compose failure unlinks the temp file and leaves the previous background intact.

### 19.4 Deletion behaviour

- **Shot files are never deleted on `delete_shot`.** Only the `Shot` object is removed from `project.shots`. The `shots/<id>/` directory and all its contents remain on disk. This is intentional: undo (via `restore_shot`) can re-insert the shot record, and the files remain available.
- **Reference files are deleted on `remove_project_reference`,** but only when the resolved path is inside `project.root_path`. External paths (e.g. a path accidentally set to an absolute path outside the project) are silently skipped without deletion.
- **On `delete_ref_segment`**: `<id>_background.png`, `<id>_thumb.png`, and `<id>_ref_raw.png` are always removed. `<id>_preview.png` is removed **only** for legacy-baked shots (no PSD, has provenance). Shots with a PSD or `source_file_path` keep their preview (PSD-backed shots get a fresh PSD composite regenerated). This is not reversible via the undo mechanism — undo is only for `apply_*` operations.
- **Export files are never deleted by the application.** Exports overwrite existing output files at the same path.

### 19.5 `mutate_project` coverage

`project_transaction.mutate_project` protects **in-memory** state (`project.shots` and `project.settings`) only. It does not roll back filesystem side-effects (PNG writes, file deletions). Methods wrapped with it in `backend_service`:

- `method_delete_shot`
- `method_restore_shot`
- `method_reorder_shots`
- `method_apply_ref_segment` / `_image` / `_3d` / `_model_captures`
- `method_restore_ref_apply`
- `method_delete_ref_segment`
- `method_delete_project_reference`
- `method_create_shot_canvas`
- `method_save_shot_drawing`
- `method_import_scene3d`
- `method_upload_project_reference`
- `method_upload_reference_video`

### 19.6 Missing-file reporting

`export_utils.missing_files(project)` iterates all shots and checks whether the files referenced by `preview_image_path`, `thumbnail_path`, `source_file_path`, `annotation_path`, and each entry in `reference_image_paths` actually exist on disk. It returns a list of `{shot_id, field, path}` dicts — one entry per broken reference. Used by `method_get_missing_files` in the backend service.

---

## 20. Generation Queue and Codex MCP Handoffs

`storyboard_tool/generation_service.py` owns generation request snapshots, queue listing, Codex result deposits, and explicit result reconciliation. A request captures authored shot details, the backend-compiled prompt, continuity context, reference paths, canvas dimensions, and an input revision hash. Request JSON is immutable after creation; mutable request status is stored separately.

```
<project>/generation/
  requests/<gen_id>.json              — immutable request snapshot
  state/<gen_id>.json                 — Storyboarder-owned mutable status
  results/<gen_id>/<out_id>.json      — result manifest deposited by MCP
  candidates/<gen_id>/<out_id>/*      — copied candidate image files
```

The desktop API exposes:

| Endpoint | Purpose |
|---|---|
| `POST /api/shots/{shot_id}/generation-requests` | Create a queue request or Codex handoff and update the shot's generation state. |
| `GET /api/generation/requests` | List requests, optionally filtered by shot, destination, or status. |
| `POST /api/generation/reconcile` | Import deposited result state into canonical shot generation metadata and mark candidates `needs-review`. |
| `POST /api/shots/{shot_id}/codex-layer/accept` | Copy one reviewed candidate into the independent fixed Codex layer and mark it accepted. |

`storyboard_tool/mcp_server.py` is a local STDIO MCP server configured by `.codex/config.toml`. It exposes read-only list/get tools plus `storyboard_submit_generation_result`, which validates and copies image artifacts into the project. The MCP server never edits `shots.json`, approves outputs, or mutates queue state. Storyboarder remains the owner of retries, stale propagation, review, and approval.

---

## 21. Scene and Character Prompt Bibles

Generation prompts have a fixed ownership hierarchy:

1. **Scene Bible** (`scenes2d/scenes2d.json`) owns stable environment, spatial layout, permanent props, baseline time/weather/light, and explicit locked anchors. The Scene 2D primary perspective is attached to generation requests as a `scene-environment` visual reference.
2. **Character Bible** (`settings.json.character_bible_prompt`) owns project-wide recurring identity and wardrobe. It does not decide who appears in a shot.
3. **Shot Override** (`shots.json`) owns framing, camera, composition, action, expression, dialogue, and angle-specific visibility. It cannot replace the two consistency layers, including in manual prompt mode.

Shots store both a backward-compatible free-text `scene` label and a stable `scene_id` link. Existing projects with no `scene_id` resolve a Scene Bible by an exact case-insensitive title match. Generation requests freeze the resolved Scene Bible, Character Bible, their visual reference, an overall `input_revision`, and a separate `consistency_revision`.

Changing a linked Scene Bible marks generated shots in that scene stale. Changing the Character Bible marks every shot with generation activity stale. No existing request snapshot is rewritten.
