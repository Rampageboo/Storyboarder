# Code Review Configuration

This file defines project-specific settings for the reusable code review workflow.

## Project context

Storyboarder is a Windows desktop-only storyboard planning app. Full agent-facing context lives in the repo root [`CLAUDE.md`](../../CLAUDE.md) — read it before auditing. Key facts:

- Entry point: `python main.py` → pywebview window over a loopback-only FastAPI server (uvicorn on `127.0.0.1`). There is no hosted server, no browser mode, no cloud sync, no auth-facing surface beyond the local plugin token.
- Backend: Python 3.11+ in `storyboard_tool/`. Layering: `api.py` (routes only) → `backend_service.py` (business logic) → domain modules (`shot_service.py`, `reference_segments.py`, `project_manager.py`, `external_tools.py`). Domain modules must not import FastAPI.
- Frontend: React 19 + TypeScript in `frontend/src/`, built by Vite into the committed bundle `storyboard_tool/web/dist/`.
- Photoshop UXP plugin: `photoshop_uxp_plugin/` (vanilla JS) talks to `/api/plugin/*` and `/api/bridge/*`. This endpoint/field contract is compatibility-sensitive — flag breakage risks, don't propose casual renames.
- Data: projects are on-disk folders (`project.json`, `settings.json`, `shots.json`, per-shot PNG/PSD). Critical writes use temp file + `os.replace()`; mutating service methods are wrapped in `project_transaction.mutate_project()`.
- Sensitive/risk-heavy modules: `project_manager.py` and `reference_segments.py` (file I/O, deletion, path containment), `backend_service.py` (validation, plugin token), `psd_recovery.py` (rewrites user PSDs), `image_utils.py` (image parsing, pixel caps), `live_bridge.py` / `app_state.py` (bridge state), `api.py` (route surface, CORS).
- Reference invariants doc: `docs/stability_contract.md` (asset ownership per shot file, allowed mutations per operation). Violations of that contract are real findings.

## Report output paths

Audit report:

`docs/review/reports/full-software-risk-audit.md`

Fix plan:

`docs/review/reports/fix-plan.md`

Fix log:

`docs/review/reports/fix-log.md`

## Folders and files that should NOT be audited as application code

Do not audit these as application code:

- `agent-workflows/` — reusable workflow prompts (never report findings about these)
- `docs/` — documentation (use it as evidence, don't audit it)
- `docs/review/reports/` — generated review output
- `.git/`, `.venv/`, `__pycache__/`, `.pytest_cache/`
- `frontend/node_modules/`
- `storyboard_tool/web/dist/` — generated Vite bundle (committed on purpose; source is `frontend/src/`)
- `storyboard_tool/web/static/runtime/scene3d_workspace.js` — generated workspace bundle
- `storyboard_tool/web/static/vendor/` — pinned Three.js vendor copies
- `logs/`, `Sessions/` — runtime output and session state, not source
- `spikes/` — throwaway experiment code, explicitly out of audit scope
- `_icon_test.png` and other stray test assets
- lock files (`requirements.lock.txt`, `frontend/package-lock.json`), unless dependency/security review requires checking them

## Application code review scope

Audit the real application code:

- `storyboard_tool/**/*.py` (backend, routes, services, domain, media, bridge)
- `main.py`, `sidecar_entry.py`
- `frontend/src/**` (React/TS source — NOT the built `dist/`)
- `photoshop_uxp_plugin/**` (UXP plugin JS)
- `scripts/*.py` (dev/validation tooling)
- `tests/**` for coverage gaps only
- launch scripts (`run.bat`, `run-silent.bat`, `launch_storyboarder.bat`, `Storyboarder.vbs`) and config where relevant

Focus areas that matter for this app: file-path containment inside the project root (path traversal into/out of user projects), data loss in save/apply/delete flows, PSD/PNG corruption, race conditions between the UI, the auto-sync poller, and the Photoshop plugin, and regressions to the plugin compatibility contract.

## Validation commands

There is no CI; all validation is local. Use these (Windows; use `npm.cmd` in shells):

```bash
# Full gate — required before claiming a fix is verified
python scripts/verify_dev.py

# Scoped modes
python scripts/verify_dev.py --backend    # py_compile + validate_migration + full pytest
python scripts/verify_dev.py --frontend   # eslint + vite build
python scripts/verify_dev.py --fast       # smoke tests, skips frontend build

# Individual checks
python -m pytest tests/                   # full backend suite
python -m pytest tests/test_smoke.py      # smoke subset
python scripts/validate_migration.py      # static tree / route invariants
cd frontend && npm.cmd run lint
cd frontend && npm.cmd run build          # also rebuilds the workspace bundle
```

Targeted suites worth running per area: `tests/test_photoshop_bridge.py`, `tests/test_plugin_backend_regression.py` (plugin contract), `tests/test_file_transactions.py`, `tests/test_project_transaction.py` (save safety), `tests/test_shot_path_containment.py`, `tests/test_storage_boundary.py` (path containment), `tests/test_reference_segments.py`, `tests/test_asset_lifecycle.py` (reference flows).

If a change touches UI, the Photoshop bridge, Scene3D, exports, or PSD flows, note that the manual GUI smoke checklist in `docs/development_workflow.md` also applies — list it as a manual verification step.

## Important project rule

The files in `agent-workflows/` are reusable workflow instructions.

Do not treat `agent-workflows/` as application code.
Do not report bugs, security issues, architecture issues, or style issues about the workflow prompt files.

Additional rules:

- Never hand-edit generated bundles (`storyboard_tool/web/dist/**`, `web/static/runtime/scene3d_workspace.js`); fixes go in `frontend/src/**` followed by a rebuild.
- `delete_shot` intentionally leaves shot files on disk (undo depends on it) — do not report this as a bug.
- Loopback-only server and permissive local CORS are by design for the desktop shell; only report them if a change actually exposes the server beyond `127.0.0.1`.
