# React Migration Cleanup Plan

**Migration complete.** React is the only UI. Shared runtime JS is under `web/static/runtime/` and `web/static/vendor/`.

## Phase status

1. ✅ **Phase 3** — Reference segment workflows moved into React (`ReferenceSidebar`, `ReferenceAssignmentPopover`, `Scene3DPanel`).
2. ✅ **Phase 4** — Scene3D runtime relocated to `web/static/runtime/`.
3. ✅ **Phase 5** — Legacy HTML and ~48 legacy static files deleted; `GET /legacy` removed; `/ref-*` standalone routes removed.
4. ✅ **Phase 6** — TypeScript policy documented in [typescript_policy.md](typescript_policy.md). Runtime JS stays JS; React stays TS/TSX.
5. ✅ **Phase 7** — `scene3d_preview_style.js` replaced by `frontend/src/scene3d/previewStyle.ts`; `scene3d.js` shim deleted; `previewStyleBridge.ts` deleted.
6. ✅ **Phase 8** — Desktop-only: `--browser`/`--host`/`--port` CLI removed; internal server starts automatically.
7. ✅ **Phase 9** — Dead code removed: back-compat alias `start_server`, dead routes `/ref-segment`/`/ref-scene3d`, dead static files `runtime/favicon.svg`/`icons.svg`.

## Remaining static file tree

```text
storyboard_tool/web/
├── dist/                          # React build output (gitignored except for committed snapshot)
│   ├── index.html
│   ├── favicon.svg
│   ├── icons.svg
│   └── assets/
└── static/
    ├── favicon.svg
    ├── favicon.ico
    ├── favicon.png
    ├── runtime/
    │   └── scene3d_workspace.js   # Scene3DEditor — compiled from frontend/src/scene3d/workspace/
    └── vendor/
        ├── three/
        │   ├── three.module.js
        │   ├── GLTFLoader.js
        │   ├── OrbitControls.js
        │   ├── TransformControls.js
        │   └── RoomEnvironment.js
        └── utils/
            └── BufferGeometryUtils.js
```

## Removed in Phase 5–9

- `storyboard_tool/web/index.html`
- `storyboard_tool/web/ref_segment.html`
- All legacy CSS (`styles.css`, `themes.css`, `reference_media.css`, `ref_segment_window.css`)
- All legacy `static/app/*`, `static/core/*`, and top-level legacy JS (see git history)
- Phase 4 re-export shims (`static/scene3d.js`, `static/reference_model_preview.js`)
- `static/runtime/scene3d.js` — 1-line re-export shim
- `static/runtime/scene3d_preview_style.js` — logic moved to `frontend/src/scene3d/previewStyle.ts`
- `static/runtime/favicon.svg`, `static/runtime/icons.svg` — misplaced, unreferenced
- Back-compat alias `desktop.start_server` (use `start_internal_server`)
- Routes `/ref-segment`, `/ref-scene3d` — standalone window artifacts, not used by desktop app

## TypeScript policy

See [typescript_policy.md](typescript_policy.md) for the full policy. Summary:

| Layer | Policy |
| --- | --- |
| React UI / state / API | TypeScript / TSX |
| Legacy UI JS | Deleted |
| Shared runtime JS | Generated via `npm run build:workspace` |
| Vendor JS (`vendor/three/*`) | Never modify |

## Remaining architecture debt

- `docs/code-review-and-refactor.md` describes the old legacy module graph and old test names (historical reference).
- The `/react` route is kept because Vite's `base: '/react/'` generates asset paths starting with `/react/`.
- The `/ref-video` route is kept because `bridge.py` opens a second pywebview window via that URL.
