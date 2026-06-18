# Feature Branch Checklist

Use this checklist before merging any feature, refactor, fix, or chore branch.

---

## Before you start

- [ ] Branch starts from the latest `main` (`git checkout main && git pull`)
- [ ] Branch has a single, clear purpose — one feature, one refactor, one fix
- [ ] Branch name follows convention: `feat/`, `refactor/`, `fix/`, `chore/`

---

## During development

- [ ] No generated JS bundles hand-edited (`storyboard_tool/web/static/runtime/`, `storyboard_tool/web/dist/`)
- [ ] No browser mode revived (`--browser` flag, argparse in `main.py`, standalone HTML windows)
- [ ] No broad unrelated refactoring mixed into the branch
- [ ] No API response shape changes unless the branch is explicitly an API contract change
- [ ] No project file format changes unless a migration and tests are included
- [ ] No user files deleted more aggressively than current behavior
- [ ] No PS bridge or Scene3D logic moved unless the branch is explicitly about that boundary

---

## Before merging

### Tests
- [ ] Existing tests pass: `python scripts/verify_dev.py`
- [ ] New behavior is covered by tests (add or update `tests/test_*.py` as needed)
- [ ] If a new edge case was fixed, a regression test was added

### Docs
- [ ] If the public API / HTTP response shape changed: `docs/current_architecture.md` updated
- [ ] If a new architectural boundary was clarified: relevant section in `docs/current_architecture.md` updated
- [ ] If a new service or module was added: ownership documented

### Verification
- [ ] Full gate passed: `python scripts/verify_dev.py` exits 0
- [ ] For Python-only changes: `python scripts/verify_dev.py --backend` exits 0
- [ ] For frontend-only changes: `python scripts/verify_dev.py --frontend` exits 0

### Manual smoke (when required)
- [ ] If UI components changed: manual GUI smoke performed (see `docs/development_workflow.md`)
- [ ] If Photoshop bridge changed: plugin connect/export/sync verified manually
- [ ] If Scene3D panel changed: GLB import, workspace open, board capture verified
- [ ] If export changed: PDF/CSV/contact-sheet output verified

---

## Hard rules (never break these)

| Rule | Why |
|---|---|
| Do not hand-edit generated JS bundles | They will be overwritten on next build; edits are silently lost |
| Do not revive browser mode | Desktop-only is a hard architectural constraint |
| Do not change `project.json` / `settings.json` format without a migration | Breaks existing projects |
| Do not delete user files more aggressively than current behavior | Data loss |
| Do not merge if `verify_dev.py` fails | Broken main blocks everyone |

---

## Quick reference — verification commands

```bash
# Full gate (required before merge)
python scripts/verify_dev.py

# Fast check during development
python scripts/verify_dev.py --fast

# Backend changes only
python scripts/verify_dev.py --backend

# Frontend changes only
python scripts/verify_dev.py --frontend

# Don't stop on first failure (useful to see all broken steps at once)
python scripts/verify_dev.py --continue-on-fail
```
