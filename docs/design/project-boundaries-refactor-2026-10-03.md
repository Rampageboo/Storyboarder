# Project state and transaction boundary refactor

Status: completed and integrated, 2026-10-03. Verification exceptions and acceptance limits are recorded below. Owner authorized scoped parallel implementation after the architecture assessment.

## Outcome and constraints

Preserve the current working tree's Board, Story Map, Comic, Drawing, Scene 2D/3D, generation and external editor workflows. Keep REST contracts, project formats, legacy compatibility and canonical Shot ownership unchanged. Refactor mechanisms, not product behavior or visual design.

The integration checkout remains `D:/MyProjects/Storyboarder`. Parallel implementation uses isolated worktrees based on a local snapshot of current source, tests and build assets; the integration checkout's existing index and modifications are preserved.

## Settled boundaries

- Frontend: ProjectContext remains the public facade. Extract cohesive project lifecycle/draft coordination and asynchronous project response acceptance. Domain drafts keep their own edit/undo semantics; every domain participating in save registers an explicit flusher. Save, Save As, New, Open, Close and workspace/route changes must await applicable pending edits and refuse the transition on save failure. Late responses for a previous project must not overwrite the active project. No new state framework or wire protocol.
- Backend: preserve current locking order and Layout 1/Layout 2 rollback coverage. Declare each operation's mutation policy locally rather than maintaining parallel string registries. Extract the execution mechanism from backend_service. Keep exceptional lifecycle coordinators explicit, maintain compatibility for imports used by callers/tests, and prove coverage and rollback with behavioral tests.
- Storage: normalization of stored reference metadata must not import the reference workflow/project_manager cycle. Extract only the pure metadata operations needed to establish this boundary and update their dependents. Keep stored values and normalization behavior unchanged.
- Verification: baseline first; serialize heavy commands on this machine. Focused behavioral tests must cover draft draining, overlapping actions, stale project responses, transaction policies, rollback and metadata compatibility. Run the full backend gate and frontend lint/build on the integrated result; exercise relevant UI flows using isolated project data. Record pre-existing failures separately.

## Ownership

| Scope | Owner | Write scope |
|---|---|---|
| Frontend state/lifecycle | frontend sub-agent, GPT-6 Astra high | frontend/src/state, hooks, required App/component call sites, frontend tests |
| Backend mutation policy | backend sub-agent, GPT-6 Astra high | backend_service.py, new mutation coordinator, story_graph metadata transaction if needed, focused backend tests |
| Verification | verifier sub-agent, GPT-6 Astra high | test evidence and scoped integration tests; no product edits without integrator handoff |
| Storage boundary and integration | root | project_storage.py, reference_segments.py, new pure reference metadata module, docs, integration |

Public type, dependency and lockfile changes require integration coordination. Workers do not edit generated bundles; the final build owns those. No commits or pushes on the integration branch are required. Worker changes are integrated without discarding or staging existing work.

## Completion evidence

### Delivered boundaries

- `ProjectContext` remains the public facade. `projectLifecycle`, `useProjectLifecycle`, `useProjectActions`, `useShotDrafts` and `projectResponses` now own action serialization, document lifetimes, draft draining and response acceptance. Shot and Comic drafts share one drain mechanism while retaining domain undo/edit behavior. Failed saves preserve the draft and block navigation. Explicit Comic conflict recovery waits for an in-flight request, then reloads without retrying the rejected draft. Comic replies retain the backend's generation-freshness changes.
- Backend mutation policies are declared beside 85 operations. `mutation_executor` owns the existing lock/rollback mechanism; policy inventory tests cover all 146 public backend handlers, including inherited export handlers. Layout 1 graph metadata rollback moved to `project_transaction`; the previous `story_graph.metadata_transaction` import remains compatible. Layout 2 recovery and special Save As/Convert lock ordering remain unchanged.
- `reference_metadata` contains the existing pure normalization logic. Storage imports it directly; workflow/project-manager facades retain compatibility. The storage import no longer loads the reference workflow through a lazy circular dependency.
- The development gate now includes frontend lifecycle tests. Architecture/workflow documentation and the production frontend bundle were updated. Two obsolete copied runtime SVG files were removed to satisfy the existing route smoke contract; source SVG files remain in `frontend/public`.

### Verification record

All automated checks were executed by the independent verifier, with heavy runs serialized. Evidence directory: `C:/Users/JieYin/.codex/visualizations/2026/10/02/01a0fd13-46dd-7341-b5d0-493117bb419e/refactor-qa/`.

| Check | Command / evidence | Result |
|---|---|---|
| Frontend lifecycle/response regression tests | `npm.cmd test` in `frontend`; `final-frontend-test.log` | Exit 0; 18 passed |
| TypeScript and both production bundles | `npm.cmd run build` in `frontend`; `final-frontend-build.log` | Exit 0; bundle-size warning only |
| Changed frontend files | Scoped ESLint; `frontend-lint-final-worker.log` | Exit 0 |
| Whole frontend lint | `npm.cmd run lint`; `integrated-frontend-lint.log` | Exit 1; 8 pre-existing errors and 1 warning remain outside this refactor |
| Migration contract | `.venv/Scripts/python.exe scripts/validate_migration.py`; `final-migration.log` | Exit 0 |
| Python syntax | `scripts.verify_dev.check_py_compile()`; `final-syntax.log` | Exit 0 |
| Browser workflow | Playwright/Edge against the isolated built application; `ui-smoke-final.log`, `ui-results.json`, `ui-*.png` | Exit 0; 9/9 checks, no page errors |
| Full backend | `.venv/Scripts/python.exe -m pytest tests/ -q` with isolated temp/cache directories; `final-backend.log` | Exit 1; 1277 passed, 2 skipped, 41 subtests passed, 1 pre-existing native Blender lease failure |
| Affected backend module after fixture repair | `.venv/Scripts/python.exe -m pytest tests/test_layout2_scenes.py -q` with isolated temp/cache directories; `layout2-scenes-fixed.log` | Exit 0; 42 passed, including real Blender native-save authorization and expired-lease rejection |

The nine browser checks cover rendering, Comic draft flushing before Board navigation, injected HTTP 500 blocking navigation without losing the draft, retry, HTTP 409 discard/reload without another rejected write, Shot draft flushing before a Story route edit, the active Drawing guard and save, Ctrl+S/Home/reopen persistence, and absence of page exceptions. The two console errors are the deliberately injected HTTP 500/409 responses.

The baseline whole-frontend lint had 9 errors and 2 warnings. The refactored App lifecycle removes one existing error; the remaining errors concern `FloatingLayersPanel`, `HomePage`, `ReferenceAssignmentPopover3dApply` and `Scene2DWorkspace`. This is not a green whole-repository lint gate.

The initial backend run encountered the shared Windows pytest-temp ACL problem; the verifier reran with a unique writable `--basetemp`. That isolated baseline had 1223 passes, 2 skips and 3 failures: two stale runtime SVG route subtests and one real Blender lease timing assertion. The copied SVG cleanup addresses the route failures.

The integrated full suite reproduced only the baseline Blender failure. Its retained bridge/heartbeat files prove that startup/save took 8.725 seconds against a 7-second initial lease: the heartbeat arrived 1.725 seconds after expiry and reported a stale lease, with matching session/path/revision. A warm standalone diagnostic passed. Evidence: `native-full-failure-evidence.json`, `native-diagnostic.json`. The native subprocess's positive-control fixture now has a test-only 120-second initial lease (the subprocess timeout is 90 seconds); production remains at 7 seconds, and the negative phase still sets expiry to zero and asserts rejection. The entire affected module then passed 42/42. The full suite was not rerun after that test-only repair; its exit-1 record above is retained.

### Integration and cleanup

Frontend worker commits: `192c67e14b74d254d39cd63ae2b21fbfd9680cda`, `cb1d81da23252b461df2006d5b6d180037d7d68b`. Backend worker commits: `8bbbb24`, `b923a2f`, `94415221862ca081ea150d053a0bf3afb3dab800`. All 10 frontend and 6 backend worker files match their final commits exactly (`integration-worker-match.json`). Root integrated these into the existing working tree and implemented the storage boundary, verification entrypoint and documentation updates.

Both managed worktrees were archived with recoverable snapshots. Their task-only branches and the temporary baseline branch were removed after integration checks. The frontend dependency junction was removed without touching the main dependency directory. The isolated QA server was stopped and port 8137 was confirmed closed. `integrated-refactor.patch` and `integrated-refactor-stat.txt` retain the review diff against the working-source baseline; the integration index was not staged by this work.

### Acceptance limits

Browser/API evidence does not establish packaged desktop, Photoshop, pen-pressure or interactive Blender acceptance. No project format, REST protocol or dependency upgrade was introduced. Existing feature work and the integration index were preserved; no integration-branch commit or push was made.
