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

## Adoption and maintenance

The consuming project records the provider/version, corpus and data boundary,
artifact/Git policy, maintainer, represented revision, and update trigger.
Installation does not authorize semantic transmission, hooks, watchers, CI,
global graphs, or committed generated artifacts.

Update once after a relevant change set stabilizes when the configured trigger
applies. Check freshness and health when map output informed the work, mapped
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
