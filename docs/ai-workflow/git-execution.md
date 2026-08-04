# Git Execution and Integrity

Read this module for Git inspection, commits, pushes, or handoffs. The active
environment uses either `codex-git` or `claude-git`; do not infer one from a
different host.

## codex-git

Codex may perform authorized Git work. Before editing or committing, inspect
the branch, HEAD, status, relevant diff, and unrelated Owner changes. Preserve
anything outside the task.

Commit only coherent intended changes with honest validation evidence. Exclude
secrets, caches, generated junk, and unrelated files. Use a feature branch when
that is the safer repository convention; never force-push. If authentication,
conflicts, or protection blocks a push, preserve the commit and report the
failure.

## claude-git

Codex performs no Git command. Claude supplies the branch/revision, tree
ownership, and files to avoid, then owns diff review, staging, commit, and push.
Codex returns implementation and validation evidence without changing Git.

## Branch currency

These instructions are files, so a branch carries whatever protocol version it
was created from, and distribution updates only the default branch. Create new
branches from a current default branch, and sync an existing branch with the
default branch before resuming work on it.

If `.protocol-lock.json` on the branch names an older version than the default
branch, the instructions just loaded are stale: sync first, then re-read the
routed modules before relying on them.

A behind branch is not dangerous to merge — files it never touched keep the
default branch's version. The cost falls on the work done under stale rules,
which is why this is checked when work starts rather than when a pull request
opens.

## Shared worktree

Never discard or rewrite unrelated work. If task changes and Owner changes
overlap in the same file and cannot be separated safely, stop and surface the
collision. Use an isolated worktree for broad or collision-prone work when
available.
