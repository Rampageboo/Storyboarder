# Updating the Protocol

Updates arrive as pull requests. Tagging a SemVer release in the source
repository runs the protocol distributor, which opens one pull request per
registered consumer. Nothing is pushed to a consumer's default branch directly,
and no update is auto-merged unless that consumer opts in.

Review the pull request, confirm the routed modules still exist, then merge.

## Read the title before merging

A pull request titled `BLOCKED: protocol vX not installed` carries only a
report. Merging it changes no protocol file and leaves the repository on its
current version, and the block repeats on every later release until it is
resolved. An ordinary `chore: update protocol to vX` pull request is the one
that installs.

## Why a repository gets blocked

`.protocol-lock.json` records the hash of every managed file as installed. A
file matching its lock hash is unmodified and is replaced; a file that differs
was changed locally and is never overwritten. A file present without a lock
entry has unknown provenance and is also left alone.

So a project whose protocol predates the lock blocks on first contact. Clear it
once by removing the managed files on a branch and letting the next release
install them cleanly, or by resolving each path and writing the lock by hand.

## What the distributor will not do

It does not touch source, `project-context/`, project documentation, or any
path outside the managed set, and it does not migrate Project Context. When a
release changes the context schema or storage boundary, follow the relevant
guide under `docs/ai-workflow/migrations/`.

The independent Research Skill updates through its own repository.
