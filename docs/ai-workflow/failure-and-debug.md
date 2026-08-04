# Failure Resolution and Codex Debug

Read this module for repeated failure, blocked validation, or an unresponsive
Codex integration.

Read the exact error, inspect the relevant path, make a bounded repair, and
rerun the failing check. If the same approach is not producing new evidence,
change approach or stop with a concise Failure Packet. Escalate earlier when
the fix requires a product, architecture, security, migration, or data-risk
decision.

If validation cannot run, report the command, blocker, reasoning performed, and
remaining uncertainty. External research may help with missing knowledge but
does not replace reproduction or validation.

For Codex integration failures, use `docs/codex-debug-solution.md` when it
matches the environment; otherwise use the same evidence-driven failure flow.
Do not ask the Owner to diagnose a technical failure.
