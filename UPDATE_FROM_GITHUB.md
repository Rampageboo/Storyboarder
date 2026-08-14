# Updating the Project Policy Release

Updates arrive as pull requests. Tagging a SemVer release in the source
repository runs the protocol distributor, which opens one pull request per
registered consumer. Nothing is pushed to a consumer's default branch directly,
and no update is auto-merged unless that consumer opts in.

Review the pull request, confirm the managed modules still exist, then merge.

`AGENTS.md` and `CLAUDE.md` are no longer release-managed. On the first update
after this change, unchanged copies proven by the old lock are removed. Locally
modified copies are preserved and block the update for explicit resolution;
they are never overwritten or silently deleted.

## Read the title before merging

A pull request titled `BLOCKED: protocol vX not installed` carries only a
report. Merging it changes no protocol file and leaves the repository on its
current version, and the block repeats on every later release until it is
resolved. An ordinary `chore: update protocol to vX` pull request is the one
that installs.

## Why a repository gets blocked

`.protocol-lock.json` records `package_id`, release identity, and normalized
hashes for managed files. A matching file may update; a locally modified or
unknown file is never overwritten.

The current package id is `project-policy`. A legacy lock with `retired: true`
retired the old project-installed collaboration package, not this new package.
Its hashes remain provenance for safe replacement/deletion during the first
project-policy update. A successful update writes a non-retired project-policy
lock, so later releases update normally.

## What the distributor will not do

It does not touch source, custom project documentation, `project-context/`,
plugin installation state, or any path outside the managed set. It does not
migrate Project Context automatically.

The independent Research Skill updates through its own repository.
