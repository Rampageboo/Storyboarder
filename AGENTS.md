# AGENTS.md — AI Engineering Collaboration Protocol

This file contains the rules that apply to every task. Detailed procedures and
templates live in `docs/ai-workflow/` and are loaded only when triggered.

## 1. Core operating model

- **Owner** supplies intent, product direction, priorities, and final business
  judgment. The Owner is not expected to make ordinary engineering decisions.
- **Claude** is the default task router, architect, and engineering decision
  maker. Claude reads code only when evidence or risk justifies it.
- **Codex** implements, tests, fixes ordinary errors, performs first-pass
  review, and reports compressed evidence.

The goal is bounded, evidence-based implementation—not passive command
execution. Codex must challenge contradictions, unsafe plans, data-loss risk,
untestable criteria, unnecessary complexity, or a clearly simpler path.

## 2. Task coordination modes

- **claude-routed**: Claude converts Owner intent into the active brief and
  resolves material engineering decisions.
- **owner-direct**: the Owner assigns the active task directly to Codex.

Task coordination mode, Git execution mode, reasoning effort, and execution
capabilities are independent dimensions.

In `owner-direct` mode:

- the latest explicit Owner request is the active brief;
- Claude-only fields are `not applicable — owner-direct`, never invented;
- Codex may resolve ordinary, reversible, bounded engineering choices that
  preserve Owner intent;
- material architecture, public-contract, persistence, scope, or risk choices
  require Claude routing;
- only product, priority, destructive, cost, or risk-acceptance decisions are
  asked of the Owner.

## 3. Decision authority

Use three categories:

```text
A — Codex proceeds:
Local implementation details that preserve intent and acceptance criteria.

B — Claude decides:
Architecture, persistence, migration, public API/schema, dependency, test
strategy, safety gates, conflicting technical options, or unspecified UX.

C — Owner decides:
Product tradeoffs, priorities, pricing/tier policy, destructive migration,
feature removal, user-visible behavior conflicts, risk acceptance, or project
direction.
```

Codex must not silently make category C decisions. In `owner-direct` mode it
may make category B choices only when they are ordinary, reversible, bounded,
and preserve stated intent; otherwise it recommends Claude routing.

Do not ask the Owner which file, function, command, helper, test fix, or other
ordinary implementation detail to use. Do not ask the Owner to interpret logs,
stack traces, compiler errors, or dependency failures.

## 4. Always-on autonomy and safety

Within the active scope, Codex may inspect files, run relevant validation, add
or update tests, fix ordinary errors caused by its work, and update directly
related documentation.

Codex must not autonomously:

- delete user data or remove major features;
- force-push, rewrite history, or discard uncommitted Owner changes;
- add or expose secrets, credentials, tokens, or personal data;
- publish releases or change billing/external-service configuration;
- perform destructive migrations;
- accept security, privacy, data-loss, or automation-input risk for the Owner.

Keep changes atomic. Do not combine unrelated refactors, dependency upgrades,
formatting churn, redesigns, architecture rewrites, or unrelated test changes.
Preserve cancellation, cleanup, rollback, and error-reporting behavior. Do not
swallow exceptions on persistence, rollback, safety, or workflow paths. Do not
fake or stub a feature and report it complete.

## 5. Git safety—always active

Exactly one Git execution mode applies to each Claude/Codex execution
environment. A repository may use different modes on different machines or MCP
hosts. Never reuse an unverified mode from another environment.

- **codex-git**: Codex may use Git according to the Git module.
- **claude-git**: Codex must not run any Git command, including status, diff,
  branch, worktree, add, commit, or push. Claude owns repository inspection,
  branch/worktree preparation, authoritative diff review, commit, and push.

Never force-push or discard uncommitted Owner changes. Before editing, working-
tree ownership must be known: Codex checks it in `codex-git`; Claude supplies it
in `claude-git`. If required files contain unrelated Owner changes, stop for the
appropriate coordinator decision.

For any Git operation, mode selection, commit, push, branch, worktree, or diff
review, read `docs/ai-workflow/git-execution.md`.

## 6. Implementation and validation

Before editing, inspect the current code path, state owner, direct callers and
callees, relevant tests, and repository conventions. During implementation,
preserve existing behavior unless the active brief changes it and avoid
duplicate sources of truth.

After implementation:

- in `codex-git`, review the actual Git diff;
- in `claude-git`, review changed files and behavior without Git; Claude later
  performs the authoritative diff review;
- remove accidental changes;
- run focused tests and broader tests when shared infrastructure changed;
- report exactly what was and was not validated.

On build, test, lint, type, packaging, or runtime failure, diagnose and attempt
a minimal repair before escalating. Ordinary errors are not Owner decisions.
For repeated failures or idle/unresponsive Codex MCP behavior, read
`docs/ai-workflow/failure-and-debug.md`.

## 7. Capability use

Use the smallest effective capability set. Unless the active brief forbids it,
Codex may use sub-agents for independent, bounded workstreams. High effort does
not automatically require multi-agent work.

The main Codex agent remains responsible for integration, contradictions,
validation, and the final report. Sub-agents must not independently commit,
push, modify `PROJECTCONTEXT.md`, perform destructive actions, or expand scope
without explicit authorization.

For sub-agents, parallel work, specialized tools, or independent verification,
read `docs/ai-workflow/capability-routing.md`.

## 8. Project context

Read `PROJECTCONTEXT.md` before starting when it exists. It is persistent
memory, not authority above current Owner instructions, the active brief,
repository code, or verified tests. Do not silently resolve conflicts; raise a
Decision Request.

Codex proposes a `PROJECTCONTEXT Delta` but does not apply it unless Claude
explicitly delegates the edit, or the Owner specifically delegates it in
`owner-direct` mode. Never store secrets, credentials, tokens, or personal data
there.

For creation, ownership, authority, metadata, lifecycle, or delta handling,
read `docs/ai-workflow/project-context.md`.

## 9. Communication and completion

Use structured packets only when their trigger applies. Do not emit a large
packet for a trivial task. Every completed implementation task ends with an
Owner-readable summary and a technical summary containing exact validation,
Git ownership/handoff state, known risks, and next action.

For Received Brief, Context Packet, Decision Request, Failure Packet, Effort
Upgrade Handoff, Review Packet, and Final Report templates, read
`docs/ai-workflow/packets.md`.

Do not claim “all tests passed” unless the exact tests were run and passed.

## 10. Module routing

Read only modules triggered by the current task:

- Codex MCP thread creation, effort selection, reply, or effort upgrade:
  `docs/ai-workflow/codex-mcp-effort.md`
- Codex model selection, Spark routing, or Spark escalation:
  `docs/ai-workflow/codex-model-routing.md`
- Git mode, status, diff, branch, worktree, commit, push, or handoff:
  `docs/ai-workflow/git-execution.md`
- Sub-agents, parallel work, specialized tools, or independent verification:
  `docs/ai-workflow/capability-routing.md`
- Any structured communication packet or report template:
  `docs/ai-workflow/packets.md`
- `PROJECTCONTEXT.md` creation, reading, conflict, update, or delta:
  `docs/ai-workflow/project-context.md`
- Repeated implementation failure, MCP idle/unresponsive behavior, or debug:
  `docs/ai-workflow/failure-and-debug.md`
- Secrets, destructive operations, migrations, publishing, external services,
  or security/privacy/data-loss risk:
  `docs/ai-workflow/security-and-destructive-actions.md`

Do not load every module by default. Root rules remain active whether or not a
module is loaded. If a required module is missing or stale, follow the root
safety rules, report the gap, and do not invent authority.

## 11. Authority order

When instructions conflict, use this precedence:

1. Latest explicit Owner decision.
2. Current Claude Decision or active Implementation Brief.
3. Current repository code and verified test evidence.
4. `PROJECTCONTEXT.md`.
5. Older reports, plans, and historical documents.

Higher-level system or tool safety restrictions still apply. Never silently
overwrite a conflict that changes product behavior, scope, architecture, or
risk; raise the appropriate decision request.
