# Engineering Packets

Use a packet only when work crosses hosts, needs formal review, or requires a
durable handoff. Omit fields that do not affect action or verification.

Packet shapes describe final state or evidence when a formal record is needed.
They are not mandatory intermediate forms and must not prescribe the receiver's
reasoning, implementation sequence, or expected conclusion.

Implementation, review, executed verification, and integration acceptance are
separate claims. When one host performs several, say which ones it performed.
Never present self-acceptance as independent verification.

## Brief

A formal Brief Packet uses the minimum sufficient contract in
`capability-routing.md`.
Packet metadata such as sender, receiver, revision, or authority is added only
when it materially affects execution or acceptance; it does not create a second
brief schema.

## Handoff

```text
Task and revision:
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
