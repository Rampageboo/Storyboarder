# Codex Model Routing

Read this module when Claude chooses between Codex execution models, including
`gpt-5.3-codex-spark`, or when a Spark task may need escalation.

Claude remains the upper-level coordinator. Spark is one Codex execution model
inside the Claude-to-Codex workflow, not a replacement for it — do not
restructure the workflow as `Claude -> Spark`.

## Model roles

- **`gpt-5.3-codex-spark` (Spark)** — low-latency Codex model for quick, targeted
  edits. Tends to make minimal precise changes, keep scope small, return fast,
  and may not run tests unless asked. Not for long-running autonomous execution.
- **Higher-capability Codex** — stronger reasoning, investigation, and sustained
  autonomous execution for complex, ambiguous, long-running, or high-risk work.

## Core routing principle

Choose the fastest, lightest model that can reliably complete **and verify** the
task — not Spark by default. Classify first by scope, ambiguity, repository
context required, architectural impact, regression risk, validation difficulty,
affected-file count, recovery cost, and whether visual/model inputs are needed.

A short-sounding request can still need broad investigation. Do not pick Spark
because a request sounds short, or a frontier model just because it is available.

## Prefer Spark when (most should hold)

- requirements, change target, and success criteria are explicit;
- relevant files/directories are known and the change is local (~1–3 files, one
  component or local feature);
- no architecture redesign, broad root-cause search, public-interface change,
  database schema change, new core dependency, or cross-repository operation;
- runnable test/build/validation commands exist;
- failure will not damage important data, and the work finishes in a few
  iterations.

These are workflow heuristics, not hard model limits; adjust for codebase size
and coupling.

## Prefer higher-capability Codex when (any usually rules out Spark)

- only a symptom is given and the root cause/location is unknown, or many files
  must be read before choosing an approach;
- multiple interdependent modules, core architecture, or the data model change;
- security boundaries (auth, payments, encryption), database migrations, or
  other irreversible data actions are involved;
- production deployment, large performance optimization, or complex
  concurrency/threading/async state is involved;
- Blender, Unreal Engine, MCP, or local services need coordinated debugging;
- visual input (image, screenshot, model appearance) must be understood;
- long-running autonomous execution or many tool rounds are needed;
- there is no reliable automatic validation, or recovery cost for a wrong edit
  is high.

## Escalate mid-task from Spark

After choosing Spark, keep checking whether the task has left Spark's scope.
Stop retrying Spark and escalate to higher-capability Codex when:

- Spark fails twice on the same objective, cannot find the root cause, or
  reports insufficient context;
- actual scope grows materially, or architecture / public-API / data-structure
  decisions become necessary;
- tests keep failing for unclear reasons, or Spark produces broad unrelated
  changes or needs many more files to continue;
- the change creates new cross-module problems, or security / compatibility /
  migration analysis is needed;
- the Owner asks for full review, deep investigation, or a complete refactor.

Escalation is not a fresh start. Hand the next model the original Owner goal,
confirmed scope and requirements, files inspected, files Spark changed, current
diff, commands run and test results, error messages, ruled-out hypotheses,
unresolved issues, prohibited scope, and final acceptance criteria.

## Spark task brief

Do not call Spark with a broad one-liner. Give a bounded, directly executable
packet:

- **Task** — one concrete outcome.
- **Scope** — exact files to inspect/modify, plus explicit "do not touch"
  (e.g. do not refactor the architecture, do not modify unrelated components).
- **Known vs expected behavior** — current behavior and the required result.
- **Required validation** — which tests/checks to run; report every modified
  file and every command with its result; inspect the final diff for unrelated
  changes.

Instruct Spark: if the root cause is outside authorized scope, stop and report
what must be investigated — do not perform a broad refactor.

## Spark result requirements

Require Spark to return: completion status (Completed / Partial / Blocked), root
cause, change summary, modified files, validation commands and results, anything
not validated, remaining risks, whether scope expanded, and whether escalation
is recommended and why.

## Claude acceptance responsibility

Do not report success merely because Spark says it is complete. Check that the
change matches the request, the diff contains only necessary edits, no
unauthorized files changed, required tests actually ran with complete results,
compile/type risks are addressed, public behavior did not change unexpectedly,
no unnecessary dependency was added, and failure paths were not missed.

Low-risk local tasks: Spark's validation plus Claude's result review may suffice.
Medium/high-risk: Claude may ask higher-capability Codex for a read-only review
even if Spark completed the edit.

## Parallel Spark tasks

Run multiple Spark workers in parallel only for independent tasks:

- no two workers modify the same file or share an uncommitted working directory;
- give each worker clear file ownership; use separate branches or Git worktrees;
- each worker runs its own relevant tests;
- Claude or higher-capability Codex performs final integration review.

Prefer isolated worktrees:

```text
main repository
|-- worktree/spark-ui
|-- worktree/spark-tests
`-- worktree/spark-export
```

## Final principle

```text
Claude judges, decomposes, and accepts.
Codex executes.
Spark is the Codex model option for fast local tasks.
Higher-capability Codex handles complex, ambiguous, long-running, high-risk tasks.
```
