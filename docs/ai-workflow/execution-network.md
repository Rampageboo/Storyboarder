# Execution Network

```yaml
side: Codex execution
activate: separate implementation + verification contexts
input: Owner-carried execution handoff
reads:
  Lead: [AGENTS.md, this module, agents/lead.md, assignment]
  Implementer: [AGENTS.md, agents/implementer.md, assignment]
  Verifier: [AGENTS.md, agents/verifier.md, assignment]
```

## Flow

```text
create: Owner -> Lead -> Implementer -> Verifier
loop:   Implementer <-> Verifier
return: Implementer + Verifier -> Lead -> Owner
```

1. Lead creates and briefs Implementer.
2. Implementer names target state. Implementer creates and briefs Verifier.
3. Implementer and Verifier exchange findings, repairs, and reruns.
4. Both report to Lead; Lead returns result|blocked handoff to Owner.

## Authority

| Actor | Owns |
|---|---|
| Owner | cross-side handoff, final acceptance |
| Lead | direction, milestones, hypothesis, cycle, stop, synthesis |
| Implementer | code, method, map correctness, Verifier assignment, repair |
| Verifier | checks, findings, evidence |

Product assessment and next-step direction occur outside this network after
Owner returns the handoff.

## Session contract

Create each role session with `model + effort + opening assignment`. Assignment
carries role, authority, outcome, scope, target, evidence, stop conditions, and
recipients. Model and effort remain fixed for the session.

## Round boundary

Lead records execution issues in the handoff. Completion or stop returns the
handoff to Owner and ends the round. Next direction enters as a new
Owner-carried handoff.

## State invariant

Implementer names target identity before verification. Verifier confirms the
same identity before and after checks. Shared mutable workspace: production code
remains fixed during checks. Isolated target: artifact/workspace identity binds
evidence.

```text
identity unconfirmed -> behavioural observation
identity changed     -> rerun
```

## Evidence semantics

Verifier knowledge of Implementer diagnosis supports executed-check evidence.
Diagnosis-independent review requires separate framing. Task record stores
durable evidence and continuity.

## Lead events

- milestone / completion
- scope expansion
- architecture / invariant conflict
- acceptance-to-evidence mapping
- brief-boundary / product-acceptance question
- two non-improving cycles
- third failed cycle / stop
- acceptance-relevant evidence limitation

## Runtime contract

Required: role-session creation with model, effort, opening task; cross-session
assignment, handoff, continuation. Cross-side transfer is Owner-carried.

References: `capability-routing.md`, `failure-and-debug.md`, `packets.md`,
`codebase-map.md`, `research-integration.md`.
