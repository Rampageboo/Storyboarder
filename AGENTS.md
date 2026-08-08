# AI Collaboration Protocol

Ordinary work loads this file. Load a module under `docs/ai-workflow/` only
when its capability or risk is triggered.

## Start

Run an internal route preflight:

1. Read project-root instructions.
2. Inspect `project-context/index.yaml`, adoption/routing metadata in
   `project-context/exact-facts.yaml`, and visible route markers such as
   `graphify-out/`.
3. Identify triggered routes and examine each route with its required inputs.

Report the preflight when a designated route is bypassed, unavailable, stale,
or materially risky. `capability-routing.md` defines route selection, fallback,
and handoff contracts.

## Work contract

- Understand affected behavior; produce the smallest complete change; follow
  project conventions; keep scope focused.
- Resolve minor reversible ambiguity. Surface material ambiguity or conflict.
- Define observable success. Verify in proportion to risk. Label assumptions,
  verified facts, and unverified work.
- Scope runtime claims to the observed layer, surface, version, and account. An
  observed outcome establishes only the capability exercised.

Owner authority:

```text
goal: latest Owner request
executor: explicit Owner assignment > project delegation > protocol default
generic start instruction: removes confirmation only
escalation: product direction | material scope | external commitment | accepted risk
```

Check routed modules before escalation. Documented defaults remain route
answers; Owner decisions require Owner input.

## Collaboration

Default: Claude plans, coordinates, and assesses; Codex implements and performs
initial verification. Claude may retain work when it is small, handoff cost
dominates, or Codex is unavailable.

A handoff carries outcome, decided boundaries, relevant state, evidence needs,
and authority. Codex selects implementation and verification methods within
that contract. `capability-routing.md` defines independent judgment.

A Claude-side round produces the execution handoff. Owner supplies goal,
authority, and product decisions. When material uncertainty remains in framing,
architecture, or acceptance, Claude and the Codex CLI peer run one evidence-led
review. Owner carries the handoff into Codex execution and assigns Lead.

## Persistent information

`project-context/` stores durable goals, confirmed decisions, and active
boundaries unavailable from code. Adopt its terminology. Repository topology
belongs to an adopted map such as Graphify; verify exact behavior in source.

Report protocol version from root `.protocol-lock.json` fields `version` and
`source`.

## On-demand modules

- delegation, parallelism, fallback, handoff: `capability-routing.md`
- Lead/Implementer/Verifier network: Lead loads `execution-network.md` and
  `agents/lead.md`; Implementer and Verifier load their role file and assignment
- Git: `git-execution.md`
- map / Graphify: `codebase-map.md`
- Project Context: `project-context.md`
- external research: `research-integration.md`
- Codex role-session creation: `codex-model-routing.md`, `codex-effort.md`
- destructive, security, privacy, billing, release, external action:
  `security-and-destructive-actions.md`
- repeated failure or formal evidence: `failure-and-debug.md`, `packets.md`,
  `packets-extended.md`

## Package boundary

Runtime rules are limited to:

- **contract** — assigns a responsibility, or states what an assignment carries;
- **state invariant** — names the physical condition evidence depends on, such
  as an identified target state or a workspace held still while it is read;
- **evidence semantics** — calibrates a claim to what its evidence supports.

Only those three belong in the runtime protocol. A rule that checks whether an
agent is behaving like its role does not, however reasonable the misuse it
imagines.

Tone, length, structure, and wording belong to host/project instructions.
Packet shapes define claim content. Instruction conflicts are surfaced.
