# CODEX_TASK.md — Photoshop plugin Scene 2D work-context handoff

Repo: `Rampageboo/Storyboarder`

Prerequisite:

```text
The Scene 2D UUID and stable-path migration task has already landed.
```

Do not begin this task while Scene 2D still uses mutable or sequential canonical IDs.

## Goal

Allow the Photoshop UXP plugin to naturally take over when a user opens a Scene 2D PSD Perspective from Storyboarder.

The plugin must explicitly understand whether the active Photoshop document represents:

```text
a Storyboard shot
or
a Scene 2D Perspective
```

Do not represent a Scene 2D Perspective as a fake shot.

Do not infer identity from editable titles.

Use immutable Scene 2D and Perspective UUIDs.

---

# Core principle

Introduce a generic work context shared by:

```text
Storyboarder frontend
FastAPI backend
live bridge
Photoshop UXP plugin
```

Supported work-context kinds:

```text
shot
scene2d
```

The context must explicitly define the active editable asset.

---

# Canonical work-context shapes

## Shot

```json
{
  "kind": "shot",
  "key": "shot:shot_001",
  "shot_id": "shot_001",
  "source_file_path": "shots/shot_001/shot_001.psd",
  "preview_image_path": "shots/shot_001/shot_001_preview.png"
}
```

## Scene 2D Perspective

```json
{
  "kind": "scene2d",
  "key": "scene2d:550e8400-e29b-41d4-a716-446655440000:f0b14cf5-15ad-44ae-a623-871930a92d3f",
  "scene_id": "550e8400-e29b-41d4-a716-446655440000",
  "perspective_id": "f0b14cf5-15ad-44ae-a623-871930a92d3f",
  "scene_title": "Living Room",
  "perspective_title": "Door View",
  "perspective_type": "psd",
  "source_file_path": "scenes2d/550e8400-e29b-41d4-a716-446655440000/perspectives/f0b14cf5-15ad-44ae-a623-871930a92d3f/source.psd",
  "preview_image_path": "scenes2d/550e8400-e29b-41d4-a716-446655440000/perspectives/f0b14cf5-15ad-44ae-a623-871930a92d3f/preview.png",
  "index": 1,
  "count": 4,
  "previous_key": "",
  "next_key": "scene2d:550e8400-e29b-41d4-a716-446655440000:..."
}
```

Titles are display metadata only.

Identity must use UUIDs and stable source paths.

---

# Part 1 — Generic runtime work context

Current runtime state is shot-specific.

Add generic state such as:

```text
active_work_context
focus_work_context
focus_token
plugin_active_work_key
plugin_open_work_keys
```

Preserve existing shot-specific fields temporarily for backward compatibility:

```text
live_selected_shot_id
plugin_selected_shot_id
plugin_open_shot_ids
```

When the active work context is a shot, keep old fields synchronized.

When it is Scene 2D, do not populate a fake selected shot.

Add typed helpers:

```python
def active_work_context(app) -> dict[str, Any]:
    ...

def set_active_shot_context(app, shot_id: str) -> None:
    ...

def set_active_scene2d_context(
    app,
    scene_id: str,
    perspective_id: str,
) -> None:
    ...

def request_work_context_focus(app, context: dict[str, Any]) -> None:
    ...
```

Validate that Scene and Perspective UUIDs exist before accepting context.

---

# Part 2 — Plugin context payload

Extend:

```text
GET /api/plugin/context
```

to return:

```json
{
  "work_context": {},
  "work_items": [],
  "selected_shot_id": "...",
  "shots": [],
  "canvas": {},
  "bridge": {}
}
```

Keep existing shot fields so the current plugin does not break during migration.

## work_items

Return editable PSD work items for:

```text
all shots
all Scene 2D PSD Perspectives
```

Suggested shape:

```json
{
  "kind": "scene2d",
  "key": "scene2d:<scene_uuid>:<perspective_uuid>",
  "label": "Living Room / Door View",
  "source_file_path": ".../source.psd",
  "preview_image_path": ".../preview.png",
  "scene_id": "<uuid>",
  "perspective_id": "<uuid>"
}
```

Do not include image Perspectives as directly editable PSD work items.

For image Perspectives, provide read-only metadata if useful.

---

# Part 3 — Opening Scene 2D from Storyboarder

When the user clicks:

```text
Open in Photoshop
```

for a Scene 2D PSD Perspective, backend behavior must become:

```text
1. Validate Scene UUID and Perspective UUID.
2. Verify Perspective type is PSD.
3. Ensure source.psd exists.
4. Set active Scene 2D work context.
5. Publish bridge state.
6. If plugin reports the PSD already open:
   request plugin focus using work key.
7. Otherwise launch/open Photoshop with source.psd.
8. Return the active work context.
```

Update:

```text
POST /api/project/scenes2d/{scene_id}/perspectives/{perspective_id}/open
```

Do not merely call the OS open function without updating context.

---

# Part 4 — Generic focus requests

Current bridge focus request is shot-specific.

Replace or extend:

```json
{
  "focus_request": {
    "kind": "scene2d",
    "key": "scene2d:<scene_uuid>:<perspective_uuid>",
    "source_file_path": ".../source.psd",
    "token": 12
  }
}
```

Maintain backward-compatible:

```text
shot_id
```

for shot focus requests if needed.

The plugin must act only when the token increases.

Passive bridge polling must never unexpectedly switch Photoshop tabs.

---

# Part 5 — Plugin heartbeat

Extend plugin heartbeat to report:

```json
{
  "active_work_key": "scene2d:<scene_uuid>:<perspective_uuid>",
  "active_document_path": "C:/.../source.psd",
  "open_work_keys": [
    "shot:shot_001",
    "scene2d:<scene_uuid>:<perspective_uuid>"
  ],
  "selected_shot_id": "",
  "open_shot_ids": []
}
```

Preserve the old shot fields.

Backend must store and expose:

```text
plugin_active_work_key
plugin_open_work_keys
```

Do not trust arbitrary keys from the plugin without matching them against backend-generated work items.

---

# Part 6 — Active Photoshop document detection

Current plugin detection is shot-specific.

Add generic detection:

```js
detectWorkItemFromDocument()
```

Matching order:

```text
1. normalized full native source path
2. normalized project-relative source path
3. exact backend work-item path
4. filename only as final non-authoritative fallback
```

Do not use titles for identity.

Do not identify Scene 2D Perspective by:

```text
Living Room
Door View
source filename derived from title
```

because titles can change.

Normalize Windows paths case-insensitively.

Handle slash differences safely.

---

# Part 7 — Plugin UI modes

The plugin has two panels:

```text
Storyboard Bridge
Storyboard Work
```

Keep both panels.

Add two UI modes:

```text
Shot mode
Scene 2D mode
```

## Bridge panel — Shot mode

Preserve current behavior:

```text
shot card
shot status
quick note
shot notes
Export preview
Export & next
auto-add at end
```

## Bridge panel — Scene 2D mode

Display:

```text
Scene 2D
Scene title
Perspective title
Perspective X of Y
PSD
```

Buttons:

```text
Export preview
Export & next perspective
Focus Storyboarder after preview export
```

Hide:

```text
shot status buttons
quick note
shot notes
duration
auto-add shot
shot-specific recovery actions unless explicitly compatible
```

Update the current card dynamically rather than duplicating an entirely separate panel if practical.

---

# Part 8 — Work panel Scene 2D mode

## Shot mode

Preserve:

```text
Shot selector
Previous
Next
Open canvas
Focus open tab
Onion skin
```

## Scene 2D mode

Show:

```text
Scene group
Perspective selector
Previous perspective
Next perspective
Open perspective
Focus open tab
```

Hide shot onion-skin tools for the first Scene 2D integration.

Do not apply shot onion-skin semantics to Scene 2D Perspectives.

Do not add Perspective overlay behavior in this task.

---

# Part 9 — Separate Scene 2D preview export

This is a critical safety boundary.

Do not route Scene 2D export through shot export logic.

Add a dedicated function:

```js
exportScene2DPerspectivePreview()
```

and a dedicated endpoint:

```text
POST /api/plugin/scenes2d/{scene_id}/perspectives/{perspective_id}/export-preview
```

## Scene 2D export behavior

Export the visible Scene 2D composite to:

```text
perspective.preview_image_path
```

For Scene 2D:

```text
- preserve normal visible artwork/background layers
- hide only temporary plugin overlay layers if present
- do not force transparent artist-foreground semantics
- do not hide normal user background layers
```

Shot export behavior must remain unchanged.

The backend must derive the destination path from Scene 2D metadata.

Do not allow the plugin to supply an arbitrary destination filesystem path.

Backend validation:

```text
Scene exists
Perspective exists
Perspective type is PSD
source file exists
preview path resolves inside project root
exported PNG exists
```

After success:

```text
update Perspective.updated_at
update Scene.updated_at
save Scene 2D metadata atomically
increment plugin change revision
return updated work context
```

Do not modify:

```text
shots.csv
shot.source_file_path
shot.preview_image_path
shot.image_path
shot.thumbnail_path
shot status
```

---

# Part 10 — PSD saved event

Add:

```text
POST /api/plugin/scenes2d/{scene_id}/perspectives/{perspective_id}/psd-saved
```

This endpoint should:

```text
verify the expected source.psd exists
update timestamps if required
increment Scene 2D change revision
return updated work context
```

It must not update shot state.

---

# Part 11 — Export & next perspective

Scene 2D behavior:

```text
1. Export current Perspective preview.
2. Find the next Perspective in the same Scene group.
3. If it is a PSD:
   open or focus it.
4. Set active work context to that Perspective.
```

At the final Perspective:

```text
- do not create a new Perspective
- do not move to another Scene group
- remain on the current Perspective
- display “Last perspective in this scene”
```

Do not reuse:

```text
autoAddAtEnd
```

That setting is shot-specific.

Image Perspectives should be skipped or handled as read-only, with clear behavior.

---

# Part 12 — Image Perspective behavior

For:

```text
perspective.type == "image"
```

do not let the plugin overwrite the imported source image.

Display:

```text
Image Perspective
Read-only source
Convert to PSD in Storyboarder to edit
```

Do not implement image-to-PSD conversion in this task.

Do not include image Perspectives in Export & next editable sequence unless a clear read-only skip is implemented.

---

# Part 13 — Storyboarder automatic preview refresh

After plugin exports a Scene 2D preview, the Scene 2D workspace should refresh automatically.

Extend bridge status with a generic plugin change payload:

```json
{
  "plugin_change": {
    "revision": 15,
    "kind": "scene2d",
    "scene_id": "<scene_uuid>",
    "perspective_id": "<perspective_uuid>"
  }
}
```

For shot changes, preserve current project refresh behavior.

For Scene 2D changes:

```text
Scene2DPanel reloads Scene 2D data
preserves selectedSceneId
preserves selectedPerspectiveId
refreshes preview cache key
does not reset zoom unnecessarily unless the Perspective changed
```

Do not reload the entire project solely to update a Scene 2D preview.

---

# Part 14 — Frontend plugin status

When Scene 2D Perspective is open in Photoshop, Storyboarder should show an appropriate state such as:

```text
Open in Photoshop
Linked
Preview updated
Preview out of date
```

Do not label it as a shot.

The frontend should use UUID identity and source path.

---

# Part 15 — Backward compatibility

Existing shot plugin behavior must continue to work:

```text
shot selection
open/focus shot
shot heartbeat
Export preview
Export & next
auto-add at end
status update
quick note
onion skin
SB bg workflow
```

Keep old plugin context fields while introducing generic work context.

Do not perform a simultaneous full plugin rewrite.

---

# Part 16 — Tests

## Backend tests

Add tests for:

```text
1. Scene 2D open sets active work context.
2. Work context contains UUID Scene/Perspective IDs.
3. Already-open Perspective triggers focus request.
4. Focus token increments.
5. Scene 2D export validates destination.
6. Scene 2D export cannot write outside project root.
7. Scene 2D export updates only Scene 2D metadata.
8. Shot records remain byte-for-byte unchanged after Scene 2D export.
9. Scene 2D psd-saved updates correct record.
10. Export & next stays inside the same Scene group.
11. Export & next stops at final Perspective.
12. Image Perspective is not overwritten.
13. Invalid UUID returns safe 400/404.
14. Heartbeat work keys are validated.
15. Existing shot plugin tests still pass.
```

## Plugin/manual tests

```text
1. Open a shot PSD.
2. Confirm plugin enters Shot mode.
3. Open a Scene 2D PSD from Storyboarder.
4. Confirm plugin enters Scene 2D mode.
5. Confirm Scene and Perspective titles display.
6. Confirm UUID is not shown as the normal label.
7. Switch Photoshop tabs between shot and Scene 2D.
8. Confirm plugin mode follows the active document.
9. Export Scene 2D preview.
10. Confirm preview.png updates.
11. Confirm no shot preview changes.
12. Confirm Storyboarder refreshes automatically.
13. Test Export & next perspective.
14. Confirm final Perspective does not auto-create.
15. Open an image Perspective.
16. Confirm it is read-only in plugin.
17. Rename Scene and Perspective in Storyboarder.
18. Reopen PSD.
19. Confirm plugin identity still works.
20. Restart Photoshop and reconnect.
21. Confirm context recovers from immutable path/UUID.
```

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests/ -q

cd frontend
npm.cmd run build
```

Reload the UXP plugin and perform manual Photoshop validation.

---

# Files likely affected

```text
storyboard_tool/runtime_state.py
storyboard_tool/live_bridge.py
storyboard_tool/app_state.py
storyboard_tool/plugin_service.py
storyboard_tool/backend_service.py
storyboard_tool/api.py
frontend/src/api.ts
frontend/src/state/LiveBridgeContext.tsx
frontend/src/components/Scene2DPanel.tsx
photoshop_uxp_plugin/backend_client.js
photoshop_uxp_plugin/panel.js
photoshop_uxp_plugin/preview_export.js
photoshop_uxp_plugin/index.html
photoshop_uxp_plugin/style.css
tests/test_plugin_scene2d.py
tests/test_plugin_bridge.py
```

---

# Do not change

```text
Scene 2D UUID model
Scene 2D stable path layout
Scene 3D capture workflow
shot ID format
shot PSD structure
SB bg behavior
shot transparent foreground export semantics
Reference segment behavior
image-to-PSD conversion
```

---

# Implementation order

```text
1. Add generic runtime work context.
2. Add backend work-context payload.
3. Add generic focus request.
4. Add Scene 2D open handoff.
5. Extend heartbeat.
6. Add plugin active-document detection.
7. Add plugin Shot/Scene2D UI modes.
8. Add dedicated Scene 2D export endpoint.
9. Add Export & next perspective.
10. Add Storyboarder automatic preview refresh.
11. Run backend tests.
12. Run frontend build.
13. Perform manual UXP validation.
```

---

# Output required

Report:

```text
Changed files
Work-context schema
How UUID identity is used
How active Photoshop documents are matched
Scene 2D open/focus behavior
Plugin Shot mode
Plugin Scene 2D mode
Dedicated Scene 2D export behavior
Export & next perspective behavior
Image Perspective behavior
Automatic Storyboarder refresh
Backward compatibility
Tests and build results
Manual Photoshop validation
Known limitations
```
