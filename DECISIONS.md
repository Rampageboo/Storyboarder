# Decisions

These decisions summarize reviewed Codex chats as of 2026-10-03. Historical decisions are labeled in their consequences; verify current code before treating them as runtime acceptance.

## Keep Shot as the canonical owner of prompt and artwork; comic documents store layout metadata.

- **Decision:** Keep Shot as the canonical owner of prompt and artwork; comic documents store layout metadata.
- **Reason:** The long-scroll/spread workflow reuses existing shots.
- **Consequences:** Edits, persistence, and export resolve artwork from shots.

## Refactor project state, save, and transaction boundaries in phases.

- **Decision:** Refactor project state, save, and transaction boundaries in phases.
- **Reason:** The architecture audit found coupled state and recovery paths.
- **Consequences:** Keep each phase reviewable and test persistence before wider migration.

### Implementation boundary — 2026-10-03

- **Decision:** Keep public project APIs, REST payloads and Layout 1/2 formats stable while extracting frontend lifecycle/draft coordination, backend operation policies and pure reference metadata normalization.
- **Reason:** The verified coupling is in ownership and coordination; a format/framework replacement is unnecessary to remove it.
- **Consequences:** Preserve existing drawing, graph, comic and external editor semantics. Declare backend mutation policy at the operation; keep lock order and rollback coverage. Storage normalization must not import reference workflows or project_manager. Independent verification compares the integrated result with the current working-source baseline.
- **Constraints:** No integration-branch commit or push; worker changes are integrated without discarding pre-existing modifications. Heavy tests/builds run sequentially through the verifier. Desktop/Photoshop/Blender acceptance remains distinct from automated browser and API checks.

## Round 2: domain commands and scene service ownership — 2026-10-03

- **Decision:** Keep lifecycle/selection and canonical response acceptance in the project facade; give board and reference operations their own command construction with one shared history owner. Split 2D/3D endpoint orchestration into domain service adapters, preserving the existing public method and mutation-policy contracts.
- **Reason:** First-round coordination is explicit, but domain inverses and scene workflows still accumulate in the central facades. Cohesive owners make those contracts reviewable without changing the data model.
- **Consequences:** History remains bounded to 50 entries and respects failed/in-flight replay invalidation. Domain adapters must not depend back on `backend_service`. Remove the shadowed export copy of the scene-file handler so its owner is unambiguous. Existing React state/lint errors are repaired under this round's explicit scope so the normal verification gate can run end to end.
- **Constraints:** Preserve domain behavior, UI, formats, APIs and existing dirty work; independent verifier runs all tests/builds. No integration commit or push.

## Use Send to Codex as the manual generation entrypoint.

- **Decision:** Use Send to Codex as the manual generation entrypoint.
- **Reason:** The provider workflow was designed without automatic generation.
- **Consequences:** Provider selection is explicit; existing artwork remains controlled.

## Project type selection — 2026-10-03

- **Decision:** Ask Video or Comic before the new-project file picker; persist `settings.project_type` as `video` or `comic` before the first project write. Missing type in old files behaves as Video without migration.
- **Reason:** Creation should start in the intended authoring workspace while retaining the shared `.sbd` artwork and layout model.
- **Consequences:** Comic starts in Comic, Video in Board. Manual workspace switching remains available, ordinary saves retain that selection, and cancelling the type choice leaves the current project and drafts untouched. Independent Verifier owns tests/builds; source and existing dirty work remain in the current checkout with one source writer at a time.
- **Save boundary:** Layout 2 recent-project history belongs to the existing application session. Opening or forgetting a recent project must not mutate canonical project settings outside a metadata revision; legacy project behavior remains unchanged.
