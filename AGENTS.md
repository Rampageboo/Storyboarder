# Project Engineering Policy

This release defines project-level constraints only. It does not define agent
roles, delegation, tool ownership, cross-conversation transport, or liveness.

## Execution baseline

Read project instructions and relevant files before acting. Understand current
behavior, define observable success, make the smallest complete change, and
preserve unrelated work. Surface instruction conflicts instead of silently
choosing through them.

## Evidence and authority

```yaml
observed: this agent directly read, ran, or saw it
reported: another source reported it
inferred: derived, not directly observed
proposed: unchecked
```

Bind claims to the observed target and producer. Success proves only the check;
repetition of one report remains one source.

The latest explicit Owner request defines the outcome. Precedence is Owner
assignment > project instruction > release default. Obtain Owner direction for
product direction, expanded permission, weakened acceptance, irreversible or
external action, and material security, privacy, data-loss, migration, billing,
or disclosure risk.

## Persistent information

`project-context/` stores durable intent, decisions, exact facts, boundaries,
and risks that source cannot recover. It is not a task log, backlog, or topology
cache. Repository maps are optional derived evidence; source and executed checks
remain authoritative.

When asked which project-policy release is installed, read
`.protocol-lock.json` and report its `package_id`, `version`, and `source`.

## On-demand modules

- Provider-neutral repository map policy: `codebase-map.md`
- Project Context: `project-context.md`
- External research: `research-integration.md`
- Destructive, security, privacy, billing, release, or external action:
  `security-and-destructive-actions.md`
- Repeated failure and evidence: `failure-and-debug.md`

## Scope of this package

When adding a rule, classify it first:

- **contract** — assigns a responsibility, or states what an assignment carries;
- **state invariant** — names the physical condition evidence depends on, such
  as an identified target state or a workspace held still while it is read;
- **evidence semantics** — calibrates a claim to what its evidence supports.

Only those three belong in this release. Role behavior, agent routing, host
transport, and response-style rules do not.
