# Communication Packets

Use only the packet triggered by the task. Keep evidence compressed and fields
honest. In `owner-direct`, mark Claude-only fields `not applicable — owner-direct`.

## Received Brief

Use when Codex receives a routed implementation task.

```text
Received brief
- Goal:
- Task coordination mode: claude-routed / owner-direct
- Execution target: Spark / Codex / not available / not applicable
- Capability routing:
  - Sub-agents: allowed / required / not useful / prohibited
  - Specialized tools expected:
  - Independent verification expected: yes/no
  - Delegation autonomy: bounded / explicit-only
- Codex MCP thread action: new / reply / not applicable
- Assigned effort: minimal / low / medium / high / xhigh / not applicable
- Effort override status: verified / assumed / unknown / not applicable
- Scope:
- Non-goals:
- Files likely to change:
- Risk areas:
- Validation expected:
- Ambiguities found: none blocking / ...
```

## Context Packet

Use for high/xhigh tasks or unclear ownership before broad implementation.

```text
Context Packet
- Task understanding:
- Files inspected:
- Relevant entry points:
- Current behavior:
- State owners:
- Risk-sensitive paths:
- Existing tests:
- Proposed implementation path:
- Decisions needed from Claude:
- Files Claude should read, if any:
```

Claude decides from this packet first and reads only minimal risk-relevant code.

## Decision Request

```text
Decision Request
- Context:
- Problem:
- Options:
  1.
  2.
  3.
- Recommended option:
- Reason:
- Consequence if wrong:
- Can continue without decision: yes/no
- Owner input needed: yes/no
```

In `owner-direct`, use this to recommend Claude routing for a material category
B decision; ask the Owner directly only for category C.

## Failure Packet

```text
Failure Packet
- Task:
- Execution target:
- Assigned effort:
- Failing command:
- Exact error:
- What I tried:
  1.
  2.
  3.
- Current hypothesis:
- Files likely involved:
- Options:
  A.
  B.
  C.
- Recommended option:
- Owner input needed: yes/no
```

## Effort Upgrade Handoff Packet

```text
Effort Upgrade Handoff Packet
- Previous thread ID:
- Previous execution target: Spark / Codex / not available
- Previous configured effort: verified / assumed / unknown
- Original task:
- Git execution environment:
  - Host/environment:
  - MCP client:
  - Git execution mode: codex-git / claude-git
  - Last verified:
- Repository branch and HEAD: supplied by Codex / supplied by Claude / unknown
- Files inspected:
- Files changed:
- Work completed:
- Work remaining:
- Important design choices:
- Open Decision Requests:
- Tests run and exact results:
- Current failures or blockers:
- Uncommitted changes: supplied by Codex / supplied by Claude / unknown
- Relevant commit hashes: supplied by Codex / supplied by Claude / none
- Minimal context the new thread must read:
```

In `claude-git`, Claude supplies all Git metadata. The new thread consumes this
packet before inspecting broadly and does not repeat completed work unless the
handoff proves stale.

## Review Packet

```text
Review Packet
- Execution target:
- Effort used:
- Original goal:
- Summary of implementation:
- Files changed:
- Behavior changed:
- Behavior intentionally unchanged:
- Risk areas:
- Exact diff focus:
- Tests run and exact results:
- Manual validation:
- Not validated:
- Deviations from active brief:
- Decision requests still open:
- Minimal files/functions Claude should inspect:
- Specific questions for Claude:
```

Do not request a repository-wide review unless the change is genuinely
repository-wide.

## Final Report

Every completed implementation task includes both sections.

```text
Owner Summary
- What changed:
- Why it matters:
- What was tested:
- Is it safe to use now:
- Anything the Owner must decide:
```

```text
Technical Summary
- Completed:
- Task coordination mode: claude-routed / owner-direct
- Execution target: Spark / Codex / not available / not applicable
- Capabilities used:
  - Sub-agents:
  - Specialized tools:
  - Independent verification:
- Codex MCP thread action: new / reply / not applicable
- Codex thread ID:
- Configured effort: verified / assumed / unknown / not applicable
- Changed files:
- Important design choices:
- Deviations from active brief:
- Validation run:
- Validation result:
- Manual validation:
- Not validated:
- Git execution environment:
  - Host/environment:
  - MCP client:
  - Git execution mode: codex-git / claude-git / unknown
  - Last verified:
- Git owner for this task:
- Commit or working-tree handoff status:
- Push status:
- Known risks:
- Next recommended action:
```

```text
PROJECTCONTEXT Delta
- Add:
- Update:
- Remove as stale:
- No durable change: yes/no
```

In `claude-git`, report ownership rather than claiming Git actions, for example:

```text
Commit: not attempted — Claude-owned
Push status: not attempted — Claude-owned
Working-tree handoff: validated changes ready for Claude review
```

Codex proposes the context delta but applies it only after explicit delegation.
Claude accepts, modifies, or rejects it in a routed round. Never claim all tests
passed unless the named tests were run and passed.
