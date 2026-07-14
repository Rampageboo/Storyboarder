以后你怎么用

第一次全量检查：

Read `agent-workflows/code_review/review-config.md` and `agent-workflows/code_review/code-review-workflow.md`.

Run mode: AUDIT_ONLY.

This is audit-only. Do not modify application code. Only create or update files under `docs/review/reports/`.

开始修第一个问题：

Read `agent-workflows/code_review/review-config.md` and `agent-workflows/code_review/code-review-workflow.md`.

Run mode: FIX_NEXT.

Fix exactly one highest-priority unresolved finding from `docs/review/reports/fix-plan.md`, update the reports, run validation, then stop.

继续修下一个：

Run mode: FIX_NEXT.

Fix exactly one next unresolved finding from `docs/review/reports/fix-plan.md`, update the reports, run validation, then stop.

指定修某个问题，比如 SEC-01：

Read `agent-workflows/code_review/review-config.md` and `agent-workflows/code_review/code-review-workflow.md`.

Run mode: FIX_SPECIFIC.

Finding ID: `SEC-01`.

Fix only this finding. Do not fix unrelated issues.

修了几个之后做检查：

Run mode: VERIFY_RECENT_FIXES.

Do not implement new fixes. Check report consistency, validation status, and whether recent fixes introduced regressions.

最后做复查：

Run mode: FINAL_POST_FIX_AUDIT.

Do not implement new fixes. Verify whether completed fixes actually resolved the original risks and upda