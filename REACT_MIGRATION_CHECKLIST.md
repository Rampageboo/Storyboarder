# React Frontend Migration Checklist

**Migration complete (Phase 6).** React is the only UI. See [docs/typescript_policy.md](docs/typescript_policy.md) for the TypeScript policy.

## Architecture

- **Build output:** `npm run build` (from `frontend/`) writes to `storyboard_tool/web/dist/` with Vite
  `base: '/react/'` (see [frontend/vite.config.ts](frontend/vite.config.ts)).
- **Serving:** FastAPI serves the React build at `GET /` and `GET /react` via `_react_index_response()`,
  and assets via `GET /react/{asset_path:path}` in [storyboard_tool/api.py](storyboard_tool/api.py).
- **Reference windows:** workflows live in React (References drawer + assignment modal + 3D Scene panel).
  `/ref-segment`, `/ref-scene3d`, `/ref-video` redirect (302) to `/` for bookmark/bridge compatibility.
- **Shared runtime:** `static/runtime/scene3d_workspace.js` (compiled from `frontend/src/scene3d/workspace/`) and `static/runtime/reference_model_preview.js`;
  `static/vendor/three/*` unchanged.
- **Removed:** legacy HTML (`index.html`, `ref_segment.html`), `GET /legacy`, and all legacy static JS/CSS.

See [docs/react_migration_cleanup_plan.md](docs/react_migration_cleanup_plan.md) for the final file tree.

## How to run

```bash
cd frontend
npm install        # first time only
npm run build      # builds into ../storyboard_tool/web/dist with base /react/
cd ..
python main.py
# then open http://127.0.0.1:8000/
```

For React dev mode with hot reload (backend must be running on :8000 for the `/api` proxy):

```bash
cd frontend
npm run dev        # http://localhost:5173/react/
```

## Manual test checklist

Run after `npm run build` + `python main.py`.

### Serving
- [ ] `http://127.0.0.1:8000/` → React app loads.
- [ ] `http://127.0.0.1:8000/react` → React app loads; assets return 200 under `/react/assets/...`.
- [ ] `http://127.0.0.1:8000/legacy` → 404.
- [ ] `/ref-segment`, `/ref-scene3d`, `/ref-video` → 302 redirect to `/`.
- [ ] `/static/runtime/scene3d_workspace.js` and `/static/runtime/reference_model_preview.js` return 200.

### Reference segments (in React — no standalone windows)
- [ ] Import image, video, and GLB references; assign to board range; Apply / Reapply / Undo / Delete.
- [ ] GLB preview, video scrubber, applied/pending markers work.
- [ ] Delete segment clears generated board background/preview.
- [ ] Scene3D panel: import GLB, capture to board.

### Core workflow
- [ ] Create/open project; add/delete/reorder boards; edit and save shot metadata.
- [ ] Photoshop source / sync preview; image/PSD import; `flushDirtyShots()` before structural actions.
- [ ] No console errors; no missing static files in network tab.

## Validation commands

Run these before release or after backend/frontend changes:

```bash
python -m py_compile storyboard_tool/api.py storyboard_tool/backend_service.py storyboard_tool/project_manager.py storyboard_tool/reference_segments.py
cd frontend; npm run build
python scripts/validate_migration.py
$env:PYTHONPATH='d:\Storyboarder'; python tests/test_smoke.py
```

Automated checks cover route serving, runtime static files, API smoke paths, and reference-segment delete behavior. Manual checklist items above still require a running app (`python main.py`).
