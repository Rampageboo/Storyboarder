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
| `Scene3DPanel.tsx` | `/static/runtime/scene3d.js` + `/static/runtime/scene3d_workspace.js` |
| `ReferenceModelPreview.tsx` | `frontend/src/scene3d/` + `/static/runtime/scene3d_preview_style.js` |
| `index.html` import map | `/static/vendor/three/three.module.js` |
