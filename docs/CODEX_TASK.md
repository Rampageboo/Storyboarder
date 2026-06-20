# CODEX_TASK.md — Storyboarder UI: compact topbar menu cleanup

Repo: `Rampageboo/Storyboarder`.

Work from the latest branch containing:

```text
b928bb25c3921480a6a794b8a4fad038c7e73ea8
```

## Goal

Clean up the top app bar so it feels more like a compact desktop application menu bar.

The current top-left buttons are visually bulky:

```text
New
Open Folder
Save
```

Replace them with a narrower menu-style UI similar in spirit to desktop apps such as Photoshop:

```text
File    Edit    View
```

This task is UI organization only.

Do not change project behavior, backend APIs, BoardStrip, Reference previews, Reference Segment slider, Photoshop plugin, or PSD logic.

---

## Current context

Recent tasks already completed:

1. BoardStrip progress bar.
2. Hover `+` insert between boards.
3. BoardStrip wheel scrolling restored.
4. Settings modal restored.
5. Reference preview cards improved.
6. GLB/model preview improved.
7. Reference Segment source-time slider restored.

Do not undo or refactor any of those.

---

## Required changes

### 1. Replace large top-left buttons with compact menu bar

In `Topbar`, replace the prominent button group:

```text
New
Open Folder
Save
```

with a compact menu bar:

```text
File
Edit
View
```

Recommended structure:

```text
File
  New Project
  Open Project Folder
  Save Project

Edit
  optional: no-op / omitted if there are no real actions available here

View
  Settings
```

Important:

* Do not add fake menu items that do nothing.
* If `Edit` or `View` would be empty, either omit that menu or keep only menus that contain real actions.
* It is acceptable to start with only `File` and `Settings` if that is cleaner.
* Prefer practical UI over imitating Photoshop exactly.

### 2. Preserve existing behavior

The menu items must call the same existing handlers as before:

```text
New Project      -> existing newProject flow
Open Folder      -> existing openProjectFromDialog flow
Save Project     -> existing saveProject flow
Settings         -> existing SettingsModal open flow
```

Do not change:

* project creation defaults
* project open behavior
* save behavior
* dirty-state handling
* Settings modal behavior
* disabled states

### 3. Keep the topbar narrow

The topbar should take less horizontal space than before.

Target visual structure:

```text
[File] [View]        Project Name / status        PS status
```

or:

```text
[File]        Project Name / status        [Settings] PS status
```

Rules:

* Do not make the topbar taller.
* Do not add large icons.
* Do not add a sidebar.
* Do not redesign the whole layout.
* Keep project title and Photoshop bridge status visible.

### 4. Dropdown behavior

Implement simple dropdown menus without new dependencies.

Expected behavior:

* Click menu label to open dropdown.
* Click a menu item to run action and close dropdown.
* Click outside to close dropdown.
* Press Escape to close dropdown if practical.
* Disable menu items when the old buttons would have been disabled.
* Keyboard accessibility should not get worse.

Do not implement native OS menus.

Do not add Electron/Tauri/native menu code.

### 5. Settings access

Settings must remain easy to access.

Acceptable options:

Option A:

```text
View > Settings
```

Option B:

```text
right-side compact Settings button
```

Option C:

```text
File > Settings
```

Use whichever requires the smallest clean change.

Do not remove Settings.

### 6. Dirty/save state

Preserve the existing dirty indicator behavior:

* Project name still shows `*` or equivalent when unsaved.
* Save item is disabled when there is nothing to save.
* Save item shows busy/disabled state during project action.

Do not change autosave/draft handling.

---

## Out of scope

Do not do any of the following:

* Do not change BoardStrip.
* Do not change reference previews.
* Do not change Reference Segment slider.
* Do not change GLB rendering behavior.
* Do not change Settings modal content.
* Do not implement plugin focus behavior.
* Do not implement Photoshop preheat behavior.
* Do not change backend APIs.
* Do not change project storage.
* Do not change PSD/Photoshop document handling.
* Do not add new dependencies.
* Do not broadly refactor `ProjectContext.tsx`.
* Do not introduce a full design system.

---

## Validation

Run:

```powershell
cd frontend
npm run build
```

Manual validation:

```text
1. Topbar opens normally.
2. File menu opens and closes.
3. New Project still works.
4. Open Folder still works.
5. Save still works.
6. Save is disabled when there are no unsaved changes.
7. Settings still opens.
8. Clicking outside closes dropdown.
9. Escape closes dropdown if implemented.
10. Project title/status still visible.
11. Photoshop bridge status still visible.
12. BoardStrip, Reference panel, and Reference Segment slider still work.
```

---

## Output required

When finished, report:

```text
Changed files
Topbar structure after the change
Which menu items were added
Confirmation that old New/Open/Save handlers were preserved
Validation results
```
