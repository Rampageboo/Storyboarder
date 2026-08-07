# Agent Assignment

Use this template whenever one agent creates another. The contract is the
minimum sufficient contract in `capability-routing.md`; this template adds the
identity header and the target.

## Identity

```yaml
agent_id: implementer-01
role: implementation-owner
role_file: agents/implementer.md
coordinator: lead-01
task: <task-id>
```

`role` and `role_file` establish authority. Valid roles: `technical-lead`,
`implementation-owner`, `verification-executor`.

Set the role's model and reasoning effort when its session is created, together
with this assignment. `agent_id` may not be a legal runtime name; derive the
runtime name under the runtime's rules, and refer to a role session by the
identifier the runtime returns.

## Target

- Repository and working directory:
- Target state and its identity:
- Applicable `project-context/` entries:
- Task record location:

## Assignment

Per `capability-routing.md`: the outcome, confirmed facts and constraints,
relevant repository state, required evidence and acceptance conditions, and the
authority and safety boundaries. Add the excluded scope and stop conditions when
they are not obvious from the outcome.

- Map scope, where a map is adopted and the change affects it:

Repository and runtime state are evidence the receiver may read. They do not
supply an outcome, a boundary, or an authority the assignment left out.

## For a verification assignment

- Verification type: baseline | focused regression | broader verification
- Checks to run:
- Expected result:
- Acceptance criterion each check tests:
- Diagnosis included: yes | no

## Communication

- Milestones and exceptions to report:
- Report recipient:

## Starting

Report a blocker only when a missing input prevents valid work.
