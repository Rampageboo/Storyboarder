@AGENTS.md

# Claude Routing

## Peer decision

Trigger: material framing, architecture, or acceptance uncertainty.

Input: outcome, evidence, constraints, draft acceptance, open conclusion.

Owner supplies goal, authority, and product decisions.

Process: Claude <-> Codex CLI peer review.

Output: settled execution handoff. Unresolved disagreement carries evidence,
authority boundary, and decision need.

## Round boundary

Claude-side deliberation writes the handoff with
`agents/assignment-template.md` for Owner.

Handoff input: goal, constraints, acceptance, authority, repository state,
required evidence.

Owner carries the handoff into Codex execution and assigns Lead. Codex execution
returns a result or blocked handoff to Owner with evidence, limitations,
execution issues, and decision needs.

Owner returns that handoff to Claude-side deliberation. Next direction starts a
new execution handoff.

## Routes

- delegation / parallelism: `capability-routing.md`
- Git: `git-execution.md`
- formal evidence / handoff: `packets.md`
