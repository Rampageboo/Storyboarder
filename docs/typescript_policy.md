# TypeScript Policy (Phase 6)

React migration is complete. This document defines where TypeScript is required and where JavaScript remains intentional.

## Rules

| Layer | Language | Location | Notes |
| --- | --- | --- | --- |
| React UI, hooks, state | **TypeScript / TSX** | `frontend/src/**` | All new UI code must be `.ts` / `.tsx` |
| React API client | **TypeScript** | `frontend/src/api/**` | Typed request/response wrappers |
| Python backend | **Python** | `storyboard_tool/**` | Unchanged |
| Shared 3D / GLB runtime | **JavaScript (ES modules)** | `storyboard_tool/web/static/runtime/**` | Loaded dynamically by React; keep JS until boundaries stabilize |
| Three.js vendor | **JavaScript (vendor)** | `storyboard_tool/web/static/vendor/**` | Never modify |
| Legacy UI JS | **Deleted** | — | Removed in Phase 5 |

## Do

- Write new features in `frontend/src` as TypeScript.
- Add types for API payloads in `frontend/src/api` and shared `frontend/src/types` as needed.
- Import shared runtime from `/static/runtime/...` paths (not legacy shim paths).
- Call `flushDirtyShots()` before state-changing structural actions in React.

## Do not

- Mass-convert `static/runtime/*.js` or vendor files to TypeScript in routine tasks.
- Add new vanilla JS UI under `storyboard_tool/web/static/` (except shared runtime modules with a documented React bridge).
- Modify `static/vendor/three/*`.

## When to convert runtime JS to TypeScript

Only after all of the following:

1. Legacy HTML is fully removed (done).
2. React is the only UI (done).
3. The runtime module's public API (`Scene3DEditor`, `hydrateReferenceModelPreviews`, etc.) is stable and documented.

Until then, treat `static/runtime/*.js` as a versioned bridge contract between React and Three.js.

## Related docs

- [react_migration_cleanup_plan.md](react_migration_cleanup_plan.md) — file inventory and phase history
- [../REACT_MIGRATION_CHECKLIST.md](../REACT_MIGRATION_CHECKLIST.md) — manual validation checklist
