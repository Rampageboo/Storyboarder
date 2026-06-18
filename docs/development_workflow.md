# Storyboarder — Development Workflow

## Overview

This document describes the recommended local development workflow for Storyboarder contributors. The project is a desktop-only application (pywebview shell + FastAPI + React/Vite). All validation runs locally; there is no CI pipeline.

---

## Quick reference

| Situation | Command |
|---|---|
| Before merging any branch | `python scripts/verify_dev.py` |
| Checking only Python changes | `python scripts/verify_dev.py --backend` |
| Checking only TypeScript/CSS changes | `python scripts/verify_dev.py --frontend` |
| Fast iteration check during feature work | `python scripts/verify_dev.py --fast` |
| Keep going after a failure | `python scripts/verify_dev.py --continue-on-fail` |

---

## `verify_dev.py` modes

### Full mode (default)
```bash
python scripts/verify_dev.py
```
Runs every check. Required before merging feature or refactor branches.

Steps in order:
1. Python syntax check (`py_compile`) on all core backend modules
2. Migration validator (`scripts/validate_migration.py`) — checks static file tree, route expectations, and desktop-shell invariants
3. Full test suite (`pytest tests/`)
4. Frontend lint (`eslint`)
5. Frontend build (`vite build`)

### Backend mode
```bash
python scripts/verify_dev.py --backend
```
Use when you have only changed Python files. Skips the frontend build (which takes a few seconds).

Steps: py_compile → validate_migration → pytest full.

### Frontend mode
```bash
python scripts/verify_dev.py --frontend
```
Use when you have only changed TypeScript, CSS, or frontend config files.

Steps: eslint → vite build.

### Fast mode
```bash
python scripts/verify_dev.py --fast
```
Use during active development for a quick sanity check between commits. Runs the smoke test suite instead of the full test suite, and skips the frontend build.

Steps: py_compile → validate_migration → pytest smoke → eslint.

When to use fast vs full:
- **fast** — iterating on a feature mid-branch; checking your last change didn't break imports or core routes
- **full** — before pushing, before opening a PR, before merging

---

## Branch workflow

### Starting a new branch
```bash
git checkout main
git pull
git checkout -b <type>/<short-description>
```

Branch naming conventions:
- `feat/` — new user-facing feature
- `refactor/` — internal restructuring with no behavior change
- `fix/` — bug fix
- `chore/` — tooling, docs, dependencies, quality gates

### During development
Run `--fast` after meaningful commits to catch regressions early.

### Before merging
Full `verify_dev.py` must pass. For changes that touch the Photoshop bridge, Scene3D panel, or UI rendering, also run a manual GUI smoke (see below).

### Merging
Prefer merge commits (not squash) for refactor/feature branches so that git history retains context.

---

## Manual GUI smoke (when required)

Manual smoke is required when changes touch:
- Any UI component (React, CSS)
- Photoshop bridge (live bridge JSON, plugin API, canvas creation)
- Scene3D panel (GLB import, capture, workspace)
- Export (PDF, contact sheet, CSV)
- Shot canvas creation / PSD recovery

Smoke procedure:
1. `python main.py` — launch the desktop app
2. Create or open a project
3. Add/delete shots
4. Import a shot image
5. Import a reference (image or video)
6. If Photoshop available: open a shot source PSD, verify bridge status
7. If Scene3D changed: import a GLB, open the workspace, capture a board
8. Export to PDF and verify output
9. Close and reopen the project — confirm state persisted correctly

Manual smoke is **not** required for:
- Documentation-only changes
- `chore/` branches that don't touch app behavior
- Refactors with full test coverage and no visual changes

---

## Individual commands

If you need to run individual checks without the script:

```bash
# Python syntax check
python -m py_compile storyboard_tool/project_manager.py storyboard_tool/backend_service.py \
    storyboard_tool/reference_segments.py storyboard_tool/external_tools.py \
    storyboard_tool/export_service.py storyboard_tool/project_transaction.py \
    storyboard_tool/app_state.py storyboard_tool/shot_service.py \
    storyboard_tool/api.py storyboard_tool/schemas.py storyboard_tool/errors.py \
    storyboard_tool/models.py

# Migration validator
python scripts/validate_migration.py

# Full test suite
python -m pytest tests/

# Smoke tests only
python -m pytest tests/test_smoke.py

# Frontend lint (Windows)
cd frontend && npm.cmd run lint

# Frontend build (Windows)
cd frontend && npm.cmd run build
```

---

## Adding a new check to `verify_dev.py`

1. Write a `check_<name>() -> bool` function in `scripts/verify_dev.py` that calls `_run()`.
2. Add it to the relevant `_steps_*()` list(s).
3. `_run()` handles printing the label, command, and failure message consistently.

Keep checks fast. If a new check takes more than ~30 seconds it belongs in full mode only, not fast or backend/frontend modes.
