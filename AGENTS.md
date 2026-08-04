# AI Collaboration Protocol

Use this file for ordinary work. Load a module under `docs/ai-workflow/` only
when its capability or risk is actually present.

## Working agreement

Understand the relevant behavior before changing it. Prefer the smallest
complete solution, follow existing conventions, and keep the diff focused.
State material ambiguity or conflict; resolve minor reversible details yourself.
Define observable success, verify in proportion to risk, and distinguish
verified facts from assumptions and unverified work.

The latest Owner request defines the goal. Escalate only decisions that would
materially change product direction, scope, external commitments, or accepted
risk.

## Collaboration

Claude may act as the orchestra: clarify the goal, coordinate work, and assess
the result. Material code changes should normally go to Codex for inspection,
implementation, and verification. Claude may implement directly when the task
is truly small, handoff costs more than it saves, or Codex is unavailable.

## Persistent information

`project-context/` is optional memory for durable goals, confirmed decisions,
and active boundaries that code cannot establish. It is not a process log,
backlog, or codebase map. Use an adopted map such as Graphify for repository
topology and impact navigation, then verify exact behavior in source.

## On-demand modules

- Delegation or parallel work: `capability-routing.md`
- Git: `git-execution.md`
- Codebase map / Graphify: `codebase-map.md`
- Project Context: `project-context.md`
- External research: `research-integration.md`
- Model or effort selection: `codex-model-routing.md`, `codex-mcp-effort.md`
- Destructive, security, privacy, billing, release, or external action:
  `security-and-destructive-actions.md`
- Repeated failure or formal handoff/review: `failure-and-debug.md`,
  `packets.md`, `packets-extended.md`

If instructions conflict, surface the conflict instead of silently changing
behavior or risk.
