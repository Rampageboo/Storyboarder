# Architecture Decisions

Normative boundaries that reading the code will not tell you. Module topology,
call graphs, and the endpoint map belong to the codebase map and
`docs/current_architecture.md`, not here.

## Layering

Routes (`api.py`) → service (`backend_service.py`) → domain (`shot_service.py`,
`reference_segments.py`, `project_manager.py`). Domain modules must not import
FastAPI. New business logic goes in the service or domain layer; routes parse
and delegate only.

## Board asset ownership

Per shot, `_preview.png` is artist artwork, `_background.png` is the reference
plate, `_codex.png` is the accepted generated layer, and `_thumb.png` is display
cache. Reference and generation flows never write `_preview.png`; Photoshop sync
never writes `_background.png` or `_codex.png`; `image_path` and
`preview_image_path` never point at background or generated assets. Details in
`docs/stability_contract.md`.

## Persistence

All critical JSON, PNG, and PSD writes go through a temp file plus
`os.replace()`. Mutating service methods wrap in
`project_transaction.mutate_project()` so a failure rolls back rather than
leaving a half-written project.

`delete_shot` removes the metadata record and leaves shot files on disk. Undo
depends on that. Do not "clean up" orphaned shot folders.

## Storage layouts

Layout 1 is a `.sbd` archive that expands to a temporary working tree and is
packed back into one file. Layout 2 is a portable project folder with a
metadata-only `.sbd` alongside external `Images/`, `PSD/`, `Blender/`,
`Exports/`, and `.storyboarder/`, avoiding one directory per shot.

Both exist in the code: `app_state.save_active_project_as_layout2`,
`convert_active_project_to_layout2`, and a `_LAYOUT2_TRANSACTIONAL_METHODS` set
in `backend_service.py`. Treat Layout 2 as implemented and verify current
behaviour in source before assuming either layout is the only path.

## Frozen external contracts

The Photoshop plugin contract is effectively frozen: do not casually rename
`/api/plugin/*` endpoints, heartbeat fields, the `storyboard_live_bridge.json`
bridge file, or the plugin's local-fallback formats. Older plugin sessions and
saved projects depend on them. The `SB bg` layer inside PSDs is plugin-owned as
a linked smart object; the backend must not round-trip it through psd_tools.

## Generation backends

A generation request names its backend explicitly: `codex` or
`stable_diffusion`. Do not add an `auto` option. The selected backend is an
execution constraint rather than a preference, and alternative image generators
are forbidden for a request that names one.

## Frontend language boundary

New UI code is TypeScript in `frontend/src/**`. Do not convert
`static/runtime/*.js` or vendored JavaScript to TypeScript. All 3D rendering is
TypeScript; Python never drives Three.js. See `docs/typescript_policy.md`.
