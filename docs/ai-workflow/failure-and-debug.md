# Failure Resolution and Codex Debug

Read this module for repeated failure, blocked validation, or an unresponsive
Codex integration.

Read the exact error, inspect the relevant path, make a bounded repair, and
rerun the failing check. If the same approach is not producing new evidence,
change approach, commission research under `research-integration.md`, or stop
with a Failure Packet. Escalate earlier when the fix requires a product,
architecture, security, migration, or data-risk decision.

If validation cannot run, report the command, blocker, reasoning performed, and
remaining uncertainty. External research may help with missing knowledge but
does not replace reproduction or validation.

## Qualifying evidence

Outcome evidence shows that a test passes, a symptom stopped, or an output was
produced. It does not by itself prove why. Causal evidence supports a mechanism;
measurement evidence supports a number under stated conditions. Label the
claim at the level the evidence actually supports.

Before making a material root-cause claim that will enter durable documents,
drive structural change, reject another credible solution, guide recurring
incidents, or rests mainly on "the symptom disappeared after this change":

- state what the candidate explanation predicts;
- name a result that would falsify it;
- check at least one credible competing explanation; and
- say whether the evidence establishes symptom removal or the mechanism.

For performance, time, memory, VRAM, or throughput claims, record the build
mode, machine or material hardware, concurrent load, cold/warm state, sample or
repeat count, and statistic used. An uncontrolled measurement is an
observation, not a regression claim.

For Codex integration failures, use `docs/codex-debug-solution.md` when it
matches the environment; otherwise use the same evidence-driven failure flow.
Do not ask the Owner to diagnose a technical failure.
