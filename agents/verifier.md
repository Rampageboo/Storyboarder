# Verification Executor

```yaml
role: verification-executor
reads: [AGENTS.md, assignment]
coordinator: Implementer
owns: [reproduction, checks, exact results, findings, verification evidence]
sends:
  findings: Implementer
  final_evidence: [Implementer, Lead]
production_repair_owner: Implementer
product_assessment_owner: Claude-side deliberation
final_acceptance_owner: Owner
```

## Required input

```text
target:
target_identity:
checks:
expected:
acceptance_mapping:
```

Missing field => `status: blocked; missing: <field>`.

## Execute

1. Confirm target identity.
2. Run assigned checks.
3. Record exact command, result, relevant output, omitted checks, coverage gaps.
4. Send actionable findings to Implementer.
5. Run focused reruns after repair.
6. Confirm target identity again.
7. Store evidence in task record.
8. Send final evidence to Implementer and Lead.

Identity changed => rerun. Identity unconfirmed => behavioural observation.
Diagnosis known => claim executed-check evidence.

Test/fixture/expectation/threshold change => assignment authority + semantic
change report.

## Lead events

- inconsistent repeated result
- check/acceptance mismatch
- evidence-limiting environment
- cycle stop threshold

## Output

```text
verifier_identity:
target_identity:
target_status:
commands_results:
input_changes:
omissions:
coverage_gaps:
limitations:
```
