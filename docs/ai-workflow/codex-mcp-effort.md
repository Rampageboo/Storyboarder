# Codex MCP Effort and Thread Lifecycle

Read this module when creating or continuing a Codex MCP thread, selecting
reasoning effort, or upgrading effort.

## Execution target

Select the lowest adequate execution target before selecting effort:

- `Spark`: small, bounded, low-risk edits where low latency matters more than
  deep repository reasoning. Good candidates include one function, one compiler
  error, a Blueprint node tweak, a button or shortcut, a prompt edit, local
  renames/formatting, or localized logic across about 1-3 files.
- `Codex`: broad or deep work that needs sustained planning, repository-wide
  context, many files, architectural refactors, complete feature
  implementation, asset/model understanding, or coordination across tools such
  as MCP, Unreal Engine, Blender, GitHub, or external services.

Spark is OpenAI's **GPT-5.3-Codex-Spark** model: a fast, low-latency,
lightweight variant of Codex (real-time coding, makes minimal targeted edits,
does not run tests by default). It is not a separate server or tool — invoke it
through the same Codex MCP `codex` tool by overriding the model, e.g.
`model: "gpt-5.3-codex-spark"`. `codex-reply` cannot change the model, so start
a new thread to switch to or from Spark.

Availability is model- and account-dependent. Verify it per execution
environment the way effort is verified: a probe call that is accepted and
returns output — rather than a model-not-found or no-access error — confirms
Spark is reachable. If the account's Codex backend does not expose the model,
mark Spark `not available` and use ordinary Codex with the lowest adequate
effort. Because Spark makes minimal edits and skips tests by default, always
pair it with explicit review and validation of its output.

If a Spark task expands into cross-file reasoning, repeated failures, unclear
requirements, shared state risk, or material architecture/public-contract/
persistence/security impact, upgrade or reroute it to ordinary Codex instead
of stretching Spark beyond its intended scope.

For the full Spark versus higher-capability Codex selection rules, escalation
triggers, handoff contents, Spark task brief shape, result requirements, Claude
acceptance checks, and parallel Spark worker limits, read
`docs/ai-workflow/codex-model-routing.md`.

## Supported effort

```text
minimal | low | medium | high | xhigh
```

`xhigh` is model-dependent. Never use `max`. Use the lowest adequate effort:

- `minimal` / `low`: mechanical named-file edits and trivial documentation.
- `medium`: routine implementation, focused tests, straightforward fixes.
- `high`: difficult debugging, multi-file workflows, persistence, API/schema,
  concurrency, security-sensitive work, or bounded refactors.
- `xhigh`: unusually difficult reasoning, ambiguous root cause, high-impact
  architecture/migration, severe risk, or repeated failed approaches.

Do not over-scan minimal/low/medium tasks or under-investigate high/xhigh tasks.

## Correct new-thread configuration

Effort is set when `codex` creates a new thread:

```json
{
  "prompt": "Implement the requested feature.",
  "cwd": "C:\\path\\to\\project",
  "config": {
    "model_reasoning_effort": "high"
  }
}
```

Do not use a top-level `effort` field. Prompt text describing an effort does
not prove that runtime configuration changed. When call details are available,
verify an equivalent `config.model_reasoning_effort` payload. If verification
is unavailable, report configured effort as `unknown`.

## Reply behavior

`codex-reply` continues an existing thread using its `threadId`. It cannot
override model, config, or reasoning effort. Never claim effort changed during
a reply.

## Effort upgrade

When current effort is insufficient:

1. Ask the existing thread for an Effort Upgrade Handoff Packet.
2. Start a new thread with the required nested config.
3. Supply the handoff, `PROJECTCONTEXT.md`, repository/Git ownership state,
   completed and remaining work, tests, failures, commits, and decisions.
4. Tell the new thread not to repeat completed work.
5. Record the new thread ID and effort-verification status.

Prefer one MCP server with per-new-thread configuration. Separate permanent
servers are only a fallback when the client cannot reliably pass nested config.

Use the packet template in `packets.md`.
