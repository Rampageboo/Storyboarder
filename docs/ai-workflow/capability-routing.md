# Capability Routing

Read this module for sub-agents, parallel workstreams, specialized tools, or
independent verification.

Reasoning effort does not determine capability use. Select the smallest
effective capability set.

## Assessment

```text
Sub-agents: allowed / required / not useful / prohibited
Independent bounded workstreams:
Specialized tools expected:
Independent verification expected: yes/no
Shared-file collision risk:
Delegation autonomy: bounded / explicit-only
```

Default:

```text
Sub-agents: allowed when Codex identifies independent bounded workstreams
Delegation autonomy: bounded
```

## Good multi-agent candidates

- separate subsystem investigations;
- competing root-cause hypotheses;
- implementation plus independent test/risk analysis;
- multiple non-overlapping modules;
- partitionable repository surveys;
- security discovery followed by independent validation.

Avoid sub-agents when work is small, sequential, dependent on an earlier
result, likely to edit the same files/state owners, coordination-heavy, or
destructive/externally visible.

Claude defines outcomes, constraints, risks, acceptance criteria, and capability
boundaries. Codex chooses the delegation structure within those boundaries.
In `owner-direct`, Codex performs the assessment itself.

The main agent integrates results, resolves contradictions, validates combined
behavior, and returns one report. Sub-agents do not independently commit, push,
modify `PROJECTCONTEXT.md`, expand scope, or perform destructive/external actions
unless the active brief explicitly authorizes the specific action.
