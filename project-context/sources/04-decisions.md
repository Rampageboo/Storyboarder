# Decisions

## Resolved

- **Layout 2 is the storage direction and is implemented in code.** Save-as and
  convert paths exist. The pre-V3 context described it as decided but not
  implemented; that is no longer accurate, so verify current behaviour in source
  rather than trusting either description.
- **The built frontend bundle is committed.** It was briefly gitignored and
  re-tracked on 2026-07-22. This is required for a Node-less install, so rebuild
  and commit `storyboard_tool/web/dist/**` whenever `frontend/src/**` changes.
- **Generation names its backend explicitly** — `codex` or `stable_diffusion`,
  never `auto`. The backend is a constraint on execution, and generation
  precision follows shot status rather than a separate user control.
- **Git execution mode is `codex-git`** on this workstation.
- **`agent-workflows/` is not application code.** Never audit, refactor, or lint
  it as part of product work.

## Pending

- **Owner GUI click-test (unverified in repository).** The prior context records
  an unclosed manual verification for completed backend changes, but the
  repository has no authoritative acceptance record that can confirm whether
  the Owner has since completed it. Backend evidence does not substitute for
  that check; report this uncertainty rather than implying acceptance.
- **`.sbd` flush cost.** A save is a full re-zip with no incremental path, and
  the Owner's documents live under OneDrive so each flush triggers a full
  re-upload. The Owner has said OneDrive is not a concern; revisit only if
  asked.
- **Desktop/Tauri and 3D streaming work** tracked in
  `docs/desktop_migration_and_3d_streaming_plan.md` is an open direction, not a
  committed migration.
