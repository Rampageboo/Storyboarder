# Project State

Verified 2026-08-04 against branch `main` at `cb77f98`.

## Validation is local and gated

There is no CI. `python scripts/verify_dev.py` is the gate and is required
before merging; `--backend`, `--frontend`, and `--fast` scope it. The backend
suite is 54 test files under `tests/`, with `test_smoke.py` as the fast subset.
Python 3.11+, dependencies in `requirements.txt`.

`npm run lint` sits at a known red baseline on `main`
(`react-hooks/set-state-in-effect` errors in App, Scene2DPanel,
ReferenceAssignmentPopover3dApply, FloatingLayersPanel). Compare against that
baseline rather than expecting green, and do not fold unrelated lint repairs
into a feature change.

Touching UI, the Photoshop bridge, Scene3D, exports, or PSD flows also needs the
manual GUI smoke checklist in `docs/development_workflow.md`. The Owner runs
that; an agent cannot claim it.

## Collaboration protocol

Installed at `v4.1.1` with hashes in `.protocol-lock.json`. Updates arrive as
pull requests from the protocol distributor on each release. Do not hand-copy
protocol files, and do not merge a pull request titled `BLOCKED` expecting it to
install anything — that kind carries only a report.

Git execution mode here is `codex-git`.

## Codebase map

A Graphify map was adopted 2026-08-04: 4917 nodes, 14255 edges, 180 communities
over 251 source files, code only. Its integrity check reported 1085
dangling-endpoint edges, 24 self-loops, and 548 collapsed edges, so use it to
locate source and read that source before making a consequential claim.

`docs/` and `agent-workflows/` are outside the map on purpose: they carry intent
and process, not repository-derived structure.

## Superseded context

`PROJECTCONTEXT.md` at the project root is the pre-V3 single-file context this
directory replaces. Roughly 300 of its 489 lines were an execution log for the
Layout 2 migration; that belongs to task records, not durable memory. It is
retained until this layout has carried real work. Do not update it.
