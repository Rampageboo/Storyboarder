# Agent Assignment

Use this template for a role-session opening assignment. The contract is the
minimum sufficient contract in `capability-routing.md`; this template adds the
identity header and the target.

## Identity

```yaml
agent_id: <role-session-id>
role: <technical-lead | implementation-owner | verification-executor>
role_file: agents/<lead | implementer | verifier>.md
coordinator: <assigning-claude-owner-or-lead-id>
task: <task-id>
```

`role` and `role_file` establish authority. Valid pairs are `technical-lead` /
`agents/lead.md`, `implementation-owner` / `agents/implementer.md`, and
`verification-executor` / `agents/verifier.md`.

For a Lead session, the coordinator and report recipient are Claude or the
assigning Owner. For Implementer and Verifier sessions, both are the Lead, which
forwards their results.

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
- Report recipient: <coordinator named in Identity>

## Starting

Report a blocker only when a missing input prevents valid work.
