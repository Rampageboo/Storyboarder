# CODEX_TASK.md — Storyboarder UI: board strip and settings cleanup

Repo: `Rampageboo/Storyboarder`. Work from the latest default branch.

## Goal

Clean up the main Storyboarder UI without changing backend behavior.

This task focuses only on:

1. Board strip usability.
2. Restoring a Settings entry point.
3. Adding two settings:

   * Canvas background color.
   * Whether to preheat Photoshop when the app opens.

Do not refactor the whole frontend. Do not redesign the reference panel in this task.

---

## Required changes

### 1. Board strip progress bar

Add a compact progress bar directly under the board strip.

Purpose:

* Show current storyboard position.
* Make the board strip feel more like a timeline.
* Should update when the selected shot changes.

Recommended behavior:

* Progress can be based on selected shot index / total shots.
* Keep it visual-only for now unless there is already drag/click timeline logic.
* Do not introduce a complex timeline model.

### 2. Move board strip horizontal scrollbar above the strip

The current horizontal scrollbar appears below the board strip and competes with the new progress bar.

Change layout so:

```text
horizontal scrollbar / scroll area control
board thumbnails
progress bar
```

Preserve existing scroll behavior.

### 3. Add hover insert button between boards

Add an insert affordance between board cards.

Behavior:

* When hovering the gap between two boards, show a compact `+` button.
* Clicking `+` inserts a new board at that position.
* Do not place the `+` directly in the center of a board thumbnail, because that conflicts with selecting the board.
* Preserve existing add-at-end behavior.
* Preserve current shot selection behavior.

Required checks:

* Insert before first board works if the UI has a left gap.
* Insert between boards works.
* Insert after last board still works through the existing add-at-end flow.

### 4. Restore Settings entry point

If the Settings button/entry is currently missing, add it back.

Preferred location:

* Top-right gear icon in the app header, or
* A compact Settings button in the existing top control area.

Do not create a full menu bar in this task.

### 5. Settings panel contents

Add or restore a Settings panel/modal with these fields:

#### Canvas background color

* User can choose/set canvas background color.
* Use the existing backend/settings mechanism if it already exists.
* Do not introduce a new settings schema if an existing `canvas_background_color` setting exists.
* Changing the value should update the app in the same way the existing canvas color flow expects.

#### Preheat Photoshop on app open

Add a boolean setting:

```text
Preheat Photoshop when Storyboarder opens
```

Behavior:

* Store it in app/project settings using the existing settings mechanism.
* Do not implement heavy Photoshop launch logic unless an existing preheat/open-Photoshop helper already exists.
* If preheat behavior already exists, wire the setting to it.
* If no preheat behavior exists, add only the setting and leave a clearly named TODO/comment for the backend hook.

---

## Out of scope

Do not do any of the following in this task:

* Do not change the reference panel.
* Do not resize reference thumbnails.
* Do not add GLB preview rendering.
* Do not restore reference segment sliders.
* Do not redesign the top-left buttons into a File/Edit/View menu.
* Do not change Photoshop plugin behavior.
* Do not change backend APIs unless required for the two settings.
* Do not touch PSD/Photoshop document manipulation.
* Do not refactor `ProjectContext.tsx` broadly.
* Do not split large files just because they are large.
* Do not add new dependencies.

---

## Validation

Run:

```powershell
cd frontend
npm run build
```

If backend settings code changes, also run:

```powershell
.venv\Scripts\python.exe -m pytest tests/ -q
```

Manual validation:

* Board strip still scrolls.
* Selected shot still updates correctly.
* Progress bar updates when selecting different shots.
* Hovering between boards shows `+`.
* Clicking `+` inserts at the intended position.
* Existing add-at-end behavior still works.
* Settings opens.
* Canvas background color setting is visible and works.
* Preheat Photoshop setting is visible and persists.

Output:

* Changed files.
* Summary of board strip layout changes.
* Summary of Settings panel changes.
* Validation results.
