# Storyboarder React Frontend

React + TypeScript + Vite UI for Storyboarder. Production build output goes to `../storyboard_tool/web/dist/` and is served at `/` and `/react`.

## Commands

```bash
npm install
npm run dev      # http://localhost:5173/react/  (proxies /api and /static to :8000)
npm run build    # writes dist + rebuilds scene3d_workspace.js
npm run build:workspace  # only rebuild /static/runtime/scene3d_workspace.js
```

## TypeScript policy

All new UI code in `frontend/src` must be TypeScript (`.ts` / `.tsx`).

Shared 3D/GLB runtime modules remain JavaScript under `storyboard_tool/web/static/runtime/` and are loaded dynamically — do not mass-convert them. See [../docs/typescript_policy.md](../docs/typescript_policy.md).

## Shared static runtime

| React component | Runtime module |
| --- | --- |
| `Scene3DPanel.tsx` | `/static/runtime/scene3d_workspace.js` (generated bundle) |
| `ReferenceModelPreview.tsx` | `frontend/src/scene3d/` (React-bundled TypeScript) |
| `index.html` import map | `/static/vendor/three/three.module.js` |

## Architecture: Scene3D source of truth

```
Source of truth (TypeScript):
  frontend/src/scene3d/**/*.ts

  Key modules:
    previewStyle.ts           — preview colour / wireframe logic (canonical)
    workspace/workspaceEditor.ts — Scene3DEditor class
    workspace/staticEntry.ts  — workspace bundle entry

Generated runtime:
  storyboard_tool/web/static/runtime/scene3d_workspace.js
    Built by: npm run build:workspace
    Contains: Scene3DEditor + all workspace helpers + preview style logic
    Loaded by: Scene3DPanel.tsx via dynamic import

Vendor runtime (do not edit):
  storyboard_tool/web/static/vendor/three/*
```

## Generated files policy

`storyboard_tool/web/static/runtime/scene3d_workspace.js` is **generated output** — do not hand-edit it.

- **Source of truth:** `frontend/src/scene3d/workspace/*.ts` + `frontend/src/scene3d/previewStyle.ts`
- **Regenerate:** `npm run build:workspace` (or `npm run build` which includes it)
- The file is committed so the Python desktop app can serve it without a separate build step.

## Deleted legacy files

The following files were removed during the TS migration and must not be recreated:

- `storyboard_tool/web/static/runtime/scene3d.js` — was a 1-line re-export shim, now unused
- `storyboard_tool/web/static/runtime/scene3d_preview_style.js` — was hand-written runtime JS, logic now lives in `frontend/src/scene3d/previewStyle.ts`
