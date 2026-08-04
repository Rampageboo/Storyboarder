# Modular Project Context

Read this module when creating, loading, or updating `project-context/`.

Project Context is compact cross-session memory. An entry earns its place only
if it passes both tests: it would still be true after the code was rewritten,
and it cannot be recovered by reading source. In practice that leaves intent
and non-goals, decisions and the reasons behind them, boundaries that must not
be crossed, and failure modes with their consequence.

Everything else belongs to the codebase map, to the task record, or nowhere.
Repository structure and as-built architecture belong to an adopted map; when
no map exists, inspect source on demand. Write nothing to fill a heading — an
empty module is honest, and a vague one costs a reader time while teaching
nothing.

Entries leave. Remove a risk once a regression test enforces it, compress a
decision once it is settled, and drop state a later stage superseded. Context
that only grows is accumulating task record; this memory should stay roughly
constant in size.

```text
project-context/
|-- index.yaml
|-- exact-facts.yaml
`-- sources/
```

Read `index.yaml` first, then only modules whose `read_when` matches the task.
Read `exact-facts.yaml` only when exact values matter. Never store secrets or
personal data; reference their approved storage location.

## When to adopt it

Create `project-context/` at the first fact that passes both tests, not at
project start. A project with nothing durable to record yet is better served by
no directory than by a template of empty headings, because empty headings read
as questions that were asked and answered.

Work that fits one session does not need it: the goal, the constraints, and the
reasoning are still in the conversation. What earns the directory is a decision
whose reason would otherwise be lost, or a boundary a later session would
otherwise cross without knowing it existed.

Whoever holds that fact writes it down. The implementer may propose it; the
Owner or assigned context integrator applies it.

Use `PROJECT_CONTEXT_TEMPLATE/` to initialize the layout. Mark unknown content
as missing rather than inventing it. Store only routing and validity metadata
for maps or research; their generated artifacts stay with their providers.

## What rots, and checking it

Intent, confirmed decisions, boundaries, and the mechanism behind a risk hold
until the decision itself changes. Anything describing current stage, adopted
tool state, or exact values is true only against the revision it was checked
at, and that is the part that goes stale.

So `exact-facts.yaml` and any state module record the revision they were
verified against. Compare it with the current revision before relying on them;
if relevant source has moved, treat that content as unverified and re-check
rather than repeating it. A stale record that reads as current is worse than
none, because it sends the next session to plan work that already exists.

Current Owner direction, the active task, source, and verified tests outrank
stored context. Surface conflicts and mark stale material instead of silently
choosing it. Existing V2 layouts use
`migrations/project-context-v2-to-v3.md`.
