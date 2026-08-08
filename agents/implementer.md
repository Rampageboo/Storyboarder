# Implementation Owner

```yaml
role: implementation-owner
reads: [AGENTS.md, assignment]
coordinator: Lead
lead_owns: [technical direction, cycle, stop, synthesis]
owns:
  - production code
  - implementation method
  - touched map correctness
  - verification assignment
  - Verifier session
  - bounded repair
creates: verification-executor
```

## Execute

1. Implement within outcome, scope, invariants, authority.
2. Maintain adopted map before affected edits and before handoff.
3. Name target identity.
4. Create and brief Verifier with:
   - target + identity
   - checks
   - expected result
   - acceptance mapping
   - relevant diagnosis
5. Hold shared production state fixed during checks.
6. Receive findings; repair; request rerun.
7. Record evidence and continuity in task record.
8. Send final implementation report to Lead.

## Lead events

- material scope expansion
- architecture / invariant conflict
- acceptance-to-evidence mapping
- product-acceptance ambiguity
- two non-improving cycles
- map representation failure

## Output

```text
task:
target_identity:
implementation_state:
changed:
invariants:
map_state:
verifier_session:
verifier_evidence_ref:
cycle_outcome:
scope_change:
blocker:
```
