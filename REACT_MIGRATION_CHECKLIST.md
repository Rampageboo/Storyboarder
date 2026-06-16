# React Frontend Migration Checklist

The React + Vite frontend under `frontend/` is being introduced as a **parallel** UI candidate served at
`/react`, alongside the existing legacy frontend at `/`. The legacy frontend is **not** removed — `/` is
only switched to React after this checklist passes.

## What changed

- **Build output:** `npm run build` (run from `frontend/`) now writes to **`storyboard_tool/web/dist/`**
  with Vite `base: '/react/'` (see [frontend/vite.config.ts](frontend/vite.config.ts)). Built asset URLs
  therefore start with `/react/assets/...`. This directory is git-ignored.
- **Serving:** FastAPI serves the build via guarded routes `GET /react` and `GET /react/{asset_path:path}`
  (SPA fallback scoped to `/react/...` only), added in [storyboard_tool/api.py](storyboard_tool/api.py).
  A missing build returns a 404 with a "run npm run build" hint instead of crashing. The existing
  no-store cache policy now also covers `/react` (avoids stale WebView2 assets).
- **Unchanged:** `/`, `/static`, `/ref-segment`, `/ref-scene3d`, `/ref-video`, and all `/api/*` routes.
  No backend business logic or API response shapes were modified.

## New config paths

| Path | Purpose |
| --- | --- |
| `storyboard_tool/web/dist/` | React production build output (served at `/react`). Git-ignored. |

## How to run

```bash
cd frontend
npm install        # first time only
npm run build      # builds into ../storyboard_tool/web/dist with base /react/
cd ..
python main.py
# then open http://127.0.0.1:8000/react
```

For React dev mode with hot reload (legacy backend must be running on :8000 for the `/api` proxy):

```bash
cd frontend
npm run dev        # http://localhost:5173/react/  (API calls proxy to :8000)
```

## Manual test checklist

Run after `npm run build` + `python main.py`, in the WebView2 app or a browser at the URLs below.

### Serving / regression
- [ ] `http://127.0.0.1:8000/` → **legacy** frontend loads and works (regression check).
- [ ] `http://127.0.0.1:8000/react` → React app loads; assets return 200 under `/react/assets/...`.
- [ ] `/ref-segment`, `/ref-scene3d`, `/ref-video` still return the legacy reference window.

### Core data flow (in `/react`)
- [ ] Create a new project (New).
- [ ] Add 3 shots (timeline **+ Add** and the between-shot insert **+** buttons).
- [ ] Edit a shot's **title**, **description**, and **duration**; click **Save** (button enables only when dirty).
- [ ] **Rapidly switch between shots after editing**: edit Shot A, switch to B and edit B, switch back to A —
      *both shots keep their unsaved edits* (no loss, no cross-shot overwrite).
- [ ] Click **Save** on a shot, then keep typing in the same shot before the response returns —
      the in-flight response does **not** revert your newer text (stale-response guard).
- [ ] Save the project (topbar **Save**; enabled when the project or any shot has unsaved changes).
- [ ] Reopen the project (see file picker below) and confirm edits persisted.

### Files / uploads
- [ ] Import image (Canvas **Upload image**) → preview updates (cache-bust via `preview_disk_mtime`).
- [ ] Import PSD/source (Advanced **Upload source (PSD)**).
- [ ] Add reference image (Advanced **Add reference image**).
- [ ] Delete preview image (Canvas **Delete image**) → placeholder shows.
- [ ] Refresh preview (Canvas **Refresh**) → re-fetches the image (no project-state replacement).

### Open via backend file picker
- [ ] Topbar **Open** launches the native file picker (no `prompt()` dialog).
- [ ] Cancelling the picker does nothing (no error, no state change).
- [ ] Choosing a `project.json` opens it and selects a sensible shot.

### Dirty / flush safety
- [ ] With an unsaved shot edit pending, trigger a structural action (Save project / Open another project /
      Delete a shot / Move a shot / Upload a file). The pending edit is flushed first.
- [ ] If a flush fails (e.g., backend stopped), the action is aborted and an error is shown; the local edit
      is **not** discarded.

## Validation commands

```bash
python -m py_compile storyboard_tool/api.py storyboard_tool/models.py storyboard_tool/backups.py
cd frontend && npm run build && cd ..
```

## Known limitations / TODO

- No debounced autosave — saves are explicit (Save) or flushed before structural actions; the per-shot
  version guard protects against late/stale responses regardless of trigger.
- `/react` assets are served `no-store` (consistent with the legacy WebView2 policy) — slightly less
  cache-efficient than Vite's content-hashed assets, but avoids stale-asset bugs during migration.
- `/` is **not** switched to React in this task. Do that only after this checklist passes.
