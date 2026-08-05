# Capability and Host Routing

Read this module for delegation, parallel work, specialized tools, or
independent review.

## Independent Judgment in Collaboration

Claude, Codex, and the Researcher are collaborating reasoning systems. The
protocol default is that Claude plans, coordinates, and assesses while Codex
implements and performs initial verification. That assignment decides
responsibility, not Codex's implementation method or conclusion.

This is the canonical brief definition. A handoff provides the minimum
sufficient contract:

- the problem or desired outcome;
- confirmed facts, decisions, and constraints;
- relevant repository or execution state;
- required evidence or acceptance conditions; and
- authority, safety, and risk boundaries.

Omit an item when it has no material effect. Specify outcomes and boundaries,
not the receiver's reasoning path. Do not prescribe an implementation sequence,
analytical framework, file-level changes, or expected conclusion unless it is
already a binding decision.

Suggestions, suspected causes, proposed steps, and referenced files are inputs
for evaluation, not established facts. The receiver independently determines
whether they are correct, necessary, and proportionate. Add detail only when it
preserves a decided invariant, prevents a concrete error, or supplies evidence
the receiver cannot efficiently recover.

## Defaults

Role, host, and authority are separate. Claude normally owns task framing,
coordination, and integration assessment; Codex normally owns implementation
and initial verification. Within decided outcomes and invariants, Codex chooses
the implementation sequence, analytical method, and file-level changes. Change
the host assignment when capability, context, availability, or handoff cost
makes another route better. A substituted host receives only the authority
needed for its task.

The precedence for executor selection is: latest explicit Owner assignment,
then project-specific delegation rules, then these defaults. "Start now" or
"just do it" waives another confirmation but is not an executor assignment.
An explicit assignment changes the host, not the task's permissions or evidence
standard. Record the designated route as examined and the Owner assignment as
the reason for bypassing it; report that detail only when it materially affects
the handoff or result.

Delegate when work is independently bounded or needs a capability the current
host lacks. Keep small, sequential, or tightly coupled work together. The main
host integrates the result and returns one coherent report.

## Route selection and fallback

For a capability, channel, map, or data source designated by the project or
task:

1. Examine the route and its required inputs. Unexamined is not unavailable.
2. If it is available and sufficiently fresh, use it.
3. If it can be refreshed at reasonable cost, refresh it and use it.
4. If a credible fallback preserves the required evidence, declare the
   fallback and continue.
5. If the fallback would materially weaken required evidence or exceed
   delegated authority, report the block.

Never silently bypass a designated route. Distinguish unexamined, unavailable,
stale, explicitly exempted, Owner-overridden, and blocked for insufficient
evidence. Handle ordinary route failures without asking the Owner; escalate
only decisions that meet the Owner boundary in `OWNER_HANDBOOK.md`.

## Before delegation

Give the receiver the minimum sufficient contract above. Confirm access to the
needed files, tools, permissions, and return channel. Narrow or stop the
delegation if those conditions are unclear; do not compensate by writing the
receiver's solution for it.

Read the finished brief once as the receiver. It is sufficient if it says what
to do without this conversation, and safe if it still leaves room to reach the
opposite conclusion.

## Parallel work

Parallel work must use either non-overlapping write scopes or isolated
alternatives. Do not let two workers modify the same state owner. Name one
integration owner and stop a worker when scope overlaps, the base revision
drifts, or isolation is lost. Use the lease in `packets-extended.md` only when
that coordination needs an explicit record.

For independent review, provide the evidence and question needed for judgment,
and withhold the sender's preferred conclusion unless the task explicitly asks
the receiver to evaluate that proposal. Separate verifiable facts (repository
state, exact diff or revision, constraints, and test results) from prior
hypotheses or conclusions.

For implementation of an approved decision, provide the binding decision and
its invariants. The receiver follows that decision but surfaces material
contradictions, unsafe assumptions, unnecessary complexity, or evidence that it
will not achieve the stated outcome. Ordinary implementation handoffs are not
blind reviews, but prior suggestions still do not become facts.

The external Research Skill is not a coding sub-agent and does not edit the
working tree or determine engineering completion. Its results enter through
`research-integration.md`.
