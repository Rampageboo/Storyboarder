# Execution Network

The Lead reads this module when a project runs implementation through more than
one agent context. It owns the topology and coordination rules. Implementer and
Verifier sessions receive what they need through their role file and assignment.

This is optional. A project without the capability, or with work that does not
earn it, uses the ordinary defaults in `capability-routing.md`.

## Roles

| Role | Short | Owns | Role file |
|---|---|---|---|
| Technical Lead | Lead | Peer discussion, direction, coordination, the cycle count | `agents/lead.md` |
| Implementation Owner | Implementer | Production code, map correctness, acting on findings | `agents/implementer.md` |
| Verification Executor | Verifier | Reproduction, checks, evidence | `agents/verifier.md` |

```text
Owner
  |
  v
Claude <-> Lead
             ├─ assigns Implementer
             └─ assigns Verifier

All handoffs pass through the Lead.
```

Claude and the Lead challenge each other as peers before a direction is
selected. The Lead coordinates afterwards: it assigns the work, and the
assignments and findings pass through it.

## Role is not model

**Give each role its own session, created with its model, reasoning effort, and
opening task set together.** Model and effort are fixed for that session's life,
so they are chosen once, at creation, alongside the work.

`codex-model-routing.md` selects the model. A role does not imply one, and
running one does not confer a role's authority — what carries a verification is
a separate execution context with an identifiable target state, not a particular
model.

## Identity

Each role receives its role, role file, and agent id from whoever creates it, in
the opening task.

## Assignment

An assignment uses the minimum sufficient contract in `capability-routing.md`.
This module adds no second schema, and `agents/assignment-template.md` adds only
an identity header and the target.

Do not rely on a new session receiving the conversation that created it. The
assignment carries the outcome, scope, checks, and authority itself. Repository
and runtime state are evidence the receiver may read; they do not supply a
boundary or an authority the assignment left out.

## What a separate verifier establishes

A separate verifier can execute checks and report their results even when it
knows the implementer's diagnosis. That does not make its review of the
diagnosis independent.

When the framing itself needs challenging, `failure-and-debug.md` routes that to
a host outside this network.

## Target state

Evidence is attached to a state. Before checks run the Implementer names the
target's identity; the Verifier confirms it matches and did not change during
the run, and `packets.md` records both.

Where agents share one mutable workspace, that means the Implementer stops
writing while checks run. Where the target is an isolated workspace or an
immutable artifact, it means the identity matches. Where the state cannot be
identified, the checks still run and the result is reported as an observation
about behaviour rather than verification of a specified state.

## Coordination

Work moves in sequence. Implementation reaches a named handoff state; the Lead
assigns verification against it; findings return through the Lead; a further
implementation cycle is assigned if the findings call for one.

Reproduction details, failing commands, expected against actual, logs, rerun
requests, and coverage gaps travel through the Lead and the task directory.

Relaying does not move ownership: the Implementer owns the change, the Verifier
owns the evidence.

## Capabilities

This protocol names no runtime, parameter, or default; those change per surface
and version, and a rule written against one is wrong elsewhere. Select this
network only where the runtime can create a session with a chosen model and task
and transfer a target state to it. Both are observable the first time a role is
created.

Where a project keeps notes on what its runtime actually did, they belong in a
dated environment record rather than in these rules, and they are observations
with a date and a scope — not a schema this protocol depends on.

## What this module does not own

- Whether the work earns this structure: `capability-routing.md`.
- Cycle counting and the stop rule: `failure-and-debug.md`.
- Evidence shape: `packets.md`.
- Map checkpoints: `codebase-map.md`.
- Escalating past the repository: `research-integration.md`.

Nothing here pushes a message outside the network; the Lead's written report is
what reaches the Owner and Claude.
