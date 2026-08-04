# Project State

Verified against the current `main` revision recorded in
`project-context/index.yaml`; map revision and health details live in
`project-context/exact-facts.yaml`.

## Validation is local and gated

There is no CI. `python scripts/verify_dev.py` is the gate and is required
before merging; `--backend`, `--frontend`, and `--fast` scope it. The backend
suite lives under `tests/`, with `test_smoke.py` as the fast subset. Read live
runtime and dependency versions from `project-context/exact-facts.yaml` and the
repository lock files rather than copying them into prose.

`npm run lint` sits at a known red baseline on `main`. Read the live failures
from that command and compare a task branch against `main`; do not freeze the
changing count or component list in context, expect green, or fold unrelated
lint repairs into a feature change.

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

A code-only Graphify map is adopted. Its current corpus size, graph figures,
represented source revision, and integrity results are recorded in
`project-context/exact-facts.yaml`. The extraction health has known warnings,
so use the map to locate source and read that source before making a
consequential claim.

`docs/` and `agent-workflows/` are outside the map on purpose: they carry intent
and process, not repository-derived structure.

## Superseded context

`PROJECTCONTEXT.md` at the project root is the pre-V3 single-file context this
directory replaces. Much of it is an execution log for the Layout 2 migration;
that belongs to task records, not durable memory. It is retained until this
layout has carried real work. Do not update it.
