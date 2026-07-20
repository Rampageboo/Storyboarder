# Living Project Context

Read this module when creating, reading, updating, or resolving a conflict with
`PROJECTCONTEXT.md`.

## Purpose

`PROJECTCONTEXT.md` is compact cross-session memory: current state, pending
decisions, module map, active gotchas, and workflow facts the next session would
otherwise rediscover. It is not a transcript, backlog, packet archive, or copy
of stable rules.

## Bootstrap

1. Owner supplies project intent.
2. Unless the repository is greenfield, Claude first requests a Codex Context
   Packet surveying code, build, conventions, constraints, and contradictions.
3. Claude reconciles evidence with Owner intent and asks only unresolved
   product/scope questions.
4. Claude creates the file from `PROJECTCONTEXT_TEMPLATE.md`, marking genuine
   uncertainty rather than guessing.

## Ownership

Claude is logical owner and final authority for the context file. Codex proposes
a delta in every relevant Final Report and edits the file only when Claude
explicitly delegates the specific update. In `owner-direct`, the Owner may
explicitly delegate the update; a later Claude-routed round may reconcile it
against current evidence.

## Authority order

1. Latest explicit Owner decision.
2. Current Claude Decision or active Implementation Brief.
3. Repository code and verified tests.
4. `PROJECTCONTEXT.md`.
5. Older reports, plans, and historical documents.

Context is persistent memory, not authority above current instructions or
evidence. Do not silently overwrite a conflict; raise a Decision Request.

## Update lifecycle

Update when a round produces durable state, a resolved/new decision, a durable
risk/gotcha, workflow-mode change, or next-fork change. Update immediately on a
direction pivot and before a long handoff.

On a no-op round, do not edit. Report:

```text
PROJECTCONTEXT update: not required — no durable context changed.
```

Codex proposes:

```text
PROJECTCONTEXT Delta
- Add:
- Update:
- Remove as stale:
- No durable change: yes/no
```

Claude accepts, modifies, or rejects the delta.

## Metadata

```text
Last updated:
Last verified branch:
Last verified commit:
Updated by:
Context confidence: current / partially stale / needs refresh

Git execution environments:
- Host/environment | MCP client | Git execution mode | Last verified
```

Do not assume one environment's Git mode applies elsewhere.

## Active gotchas

Keep only active, high-value gotchas. Remove or archive one when the defect is
fixed, a regression test permanently enforces it, the workflow no longer
exists, or the information moved into durable technical documentation.

## Boundaries

- Stable rules remain in `AGENTS.md` or workflow modules.
- Goals and acceptance criteria remain in the plan/backlog.
- Referenced evidence must be tracked or otherwise available to the next
  session—not only local, ignored, or session-temporary.
- Never store secrets, credentials, tokens, or personal data. Reference the
  storage location, never the value.
