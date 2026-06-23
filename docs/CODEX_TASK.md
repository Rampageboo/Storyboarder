# CODEX_TASK.md — Harden Scene 2D Perspective duplication rollback and UI state

Repository:

```text
Rampageboo/Storyboarder
```

Base commit:

```text
861f60f3b5d4b0a0a9903d504dff2a2f2087cdf3
```

## Objective

Finish the reliability pass for the existing Scene 2D **Duplicate perspective** feature.

The current implementation already correctly provides:

```text
Right-click Perspective
→ Duplicate perspective
→ new UUID
→ independent source/preview files
→ inserted immediately after source
→ duplicate selected
→ Primary unchanged
→ References unchanged
```

Preserve all of that.

Fix these remaining issues:

```text
1. Rollback restoration failures are currently swallowed.
2. Duplicate files may be deleted even when metadata rollback was incomplete.
3. The duplicate verifier does not strictly verify Scene meta against scenes2d.json.
4. The duplicate verifier ignores malformed/missing Scene meta.
5. The frontend can end on the wrong Scene if the user switches Scene while duplication is running.
6. Rapid repeated actions need a hard in-flight guard.
7. Add failure-injection tests for partial save, verification failure, and rollback failure.
```

This is a localized reliability task.

Do not redesign Scene 2D.

---

# Product behavior to preserve

Do not change:

```text
left Scene group list
horizontal Perspective strip
floating Inspector
floating zoom controls
drag-to-reorder
Move to scene
Set primary
Add to References
Open in Photoshop
Refresh preview
existing ContextMenu component
```

Do not add whole-Scene duplication.

Do not automatically:

```text
open Photoshop
make the duplicate Primary
add the duplicate to References
move it to another Scene
```

---

# Part 1 — Make rollback explicit and verifiable

## Current problem

The duplicate operation currently behaves approximately like:

```python
try:
    copy files
    save metadata
    verify
except BaseException:
    try:
        restore index
    except:
        pass

    try:
        restore Scene meta
    except:
        pass

    delete duplicate files
    raise
```

This is unsafe.

Possible result:

```text
metadata save succeeds
→ later verification fails
→ metadata restore fails
→ duplicate folder is still deleted
→ scenes2d.json may reference files that no longer exist
```

Do not silently swallow rollback failures.

---

## Required rollback result

Add a small result structure, for example:

```python
@dataclass
class DuplicateRollbackResult:
    index_restored: bool = False
    meta_restored: bool = False
    metadata_verified: bool = False
    duplicate_files_removed: bool = False
```

A dictionary is also acceptable, but fields must be explicit.

Add a helper such as:

```python
def _rollback_perspective_duplicate(
    *,
    index_path: Path,
    index_bytes: bytes | None,
    meta_path: Path,
    meta_bytes: bytes | None,
    new_dir: Path,
    staging_dir: Path,
) -> DuplicateRollbackResult:
    ...
```

---

# Part 2 — Restore and verify metadata before deleting files

Rollback sequence must be:

```text
1. Attempt to restore scenes2d.json.
2. Attempt to restore the Scene meta JSON.
3. Verify both restored files exactly match their pre-operation state.
4. Only after metadata restoration is verified:
   remove new duplicate directory
   remove staging directory
5. If metadata restoration cannot be verified:
   preserve duplicate/staging files
   report rollback failure
```

Use byte-level verification because original bytes are already captured:

```python
def _bytes_match_original(path: Path, original: bytes | None) -> bool:
    if original is None:
        return not path.exists()
    return path.is_file() and path.read_bytes() == original
```

Required:

```text
index_restored = byte-identical or correctly absent
meta_restored = byte-identical or correctly absent
metadata_verified = both true
```

Do not consider rollback complete merely because `_restore_bytes()` returned without throwing.

---

## File cleanup rule

Only remove:

```text
new UUID Perspective directory
.duplicate-<operation-id> staging directory
```

when:

```python
rollback_result.metadata_verified is True
```

If restoration is incomplete:

```text
do not delete new_dir
do not delete staging_dir unless it is definitely unrelated to persisted metadata
```

Keeping extra files is safer than leaving metadata pointing to deleted files.

Hidden staging folders are not loaded as Perspectives, so preserving one after rollback failure is acceptable.

---

# Part 3 — Report both operation and rollback errors

Preserve the original operation error.

When rollback also fails, raise a clear combined error.

Suggested pattern:

```python
except BaseException as operation_error:
    rollback_result = ...
    if not rollback_result.metadata_verified:
        raise RuntimeError(
            "Scene 2D Perspective duplication failed and automatic rollback "
            "could not be verified. Duplicate recovery files were preserved. "
            f"Original error: {operation_error!r}"
        ) from operation_error
    raise
```

Log detailed rollback exceptions with `LOGGER.exception()` or equivalent.

Do not use:

```python
except Exception:
    pass
```

for metadata rollback.

The API may still return HTTP 500 for unexpected copy/save/verification failures.

Do not convert rollback corruption into a misleading HTTP 400.

---

# Part 4 — Strict duplicate verification

Strengthen:

```python
_verify_perspective_duplicate(...)
```

The verifier must treat these as failures:

```text
scenes2d.json missing
scenes2d.json malformed
Scene missing from index
Scene meta missing
Scene meta malformed
Scene meta is not an object
Perspective order differs
Primary differs
source/preview paths differ
duplicate metadata differs
```

Do not suppress Scene meta parsing failures.

Remove logic equivalent to:

```python
except (...):
    pass
```

from required persistence verification.

---

## Compare canonical Scene metadata

Read the target Scene independently from:

```text
scenes2d/scenes2d.json
scenes2d/<scene-id>/<scene-id>_meta.json
```

Normalize both using the existing Scene normalization logic.

Then compare the complete canonical Scene payload, including:

```text
Scene id
title
description
linked_scene3d_id
primary_perspective_id
can_be_reference
Perspective order
Perspective IDs
titles
types
source_file_path
preview_image_path
linked_scene3d_id
linked_scene3d_view
created_at
updated_at
```

Do not sort Perspective IDs before comparison.

Ordering is meaningful.

Suggested:

```python
index_scene = _normalize_scene(index_scene_raw, legacy=True)
meta_scene = _normalize_scene(meta_raw, legacy=True)

if index_scene != meta_scene:
    raise ValueError("Duplicate verify: Scene meta disagrees with scenes2d.json.")
```

Be careful not to call migration or recovery logic that rewrites files merely to verify them.

---

# Part 5 — Verify original data was unchanged

Before duplication, capture:

```text
source file bytes or SHA-256
source preview bytes or SHA-256 when present
original Primary ID
canonical Reference links
```

After save, verify:

```text
source file still exists
source file hash unchanged
source preview hash unchanged when it existed
Primary ID unchanged
Reference links semantically unchanged
```

Current verification only checks that no Reference points to the duplicate.

Strengthen it to ensure the complete normalized Reference list is unchanged:

```python
references_before = project_manager.normalize_reference_links(...)
references_after = project_manager.normalize_reference_links(...)

if references_after != references_before:
    raise ValueError("Duplicate verify: reference links changed during duplication.")
```

Pass the expected values into the verifier explicitly.

Do not mutate `settings.json`.

---

# Part 6 — Keep returned data consistent after verification

After successful save and verification, return data that matches the verified persisted data.

Prefer re-reading the verified Scene from canonical storage, or ensure the returned local objects are exactly the same normalized objects written by `_save_scenes()`.

Avoid returning a stale pre-normalization object.

Return shape remains:

```json
{
  "scene": {},
  "perspective": {},
  "scenes": []
}
```

Do not change the REST contract.

---

# Part 7 — Fix frontend Scene-switch race

## Current problem

The duplicate callback captures the correct source Scene ID, but after the asynchronous request succeeds it currently only runs:

```ts
setScenes(payload.scenes)
setSelectedPerspectiveId(payload.perspective.id)
```

During the request, the user can click another Scene in the Scene list.

The duplicate then exists in the original Scene, while the UI may remain on a different Scene.

---

## Required success update

Capture the source Scene ID before starting:

```ts
const sourceSceneId = selectedScene.id
```

Call the API with that explicit ID.

After success:

```ts
setScenes(payload.scenes)
setSelectedSceneId(payload.scene.id)
setSelectedPerspectiveId(payload.perspective.id)
```

This guarantees the newly duplicated Perspective is visible and selected.

Do not depend on whatever Scene happens to be selected when the request finishes.

---

# Part 8 — Add a hard duplicate in-flight guard

React `setBusy(true)` is asynchronous and is not by itself a strict double-action guard.

Add:

```ts
const duplicateInFlightRef = useRef(false)
```

Required callback pattern:

```ts
if (duplicateInFlightRef.current) return
duplicateInFlightRef.current = true
setContextMenu(null)
setBusy(true)

try {
  ...
} finally {
  duplicateInFlightRef.current = false
  setBusy(false)
}
```

One user action must generate one request.

The existing menu item should remain disabled while `busy` is true.

Do not create multiple duplicate-specific UI states unless necessary.

---

# Part 9 — Preserve clicked-Perspective targeting

Continue to pass the explicit Perspective ID stored in:

```ts
contextMenu.perspectiveId
```

Do not change duplication to rely solely on:

```ts
selectedPerspective
```

The right-clicked Perspective must be the one duplicated, even if selection changes before the callback begins.

Capture:

```ts
const sourcePerspective =
  selectedScene.perspectives.find((item) => item.id === perspectiveId)
```

before awaiting.

The toast should continue to use human-readable titles.

---

# Part 10 — Backend failure-injection tests

Add tests to `tests/test_scene2d.py`.

## Preview-copy failure

Patch `shutil.copy2` so:

```text
source copy succeeds
preview copy fails
```

Assert:

```text
HTTP 500
source files unchanged
index unchanged
Scene meta unchanged
no visible duplicate metadata
no final duplicate directory
no staging directory when rollback verified
```

---

## Verification failure after successful save

Patch:

```python
_verify_perspective_duplicate
```

to raise after `_save_scenes()` succeeds.

Assert:

```text
index restored byte-for-byte
Scene meta restored byte-for-byte
new duplicate directory removed
source unchanged
References unchanged
```

---

## Partial save failure

Simulate:

```text
scenes2d.json is written
Scene meta write then fails
```

Do not only mock `_save_scenes()` before it writes anything.

Patch the atomic-write layer or provide a side effect based on the target path.

Assert rollback restores both files.

---

## Index rollback failure

Cause the operation to fail after metadata save, then make restoration of `scenes2d.json` fail.

Assert:

```text
request returns 500
rollback failure is visible in the error/log
new duplicate directory is preserved
it is not deleted
no silent pass occurs
```

---

## Scene meta rollback failure

Same as above, but fail restoration of Scene meta.

Assert:

```text
new duplicate directory is preserved
rollback is reported as unverified
source remains intact
```

---

## Malformed Scene meta verification

After save, corrupt the Scene meta JSON before verification.

Assert:

```text
verification fails
rollback runs
original Scene meta is restored
duplicate directory is removed only after successful rollback verification
```

---

## Order mismatch verification

Modify only the Perspective order in Scene meta.

Assert verifier rejects it.

Do not compare sorted IDs.

---

## Path mismatch verification

Change duplicate `source_file_path` or `preview_image_path` only in Scene meta.

Assert verifier rejects it.

---

# Part 11 — Frontend validation

Where React component test infrastructure exists, add tests for:

```text
right-click menu includes Duplicate perspective
clicked Perspective ID is sent to duplicate API
returned source Scene becomes selected
returned duplicate becomes selected
two rapid calls result in one API request
```

If no usable component-test infrastructure exists:

```text
keep callback logic small
run TypeScript build
perform manual validation
report that component behavior was not automated
```

Do not add brittle source-text assertions as the only frontend test.

---

# Part 12 — Existing tests to preserve

The following must continue passing:

```text
PSD with preview duplication
PSD without preview
Image duplication
extension preservation
Copy / Copy 2 / Copy 3
deep-copy linked_scene3d_view
first/middle/last insertion
Primary unchanged
References unchanged
missing source returns 404
API response shape
```

Do not weaken existing assertions to make new tests pass.

---

# Part 13 — Manual validation

## Normal duplicate

```text
1. Right-click a Perspective.
2. Choose Duplicate perspective.
3. Confirm the copy appears directly after the source.
4. Confirm the source Scene remains selected.
5. Confirm the new duplicate is selected.
6. Confirm Primary is unchanged.
```

## Scene-switch race

```text
1. Start duplicating a large PSD.
2. Immediately click another Scene.
3. When duplication finishes, confirm the UI returns to the source Scene.
4. Confirm the new duplicate is selected and visible.
```

## Repeat-action protection

```text
1. Right-click a large Perspective.
2. Trigger Duplicate repeatedly as quickly as possible.
3. Confirm exactly one duplicate is created for one accepted action.
```

## Independent files

```text
1. Duplicate a PSD Perspective.
2. Edit and save the duplicate PSD.
3. Confirm the original PSD remains unchanged.
```

## References

```text
1. Add the source Perspective to References.
2. Duplicate it.
3. Confirm only the source remains in References.
```

---

# Part 14 — Task-scoped self-review

Before finishing:

```text
inspect the full diff
inspect duplicate_perspective callers and return consumers
inspect all rollback branches
inspect verifier failure branches
inspect ContextMenu callback timing
inspect duplicate API error mapping
```

Explicitly check:

```text
no swallowed rollback exception
no deletion of recovery files after unverified rollback
no second source of truth for selected Scene
no accidental Primary change
no accidental Reference duplication
no layout changes
```

---

# Required commands

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests/test_scene2d.py -q
.venv\Scripts\python.exe -m pytest tests/ -q
```

Build:

```powershell
cd frontend
npm.cmd run build
```

Run any existing frontend component tests relevant to Scene 2D.

Do not claim tests passed unless actually executed.

---

# Acceptance-criteria matrix

Before committing, provide a matrix:

```text
Requirement
Implementation location
Test location
Verification result
```

Required rows:

```text
rollback restore errors are not swallowed
metadata restoration is byte-verified
duplicate files removed only after verified rollback
duplicate files preserved after rollback failure
missing/malformed Scene meta fails verification
Perspective order compared exactly
full canonical Scene meta compared
source file remains unchanged
source preview remains unchanged
References remain unchanged
source Scene selected after duplicate
duplicate selected after success
double-action guard
existing duplicate behavior preserved
```

Do not commit while a required row is blank.

---

# Acceptance criteria

Complete only when:

```text
- ordinary duplication still works
- rollback restoration failures are reported
- duplicate files are not deleted after unverified rollback
- metadata rollback is byte-verified
- Scene meta verification is strict
- Perspective ordering differences are detected
- full canonical Scene metadata agrees
- source files remain unchanged
- References remain unchanged
- the UI returns to the source Scene after duplication
- the returned duplicate is selected
- rapid repeat actions cannot create unintended duplicate requests
- all focused tests pass
- full backend tests pass
- frontend build passes
```

---

# Suggested commit

```text
fix: harden Scene 2D duplicate rollback
```

---

# Output required

Report:

```text
Changed files

Rollback:
  restoration sequence
  verification rules
  cleanup rules
  rollback-failure behavior

Verifier:
  index checks
  Scene meta checks
  order comparison
  path comparison
  source integrity
  Reference integrity

Frontend:
  source Scene selection
  duplicate selection
  in-flight guard

Focused tests
Full pytest result
Frontend build result
Manual validation performed
Manual validation not performed
Known limitations
Acceptance-criteria matrix
Final commit SHA
```
