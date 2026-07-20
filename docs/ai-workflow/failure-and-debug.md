# Failure Resolution and Codex Debug

Read this module for repeated implementation failures, blocked validation, or
idle/unresponsive Codex MCP behavior.

## Focused repair

On build, test, lint, type, packaging, or runtime failure:

1. read the exact error;
2. identify the likely root cause;
3. inspect directly relevant files;
4. apply a minimal fix;
5. rerun the failing command.

Codex may perform up to three focused repair cycles for the same failure. Then
return a Failure Packet. Escalate earlier for architecture contradiction, scope
change, conflicting tests, data-loss/security/migration risk, destructive
behavior, or materially different technical options.

If validation cannot run, report the exact command, exact blocker, reasoning
performed, and what remains unverified.

## Codex MCP idle or failure

1. If `docs/codex-debug-solution.md` exists and applies to the current MCP
   environment, read and follow it first.
2. If it is missing, stale, or does not cover the failure, use the Failure
   Packet workflow.
3. After resolving a repeatable MCP problem, update that debug document only
   with verified evidence, not speculation.

Claude chooses continue, change approach, narrow scope, or stop. The Owner is
not asked to interpret technical failures.

Use Failure Packet templates from `packets.md`.
