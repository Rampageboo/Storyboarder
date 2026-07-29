# PROJECTCONTEXT.md — Storyboarder

> Persistent project memory for the AI Collaboration Protocol. Not authority
> above current Owner instructions, the active brief, repository code, or
> verified tests. Durable collaboration rules live in `AGENTS.md`, `CLAUDE.md`,
> and `docs/ai-workflow/`.

## Context metadata

```text
Last updated: 2026-07-30
Last verified branch: codex/local-updates-20260730
Last verified commit: 29a07ac (implementation baseline; this context update is the next commit)
Updated by: Codex (Owner-delegated; reconciled Codex Ultra + ChatGPT Pro architecture reviews)
Context confidence: current for the Layout 2 decision and execution plan; historical working-state snapshots below remain reference-only

Git execution environments:
- Windows 11 / Codex desktop | local shell | mode: codex-git | Last verified: 2026-07-30
```

## 1. What this project is

Storyboarder is a **Windows desktop-only** storyboard planning app:

- **Shell**: pywebview (EdgeWebView2 window) launched by `python main.py`
- **Server**: FastAPI + uvicorn on `127.0.0.1:<port>` — internal implementation detail, loopback only, never browser-exposed
- **Frontend**: React 19 + TypeScript, built with Vite from `frontend/src/` into `storyboard_tool/web/dist/`. The prebuilt bundle is **committed** (required for Node-less `pip install` + `python main.py`). It had briefly been gitignored; re-tracked 2026-07-22 (commit f48c99c). Rebuild with `cd frontend && npm run build` after editing `frontend/src/**`.
- **3D**: Three.js (pinned vendor copy) + a separately compiled Scene3D workspace bundle
- **Photoshop integration**: a UXP plugin in `photoshop_uxp_plugin/` talks to `/api/plugin/*` and `/api/bridge/*`
- **Storage (current implementation)**: `.sbd` documents expand to a temporary working tree and are packed back into one archive. No database, no cloud, no network features.
- **Storage (decided target, implementation pending)**: Layout 2 is a portable project folder containing a metadata-only `MyProject.sbd` plus external `Images/`, `PSD/`, `Blender/`, `Exports/`, and `.storyboarder/`. It avoids one directory per shot. The complete gated execution plan is in §2.

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

### Layout 2 storage migration — final execution decision (2026-07-30)

```text
STATUS: DECIDED, NOT IMPLEMENTED, FEATURE-GATED.

Implementation baseline:
- Branch: codex/local-updates-20260730
- Commit: 29a07ac
- Full baseline validation: 812 passed, 1 skipped, 2 warnings.
- Frontend TypeScript/Vite build: passed.

Independent review records:
- Codex Ultra task: "裁决 Storyboarder 存储迁移"
  Thread ID: 019fae64-6075-76a1-9dcc-223b75a7e25c
  Result: Amend; reproduced a P0 dirty-project transition data-loss path.
- ChatGPT Pro conversation: "Storyboarder Layout 2 审核"
  https://chatgpt.com/c/6a6a1ce1-a2fc-83ec-95e1-b54caba30e79
  Result: Amend with conditions; independently inspected the pushed GitHub branch.

Final reconciliation:
- Accept Ultra's transition gate, strict resolver, metadata-only .sbd, plugin
  protocol v2, and transactional Save As/Convert design.
- Accept Pro's requirement that Save As/Convert snapshot a frozen consistent
  view and use one monotonic revision model for work-state recovery.
- Do not require a project-wide filesystem watcher in the first implementation.
  Images, PSDs, and Blender files are intentionally user-editable. The backend
  must never trust a client-supplied path or ingest an unknown write as metadata;
  a later integrity scanner may report forbidden legacy/plugin writes without
  invalidating legitimate external asset edits.
- Do not add Assets/External, generation-mode subfolders, or Blender/Cache in
  Layout 2 v1. They weaken the simple stable layout. Generation mode belongs in
  metadata; derived Blender previews remain under .storyboarder/cache/scene3d.
```

#### Gate 0 — mandatory transition-safety fix

This is P0 and must land before any Layout 2 write path is enabled. Current code
can lose dirty `.sbd` work when New/Open changes the active project before the
old document is durably saved.

```text
ACTIVE PROJECT
→ acquire one backend project-transition lock
→ flush frontend drafts
→ serialize complete backend state
→ drain or freeze the transaction log
→ apply plugin inbox writes, or mark them explicitly excluded/uncommitted
→ quiesce background/plugin writers
→ ask external Blender to save/release; abort on failure
→ save/release built-in Blender writer; abort on failure
→ durable-save source, or ABORT
→ open and validate the candidate project separately
→ atomically swap active app state
→ rotate session/bridge identifiers
→ clean the old runtime root last
```

Failure invariant: the old project stays active, its work root and dirty state
remain intact, and its session ID is not changed. No cleanup may precede the
successful app-state swap.

Save As and Convert are deliberately different: they do not save back into the
source. They freeze the current consistent in-memory/work-tree state, materialize
that snapshot into the target, and leave the source document byte-for-byte
unchanged.

#### D1 — schema, path protocol, and compatibility

- Advance `PROJECT_JSON_VERSION` from 3 to 4 when Layout 2 is introduced and
  update all mirrored constants in the same slice.
- A missing `layout` means Layout 1. Layout 2 requires `layout: 2`, stable
  `project_id`, and `storage_revision`. Unknown layout/version values fail
  closed; never guess.
- Add `storyboard_tool/project_layout.py` as the only path authority. It must
  distinguish `project_root` (portable folder) from `metadata_root` (expanded
  metadata/work state).
- Persist only project-root-relative POSIX paths. Reject absolute paths, drive
  paths, UNC paths, leading slashes, backslashes, `..`, reparse-point escape,
  and case-fold collisions.
- A valid persisted path is data and wins. Layout defaults choose a path only
  when its field is empty. A missing stored target is an integrity error; never
  silently rebind it to a guessed canonical path.
- Layout 1 must remain behaviorally identical while consumers are moved behind
  the resolver. Layout 2 stays disabled until all consumers pass the gate.

Layout 2 disk contract:

```text
MyProject/
├─ MyProject.sbd
├─ Images/
│  ├─ Shots/
│  │  ├─ <shot-id>_preview.png
│  │  ├─ <shot-id>_background.png
│  │  └─ <shot-id>_codex.png
│  ├─ Scene2D/
│  │  ├─ <perspective-uuid>.<image-ext>
│  │  └─ <perspective-uuid>_preview.png
│  ├─ References/<asset-uuid>.<image-ext>
│  └─ Generated/<request-id>_<output-id>.<image-ext>
├─ PSD/
│  ├─ Shots/<shot-id>.psd
│  └─ Scene2D/<perspective-uuid>.psd
├─ Blender/
│  ├─ <scene3d-id>.<blend|glb|gltf>
│  └─ References/<asset-uuid>.<blend|glb|gltf>
├─ Exports/
└─ .storyboarder/
   ├─ state.json
   ├─ work/                         # JSON only
   ├─ cache/
   │  ├─ thumbnails/<shot-id>.png
   │  └─ scene3d/<scene3d-id>/storyboarder_preview.glb
   ├─ media/references/
   ├─ backups/
   ├─ recovery/
   └─ transactions/
```

Layout 2 forbids `shots/<id>/`, root-level `project.json`,
`storyboard_bridge.json`, and `canvas_color.txt`. Default `.blend` creation is
lazy. Blender-owned external references use portable `//` relative paths.

#### D2 — metadata-only `.sbd` and recovery revision

The `.sbd` uses an explicit allowlist:

- `project.json`, `settings.json`, `shots.json`
- `annotations/**/*.json`, `notes/**/*.json`
- `scenes2d/**/*.json`, `scenes3d/**/*.json`
- `generation/requests/**/*.json`, `generation/state/**/*.json`,
  `generation/results/**/*.json`
- `cover.png`, stored uncompressed and no larger than 65,536 bytes

It must contain no other PNG, PSD, BLEND, GLB/GLTF, video, export, thumbnail
cache, backup, bridge, runtime, IPC, or transaction file.

Use one authoritative monotonic revision:

- `global_revision`: signed 64-bit monotonic integer.
- `commit_id`: UUID for the committed snapshot.
- Every accepted state mutation writes work state at revision N+1.
- Committing `.sbd` writes that same revision, then records
  `committed_revision`.
- Startup recovers work state only when `work_revision > committed_revision`;
  otherwise the `.sbd` is authoritative.
- Invariant: `sbd_revision <= work_revision`; no competing revision counters.

Because Layout 2 autosaves only JSON, each accepted mutation may durably flush
work metadata. Binary assets are never repacked into `.sbd`.

#### D3/D5 — Save As and Convert

- Save As supports 1→1 and 2→2 only. It never changes layout implicitly.
- Convert is the only 1→2 path. No 2→1 conversion.
- Save As 2→2 copies the complete portable project folder from a frozen
  consistent snapshot. It preserves unknown user files byte-for-byte but
  excludes active runtime/session/transaction artifacts.
- Convert 1→2 semantically classifies and rewrites known legacy members.
  Unknown members cause failure plus an inventory report; they are not silently
  moved into a miscellaneous bucket.
- Both operations hard-block before staging while any external or built-in
  Blender writer can still mutate project files.
- Destination must not exist and is never merged. Reject destinations nested
  inside the source.
- Preflight available space, path collisions, locks, reparse points, and all
  stored references.
- Stage beside the destination on the same volume; write and validate the
  complete target there, then use one atomic directory rename.
- Before commit, verify source file hashes/sizes are unchanged, every rewritten
  reference exists, the `.sbd` parses, its allowlist/cap holds, and file counts
  reconcile.
- Rename failure preserves the staging folder for recovery and reports it.
  Activation failure preserves the completed target but leaves the source
  active. No retry loop and no source deletion.
- On success, Layout 2 `project.json` records `converted_from` with source path,
  timestamp, source version, and source hash.

#### D4 — Photoshop/Blender path migration contract

Backend protocol v2 is mandatory for Layout 2. The current UXP plugin (0.6.7),
or any client without protocol v2 plus `explicit_asset_paths_v2`, is "old".

Compatibility matrix:

- Layout 1 + old plugin: supported with existing linked/legacy behavior.
- Layout 1 + new plugin: exact backend paths preferred; explicit legacy
  standalone fallback remains available.
- Layout 2 + old plugin: hard block. Context and mutation endpoints return 426
  before disclosing a writable project root; prompt plugin upgrade.
- Layout 2 + new plugin: online protocol-v2 operation only. Offline
  plugin-managed project writes fail closed. Native Ctrl+S remains possible for
  an already-open canonical PSD, followed by hash/role validation on reconnect.

Protocol-v2 context sends exact paths per asset role plus
`project_session_id`, `context_revision`, `path_mode=explicit-assets`, and
`offline_write_allowed=false`. Every write sends protocol header, session ID,
context revision, work key, asset role, and a short-lived single-purpose write
intent token.

The backend recomputes the canonical target from work key + role and ignores
the client path as authority. Preview writes first land in
`.storyboarder/transactions/.../plugin-inbox`; validate type, size, role,
session, revision, and token; then same-volume `os.replace`; metadata commits
last.

`shot_folder` keeps its legacy meaning only for Layout 1. For Layout 2 it is
empty and unsupported—never alias it to `Images/`, `PSD/`, or project root.
Protocol-v1 Layout 2 responses must scrub project root, project JSON, shot
folder, and source paths before returning 426.

Per-shot plugin IPC becomes `PSD/<shot-id>_bridge.json` only if still required
by the online protocol. Project canvas color belongs in
`.storyboarder/canvas_color.txt`. Blender add-on and built-in viewport writers
must use the same resolver/session/revision gate and store external `.blend`
asset links as `//` paths.

#### Non-negotiable invariants

1. Only the transition coordinator may change the active project.
2. Every persistent path resolves through `project_layout.py`.
3. One revision is authoritative across work state, recovery, and `.sbd`.
4. A snapshot begins only after all known writers are enumerated and quiesced.
5. `.sbd` membership is allowlist-only; `cover.png` is the only binary.
6. Backend metadata never trusts a plugin/client-supplied filesystem path.
7. Convert never writes, renames, or deletes the source.
8. Save As never merges with an existing destination.
9. Plugin writes require current session/revision/role/token and an atomic
   inbox-to-canonical commit.
10. Unknown or legacy stray writes are reported; they are never silently
    ingested, deleted, or used to invalidate legitimate user asset edits.

#### Ordered implementation slices and acceptance gates

0. Transition coordinator — `backend_service.py`, `app_state.py`,
   `project_manager.py`, `bpy_viewport.py`, `ProjectContext.tsx`.
   Gate: dirty A→New/Open B never loses data; fault injection at every stage;
   writer enumeration and quiesce timeout; no early cleanup.
1. `project_layout.py`, project-root model, strict resolver, schema v4.
   Gate: Layout 1 zero behavior change; unknown version, absolute/UNC,
   traversal, reparse, and case-collision tests; Layout 2 still off.
2. Route every path consumer through the resolver.
   Gate: Layout 1 shot/reference/generation/export/scene/Blender/plugin
   regression suite passes with no duplicate path construction.
3. Metadata-only `.sbd`, `.storyboarder/work`, revision recovery, cover/recents.
   Gate: archive allowlist/cap tests, revision conflict/recovery tests, no
   temporary binary asset tree for Layout 2.
4. Backend Photoshop protocol/layout gate.
   Gate: protocol-v1 Layout 2 returns 426 before path disclosure; legacy fields
   scrubbed; stale session/revision/role/token rejected.
5. UXP protocol v2.
   Gate: no shot-path concatenation or fixed shared bridge files; offline writes
   fail closed; native Ctrl+S canonical PSD reconnect validation; Node/UXP tests.
6. Layout 2 shot/reference/generation/export assets.
   Gate: no per-shot folders; exact role paths; atomic write-failure tests.
7. Scene2D/Scene3D/Blender paths.
   Gate: metadata-only scene moves, persisted paths preserved, lazy `.blend`,
   built-in and external writer gates, portable `//` references.
8. Transactional Save As 2→2.
   Gate: snapshot determinism under concurrent activity; existing/nested
   destination, disk-full, locked-file, hash, rename, and activation faults.
9. Transactional Convert 1→2.
   Gate: representative legacy fixtures; unknown/missing/collision/reparse/crash
   reports; original source hash remains unchanged in every outcome.
10. Enable Layout 2 creation/default/UI/docs.
    Gate: full backend/frontend/UXP/Blender suite, real conversion fixtures, and
    Windows/OneDrive/locked-file manual smoke before changing the default.

The same execution task is authorized to complete Slices 0–10 sequentially.
Each slice remains a separate reviewable commit. The agent must run and pass the
slice gate before continuing, diagnose and repair ordinary failures, and must
not skip, combine, or reorder slices merely to keep moving. A red gate pauses
later slices until repaired. Layout 2 remains behind a disabled feature flag
through Slice 9.

Other-computer handoff:

```powershell
git clone https://github.com/Rampageboo/Storyboarder.git
cd Storyboarder
git fetch --prune origin
git switch --create codex/local-updates-20260730 --track origin/codex/local-updates-20260730
git status --short
git log -2 --oneline
```

Then read AGENTS.md and this section in full. Create one fresh implementation
branch from this baseline (for example `codex/layout2-storage-migration`) and
complete Slices 0–10 in order on that branch. Before editing, re-run the baseline
tests. After every slice, run its gate, review the actual diff, and create a
separate commit before proceeding. Continue autonomously through ordinary
implementation and test repairs. Stop only for a material architecture,
persistence-contract, destructive-migration, or user-visible product decision
not already resolved here. Do not pop or recreate the original machine's stash;
it is intentionally not part of this handoff.

## 3. Generation handoff decision / next fork

```text
Decision: "Send to Codex" remains the single handoff to the Codex agent. Stable Diffusion is not a separate receiver; it is a tool/workflow that Codex may operate after receiving the task.
Backend choices: explicit only - `codex` or `stable_diffusion`. Do not add `auto`.
Workflow meaning:
- `backend=codex`: Codex directly handles image generation.
- `backend=stable_diffusion`: Codex MUST prepare prompt/reference/size/seed settings and operate Stable Diffusion to generate the image. The selected backend is an execution constraint, not a preference; prior conversation context must not override it and OpenAI imagegen/DALL-E/other generators are forbidden for that request.
Status/detail strategy: generation precision should follow shot/status/mode. Draft should favor speed with proportional downscale, low resolution, possible upscale back to panel size, and rough/line-art storyboard output. Cleaner/final statuses can increase resolution, steps, refinement, and polish.
Next fork: complete Layout 2 Slices 0–10 sequentially from the final execution decision in §2. Keep Layout 2 disabled through Slice 9 and preserve one commit plus one passing gate per slice.
Owner input needed: no for the above semantics; yes only for later SD-specific runtime/configuration choices.

Progress (2026-07-21):
- DONE: `provider` field on the request snapshot (generation_service PROVIDERS={codex,stable_diffusion}, default codex, validated before any FS write). Backend Spark-authored slice, kept.
- DONE: `provider` threaded end-to-end — GenerationRequestCreateRequest.provider, api create-generation-request route, method_create_generation_request(shot_id, destination, provider). Default codex, backward compatible.
- DONE: single and batch Codex handoff prompts are provider-aware. The stable_diffusion variant states a mandatory backend requirement at the start, instructs Codex to OPERATE Stable Diffusion per the request's generation_plan, and explicitly forbids OpenAI imagegen, DALL-E, or any alternative image generator. Request snapshots also carry machine-readable `execution_constraints` with `required_backend`, `backend_is_mandatory`, and `forbid_alternative_image_generators`.
- DONE: `mode` field (draft/clean/final) + per-mode `generation_plan` block. Owner spec 2026-07-21. Default mode derives from shot.status (Draft->draft, In Progress/Review->clean, Approved/Final->final); explicit `mode` overrides. Chosen default profile numbers (tunable, in generation_service._MODE_PROFILES): draft = longest-edge 768, steps 12, cfg 5.0, upscale_to_panel, overwrite_final False; clean = longest-edge 1024, steps 22, cfg 6.5, use_prior_frame_as_reference; final = full panel size, steps 32, cfg 7.0, overwrite_final True. generation_plan carries target_width/height, panel_width/height, steps, cfg_scale, style_hint, use_prior_frame_as_reference, output_policy{preserve_aspect_ratio, upscale_to_panel, overwrite_final}. These are ADVISORY payload guidance — no engine executes them yet.
- Field mapping (Owner payload -> existing snapshot): target->destination, backend->provider; new: mode, generation_plan, generation_plan.output_policy. Existing snake_case field names NOT renamed.
- DONE: generation_plan.prior_frame — for clean/final (use_prior_frame_as_reference), the request now carries the shot's accepted Codex layer (_codex.png) as {source, project_relative_path, absolute_path, exists}; null in draft or when no layer exists. SD handoff prompt says to use prior_frame as the img2img base. Advisory: the actual img2img/upscale/overwrite-final execution is still Codex/SD-operator side, not built here.
- PERF: `.sbd` save = full re-zip of the whole working root on EVERY autosave (add-board etc.) via project_document.pack_document → cost scales with project size ("long wait"). Measured: 48 MB incompressible artwork = 1244 ms at DEFLATE-6. Fix shipped: STORE already-compressed imports (png/jpg/mp4…) + DEFLATE level 1 for the rest (PSD canvases stay compressible → ~1 MB not 91 MB). ~2x faster, negligible size change, backward compatible. STRUCTURAL FIX SHIPPED (Owner-approved 2026-07-23): interactive `_autosave` now writes metadata to the working tree but DEFERS the .sbd pack (`save_project(flush_document=False)`); Add board dropped 200-1200 ms → ~8 ms. The pack now runs on periodic autosave (frontend useAutosave hook, interval `autosave_interval_minutes` setting = 3/5/10, default 5), manual save (Ctrl+S / menu, already existed), and save-on-close (shutdown_reference_cleanup save_if_dirty). Folder projects unchanged (metadata write is already durable; not left dirty). .sbd projects are left dirty after edits until a flush. `backups/` is now EXCLUDED from the .sbd pack (project_document._UNPACKED_DIRS) — it is a local, write-only recovery snapshot set the app never reads back, so embedding it only bloated the document and slowed saves; for .sbd it now lives only in the temp working tree (session-local).
- DONE: dispatch does not immediately clear staged queue entries. The send popup records `clear_queue_on_result`; only successful result submission clears the matching staged queue entry when that option is enabled. If disabled, the queue remains available after results return.
- DONE (UI, revised per Owner): Queue offers Current, Queued, and All send scopes through a shared popup. The popup selects Codex or Stable Diffusion, controls clear-after-result, and exposes Modify only as a disabled/coming-soon placeholder. Precision follows shot Status; frontend sends no explicit mode. Layers and Queue are separate floating islands. The far-right More rail auto-hides at the edge; Shot Inspector remains visible. PENDING: Owner GUI click-test.
- NEXT FORK: complete §2 Slices 0–10 sequentially. The architecture review is complete; the execution task may continue autonomously after each passing gate, while Layout 2 remains disabled through Slice 9.
- Validation for the latest generation-backend constraint change: 42 focused tests passed. The broader staged feature set previously passed 803 tests with 1 skipped and 33 subtests; frontend TypeScript/Vite build passed. Lint remains at the known baseline (9 errors, 2 warnings). Owner GUI click-test remains pending.
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
Current task coordination mode: owner-direct
Current capability policy:
- Sub-agents: allowed
- Delegation autonomy: bounded
Active host/environment: Windows 11 / Codex desktop
Active MCP client: local Codex tools
Active Git execution mode: codex-git
Git mode last verified: 2026-07-28
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
