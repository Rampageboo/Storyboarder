# Git Execution and Integrity

Read this module for Git inspection, commits, pushes, or handoffs.

The host that made a change commits it. Before editing or committing, inspect
the branch, HEAD, status, the relevant diff, and unrelated Owner changes, and
preserve anything outside the task.

Commit only coherent intended changes with honest validation evidence. Exclude
secrets, caches, generated junk, and unrelated files. Use a feature branch when
that is the safer repository convention; never force-push. If authentication,
conflicts, or protection blocks a push, preserve the commit and report the
failure.

## Assigning Git to one host

A project whose hosts work the same tree at the same time gives Git to one of
them, because two hosts staging one tree produce commits neither intended.
`codex-git` leaves Git with the implementing host. `claude-git` gives Claude the
branch and revision, diff review, staging, commit, and push, while Codex returns
implementation and validation evidence without running a Git command.

A project that adopts either arrangement says so in its own instructions. Absent
that, the default above applies; do not infer an assignment from which host is
running.

## Branch currency

These instructions are files, so a branch carries whatever protocol version it
was created from, and distribution updates only the default branch. Create new
branches from a current default branch, and sync an existing branch with the
default branch before resuming work on it.

If `.protocol-lock.json` on the branch names an older version than the default
branch, the instructions just loaded are stale: sync first, then re-read the
routed modules before relying on them.

No lock file at all is a third state, not a current one. The version is unknown,
and distribution never overwrites a managed file whose provenance it cannot
prove, so every later release blocks until the lock exists. Resolve it once
rather than treating the repository as up to date.

An update that lands while a task is running does not apply to that task.
Finish under the version it started from and re-read at the next task boundary.
Adopting new rules halfway leaves finished and unfinished work under different
ones, which is worse than being one version behind.

A behind branch is not dangerous to merge — files it never touched keep the
default branch's version. The cost falls on the work done under stale rules,
which is why this is checked when work starts rather than when a pull request
opens.

## Shared worktree

Never discard or rewrite unrelated work. If task changes and Owner changes
overlap in the same file and cannot be separated safely, stop and surface the
collision. Use an isolated worktree for broad or collision-prone work when
available.
