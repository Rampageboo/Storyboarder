# PROJECTCONTEXT.md — Storyboarder

> Persistent project memory for the AI Collaboration Protocol. Not authority
> above current Owner instructions, the active brief, repository code, or
> verified tests. Durable collaboration rules live in `AGENTS.md`, `CLAUDE.md`,
> and `docs/ai-workflow/`.

## Context metadata

```text
Last updated: 2026-07-21
Last verified branch: main
Last verified commit: d8e7023 (Codex batch/pull + inspector-collapse & queue UI)
Updated by: Claude
Context confidence: current

Git execution environments:
- Windows 11 / VSCode Claude Code extension | codex-user MCP | mode: unverified — verify before Git ops | Last verified: —
```

## 1. What this project is

Storyboarder is a **Windows desktop-only** storyboard planning app:

- **Shell**: pywebview (EdgeWebView2 window) launched by `python main.py`
- **Server**: FastAPI + uvicorn on `127.0.0.1:<port>` — internal implementation detail, loopback only, never browser-exposed
- **Frontend**: React 19 + TypeScript, built with Vite from `frontend/src/`, committed as a prebuilt bundle to `storyboard_tool/web/dist/`
- **3D**: Three.js (pinned vendor copy) + a separately compiled Scene3D workspace bundle
- **Photoshop integration**: a UXP plugin in `photoshop_uxp_plugin/` talks to `/api/plugin/*` and `/api/bridge/*`
- **Storage**: projects are folders on disk (`project.json`, `settings.json`, `shots.json`, per-shot PNG/PSD files). No database, no cloud, no network features.

Non-goals (do not add): browser mode, hosted server, cloud sync, audio, multi-window.

## 2. Current state

```text
Current working area: AI collaboration protocol files (this update)
Last completed task: installed AI Collaboration Protocol v4 (AGENTS/CLAUDE/docs/ai-workflow)
Current build/test status: not re-run this round — no application code changed
```

## 3. Pending decision / next fork

```text
Pending decision: whether to wire Codex into Storyboarder generation flows
Why it matters: mcp_server.py / generation_service.py exist for Codex handoffs but Owner deferred integration
Options: keep deferred / begin integration
Recommended option: keep deferred until Owner asks ("暂时不要codex接入")
Owner input needed: yes
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

1. **Generated files are committed but never hand-edited.**
   - `storyboard_tool/web/dist/**` — regenerate with `cd frontend && npm run build`
   - `storyboard_tool/web/static/runtime/scene3d_workspace.js` — regenerate with `npm run build:workspace`
   - `storyboard_tool/web/static/vendor/three/**` — pinned vendor, never modify
   After editing `frontend/src/**`, rebuild the bundle or the running app won't reflect the change.

2. **Layering**: routes (`api.py`) → service (`backend_service.py`) → domain (`shot_service.py`, `reference_segments.py`, `project_manager.py`). Domain modules must not import FastAPI. New business logic goes in the service/domain layer, never in routes.

3. **Board asset ownership** (details: `docs/stability_contract.md`): per shot, `_preview.png` is artist artwork, `_background.png` is the reference plate, `_codex.png` is the accepted generated layer, and `_thumb.png` is display cache. Reference/Codex flows must never write `_preview.png`; Photoshop sync must never write `_background.png` or `_codex.png`; `image_path`/`preview_image_path` must never point at background/Codex assets.

4. **Atomic writes**: all critical JSON/PNG/PSD writes use temp file + `os.replace()`. Keep this pattern for any new persistence code. Wrap new mutating service methods in `project_transaction.mutate_project()`.

5. **Photoshop plugin contract is frozen-ish**: do not casually rename `/api/plugin/*` endpoints, heartbeat fields, bridge file names (`storyboard_live_bridge.json`), or the plugin's local-fallback file formats — older plugin sessions and saved projects depend on them. The `SB bg` layer in PSDs is plugin-owned (linked smart object); the backend must not round-trip it through psd_tools.

6. **TypeScript policy** (`docs/typescript_policy.md`): new UI code is TS/TSX in `frontend/src/**`. Do not convert `static/runtime/*.js` or vendor JS to TS. All 3D rendering is TypeScript-only — Python never drives Three.js.

7. **Deletion semantics**: `delete_shot` removes only the metadata record; shot files stay on disk (undo depends on this). Do not "clean up" shot folders.

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
