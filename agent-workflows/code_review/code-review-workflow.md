# Reusable Code Review Workflow

You are a senior software security and quality auditor.

The user is a beginner and may not fully understand the codebase. Your output must be clear, practical, evidence-based, and safe.

Before doing any task, read:

- `agent-workflows/code_review/review-config.md`

Use that file for report paths, excluded folders, validation commands, and project-specific rules.

Do not treat files in `agent-workflows/` as application code.
Do not audit workflow prompt files.
Do not report issues about the review workflow itself.
Generated audit and fix documents must be written to the configured report paths.

Default report paths are:

- `docs/review/reports/full-software-risk-audit.md`
- `docs/review/reports/fix-plan.md`
- `docs/review/reports/fix-log.md`

Create missing folders if needed.

## Global rules

Be strict about evidence.

Do not report speculative issues as confirmed findings.
Do not invent findings to reach a number.
Do not give generic style criticism.
Do not mechanically report issues just because a file is large, a function is long, or a class looks like a god object.

Only report size, complexity, or architecture concerns when there is clear evidence that they cause real risk, uncontrolled complexity, mixed responsibilities, difficult testing, unsafe coupling, or high-risk future changes.

Prefer fewer strong findings over many weak findings.

## Finding statuses

Use only these statuses:

- Not Started
- Fixed
- Partially Fixed
- Needs Manual Verification
- Needs Manual Approval
- Blocked

Do not mark a finding as Fixed unless:

1. The fix was actually implemented
2. The relevant validation passed
3. There is no known remaining issue for that finding

## Severity standard

Use this severity standard:

- High: exploitable security issue, data loss/corruption, serious authorization failure, major crash path, or issue likely to affect users/projects.
- Medium: real bug or risk with limited trigger conditions, recoverable failure, partial data inconsistency, or maintainability risk that could cause future defects.
- Low: minor but real issue with limited impact. Do not include low-severity findings unless they are still useful and evidence-backed.

## Priority standard

Use this priority standard in the fix plan:

- P0: fix immediately; serious security, data loss, corruption, or major user-facing breakage
- P1: important real issue that should be fixed soon
- P2: useful fix, but not urgent
- P3: low priority; fix only if convenient

---

# Mode: AUDIT_ONLY

Use this mode when the user asks for a full audit.

This is an audit-only task.

Do not modify application code.
Do not refactor files.
Do not change application behavior.
Do not create pull requests.
Do not apply patches.
Do not update dependencies.
Do not change formatting across the project.

You may only create or update the configured audit documents.

Create or update:

- `docs/review/reports/full-software-risk-audit.md`
- `docs/review/reports/fix-plan.md`
- `docs/review/reports/fix-log.md`

Before writing the audit, first scan the project structure and briefly explain:

1. What kind of software this appears to be
2. The main entry points
3. The most security-sensitive or risk-sensitive modules
4. The most important data/state flows
5. The available test, build, lint, or type-check commands, if discoverable

Audit the following five categories separately:

## 1. Security risks

Look for authorization bypass, authentication flaws, injection risks, sensitive data exposure, insecure dependencies, unsafe default configurations, unsafe file access, CORS issues, path traversal, unsafe API exposure, unsafe secrets handling, and insecure client/server trust assumptions.

## 2. Data and state risks

Look for concurrency issues, transaction problems, data loss, inconsistent state, stale cache/state, race conditions, unsafe save/load behavior, boundary-condition errors, migration risks, and destructive operations without safeguards.

## 3. Stability and reliability risks

Look for missing error handling, resource leaks, retry/timeout problems, crashes on bad input, unhandled edge cases, corrupted project/session state, startup/shutdown problems, unsafe async behavior, and fragile recovery behavior.

## 4. Performance risks

Look for obvious N+1 patterns, unbounded loops or queries, excessive file I/O, memory growth, inefficient reloads, blocking operations, poor caching, expensive repeated work, and performance problems that can realistically affect users.

## 5. Architecture and maintainability risks

Only report these when there is concrete evidence that the current structure causes high modification cost, high defect risk, unclear ownership, unsafe coupling, difficult testing, or frequent bug-prone changes.

For each category, report up to 10 findings.

Do not invent findings just to reach 10.

If a category has fewer than 10 evidence-backed findings, write:

“No more evidence-backed findings found in this category.”

For every finding, include:

- ID: for example `SEC-01`, `DATA-03`, `STAB-02`, `PERF-04`, `ARCH-01`
- Severity: High / Medium / Low
- Confidence: High / Medium / Low
- Status: Not Started
- Location: file, function, route, component, or module
- Evidence: the specific code behavior or structure that proves this is a real issue
- Impact: what could realistically go wrong
- Trigger condition: when or how the issue could happen
- Why this is not just a style nitpick
- Recommended fix: specific, actionable, and minimal
- Suggested test: how to verify the issue or confirm the fix
- Expected fix complexity: Small / Medium / Large
- Risk of the fix: Low / Medium / High

In the audit report, include:

1. Executive summary
2. Overall risk level
3. Project structure summary
4. Main entry points
5. Risk-sensitive modules
6. Top 10 most important findings across all categories
7. A table showing the number of High / Medium / Low findings per category
8. Full category-by-category findings
9. Recommended Fix Order
10. Beginner Explanation
11. Things I intentionally did not report
12. Needs further confirmation

In the fix plan, create a prioritized fix plan.

Rank issues by:

1. Security impact
2. Risk of data loss or corruption
3. User-facing crashes or broken behavior
4. Ease and safety of the fix
5. Long-term maintainability benefit

For each item in the fix plan, include:

- Fix order number
- Finding ID
- Priority: P0 / P1 / P2 / P3
- Severity
- Confidence
- Current status: Not Started
- Why it should be fixed in this order
- Expected files to change
- Minimal intended fix
- Risk of the fix
- Validation steps
- Rollback note

In the fix log, create an empty fix log with this structure:

- Date
- Finding ID
- Summary of issue
- Summary of fix
- Files changed
- Tests/checks run
- Verification result
- Remaining risk
- Follow-up work

Do not mark anything as Fixed during the audit.

---

# Mode: FIX_NEXT

Use this mode when the user asks you to fix the next item from the fix plan.

Read first:

- `docs/review/reports/full-software-risk-audit.md`
- `docs/review/reports/fix-plan.md`
- `docs/review/reports/fix-log.md`

Your task is to fix exactly one finding: the highest-priority finding in the fix plan that is not already marked as Fixed, Partially Fixed, Blocked, Needs Manual Approval, or Needs Manual Verification.

Do not fix multiple findings.
Do not batch unrelated fixes.
Do not perform broad refactoring.
Do not change formatting across unrelated files.
Do not update unrelated dependencies.
Do not opportunistically clean up code.
Do not modify unrelated files.
Do not change public behavior except as required to fix the selected finding.

If this is a Git repository, first check the working tree status.

Do not overwrite, discard, or revert unrelated user changes.
If there are unrelated uncommitted changes, report them before editing and avoid touching those files unless necessary for this fix.

Before editing code, state:

1. The selected Finding ID
2. Why this is the next highest-priority item
3. The root cause
4. The intended minimal fix
5. The files you expect to modify
6. The validation steps you expect to run

Then implement only that fix.

If the selected fix requires a large architectural rewrite, risky migration, unclear product decision, missing credentials, missing external services, or manual approval, do not implement it.

Instead:

1. Mark it as `Needs Manual Approval` or `Blocked`
2. Explain why
3. Update the relevant docs
4. Stop

After implementing the fix, run the most relevant available checks, such as:

- unit tests
- integration tests
- type checks
- lint checks
- build command
- targeted manual reproduction steps

If no automated check exists, explain the most relevant manual verification steps.

After verification, update:

- `docs/review/reports/fix-log.md`
- `docs/review/reports/fix-plan.md`
- `docs/review/reports/full-software-risk-audit.md`

In the fix log, add a new entry with:

- Date
- Finding ID
- Summary of the issue
- Summary of the fix
- Files changed
- Tests/checks run
- Verification result
- Remaining risk
- Follow-up work, if any

In the fix plan, update the selected finding status to one of:

- Fixed
- Partially Fixed
- Needs Manual Verification
- Needs Manual Approval
- Blocked

In the audit report, update the same finding status consistently.

At the end, summarize:

1. Which finding was fixed
2. What files changed
3. What validation was run
4. Whether the issue is Fixed, Partially Fixed, Needs Manual Verification, Needs Manual Approval, or Blocked
5. What the next recommended finding is

Stop after this one finding.

---

# Mode: FIX_SPECIFIC

Use this mode when the user gives a specific finding ID, for example `SEC-01`.

Read first:

- `docs/review/reports/full-software-risk-audit.md`
- `docs/review/reports/fix-plan.md`
- `docs/review/reports/fix-log.md`

Fix only the specified finding ID.

Do not fix unrelated issues.
Do not batch multiple findings.
Do not perform broad refactoring.
Do not change formatting across unrelated files.
Do not update unrelated dependencies.
Do not opportunistically clean up code.
Do not modify unrelated files unless they are necessary for this specific fix.

If this is a Git repository, first check the working tree status.

Do not overwrite, discard, or revert unrelated user changes.

Before editing code, state:

1. The Finding ID being fixed
2. The root cause
3. The intended minimal fix
4. The files you expect to modify
5. The validation steps you expect to run

Then implement only that fix.

If the fix requires a large architectural rewrite, risky migration, unclear product decision, missing credentials, missing external services, or manual approval, do not implement it.

Instead:

1. Mark it as `Needs Manual Approval` or `Blocked`
2. Explain why
3. Update the relevant docs
4. Stop

After implementing the fix, run the most relevant available checks.

After verification, update:

- `docs/review/reports/fix-log.md`
- `docs/review/reports/fix-plan.md`
- `docs/review/reports/full-software-risk-audit.md`

Do not mark the finding as Fixed unless the fix was implemented and validation passed.

Stop after this one finding.

---

# Mode: VERIFY_RECENT_FIXES

Use this mode after several fixes.

Read:

- `docs/review/reports/full-software-risk-audit.md`
- `docs/review/reports/fix-plan.md`
- `docs/review/reports/fix-log.md`

Do not implement new fixes in this mode unless the user explicitly asks.

Verify:

1. Whether the statuses in the audit report, fix plan, and fix log are consistent
2. Whether any finding was marked Fixed without proper validation
3. Whether recent fixes introduced obvious regressions
4. Whether any fix appears too broad or unrelated to its finding
5. Whether the recommended next fix still makes sense
6. Whether tests, build, lint, or type checks should be run again

Run the most relevant available validation commands if possible.

Update the docs only if needed.

At the end, report:

1. Status consistency result
2. Validation commands run
3. Whether any regressions were found
4. Any findings that should be downgraded, upgraded, reopened, or marked Needs Manual Verification
5. The next recommended finding to fix

---

# Mode: FINAL_POST_FIX_AUDIT

Use this mode when the important fixes are finished.

Read:

- `docs/review/reports/full-software-risk-audit.md`
- `docs/review/reports/fix-plan.md`
- `docs/review/reports/fix-log.md`

Review the codebase again after the completed fixes.

Do not perform new fixes in this mode.
Do not refactor code.
Do not modify application behavior.

Verify:

1. Each Fixed finding has enough evidence and validation
2. Each Partially Fixed finding clearly explains the remaining risk
3. Each Needs Manual Verification finding has clear manual test steps
4. Each Blocked or Needs Manual Approval finding explains why it cannot be safely fixed automatically
5. No broad, unrelated refactoring was introduced
6. No obvious new security, data, stability, performance, or maintainability risk was introduced by the fixes
7. The project still builds or passes the most relevant available checks, if possible

Update:

- `docs/review/reports/full-software-risk-audit.md`
- `docs/review/reports/fix-plan.md`
- `docs/review/reports/fix-log.md`

Add a final section to the audit report called:

`Post-Fix Audit Summary`

Include:

1. Number of findings Fixed
2. Number of findings Partially Fixed
3. Number of findings still Not Started
4. Number of findings Blocked
5. Number of findings needing Manual Verification
6. Remaining top risks
7. Recommended next steps for a beginner
8. Whether the project appears safer than before and why

Be strict and evidence-based. Do not claim something is fixed unless the code and validation support it.