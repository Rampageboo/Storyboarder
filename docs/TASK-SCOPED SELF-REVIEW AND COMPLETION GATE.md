# TASK-SCOPED SELF-REVIEW AND COMPLETION GATE

Apply this completion gate after implementing the requested task and before creating the final report.

This is not a request for a repository-wide refactor.

The review boundary is:

```text
- files changed by this task
- direct callers and callees of changed functions
- schemas and state consumed or produced by the changed code
- adjacent UI modes sharing the same components
- persistence, restart, rollback, and failure paths touched by the task
- tests and mocks representing the changed APIs
```

Do not stop after making the literal requested edit.

You must perform a second engineering pass to determine whether the change introduced or exposed directly related defects.

---

# 1. Restate the task contract before reviewing

Create a concise internal checklist containing:

```text
requested behavior
behavior that must remain unchanged
data-safety invariants
UI-state invariants
persistence/restart invariants
compatibility constraints
```

Use this checklist to evaluate the final diff.

Do not judge completion only by whether the requested line of code exists.

---

# 2. Review the complete task diff

Before stopping, inspect the complete diff from the task’s base commit to the final commit.

For every changed file, ask:

```text
Why was this file changed?
Is every change required?
Did the change create dead code?
Did the change leave old logic running in parallel?
Did the change introduce a second source of truth?
Did the change alter unrelated behavior?
```

Remove accidental, obsolete, or duplicated code.

Do not include unrelated formatting or architecture changes unless they are necessary.

---

# 3. Trace changed functions through direct callers and callees

For every materially changed function:

```text
inspect every direct caller
inspect every directly invoked helper
inspect the data shape passed in and returned
inspect error handling
inspect state mutation
inspect cleanup/finally behavior
```

Typical derived issues to look for:

```text
caller still assumes the old return shape
one caller bypasses the new validation
new helper exists but is not called from every relevant route
success path updated but failure path still uses old behavior
state updated on disk but not in memory
UI data updated but selector/card is not rerendered
```

Fix directly related issues discovered in this trace.

---

# 4. Check for multiple sources of truth

Explicitly identify all state representing the same concept.

Examples:

```text
runtime state and cached state
index metadata and per-item metadata
disk settings and in-memory settings
active document and stored work context
current window state and separate maximized boolean
backend title and frontend fallback label
```

For each concept:

```text
choose one authoritative source
derive secondary values from it
remove or synchronize parallel state
```

Do not leave two independently mutable facts representing the same state unless synchronization is explicit and tested.

---

# 5. Run a state-transition audit

List every state relevant to the task.

Examples:

```text
connected / disconnected / manual
shot / scene2d / unmatched
normal / maximized / minimized
prepared / files_moved / metadata_committed / rollback_failed
empty / provisional / cached
first item / middle item / last item
```

Then examine transitions, not only isolated states:

```text
A → B
B → A
A → C
failure halfway through A → B
restart halfway through A → B
repeated A → B
```

Check that:

```text
old UI is cleared
new UI is populated
buttons are enabled/disabled correctly
state is not resurrected from stale caches
data does not remain split between two states
```

---

# 6. Audit empty, stale, and missing values

Test or reason through:

```text
empty string
empty list
null
missing field
deleted item
unknown ID
stale heartbeat/context
zero items
one item
first item
last item
title missing
file missing
folder inaccessible
```

An explicitly empty newer value must not accidentally fall back to stale older data.

Human-facing UI must not expose internal identifiers merely because a title is empty.

---

# 7. Audit failure and cleanup behavior

For every operation that writes data, moves files, changes state, or opens external applications, inspect:

```text
failure before the operation
failure halfway through
failure after the main operation but before metadata/state update
failure during rollback
failure during cleanup
process termination and restart
```

Check all `except` and `finally` blocks.

Critical rule:

```text
cleanup must not destroy recovery information when recovery is incomplete
```

Do not swallow rollback or recovery errors.

Preserve journals/backups when automatic recovery cannot be proven complete.

---

# 8. Audit persistence and restart behavior

When the task touches persistent state, verify:

```text
disk state
in-memory state
cache state
per-item metadata
canonical index
reference links
saved window/UI state
```

all agree after:

```text
success
ordinary failure
restart
repeated recovery
```

Recovery must be idempotent where applicable.

Do not verify only the primary JSON file if secondary metadata files are also written.

---

# 9. Audit UI modes that share components

When changing a shared panel, card, selector, toolbar, or state renderer, inspect every mode using it.

Examples:

```text
Shot
Scene 2D
unmatched
disconnected
manual
empty state
image/read-only mode
```

Check:

```text
padding and alignment
stale content clearing
hidden elements
disabled actions
human-readable labels
long titles
empty titles
narrow widths
```

Do not fix one mode by introducing a height, spacing, or state regression in another.

---

# 10. Audit real API assumptions

Compare tests and mocks against the real API surface used by production.

Examples:

```text
method versus property
initial configuration versus live state
event ordering
path versus filename
zero-based versus one-based index
native path versus file URL
```

Do not create a fake test API that makes invalid production code appear correct.

When relying on framework behavior, inspect the installed/version-locked API or existing project usage.

---

# 11. Add task-adjacent tests

At minimum add or update tests for:

```text
happy path
first/last or empty boundary
state transition
failure path
stale/missing data
regression that motivated the task
```

For persistent or transactional changes also test:

```text
failure after each major stage
rollback failure
restart recovery
idempotent retry
```

For UI routing, test element visibility or extract pure routing helpers.

Do not rely only on source-string assertions when behavior can be tested directly.

---

# 12. Perform a red-team pass after tests pass

After the first successful test run, review the diff again and try to break it.

Ask:

```text
What happens if this value is empty?
What happens if this event arrives in a different order?
What happens if the user changes mode before the request completes?
What happens if the process stops after this line?
What happens if cleanup fails?
What happens if the operation is repeated?
What happens if the item was deleted?
What happens if two items have the same filename/title?
What happens when the window is minimized/maximized?
What happens at first and last item?
```

Fix task-adjacent defects found during this pass.

Then rerun the relevant tests.

---

# 13. Control scope

Fix an additionally discovered issue when all are true:

```text
it is directly caused by or exposed by this task
it affects correctness, data safety, or the requested workflow
the fix is localized
the fix can be tested
```

Do not silently expand into:

```text
unrelated feature work
large architecture rewrites
general style cleanup
repository-wide modernization
```

When a discovered issue is real but too broad:

```text
do not hide it
do not claim full completion
report it clearly as a remaining issue
explain why it was not changed
```

---

# 14. Verification requirements

Run:

```text
focused tests for changed behavior
related integration tests
full backend test suite where practical
frontend/plugin build or syntax checks
manual validation for host-dependent behavior
```

Host-dependent examples include:

```text
Photoshop UXP
pywebview desktop geometry
WinForms splash
Blender
OS file dialogs
```

Do not claim a host-dependent test passed unless it was actually performed.

Do not treat “code compiles” as proof that a UI workflow works.

---

# 15. Final completion report

The final report must contain these sections:

```text
Requested changes completed

Additional task-adjacent issues discovered
  - issue
  - why it was related
  - whether it was fixed

Self-review findings
  - duplicate-state audit
  - transition audit
  - failure/recovery audit
  - API-assumption audit

Tests actually run
  - exact command
  - exact result

Manual validation actually performed

Tests or manual validation not performed

Known limitations and remaining risks

Files changed

Final commit SHA
```

Explicitly distinguish:

```text
verified
reasoned but not manually verified
not tested
```

Do not write:

```text
all tests passed
manual validation passed
fully fixed
```

without evidence.

---

# 16. Completion criteria

Do not stop until:

```text
- the requested behavior is implemented
- directly related callers/callees were reviewed
- duplicate state sources were reconciled
- relevant state transitions were checked
- failure and cleanup paths were reviewed
- task-adjacent regressions were tested
- the final diff was reviewed a second time
- test claims are evidence-based
- remaining risks are reported honestly
```

The goal is not to make the task larger.

The goal is to prevent a narrow literal fix from leaving an obvious adjacent defect that requires another immediate repair task.
