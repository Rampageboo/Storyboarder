# React Migration Cleanup Plan

**Migration complete (Phase 5).** React is the only UI. Shared runtime JS remains under `web/static/runtime/` and `web/static/vendor/`.

## Phase status

1. ✅ **Phase 3** — Reference segment workflows moved into React (`ReferenceSidebar`, `ReferenceAssignmentPopover`, `Scene3DPanel`).
2. ✅ **Phase 4** — `scene3d.js` and `reference_model_preview.js` relocated to `web/static/runtime/`.
3. ✅ **Phase 5** — Legacy HTML and ~48 legacy static files deleted; `GET /legacy` removed; `/ref-*` redirect to `/`.
4. ✅ **Phase 6** — TypeScript policy documented in [typescript_policy.md](typescript_policy.md). Runtime JS stays JS; React stays TS/TSX.

## Remaining static file tree

```text
storyboard_tool/web/
├── dist/                          # React build output (gitignored)
└── static/
    ├── favicon.svg
    ├── favicon.ico
    ├── favicon.png
    ├── runtime/
    │   ├── scene3d_workspace.js        # Scene3DEditor — compiled from frontend/src/scene3d/workspace/
    │   └── reference_model_preview.js  # GLB preview — React ReferenceModelPreview
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

## Removed in Phase 5

- `storyboard_tool/web/index.html`
- `storyboard_tool/web/ref_segment.html`
- All legacy CSS (`styles.css`, `themes.css`, `reference_media.css`, `ref_segment_window.css`)
- All legacy `static/app/*`, `static/core/*`, and top-level legacy JS (see git history)
- Phase 4 re-export shims (`static/scene3d.js`, `static/reference_model_preview.js`)

## TypeScript policy (Phase 6)

See [typescript_policy.md](typescript_policy.md) for the full policy. Summary:

| Layer | Policy |
| --- | --- |
| React UI / state / API | TypeScript / TSX |
| Legacy UI JS | Deleted |
| Shared runtime JS | Keep as JS for now |
| Vendor JS (`vendor/three/*`) | Never modify |

## Remaining migration debt

- Optional: canonicalize `/react` → `/` redirect (both currently serve the same build).
- Optional: convert `static/runtime/*.js` to TypeScript after runtime API boundaries stabilize.
- `docs/code-review-and-refactor.md` still describes the old legacy module graph (historical reference only).
