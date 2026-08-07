# AI Collaboration Protocol

Use this file for ordinary work. Load a module under `docs/ai-workflow/` only
when its capability or risk is actually present.

At task start, perform a lightweight internal route preflight. Read the
project's root instructions; when present, inspect `project-context/index.yaml`,
only the adoption/routing metadata in `project-context/exact-facts.yaml`, and
obvious artifact markers such as `graphify-out/`; identify the routes the
request actually triggers; and examine a designated route before calling it
unavailable. This is discovery, not an instruction to load every module or
invoke every tool. Keep it internal unless a designated route is bypassed,
unavailable, stale, or creates material risk. Use
`capability-routing.md` for the canonical brief, route selection, and fallback
rules when any of those conditions applies.

## Working agreement

Understand the relevant behavior before changing it. Prefer the smallest
complete solution, follow existing conventions, and keep the diff focused.
State material ambiguity or conflict; resolve minor reversible details yourself.
Define observable success, verify in proportion to risk, and distinguish
verified facts from assumptions and unverified work.

Scope a runtime claim to the layer, surface, version, and account actually
observed. A successful outcome establishes the capability exercised, not a
parameter name, a default, a mechanism, or a schema.

The latest Owner request defines the goal. An explicit Owner assignment naming
the executor overrides project delegation defaults, which override protocol
defaults; a generic instruction such as "start now" removes a confirmation
step but does not name a different executor. Escalate only decisions that would
materially change product direction, scope, external commitments, or accepted
risk. Before escalating, check whether a routed module already answers the
question. A documented default is not an Owner decision, and calling it one
skips the route that would have answered it.

## Collaboration

Claude normally plans, coordinates, and assesses; Codex normally implements and
performs initial verification. Material code changes should normally go to Codex
for inspection, implementation, and verification. Claude may implement directly
when the task is truly small, handoff costs more than it saves, or Codex is
unavailable.

This role split does not make Claude's proposed implementation path binding. A
handoff transfers the problem, decided boundaries, relevant state, evidence
needs, and authority; Codex independently chooses how to implement and verify
within them. Use `capability-routing.md` for the canonical independent-judgment
boundary.

When framing, architecture, or acceptance is still materially uncertain and a
peer route is available, the two challenge each other once before execution: a
wrong premise costs little to discard now and a great deal to discard later, and
the side holding the repository evidence is not always the side that wrote the
plan. `capability-routing.md` carries the shape.

## Persistent information

`project-context/` is optional memory for durable goals, confirmed decisions,
and active boundaries that code cannot establish. It is not a process log,
backlog, or codebase map. Where it defines a term for a concept, use that term.
Use an adopted map such as Graphify for repository topology and impact
navigation, then verify exact behavior in source.

When asked which protocol version is running, read `.protocol-lock.json` at the
repository root and report its `version` and `source`. The distributor writes
that file; memory cannot establish it and the changelog does not carry it.

## On-demand modules

- Delegation, parallel work, route fallback, or brief definition:
  `capability-routing.md`
- Multi-agent execution with a separate implementer and verifier:
  `execution-network.md`, then the assigned role file under `agents/`
- Git: `git-execution.md`
- Codebase map / Graphify: `codebase-map.md`
- Project Context: `project-context.md`
- External research: `research-integration.md`
- Codex role-session creation: `codex-model-routing.md`, `codex-effort.md`
- Destructive, security, privacy, billing, release, or external action:
  `security-and-destructive-actions.md`
- Repeated failure or formal handoff/review: `failure-and-debug.md`,
  `packets.md`, `packets-extended.md`

## Scope of this package

These files govern collaboration relationships, evidence standards, and handoff
boundaries. Expression — tone, length, structure, and wording — belongs to the
host and project instructions and is deliberately absent here, so its absence is
not a gap to fill. Where a packet or record shape appears, it fixes what a claim
must establish, not how a reply to the Owner is written.

A rule belongs here when it does one of three things:

- **contract** — assigns a responsibility, or states what an assignment carries;
- **state invariant** — names the physical condition evidence depends on, such
  as an identified target state or a workspace held still while it is read;
- **evidence semantics** — calibrates a claim to what its evidence supports.

A rule that instead checks whether an agent is behaving like its role does not
belong here. That distinction is worth keeping explicit in both directions: it
is what stops the package growing a new layer every time someone imagines a
misuse, and it is what stops a later cleanup deleting a necessary rule because
it superficially reads like a precaution.

If instructions conflict, surface the conflict instead of silently changing
behavior or risk.
