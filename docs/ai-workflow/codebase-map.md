# Codebase Map

Read this module when a project adopts Graphify or another repository map.

## Boundary

A map is optional derived context. Use a current map to locate relevant source
and relationships, then inspect source and tests before editing or making
consequential claims. A missing or stale map never blocks ordinary source
inspection.

The map owns repository-derived topology: files, symbols, calls, imports,
dependencies, flows, impact relationships, and as-built architecture. Project
Context owns durable intent, confirmed decisions, exact facts, active external
boundaries, and high-value risks. Do not duplicate one in the other.

Being derived from code, a map shows a mechanism but not the reason for it, the
rule around it, or a prohibition — an absence has no representation in source.
The two are complementary, so an adopted map never retires Project Context.

## Adoption and maintenance

The consuming project records the provider/version, corpus and data boundary,
artifact/Git policy, maintainer, represented revision, and update trigger.
Installation does not authorize semantic transmission, hooks, watchers, CI,
global graphs, or committed generated artifacts.

When only agents read the map, rebuild it immediately before querying instead of
keeping it fresh between sessions. An on-demand rebuild removes the difference
between a current and a stale map rather than policing it, and it fails visibly
where a background rebuild fails silently. The agent that queries the map rebuilds it
first and verifies that the rebuild ran; a separately routed worker takes the
executor route in `codex-model-routing.md`. The rebuild itself is deterministic,
so model capability does not change its result.

Adopt an automatic trigger such as a commit hook only when something outside an
agent session reads the map. Record where that automation is installed:
automation that lives outside the repository does not travel with a clone, so a
second clone runs without it and says nothing.

Check freshness and health when map output informed the work, mapped
source changed, or current map state is part of acceptance. When map and source
disagree, source wins and the map is stale or defective.

## Graphify

Graphify is the documented default, not a project dependency. Its installed
Skill owns build, query, update, cache, hook, export, and troubleshooting
instructions. Artifacts normally live under `graphify-out/`; keep them within
the project's approved data and Git policy.

A handoff need report map state only when it affected the task: provider,
represented revision, query used, source verified, freshness/health warnings,
and artifact disposition.
