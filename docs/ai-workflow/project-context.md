# Modular Project Context

Read this module when creating, loading, or updating `project-context/`.

Project Context is compact cross-session memory for durable goals, confirmed
decisions, exact facts, active boundaries, and high-value risks that cannot be
reliably derived from source. A current stage or next endpoint belongs only
while it remains useful across sessions.

It is not a transcript, backlog, task log, packet archive, or codebase map.
Repository structure and as-built architecture belong to an adopted map; when
no map exists, inspect source on demand.

```text
project-context/
|-- index.yaml
|-- exact-facts.yaml
`-- sources/
```

Read `index.yaml` first, then only modules whose `read_when` matches the task.
Read `exact-facts.yaml` only when exact values matter. Never store secrets or
personal data; reference their approved storage location.

Use `PROJECT_CONTEXT_TEMPLATE/` to initialize the layout. Mark unknown content
as missing rather than inventing it. Store only routing and validity metadata
for maps or research; their generated artifacts stay with their providers.

Update context only when a durable goal, decision, boundary, risk, or validity
limit changes. Routine progress, commands, validation logs, and temporary
findings remain in the task record. The implementer may propose a delta; the
Owner or assigned context integrator applies it.

Current Owner direction, the active task, source, and verified tests outrank
stored context. Surface conflicts and mark stale material instead of silently
choosing it. Existing V2 layouts use
`migrations/project-context-v2-to-v3.md`.
