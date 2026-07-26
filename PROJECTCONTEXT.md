# PROJECTCONTEXT.md — Storyboarder

> Persistent project memory for the AI Collaboration Protocol. Not authority
> above current Owner instructions, the active brief, repository code, or
> verified tests. Durable collaboration rules live in `AGENTS.md`, `CLAUDE.md`,
> and `docs/ai-workflow/`.

## Context metadata

```text
Last updated: 2026-07-26
Last verified branch: main (uncommitted working tree)
Last verified commit: efae970
Updated by: Claude
Context confidence: current

Git execution environments:
- Windows 11 / VSCode Claude Code extension | codex-user MCP | mode: unverified — verify before Git ops | Last verified: —
```

## 1. What this project is

Storyboarder is a **Windows desktop-only** storyboard planning app:

- **Shell**: pywebview (EdgeWebView2 window) launched by `python main.py`
- **Server**: FastAPI + uvicorn on `127.0.0.1:<port>` — internal implementation detail, loopback only, never browser-exposed
- **Frontend**: React 19 + TypeScript, built with Vite from `frontend/src/` into `storyboard_tool/web/dist/`. The prebuilt bundle is **committed** (required for Node-less `pip install` + `python main.py`). It had briefly been gitignored; re-tracked 2026-07-22 (commit f48c99c). Rebuild with `cd frontend && npm run build` after editing `frontend/src/**`.
- **3D**: Three.js (pinned vendor copy) + a separately compiled Scene3D workspace bundle
- **Photoshop integration**: a UXP plugin in `photoshop_uxp_plugin/` talks to `/api/plugin/*` and `/api/bridge/*`
- **Storage**: projects are folders on disk (`project.json`, `settings.json`, `shots.json`, per-shot PNG/PSD files). No database, no cloud, no network features.

Non-goals (do not add): browser mode, hosted server, cloud sync, audio, multi-window.

## 2. Current state

```text
Current working area (2026-07-26, owner-direct, UNCOMMITTED on main): three Owner-requested changes.
1. HOME SCREEN. Startup no longer reopens the last document — method_bootstrap returns {session, project, recents, opened_last_project:false, startup_timings} and never calls open_project. Measured on the Owner's real 46.9 MB document: bootstrap 15 ms (was a full .sbd extract). New domain module `recents.py` describes recent documents WITHOUT opening them (reads shots.json + one _thumb.png member straight out of the zip; 4 entries incl. 2 real documents = 7-15 ms, ~22 KB thumbs). New routes GET /api/app/recents, POST /api/app/recents/forget, POST /api/app/close-project. New `HomePage.tsx/.css` (Photoshop-welcome layout: New file/Open sidebar + Recent thumbnail grid) replaces the old WelcomePanel. Left rail gained a Home button; Home == close the document (flushes first), so `!project` is the only Home condition — no extra view state. `_persist_app_session` now MERGES session recents with the document's own list (previously the newest document's list overwrote the app-level one, so Home would have shown almost nothing).
2. EXPORT SCOPE. Every export accepts `shot_id`: empty = whole storyboard, set = that board only, output suffixed `_board-NNN` so a single-board export never overwrites the whole-storyboard file. `export_service.scope_to_shot()` returns a dataclasses.replace view (same paths/settings, one shot) so no exporter internals changed. ExportModal has a Whole storyboard / Current board only toggle that applies to all six export types; Open re-sends the scope the file was written with.
3. SHUTDOWN. Save-on-close moved OFF the post-window-close path onto pywebview's `window.events.closing` (verified present in pywebview 6.2.1), so the 46.9 MB re-zip finishes while the window is still up (titled "Saving..."), not after it disappears. `_finalize()` is idempotent; the old post-start() path remains only as a fallback.
Validation: pytest 738 passed / 1 skipped / 30 subtests; tsc+vite build passes; bundle rebuilt and committed-to-tree; eslint at the pre-existing baseline (9 errors, 2 warnings — proven identical with the changes stashed). Backend flows driven end-to-end against a real .sbd. Owner GUI click-test PENDING.

Previous working area: board UX on branch feat/generation-provider-mode (pushed). Branch carries: generation provider/mode (backend+UI), periodic-autosave save model, .sbd pack perf fixes, export feature (video+UI), and board Strip/Grid view + smooth wheel scroll.
Board view: BoardWorkspace now has a Strip/Grid toggle. Grid = BoardGrid.tsx (responsive tile grid of all boards, reuses ShotThumb; click selects -> same ShotInspector detail; trailing "Add board" tile). BoardStrip horizontal wheel scroll now eases toward an rAF target (was instant per-notch = stepped).
Last completed task: EXPORT feature. NEW video animatic (storyboard -> .mp4, H.264 via ffmpeg / mp4v fallback, duration-driven, optional captions) in video_export.py. Discovered the backend already had a full export suite (PDF one_per_page/two_per_page/thumbnails, contact sheet, shot-list CSV, timing JSON, image sequence) but NO frontend UI exposed any of it. Built ExportModal (video + PDF layout picker + images + data) reached from the RightRail "More > Export…" menu; new api/export.ts; new POST /api/export/open opens a generated file in the OS default app (os.startfile). PDF one_per_page already IS the "shot detail" export (big image + all metadata).
Current build/test status: full suite 726 passed, 1 skipped, 0 failed (the 2 previously-noted failures were fixed earlier this branch). Frontend tsc+vite build passes; lint at pre-existing baseline (8 errors, none new). GUI click-test by Owner pending.
```

## 3. Generation handoff decision / next fork

```text
Decision: "Send to Codex" remains the single handoff to the Codex agent. Stable Diffusion is not a separate receiver; it is a tool/workflow that Codex may operate after receiving the task.
Backend choices: explicit only - `codex` or `stable_diffusion`. Do not add `auto`.
Workflow meaning:
- `backend=codex`: Codex directly handles image generation.
- `backend=stable_diffusion`: Codex prepares prompt/reference/size/seed settings and operates SD to generate the image.
Status/detail strategy: generation precision should follow shot/status/mode. Draft should favor speed with proportional downscale, low resolution, possible upscale back to panel size, and rough/line-art storyboard output. Cleaner/final statuses can increase resolution, steps, refinement, and polish.
Next fork: implement provider/mode fields in the generation request payload and UI selector while preserving the user-facing "Send to Codex" handoff semantics.
Owner input needed: no for the above semantics; yes only for later SD-specific runtime/configuration choices.

Progress (2026-07-21):
- DONE: `provider` field on the request snapshot (generation_service PROVIDERS={codex,stable_diffusion}, default codex, validated before any FS write). Backend Spark-authored slice, kept.
- DONE: `provider` threaded end-to-end — GenerationRequestCreateRequest.provider, api create-generation-request route, method_create_generation_request(shot_id, destination, provider). Default codex, backward compatible.
- DONE: codex_handoff_prompt(request_id, *, provider="codex", mode="") is provider+mode-aware; stable_diffusion variant instructs Codex to OPERATE Stable Diffusion per the request's generation_plan (build prompt from compiled_prompt, apply negative_prompt+references, preserve aspect, upscale back to panel) instead of generating directly.
- DONE: `mode` field (draft/clean/final) + per-mode `generation_plan` block. Owner spec 2026-07-21. Default mode derives from shot.status (Draft->draft, In Progress/Review->clean, Approved/Final->final); explicit `mode` overrides. Chosen default profile numbers (tunable, in generation_service._MODE_PROFILES): draft = longest-edge 768, steps 12, cfg 5.0, upscale_to_panel, overwrite_final False; clean = longest-edge 1024, steps 22, cfg 6.5, use_prior_frame_as_reference; final = full panel size, steps 32, cfg 7.0, overwrite_final True. generation_plan carries target_width/height, panel_width/height, steps, cfg_scale, style_hint, use_prior_frame_as_reference, output_policy{preserve_aspect_ratio, upscale_to_panel, overwrite_final}. These are ADVISORY payload guidance — no engine executes them yet.
- Field mapping (Owner payload -> existing snapshot): target->destination, backend->provider; new: mode, generation_plan, generation_plan.output_policy. Existing snake_case field names NOT renamed.
- DONE: generation_plan.prior_frame — for clean/final (use_prior_frame_as_reference), the request now carries the shot's accepted Codex layer (_codex.png) as {source, project_relative_path, absolute_path, exists}; null in draft or when no layer exists. SD handoff prompt says to use prior_frame as the img2img base. Advisory: the actual img2img/upscale/overwrite-final execution is still Codex/SD-operator side, not built here.
- PERF: `.sbd` save = full re-zip of the whole working root on EVERY autosave (add-board etc.) via project_document.pack_document → cost scales with project size ("long wait"). Measured: 48 MB incompressible artwork = 1244 ms at DEFLATE-6. Fix shipped: STORE already-compressed imports (png/jpg/mp4…) + DEFLATE level 1 for the rest (PSD canvases stay compressible → ~1 MB not 91 MB). ~2x faster, negligible size change, backward compatible. STRUCTURAL FIX SHIPPED (Owner-approved 2026-07-23): interactive `_autosave` now writes metadata to the working tree but DEFERS the .sbd pack (`save_project(flush_document=False)`); Add board dropped 200-1200 ms → ~8 ms. The pack now runs on periodic autosave (frontend useAutosave hook, interval `autosave_interval_minutes` setting = 3/5/10, default 5), manual save (Ctrl+S / menu, already existed), and save-on-close (shutdown_reference_cleanup save_if_dirty). Folder projects unchanged (metadata write is already durable; not left dirty). .sbd projects are left dirty after edits until a flush. `backups/` is now EXCLUDED from the .sbd pack (project_document._UNPACKED_DIRS) — it is a local, write-only recovery snapshot set the app never reads back, so embedding it only bloated the document and slowed saves; for .sbd it now lives only in the temp working tree (session-local).
- DONE: dispatching a shot to Codex clears its pending queue (staging) entry — generation_service.clear_pending_queue_requests, called by single Send to Codex and Send All to Codex (batch). Codex-destination requests stay (they track handoff + results). Fixes the duplicate Queue+Codex rows. Backend-only; the panel reloads after dispatch.
- DONE (UI, revised per Owner): standalone Mode selector REMOVED — precision follows shot Status (backend derives; frontend `generationModeForStatus` mirrors it for display), no 'auto'. "Send to Codex" opens a confirmation popup with the Backend (Codex/Stable Diffusion) choice + shows Status→mode. Send to Queue sends provider=codex; Send All to Codex unchanged. Frontend sends no explicit mode (backend derives from status). tsc+vite build pass. PENDING: Owner GUI click-test.
- Two pre-existing UNRELATED test failures on this branch (not from this work; proven via stash baseline): blender smoke mock arity; project_document .sbd missing shot .psd. Fix separately if desired.
```

## 4. What's built — module map

| Path | Role |
|---|---|
| `main.py` → `storyboard_tool/main.py` | Entry point: `create_app()` + `open_desktop_window()` |
| `storyboard_tool/api.py` | All FastAPI routes (~90). Parses requests, delegates to service. **No business logic here.** |
| `storyboard_tool/backend_service.py` | `StoryboardBackendService` — single business-logic entry point (`method_*` handlers) |
| `storyboard_tool/shot_service.py` | Shot domain logic. No FastAPI/HTTP imports; raises `ValueError` |
| `storyboard_tool/project_manager.py` | Project lifecycle, canonical file paths, atomic JSON writes |
| `storyboard_tool/reference_segments.py` | Reference library + segment apply/undo/delete flows |
| `storyboard_tool/scene2d.py` | Scene 2D library plus Scene Bible environment prompts, locked anchors, and primary visual references |
| `storyboard_tool/generation_service.py` | Immutable generation requests, queue status, Codex result deposits/reconciliation |
| `storyboard_tool/mcp_server.py` | Local STDIO MCP tools for Codex generation handoffs |
| `storyboard_tool/project_transaction.py` | `mutate_project()` — in-memory snapshot/rollback for mutating operations |
| `storyboard_tool/app_state.py` | Transport-agnostic project/app-state helpers (`_require_project`, `_autosave`, bridge payloads) |
| `storyboard_tool/recents.py` | Home-screen recent documents: describes a `.sbd` (name, boards, first-board thumbnail) without extracting it |
| `storyboard_tool/live_bridge.py`, `psd_recovery.py`, `image_utils.py`, `export_service.py` | Photoshop bridge, PSD rebuild, media, exports |
| `frontend/src/` | React/TS source. State: `state/ProjectContext.tsx` (project payload) + `state/LiveBridgeContext.tsx` (bridge polling) |
| `frontend/src/scene3d/` | 3D workspace TS source; `workspace/` compiles to a separate runtime bundle |
| `photoshop_uxp_plugin/` | UXP plugin (vanilla JS): `panel.js`, `backend_client.js` |
| `tests/` | pytest suite (backend); `test_smoke.py` is the fast subset |
| `scripts/verify_dev.py` | The validation gate (see §6 commands) |
| `docs/` | Architecture and policy docs — read before structural changes |
| `agent-workflows/` | Reusable agent workflow prompts (code review). **Not application code — never audit or refactor it.** |

### Commands

```bash
# Run the app (desktop window; do NOT open the URL in a browser)
python main.py

# Full validation gate — required before merging
python scripts/verify_dev.py

# Scoped: --backend (py_compile + validate_migration + pytest)
#         --frontend (eslint + vite build)
#         --fast (smoke tests, skips frontend build)

# Individual checks
python -m pytest tests/            # full suite
python -m pytest tests/test_smoke.py
cd frontend && npm.cmd run lint    # Windows: npm.cmd
cd frontend && npm.cmd run build   # tsc -b && vite build && build:workspace
```

There is no CI; all validation is local. Python 3.11+, deps in `requirements.txt` (`.venv/` exists in-repo).

## 5. Hard-won active gotchas

1. **Generated bundles are never hand-edited; rebuild after editing `frontend/src/**`.**
   - `storyboard_tool/web/dist/**` — regenerate with `cd frontend && npm run build`. **Committed** (re-tracked 2026-07-22; needed for Node-less deploy). Rebuild and commit the bundle whenever `frontend/src/**` changes.
   - `storyboard_tool/web/static/runtime/scene3d_workspace.js` — regenerate with `npm run build:workspace`.
   - `storyboard_tool/web/static/vendor/three/**` — pinned vendor, never modify.
   After editing `frontend/src/**`, rebuild the bundle or the running app won't reflect the change.
   Also note: `npm run lint` is currently RED on `main` (8 pre-existing `react-hooks/set-state-in-effect` errors in App/Scene2DPanel/ReferenceAssignmentPopover3dApply/FloatingLayersPanel) — not from recent work.

2. **Layering**: routes (`api.py`) → service (`backend_service.py`) → domain (`shot_service.py`, `reference_segments.py`, `project_manager.py`). Domain modules must not import FastAPI. New business logic goes in the service/domain layer, never in routes.

3. **Board asset ownership** (details: `docs/stability_contract.md`): per shot, `_preview.png` is artist artwork, `_background.png` is the reference plate, `_codex.png` is the accepted generated layer, and `_thumb.png` is display cache. Reference/Codex flows must never write `_preview.png`; Photoshop sync must never write `_background.png` or `_codex.png`; `image_path`/`preview_image_path` must never point at background/Codex assets.

4. **Atomic writes**: all critical JSON/PNG/PSD writes use temp file + `os.replace()`. Keep this pattern for any new persistence code. Wrap new mutating service methods in `project_transaction.mutate_project()`.

5. **Photoshop plugin contract is frozen-ish**: do not casually rename `/api/plugin/*` endpoints, heartbeat fields, bridge file names (`storyboard_live_bridge.json`), or the plugin's local-fallback file formats — older plugin sessions and saved projects depend on them. The `SB bg` layer in PSDs is plugin-owned (linked smart object); the backend must not round-trip it through psd_tools.

6. **TypeScript policy** (`docs/typescript_policy.md`): new UI code is TS/TSX in `frontend/src/**`. Do not convert `static/runtime/*.js` or vendor JS to TS. All 3D rendering is TypeScript-only — Python never drives Three.js.

7. **Deletion semantics**: `delete_shot` removes only the metadata record; shot files stay on disk (undo depends on this). Do not "clean up" shot folders.

8. **A `.sbd` save is a full re-zip, and there is no incremental path.** The Owner's real document is 46.9 MB packed (139.6 MB expanded: 93.3 MB PSD + 45.6 MB PNG), so every flush rewrites the whole file. Two consequences: (a) never move a flush somewhere the user cannot see it finish; (b) their documents live in `C:\Users\JieYin\OneDrive\...`, so each flush also makes OneDrive re-upload the entire file and `pack_document`'s staging `.tmp` (written in the document's own folder) gets synced too. Not fixed — Owner said OneDrive is not the concern; revisit only if asked.

9. **Adding an export type or option means touching four layers**: `api.py` route → `service_exports.py` `method_export_*` → `export_service.py` → the exporter. A method missed in the middle layer only fails when the route is called; `tests/test_export_service.py::TestExportScopeIsWiredEverywhere` pins the whole set (added after `method_export_image_sequence` was in fact missed).

10. **Anything that deletes a work tree must stop the background loops first.** Every open `.sbd` expands into `%TEMP%/storyboarder-*`, and `bridge_refresh_loop` writes `storyboard_live_bridge.json` into the project root every 1.5 s. Deleting the tree while that loop runs makes Windows leave a delete-pending ghost directory that nothing — not `rmtree`, not `icacls`, not Explorer — can reopen or remove; only a reboot clears it. That is where the ~35 empty `storyboarder-*` husks on the Owner's machine came from. `app_state.stop_background_loops(app)` now runs before every cleanup path (desktop `_finalize`, api lifespan). Work trees carry a `.storyboarder-session.json` marker (pid + document path, excluded from the pack) so `project_document.sweep_orphaned_working_roots()` can reclaim crashed sessions' trees at startup — conservatively: never a live owner's tree, and never one holding writes newer than its document, since that is a crashed session's only copy of unsaved work. `tests/conftest.py` reclaims what the suite creates (session-scoped on purpose: scanning TEMP per test cost the suite ~40 s).

## 6. Workflow notes

```text
Claude role: default task router / architect / engineering decision maker
Current execution target: Codex (codex-user MCP) available; integration into product flows deferred by Owner
Codex MCP status: codex-user MCP tools present in session; see docs/codex-debug-solution.md for this env's verified quirks
Current Codex thread ID: —
Current configured effort: unknown — verify per docs/ai-workflow/codex-mcp-effort.md before relying on it
Current task coordination mode: claude-routed
Current capability policy:
- Sub-agents: allowed
- Delegation autonomy: bounded
Active host/environment: Windows 11 / VSCode Claude Code extension
Active MCP client: codex-user
Active Git execution mode: unverified — verify before any Git operation
Git mode last verified: —
Review mode: report-only
```

## 7. Where durable rules live

```text
AI collaboration rules:
- AGENTS.md
- CLAUDE.md
- docs/ai-workflow/
- docs/codex-debug-solution.md (environment-specific Codex MCP debug record)

Architecture/build/test docs:
- docs/current_architecture.md — authoritative module/endpoint map
- docs/stability_contract.md — per-shot files, saves, recovery
- docs/development_workflow.md — branching, validation modes, manual GUI smoke checklist
- docs/typescript_policy.md — frontend language boundaries
- docs/desktop_migration_and_3d_streaming_plan.md — ongoing desktop/Tauri + 3D streaming work

Code-review workflow:
- agent-workflows/ (reports go to docs/review/reports/)
```

## 8. Working conventions

- Branch names: `feat/`, `fix/`, `refactor/`, `chore/`. Full `verify_dev.py` before merge; manual GUI smoke when touching UI, bridge, Scene3D, exports, or PSD flows (checklist in `docs/development_workflow.md`).
- Changes touching the UXP plugin usually need matching changes in `storyboard_tool/backend_service.py` + `app_state.py` and a look at `tests/test_photoshop_bridge.py` / `test_plugin_backend_regression.py`.
- The user runs Windows; prefer `npm.cmd` in shells, and remember paths are case-insensitive.
