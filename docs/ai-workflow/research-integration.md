# Optional Research Integration

Read this module when engineering work is blocked on knowledge the repository
cannot supply, or when it consumes the independently installed
`run-chatgpt-research` Skill.

The Skill owns research execution, sources, evaluation, and its packet format.
The Research Packet is the final research delivery format, not the default for
intermediate collaboration or engineering handoffs.
The project owns the question, supplied context, permissions, budget, retention,
and how results affect engineering decisions. Research is optional and never a
prerequisite for ordinary project startup.

## When to commission it

Commission research when the remaining gap is external knowledge rather than
local diagnosis: focused repair cycles have stopped producing new evidence and
the unknown is third-party behavior, a version difference, or a current fact the
repository cannot settle; several viable designs or algorithms need independent
comparison against published practice before one is built on; a plan about to be
committed to has no local reviewer able to contest it on evidence; or the work
depends on a domain the project has never established, where guessing would be
indistinguishable from deciding.

Do not commission research for a fact one authoritative source settles, to avoid
an ordinary engineering decision, or before the failure is reproduced and stated
exactly. Write down the question, the verified facts, the constraints, and the
decision it must unblock first. If those cannot be filled in, the work is
under-diagnosed rather than blocked.

Send only relevant context and approved source identities. Private content must
stay within both the project's data policy and the Skill's transmission rules.

A Research Packet is evidence or a recommendation unless the project explicitly
delegated a decision. It is not implementation completion, Git authority,
release approval, or permission for an external/destructive action. Verify
consequential exact facts before implementation and store only durable decisions
or validity limits in Project Context.

Claude and Codex may commission the same Skill contract. Research does not
route coding work or change engineering roles.
