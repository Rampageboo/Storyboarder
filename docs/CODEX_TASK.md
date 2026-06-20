# CODEX_TASK.md — Photoshop UXP: split one plugin package into two panels

Repo: `Rampageboo/Storyboarder`.

Work from the latest branch containing:

```text
70dbc21b87e4fb493b322c98598f93c80c70bde3
```

## Goal

Split the current Photoshop UXP plugin UI into two Photoshop panels inside the same plugin package.

Do not create a second plugin.

Keep:

```text
one manifest.json
one plugin id
one plugin version
shared backend client
shared plugin settings
shared storage
```

Add a second panel entrypoint so Photoshop can show two panels:

```text
Storyboard Bridge
Storyboard Work
```

This is a layout / panel architecture task only. Do not change export behavior, PSD behavior, backend APIs, or Storyboarder frontend.

---

# Target panel split

## Panel 1 — Storyboard Bridge

This panel corresponds to the current “current shot + export” layout.

It should contain:

```text
Connection status
Current shot card
Shot title / id / index / status / duration
Action note / camera note / latest notes if already shown
Quick note input
Add note button

Preview export
Export & next
Export preview
Auto-add at end
Focus Storyboarder after preview export

Plugin settings that are directly related to export/link behavior
```

This panel is about:

```text
What am I editing?
What is the current shot state?
Export preview back to Storyboarder.
```

Keep this panel compact, but it can be taller than the work panel.

## Panel 2 — Storyboard Work

This panel corresponds to the shot controls and onion skin controls.

It should contain:

```text
Shot select
Previous
Next
Open canvas
Focus open tab

Onion skin
Overlay count
Opacity
Apply previous overlay
Apply next overlay
Clear overlay
```

This panel is about:

```text
Move between shots.
Open/focus PSD tabs.
Use onion skin while drawing.
```

This panel should be the practical drawing/work panel.

---

# Advanced / low-frequency controls

Avoid putting low-frequency controls in the Work panel unless necessary.

Place these in the Bridge panel under a compact collapsible Advanced section, or a small Settings/Advanced area:

```text
Reconnect
Ensure template layers
Recover broken PSD
Choose project folder
Choose shot folder
Canvas color / auto-apply color / apply canvas color
```

Do not let these dominate either panel.

---

# Technical direction

The current plugin has one `manifest.json` and one panel entrypoint.

Update the UXP manifest using the correct manifest v5 pattern for multiple panel entrypoints in the same plugin package.

Important:

* Do not create a second `manifest.json`.
* Do not create a second plugin id.
* Do not duplicate backend polling aggressively.
* Do not create two independent settings files.
* Do not fork the backend client.
* Do not create separate logic copies that will drift.

Prefer one shared JS codebase with panel-specific DOM binding.

Because the two panels will not contain all the same DOM elements, make event binding null-safe:

```text
const node = $("someId")
if (node) node.addEventListener(...)
```

Do this for all controls that may exist in only one panel.

Do not allow one missing DOM element in one panel to break the entire plugin initialization.

---

# Suggested file structure

Use the simplest structure that works with the current UXP setup.

Possible structure:

```text
photoshop_uxp_plugin/
  manifest.json
  bridge.html
  work.html
  panel.js
  backend_client.js
  preview_export.js
  layer_roles.js
  layer_sync.js
  panel_storage_adapter.js
  style.css
```

Alternative structure is acceptable if required by UXP manifest v5, but keep one plugin package and two panel entrypoints.

Do not convert to React.
Do not add a bundler.
Do not add dependencies.

---

# Shared state and settings

The two panels should share plugin settings:

```text
focus_storyboard_after_preview_export
auto_add_at_end
```

Use the existing plugin settings storage.

If both panels are open at the same time:

* Settings changes in one panel should not corrupt the other.
* It is acceptable if the other panel sees the updated setting after reload or next refresh.
* Prefer lightweight sync where practical.

`auto_add_at_end` should still affect `Next` / `Export & next` behavior.

---

# Polling / heartbeat rule

Avoid double-heavy polling if both panels are open.

Preferred behavior:

```text
Storyboard Bridge panel owns full bridge polling / heartbeat.
Storyboard Work panel may use the same shared bridge helpers, but should avoid adding a second aggressive polling loop if possible.
```

If avoiding duplicated polling is too risky in this task, keep the existing polling behavior but do not make it worse than two panels each polling at the current interval.

Do not introduce backend load-heavy loops.

---

# Behavior constraints

Do not change:

```text
Export preview
Export & next
Preview PNG export logic
Layer visibility during export
PSD save/open behavior
SB bg behavior
Focus Storyboarder after export behavior
Auto-add behavior
Previous / Next behavior
Open canvas behavior
Focus open tab behavior
Onion skin behavior
Quick note behavior
Recover PSD behavior
Backend bridge API
Storyboarder frontend
Project metadata storage
```

This is a UI/panel split only.

---

# Required cleanup

The previous single-panel `Main / Settings / Advanced` layout can be removed or simplified.

After this task:

```text
No fake tabs inside one panel unless they are still needed for Advanced/Settings.
No duplicated large sections.
No giant all-in-one vertical panel.
```

The user should be able to open:

```text
Window > Plugins > Storyboard Bridge
Window > Plugins > Storyboard Work
```

or the equivalent Photoshop UXP panel entries.

---

# Manual validation

Test in UXP Developer Tool / Photoshop.

## Panel availability

```text
1. Load plugin.
2. Confirm Photoshop shows two panel entries:
   - Storyboard Bridge
   - Storyboard Work
3. Open both panels.
4. Confirm both panels load without JS errors.
```

## Storyboard Bridge panel

```text
1. Connection status updates.
2. Current shot card updates.
3. Quick note still works.
4. Export preview still works.
5. Export & next still works.
6. Auto-add at end still persists.
7. Focus Storyboarder after preview export still persists and works.
8. Advanced/low-frequency controls still work if located here.
```

## Storyboard Work panel

```text
1. Shot select loads.
2. Previous works.
3. Next works.
4. Open canvas works.
5. Focus open tab works.
6. Onion skin overlay count works.
7. Opacity works.
8. Apply previous overlay works.
9. Apply next overlay works.
10. Clear overlay works.
```

## Two-panel interaction

```text
1. Keep both panels open.
2. Change selected shot through Work panel.
3. Confirm Bridge panel eventually reflects the correct current shot, or at minimum does not break.
4. Export from Bridge panel.
5. Navigate from Work panel.
6. Confirm no duplicate shot creation or broken selection.
```

## Regression

```text
1. No backend errors.
2. No PSD corruption.
3. No project metadata rewrite from plugin in linked mode.
4. No missing DOM id crash.
5. Plugin settings persist after reload.
```

---

# If UXP multi-panel support is unclear

Do not fake a broken implementation.

If the current manifest/runtime pattern cannot safely support two panels without a larger architecture change, stop and report:

```text
What manifest change is required
Which files need to split
What shared-state risk exists
A safer staged plan
```

Do not force a brittle implementation that only appears to work.

---

# Output required

When finished, report:

```text
Changed files
Manifest entrypoint changes
Names of the two Photoshop panels
Which controls are in Storyboard Bridge
Which controls are in Storyboard Work
How shared plugin settings are handled
Whether polling/heartbeat was changed
Validation results
Known limitations
```
