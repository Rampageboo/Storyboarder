# Capability and Host Routing

Read this module for delegation, parallel work, specialized tools, or
independent review.

## Defaults

Role, host, and authority are separate. Claude normally coordinates and
assesses; Codex normally implements and performs initial verification. Change
that assignment when capability, context, availability, or handoff cost makes
another route better. A substituted host receives only the authority needed for
its task.

Delegate when work is independently bounded or needs a capability the current
host lacks. Keep small, sequential, or tightly coupled work together. The main
host integrates the result and returns one coherent report.

## Before delegation

Give the worker the outcome, scope, constraints, repository state, acceptance
criteria, and required evidence. Confirm that it can access the needed files,
tools, permissions, and return channel. Narrow or stop the delegation if those
conditions are unclear.

## Parallel work

Parallel work must use either non-overlapping write scopes or isolated
alternatives. Do not let two workers modify the same state owner. Name one
integration owner and stop a worker when scope overlaps, the base revision
drifts, or isolation is lost. Use the lease in `packets-extended.md` only when
that coordination needs an explicit record.

For independent review, provide the brief, exact diff or revision, acceptance
criteria, and evidence without relying on the implementer's narrative.

The external Research Skill is not a coding sub-agent and does not edit the
working tree or determine engineering completion. Its results enter through
`research-integration.md`.
