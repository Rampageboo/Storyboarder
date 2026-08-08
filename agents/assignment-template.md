# Agent Assignment

Canonical handoff contract: `capability-routing.md`.

```yaml
identity:
  agent_id: <runtime-id>
  role: <technical-lead | implementation-owner | verification-executor>
  role_file: agents/<lead | implementer | verifier>.md
  coordinator: <Owner | session-id>
  task: <task-id>

target:
  repository: <path>
  working_directory: <path>
  state_identity: <revision|artifact|workspace-id>
  project_context: <entries>
  task_record: <path>

contract:
  outcome: <result>
  facts_constraints: <list>
  scope: <included|excluded>
  invariants: <list>
  acceptance: <criteria>
  evidence: <required>
  authority: <writes|external actions|risk>
  stop: <conditions>
  map_scope: <provider|affected scope>

verification: # verification-executor only
  type: <baseline|focused regression|broader verification>
  checks: <commands|actions>
  expected: <results>
  acceptance_mapping: <check -> criterion>
  diagnosis_included: <yes|no>

communication:
  task_record: <path>
  lead_events: <list>
  findings_recipient: <Implementer id>
  final_evidence_recipients: [<Implementer id>, <Lead id>]
```

Coordinator chain:

```text
Lead <- Owner
Implementer <- Lead
Verifier <- Implementer
```

Create session with model, effort, and this assignment together.
