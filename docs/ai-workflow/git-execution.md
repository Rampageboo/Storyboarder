# Git Execution and Integrity

Read this module for Git mode selection, status, diff, branch, worktree, commit,
push, or working-tree handoff.

## Environment-scoped mode

Exactly one mode is active per Claude/Codex execution environment. The same
repository may use different modes on different machines or MCP hosts. Record:

```text
Host/environment:
MCP client:
Git execution mode: codex-git / claude-git
Last verified:
```

Do not infer a mode from another environment or silently change it mid-task.

## codex-git

Codex may run permitted Git commands. Before editing, inspect status, branch,
HEAD, and unrelated changes. Preserve Owner work.

Codex may create a feature branch or isolated worktree when risk, breadth, or
multi-agent work justifies it. Commit only when:

- the task is coherent and complete;
- relevant validation passed, or unavailable validation is explicitly accepted;
- the tree contains only intended changes;
- no secrets, junk, caches, local environment files, or build artifacts enter
  the commit.

Push only clean commits to a safe branch. Never force-push. Do not push directly
to main/master when the repository normally uses feature branches or protection.
If direct commits are the established workflow and no safer path exists, a
validated commit may be pushed to the current branch.

If authentication, permissions, remote conflicts, or protection blocks push,
do not retry destructively; report the exact failure and preserve the commit.

## claude-git

Codex runs no Git command—not even status or diff. Claude must supply before
implementation:

- branch and HEAD;
- whether unrelated changes exist;
- files Codex must avoid;
- branch/worktree prepared for the task.

Codex reviews changed files and behavior without Git and hands back clean,
intended-only working-tree changes.

Before committing, Claude must:

1. inspect repository status;
2. inspect changed-file list and diff stat;
3. inspect the focused diff of Codex-changed files;
4. exclude unrelated Owner changes, secrets, generated junk, artifacts, and
   unintended files;
5. confirm reported validation.

Claude then owns add, commit, and push. This focused integrity review does not
authorize a repository-wide review.

## Shared working-tree safety

Never overwrite, format, revert, reset, move, or delete unrelated Owner changes.
If a required file contains unrelated changes, stop for the active coordinator.
High-risk, broad, or multi-agent tasks should use an isolated worktree when the
active Git owner can safely create one.
