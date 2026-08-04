# Risks and Gotchas

Active, expensive to rediscover, and not visible from reading one file.

## Deleting a work tree while background loops run bricks the directory

Every open `.sbd` expands into `%TEMP%/storyboarder-*`, and
`bridge_refresh_loop` writes `storyboard_live_bridge.json` into the project root
every 1.5 s. Deleting that tree while the loop runs leaves a Windows
delete-pending ghost directory that nothing can reopen or remove — not
`rmtree`, not `icacls`, not Explorer. Only a reboot clears it. That is where the
roughly 35 empty `storyboarder-*` husks on the Owner's machine came from.

`app_state.stop_background_loops(app)` now runs before every cleanup path.
Work trees carry a `.storyboarder-session.json` marker so
`project_document.sweep_orphaned_working_roots()` can reclaim a crashed
session's tree at startup — never a live owner's tree, and never one holding
writes newer than its document, since that is the only copy of unsaved work.

## Generated bundles are never hand-edited

`storyboard_tool/web/dist/**` regenerates with `npm run build`;
`static/runtime/scene3d_workspace.js` with `npm run build:workspace`;
`static/vendor/three/**` is pinned and never modified. Editing
`frontend/src/**` without rebuilding means the running app does not reflect the
change, which reads as a code bug rather than a stale artifact.

## Adding an export type touches four layers

`api.py` route → `service_exports.py` `method_export_*` → `export_service.py` →
the exporter. A method missed in the middle layer only fails when the route is
called. `tests/test_export_service.py::TestExportScopeIsWiredEverywhere` pins
the whole set; it exists because `method_export_image_sequence` was in fact
missed.

## A `.sbd` save rewrites the entire document

There is no incremental path. The reference document is 46.9 MB packed. Never
move a flush somewhere the user cannot watch it finish — that was the reason
save-on-close moved onto pywebview's `closing` event rather than running after
the window disappears.

## Plugin changes ripple

A change touching the UXP plugin usually needs matching changes in
`backend_service.py` and `app_state.py`, plus a look at
`tests/test_photoshop_bridge.py` and `test_plugin_backend_regression.py`.

## The map has known edge damage

The 2026-08-04 build reported 1085 dangling-endpoint edges, 24 self-loops, and
548 collapsed edges. Map answers about call paths and impact may be incomplete.
