# Capability and Host Routing

Load for delegation, parallel work, specialized capability, route failure, or
independent review.

## Handoff contract

Claude, Codex, and Researcher are reasoning systems. Role, host, and authority
remain separate.

A handoff carries the minimum sufficient contract:

```yaml
outcome: <desired result>
facts_constraints: <confirmed>
state: <repository|execution identity>
acceptance_evidence: <required>
authority_risk: <boundary>
```

Add scope, invariants, exclusions, and stop conditions when material. Specify
outcome and boundaries; receiver owns method and conclusion. Omit immaterial
fields.

Receiver treatment of sender input:

```text
binding decision -> obey within authority; surface contradiction
fact             -> verify when material
suggestion       -> hypothesis
suspected cause  -> hypothesis
proposed step    -> candidate method
referenced file  -> candidate evidence
```

Add detail when it preserves an invariant, prevents a concrete error, or
supplies expensive-to-recover evidence.

## Defaults and selection

```text
Claude: task framing | coordination | integration assessment
Codex:  implementation | initial verification
executor precedence: explicit Owner assignment > project rule > protocol default
```

An explicit assignment changes executor, preserving permissions and evidence
requirements. Generic start language removes confirmation only. Substitute a
host when capability, context, availability, or handoff cost requires it; grant
task-scoped authority.

Delegate independently bounded work or work requiring another capability. Keep
small, sequential, or tightly coupled work together. The coordinating host
integrates one report.

## Structure by risk

Use separate implementation/verification contexts, formal packets, and map
checkpoints when risk justifies their cost. Strong triggers for separation:

- architecture or public interface;
- dependency, schema, or migration;
- security, authorization, privacy, or destructive action;
- multi-component impact;
- no deterministic focused check;
- mapped relationship change.

Self-verification remains valid when a separate context is unavailable and the
report identifies it. Acceptance criteria may require separation. Task size is
not the selector: materiality and evidence risk are. Record the selected path.

## Route state

For a project/task-designated capability, channel, map, or data source:

```text
examine route + inputs
  -> fresh: use
  -> refreshable at reasonable cost: refresh, use
  -> evidence-equivalent fallback: declare, use
  -> weakened evidence or exceeded authority: blocked
```

Ordinary route failures stay with the executor. Owner receives decisions that
meet the boundary in `OWNER_HANDBOOK.md`.

## Claude-side peer review

Trigger: material uncertainty in framing, architecture, or acceptance and an
available peer route.

Run before execution and, where possible, before acceptance is settled.

Input: outcome, evidence, constraints, draft acceptance, risks, open questions,
open conclusion.

Peer returns: evidence-supported claims, unverified assumptions, simplest
credible approach, material alternatives, falsifiable conditions.

The Claude-side peer discussion settles the execution handoff. Unresolved
product, risk, or cost choices remain Owner decisions; carry disagreement with
evidence and decision boundary. One exchange is normal; continue only for a
remaining material issue. A settled handoff closes the round.

## Delegation gate

Proceed with confirmed files, tools, permissions, required inputs, and return
channel. Receiver reads the handoff once: it must stand alone and preserve room
for an evidence-supported contrary conclusion.

## Parallelism and judgment

Parallel writers use non-overlapping scopes or isolated alternatives. Name one
integration owner. Scope overlap, base drift, or isolation loss ends the
affected worker. Use the lease in `packets-extended.md` when coordination needs
a durable record.

Independent review input carries evidence, question, repository state, exact
revision/diff, constraints, and test results. Sender preference is included only
when proposal evaluation is the task.

Approved implementation input carries the binding decision and invariants. The
receiver follows them and reports contradictions, unsafe assumptions,
unnecessary complexity, or contrary evidence.

External Research Skill contract:

```yaml
route: research-integration.md
output: evidence
working_tree_owner: engineering executor
completion_owner: engineering coordinator
```
