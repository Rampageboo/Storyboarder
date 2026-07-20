# Codex Debug Solution

## Applicability

This document records verified failures from the `codex-user` MCP environment
used on 2026-07-09/10. Apply a symptom only when the current MCP client, tool
shape, and observed failure match. It does not override `AGENTS.md` or the
current environment's verified Git/effort capabilities. For generic failure
routing, read `docs/ai-workflow/failure-and-debug.md` first.

When Codex (the `codex-user` MCP tool) is not working / not responding / seems
idle, diagnose by SYMPTOM. These are all real failures that happened on
2026-07-09/10; every fix below was verified working. Work top to bottom — the
layers mask each other.

## Diagnosis method (use this before guessing)

- **Control test**: send a trivial call first —
  `prompt: "Reply with exactly: PING OK"`, `approval-policy: "never"`,
  `sandbox: "read-only"`. If PING passes but the real task fails, the problem
  is the task's content or duration, not the channel.
- **Ground truth for what actually ran**: Codex session rollouts at
  `~/.codex/sessions/<yyyy>/<mm>/<dd>/rollout-*.jsonl`. The `turn_context`
  line shows the real `model` and `effort` per turn; `token_count` events show
  real usage; `patch_apply_end` events prove it was editing files.
- **Check live env vars** in a PowerShell tool call:
  `$env:MCP_TOOL_TIMEOUT`, `$env:CLAUDE_CODE_MCP_TOOL_IDLE_TIMEOUT`.
  Settings-file env changes only apply after a window reload.
- A user message typed while a sync MCP call is pending **cancels the call**
  ("request interrupted by user"). Long runs require leaving the conversation
  untouched. Do not confuse this with a real failure.

## Symptom 1: call is rejected INSTANTLY, user saw no permission prompt

Cause: missing permission allow rules; the VSCode extension may fail to render
the permission prompt, so the pending call dies silently.

Fix: in `~/.claude/settings.json` add
`permissions.allow: ["mcp__codex-user__codex", "mcp__codex-user__codex-reply"]`,
then **reload the window**. Claude cannot add these itself (self-modification
is blocked) — the owner must edit the file or use `/permissions`.

## Symptom 2: PING passes, but the full brief is rejected instantly

Cause: the auto-mode safety classifier silently blocks briefs whose content
reads as "autonomous agent that commits/pushes" (git commit/push instructions,
"never force-push", etc.).

Fix for this affected host: strip all Git instructions from the brief and use
`claude-git`. Codex leaves changes in the working tree; Claude reviews and owns
Git. Record this as an environment-specific mode according to
`docs/ai-workflow/git-execution.md`; do not assume other hosts behave the same.

## Symptom 3: task runs ~30 min, then dies with "sent no response or progress for 1800s"

Cause: MCP idle timeout. Codex streams no progress to the host, so a long
build/think looks dead and the host kills it — even mid-work.

Fix: `~/.claude/settings.json` → `env.CLAUDE_CODE_MCP_TOOL_IDLE_TIMEOUT = "0"`
(disabled; owner-approved). Reload window. Stuck-detection is then manual:
check the session rollout file's timestamps or the codex process before ever
cancelling. Owner directive: never kill a long run without evidence it is
actually stuck.

## Symptom 4: task dies after hours with a plain timeout

Cause: MCP total-duration cap.

Fix: `~/.claude/settings.json` → `env.MCP_TOOL_TIMEOUT = "14400000"` (4 h
fuse) and `MCP_TIMEOUT = "120000"` (server startup). Reload window.

## Symptom 5: Codex runs but is slow, shallow, low token usage

Cause in the verified `codex-user` tool shape: reasoning effort. That tool
exposed no effort/model parameters, so writing "effort: xhigh" in the brief did
nothing. Its effective knob was `~/.codex/config.toml` →
`model_reasoning_effort` (and `model`).

Fix for that tool shape: set the desired effort in config.toml, reload the
window so the MCP server restarts, then verify the new rollout's `turn_context`.
If the current MCP tool accepts nested `config.model_reasoning_effort`, follow
`docs/ai-workflow/codex-mcp-effort.md` instead. Never claim the configured
effort changed without current-environment evidence. Signature of the original
problem: a long run whose `reasoning_output_tokens` was tiny while it
mechanically applied patches.

## Symptom 6: `codex exec` CLI hangs at "Reading additional input from stdin..."

Cause: no TTY in tool shells.

Fix: pipe the prompt: `"..." | codex exec ... -` (note the trailing `-`).
(The owner prefers the MCP channel for real tasks; CLI is for probes like
validating a model id or effort value.)

## Working call shape (known good)

- `mcp__codex-user__codex`: `prompt` (no git instructions),
  `cwd`, `approval-policy: "never"`, `sandbox: "read-only"` (investigation) or
  `"workspace-write"` (implementation).
- `mcp__codex-user__codex-reply` with the returned `threadId` continues a
  session with context intact. Threads may not survive a Codex CLI upgrade
  ("Session not found") — restart with a fresh brief that tells Codex to
  inspect the working tree first.
