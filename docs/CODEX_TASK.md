# CODEX_TASK_P1_FIXES.md — Fix remaining Scene 2D plugin P1 reliability issues

Repo:

```text
Rampageboo/Storyboarder
```

Base commit:

```text
2f810d7281e2232bf38f3277443af15fb6c983d1
```

## Goal

Fix the three remaining P1 reliability issues in the Scene 2D Photoshop integration:

```text
1. Backend open/focus decisions use stale runtime heartbeat state instead of the newest validated heartbeat source.

2. Shot-only automatic background/canvas synchronization may still modify a Scene 2D or unrelated Photoshop document.

3. Scene 2D UUID migration crash recovery may roll forward after scenes2d.json is committed even when settings.json/reference_links are still legacy or incomplete.
```

These are release-blocking data-safety and workflow issues.

Do not include P2 cleanup, broad refactors, or UI redesign.

---

# P1-1 — Use one authoritative validated plugin work-key state

## Current problem

The plugin normally writes its heartbeat to:

```text
C:/Users/Public/StoryboardTool/storyboard_plugin_heartbeat.json
```

When that succeeds, it may not send the HTTP heartbeat.

`/api/bridge/status` now combines:

```text
file heartbeat
HTTP/runtime heartbeat
timestamp freshness
backend work-item validation
```

However, `method_open_scene2d_perspective()` still directly checks:

```python
runtime_state.plugin_open_work_keys(self.app)
```

That value may be stale or empty even when the file heartbeat is newer.

This creates two failure modes:

```text
Perspective is already open
→ runtime state says closed
→ Storyboarder opens it again

Perspective was closed
→ stale runtime state says open
→ backend sends a dead focus request
→ PSD is not reopened
```

---

## Required solution

Create one shared backend helper that returns the newest validated plugin state for the current project.

Suggested public helper location:

```text
storyboard_tool/app_state.py
```

Suggested API:

```python
def plugin_work_key_state(app: FastAPI) -> tuple[str, list[str]]:
    """
    Return:
      active_work_key
      open_work_keys

    Source:
      newest valid file or HTTP heartbeat

    Validation:
      only backend-generated current-project work-item keys
    """
```

It may reuse the current internal logic in:

```text
_plugin_work_key_state()
_valid_plugin_work_keys()
```

Rename or expose these helpers cleanly rather than duplicating the logic.

---

## Authoritative source rules

The helper must:

```text
1. Determine whether file heartbeat or HTTP heartbeat is newer.
2. Respect explicitly empty fields from the newer heartbeat.
3. Validate all work keys against current PluginBridgeService.work_items(project).
4. Remove duplicate open keys.
5. Ignore malformed, deleted, stale, or cross-project keys.
6. Return empty state when no project or plugin is not linked.
```

Important:

```text
newer heartbeat says open_work_keys: []
```

must mean “nothing is open”.

Do not fall back to an older non-empty value merely because the newer list is empty.

The same applies to:

```text
active_work_key: ""
selected_shot_id: ""
open_shot_ids: []
```

---

## Use the shared helper everywhere decisions are made

Replace direct reads of:

```python
runtime_state.plugin_open_work_keys(app)
runtime_state.plugin_active_work_key(app)
```

where the code is making a real open/focus decision.

At minimum update:

```text
storyboard_tool/backend_service.py
  method_open_scene2d_perspective()

any shot open/focus path that decides:
  already open → focus
  not open → launch/open PSD
```

The bridge status payload must also continue using this same helper.

Target behavior:

```python
active_key, open_keys = app_state.plugin_work_key_state(self.app)

if work_key in open_keys:
    request path-based focus
else:
    open the PSD
```

Do not use unvalidated heartbeat values for open/focus decisions.

---

## Tests for P1-1

Add tests covering both heartbeat channels and freshness.

Required cases:

```text
1. File heartbeat newer, Perspective open:
   open endpoint issues focus request
   open_project_file is not called

2. File heartbeat newer, explicitly empty open_work_keys:
   stale HTTP runtime says open
   open endpoint opens the PSD instead of focusing

3. HTTP heartbeat newer:
   its validated open keys are used

4. File heartbeat includes unknown key:
   key is ignored
   PSD is opened

5. File heartbeat reports deleted Perspective:
   key is ignored

6. Two identical source.psd work items:
   correct key is used only when explicitly reported

7. Newer heartbeat has active_work_key = "":
   stale active key is not resurrected
```

Tests should assert whether:

```text
project_manager.open_project_file
runtime_state.request_work_context_focus
```

were called.

Do not only assert the final HTTP status.

---

# P1-2 — Isolate all shot-only Photoshop automation

## Current problem

The plugin now correctly detects:

```text
shot
scene2d
unmatched
```

However, parts of the old shot workflow still run globally inside bridge polling.

Examples include:

```js
const shotId = detectShotFromDocument() || live.selected_shot_id;
```

and:

```js
if (colorChanged && app.activeDocument && isAutoApplyColorEnabled()) {
  await applyCanvasBackground();
}
```

When the active document is a Scene 2D `source.psd`, the fallback to `live.selected_shot_id` may cause shot-only automation to modify that Scene 2D PSD.

This can alter:

```text
Background layer
SB bg
canvas color
shot-specific layer state
```

Scene 2D must preserve its own visible composite and normal user background layers.

---

## Required rule

The active work context controls what automation may run.

```text
active context kind == shot
  shot-only behavior allowed

active context kind == scene2d
  no shot-only document mutation

active context kind == unmatched
  no project document mutation
```

Do not use `live.selected_shot_id` as proof that the active Photoshop document is a shot.

The actual active document match is authoritative.

---

## Add explicit context predicates

Suggested helpers:

```js
function activeIsShot() {
  return activeWorkContext()?.kind === "shot";
}

function activeIsScene2D() {
  return activeWorkContext()?.kind === "scene2d";
}

function activeIsUnmatched() {
  return activeWorkContext()?.kind === "unmatched";
}
```

Use them consistently.

---

## Protect all shot-only behavior

Audit and guard at least:

```text
applyCanvasBackground()
scheduleBackgroundSyncForActiveDocument()
syncActiveDocumentBackground()
ensureTemplateLayersForActiveDocument()
shotFolder assignment based on selected shot
shot status/quick note actions
shot onion skin operations
shot preview save/export
SB bg synchronization
shot-only layer repair
auto-apply canvas color
```

The required pattern is:

```js
const ctx = activeWorkContext();

if (ctx?.kind !== "shot") {
  return;
}
```

For user-triggered shot buttons, throw a clear message instead of silently returning:

```text
The active Photoshop document is not a storyboard shot.
Activate a linked shot PSD first.
```

For automatic background polling, silently skip Scene 2D and unmatched documents.

---

## Fix `applyLiveBridge()`

Do not do this globally:

```js
const shotId = detectShotFromDocument() || live.selected_shot_id;
```

Use the synchronized active context:

```js
const activeCtx = activeWorkContext();

if (activeCtx?.kind === "shot") {
  const shotId = activeCtx.shot_id;
  // shot selection, shot folder, background sync
}
```

`live.selected_shot_id` may remain useful as a pending Storyboarder selection only when:

```text
there is no active Photoshop document
```

It must not override a Scene 2D or unmatched active document.

---

## Auto canvas color rule

Change:

```js
if (colorChanged && app.activeDocument && isAutoApplyColorEnabled()) {
  await applyCanvasBackground();
}
```

to the equivalent of:

```js
if (
  colorChanged &&
  app.activeDocument &&
  activeWorkContext()?.kind === "shot" &&
  isAutoApplyColorEnabled()
) {
  await applyCanvasBackground();
}
```

Also make `applyCanvasBackground()` itself validate the context so it remains safe if called from another path.

Use defense in depth:

```text
caller guard
+
function-level guard
```

---

## Scene 2D must never receive shot background automation

Verify that while a Scene 2D tab is active:

```text
canvas background color changes in Storyboarder
plugin bridge polling occurs
selected shot changes in Storyboarder
plugin reconnects
```

none of these operations modify the Scene 2D document.

The same rule applies to an unrelated PSD.

---

## Tests for P1-2

Where possible, extract pure decision helpers.

Suggested pure helper:

```js
function shouldRunShotAutomation(workContext) {
  return workContext?.kind === "shot";
}
```

Add Node tests for:

```text
shot → true
scene2d → false
unmatched → false
null → false
```

Also add static or integration checks ensuring:

```text
applyCanvasBackground has an internal shot guard
syncActiveDocumentBackground has a shot guard
applyLiveBridge only schedules shot background sync in shot mode
```

Manual UXP test remains mandatory:

```text
1. Open a shot PSD.
2. Confirm normal shot background sync still works.
3. Open a Scene 2D source.psd.
4. Change Storyboarder canvas color.
5. Wait through several bridge polls.
6. Confirm Scene 2D layers and background remain unchanged.
7. Open an unrelated PSD and repeat.
8. Return to shot PSD.
9. Confirm shot background sync resumes.
```

---

# P1-3 — Verify settings/reference links before migration roll-forward

## Current problem

Migration commit order is broadly:

```text
write UUID scenes2d.json
write UUID scene meta files
write migrated settings.json/reference_links
mark metadata_committed
```

A hard crash can occur after `scenes2d.json` is valid but before `settings.json` is updated.

Current crash recovery for:

```text
state == metadata_committing
```

mainly verifies the UUID Scene payload and source files.

It may roll forward even though `settings.json` still contains:

```text
source_scene2d_id = scene_001
source_scene2d_perspective_id = persp_001
legacy preview path
```

Then legacy directories may be deleted while reference links remain stale.

---

## Required journal additions

When preparing the migration, persist enough expected information to verify the settings commit.

Add fields such as:

```json
{
  "settings_changed": true,
  "expected_reference_links": [
    {
      "id": "...",
      "source_scene2d_id": "<scene_uuid>",
      "source_scene2d_perspective_id": "<perspective_uuid>",
      "path": "scenes2d/<scene_uuid>/perspectives/<perspective_uuid>/preview.png"
    }
  ],
  "expected_settings_hash": "<sha256>"
}
```

Choose either:

```text
full expected migrated settings hash
```

or:

```text
canonical expected affected reference links
```

Using both is acceptable.

Do not place sensitive absolute filesystem paths in the journal.

All stored paths must remain project-relative.

---

## Canonical hashing

If using a settings hash:

```python
json.dumps(
    settings,
    sort_keys=True,
    separators=(",", ":"),
    ensure_ascii=False,
)
```

Then compute:

```python
hashlib.sha256(encoded_json).hexdigest()
```

Do not hash raw pretty-printed file bytes because formatting changes are not semantic.

---

## Add a complete commit verifier

Create a helper such as:

```python
def _verify_migration_commit(
    project: Project,
    journal: dict[str, Any],
) -> None:
    ...
```

It must validate all of the following:

### Scene payload

```text
- scenes2d.json is valid JSON
- expected migrated Scene UUIDs exist
- every Perspective ID is a UUID
- every Perspective source path is canonical
- every Perspective preview path is canonical
- required source files exist
- image Perspective preview/source exists
```

### Settings payload

If `settings_changed` is true:

```text
- settings.json exists
- settings.json is valid JSON
- semantic settings hash matches the expected migrated settings
  OR all affected reference links match the expected migrated values
```

### Reference links

For every migrated Scene 2D reference:

```text
- source_scene2d_id uses the expected Scene UUID
- source_scene2d_perspective_id uses the expected Perspective UUID
- path points to the expected UUID preview path
- no affected legacy scene_### or persp_### key remains
```

Do not reject unrelated non-Scene2D reference links.

---

## Recovery decision

For journal state:

```text
metadata_committing
```

Roll forward only when `_verify_migration_commit()` fully passes.

If any Scene or settings requirement fails:

```text
restore original canonical files from .uuid_migration_backup
restore settings.json
restore in-memory project.settings
remove only UUID paths created by this migration
keep all legacy files
remove journal and backup only after successful rollback
```

For:

```text
metadata_committed
cleanup_pending
```

also run the complete verifier before deleting legacy roots.

If verification fails at these states:

```text
do not delete legacy roots
do not remove backups
raise a clear recovery error
```

Be conservative. Data preservation is more important than automatic cleanup.

---

## Ensure in-memory settings consistency

After successful roll-forward:

```python
project.settings = parsed_verified_settings
```

After rollback:

```python
project.settings = restored_original_settings
```

Do not leave disk and memory different.

---

## Tests for P1-3

Add crash-recovery tests.

### Case 1 — Scene metadata committed, settings still legacy

Setup:

```text
journal state = metadata_committing
UUID scenes2d.json is valid
UUID source files exist
settings.json still references scene_001 / persp_001
```

Expected:

```text
rollback
legacy canonical metadata restored
legacy files retained
UUID staged paths removed
```

### Case 2 — Settings partially migrated

One field UUID, another field legacy.

Expected:

```text
rollback
```

### Case 3 — Reference path remains legacy

IDs are UUID but `path` points to old preview.

Expected:

```text
rollback
```

### Case 4 — Complete UUID Scene and settings payload

Expected:

```text
roll forward
legacy roots cleaned
journal removed
backup area removed
project.settings equals verified disk settings
```

### Case 5 — Unrelated reference links

Ensure non-Scene2D references do not block valid roll-forward.

### Case 6 — Corrupt settings JSON

Expected:

```text
no roll-forward
no legacy deletion
safe rollback or clear recovery error
```

### Case 7 — `metadata_committed` but settings invalid

Expected:

```text
legacy roots are not deleted
backup and journal remain available
clear error is returned
```

---

# Scope

Likely files:

```text
storyboard_tool/app_state.py
storyboard_tool/backend_service.py
storyboard_tool/plugin_service.py
storyboard_tool/runtime_state.py
storyboard_tool/scene2d.py

photoshop_uxp_plugin/panel.js
photoshop_uxp_plugin/preview_export.js
photoshop_uxp_plugin/backend_client.js

tests/test_plugin_scene2d.py
tests/test_photoshop_bridge.py
tests/test_scene2d_migration.py
tests/test_plugin_work_item_paths.mjs
```

Change additional files only where required by these three P1 issues.

---

# Do not change

```text
Scene 2D UUID model
Scene 2D canonical source.psd / preview.png paths
shot ID format
shot folder structure
Scene 3D architecture
SB bg embedded reference behavior
shot transparent preview export semantics
Scene 2D visible-composite export semantics
preview-analysis lifecycle
splash lifecycle
plugin package/two-panel architecture
```

Do not include:

```text
Windows full-path lowercase P2
preview-analysis retry P2
plugin UI redesign
image-to-PSD conversion
Perspective onion skin
```

---

# Required validation

## Backend tests

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests/test_plugin_scene2d.py -q
.venv\Scripts\python.exe -m pytest tests/test_photoshop_bridge.py -q
.venv\Scripts\python.exe -m pytest tests/test_scene2d_migration.py -q
```

Then:

```powershell
.venv\Scripts\python.exe -m pytest tests/ -q
```

## Plugin helper tests

Run:

```powershell
node --test tests/test_plugin_work_item_paths.mjs
```

## Frontend build

Even if no frontend code changes are expected, run:

```powershell
cd frontend
npm.cmd run build
```

## Manual Photoshop validation

Mandatory:

```text
1. Open a shot PSD.
2. Confirm shot background sync works.
3. Open a Scene 2D source.psd.
4. Change canvas background color in Storyboarder.
5. Confirm Scene 2D PSD is not modified.
6. Switch selected shot in Storyboarder.
7. Confirm Scene 2D PSD remains untouched.
8. Open an unrelated PSD.
9. Confirm no shot automation affects it.
10. Return to shot PSD.
11. Confirm shot automation resumes.
12. Open an already-open Scene 2D Perspective from Storyboarder.
13. Confirm path-based focus occurs.
14. Close that tab.
15. Wait for a fresh file heartbeat.
16. Click Open again.
17. Confirm the PSD reopens instead of receiving a dead focus request.
```

Do not claim manual validation passed unless Photoshop was actually used.

---

# Acceptance criteria

This task is complete only when:

```text
- every backend open/focus decision uses the same newest validated heartbeat state
- explicitly empty newer heartbeat values override stale non-empty state
- Scene 2D and unmatched documents cannot receive shot background/canvas automation
- Scene 2D export remains functional
- shot background workflow remains functional
- migration cannot roll forward while settings/reference links are incomplete
- metadata_committed cleanup never deletes legacy roots when full commit verification fails
- all focused and full tests pass
- manual Photoshop smoke test is reported honestly
```

---

# Suggested commit structure

One remediation task, optionally split into three commits:

```text
fix: use authoritative plugin heartbeat state

fix: isolate shot automation from Scene2D documents

fix: verify migration settings before roll-forward
```

All three must be completed before stopping.

---

# Output required

Report:

```text
Commits created
Changed files

Authoritative heartbeat-state helper
Every caller migrated to the shared helper
How explicit empty heartbeat fields are handled
Tests covering file-vs-HTTP freshness

Shot-only automation guards
Functions protected
Manual Scene2D/unmatched document validation

Migration journal additions
Settings/reference verification algorithm
Rollback and roll-forward decision rules
Crash-recovery tests added

Focused pytest results
Full pytest result
Node test result
Frontend build result
Manual Photoshop validation result
Known limitations
Final commit SHA
```
