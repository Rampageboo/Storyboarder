# Engineering Packets

Use a packet only when work crosses hosts, needs formal review, or requires a
durable handoff. Ordinary Owner conversation should remain natural and concise.
Omit fields that do not affect action or verification.

Implementation, review, executed verification, and integration acceptance are
separate claims. When one host performs several, name that collapse; for
example: `integration acceptance: self-accepted, no independent verifier`.
Never present self-acceptance as independent verification.

## Brief

```text
Goal and required outcome:
Scope, constraints, and protected behavior:
Acceptance criteria and validation:
Authority, permissions, and important risks:
Repository/Git state and relevant context:
```

## Handoff

```text
From/to; task and revision:
Completed and remaining work:
Files/repository state and authority transferred:
Evidence, failures, risks, and freshness limits:
Receiver: accepted / narrowed / rejected
```

## Decision or failure

```text
Problem and evidence:
Options and consequences:
Recommendation:
Can continue safely without a decision: yes/no
```

## Implementation or review evidence

```text
Behavior and files changed:
Commands/tests/manual checks and exact results:
Not run or not verified:
Material findings, risks, and deviations:
Git/handoff state:
Review / verification / acceptance state, when assigned:
```

## Owner report

`OWNER_HANDBOOK.md` defines what an Owner report answers. Mention model, role,
packet IDs, hashes, map state, or Project Context only when they materially
affected the task.

Rare context, effort-upgrade, parallel-lease, and routing-evaluation records
live in `packets-extended.md`.
