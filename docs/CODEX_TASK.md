# CODEX_TASK.md — Photoshop UXP plugin UI cleanup

Repo: `Rampageboo/Storyboarder`.

Work from the latest branch containing:

```text
992156b486a3c42c29f7537f9f43b333f7723445
```

## Goal

Clean up the Photoshop UXP plugin panel UI.

The plugin currently works, but the panel has become too long and cluttered. This task should reorganize the existing controls into clearer sections/views without changing workflow behavior.

This is a UI organization task only.

Do not change preview export behavior, PSD behavior, backend APIs, Storyboarder frontend, or project storage.

---

## Required UI structure

Reorganize the plugin into three logical views or sections:

```text
Main
Settings
Advanced
```

Use the simplest implementation that fits the current plain HTML/CSS/JS plugin structure.

Do not add React, bundlers, or new dependencies.

---

# 1. Main view

The Main view is the default view.

It should contain only high-frequency daily actions:

## Header

Show:

```text
Storyboard Bridge
connection status
current shot title / id
```

Keep the connection status visible.

## Current shot card

Keep the current shot card, but make it more compact.

It should show:

```text
shot number / total
shot title
status
duration
action note
quick note input
```

Do not make it taller than necessary.

## Preview export

Keep this section prominent:

```text
Export & next
Export preview
Auto-add at end
Focus Storyboarder after preview export
```

Do not change the actual export logic.

## Shot navigation

Keep:

```text
Previous
Next
Open canvas
Focus open tab
```

But keep this compact.

---

# 2. Settings view

Add a small settings entry point, preferably a gear button near the plugin header.

Settings should contain plugin-local settings only:

```text
Focus Storyboarder after preview export
Auto-add at end
```

If these checkboxes also remain in Main for convenience, avoid duplication where possible.

Rules:

* Plugin settings must still persist using the existing plugin settings store.
* Do not move Storyboarder project settings into the Photoshop plugin.
* Do not add Photoshop preheat here. Preheat belongs to Storyboarder Settings.

Settings view should have a Back button.

---

# 3. Advanced view

Move low-frequency or technical controls here:

```text
Onion skin
Overlay count
Opacity
Apply previous overlay
Apply next overlay
Clear overlay
Ensure template layers
Recover broken PSD
Choose project folder
Choose shot folder
Reconnect
```

Advanced view should be reachable from Main, but not visually dominate the default panel.

Advanced view should have a Back button.

---

## Layout constraints

The plugin panel is narrow when docked in Photoshop.

Design for a narrow panel:

```text
width around 280–340px
vertical scrolling allowed
no horizontal scrolling
buttons full-width or two-column only when safe
```

Do not increase the panel’s required width.

Do not use large headers or oversized cards.

---

## Behavior constraints

Do not change:

```text
Export preview
Export & next
Focus Storyboarder after export
Open canvas
Focus open tab
Previous / Next
Auto-add behavior
Onion skin behavior
Layer template behavior
PSD recovery behavior
Backend link / heartbeat behavior
```

This task should preserve existing function names and event handlers where possible.

If controls are moved in the DOM, make sure existing event listeners still bind correctly.

---

## Out of scope

Do not do any of the following:

* Do not change Storyboarder frontend.
* Do not change backend APIs.
* Do not change preview export image generation.
* Do not change PSD save/open behavior.
* Do not change SB background layer behavior.
* Do not add Photoshop preheat to the plugin.
* Do not add new dependencies.
* Do not convert the plugin to React.
* Do not remove any existing feature.
* Do not implement new features.
* Do not change project metadata storage.
* Do not touch BoardStrip, Reference panel, or Reference Segment slider.

---

## Validation

Manual validation in UXP Developer Tool:

```text
1. Plugin loads.
2. Main view opens by default.
3. Connection status still updates.
4. Current shot card still updates.
5. Export preview still works.
6. Export & next still works.
7. Focus Storyboarder after export still works if enabled.
8. Previous / Next still work.
9. Open canvas still works.
10. Focus open tab still works.
11. Settings view opens and Back returns to Main.
12. Plugin settings persist after reload.
13. Advanced view opens and Back returns to Main.
14. Onion skin controls still work.
15. Recover broken PSD still works.
16. Reconnect still works.
```

If there is any build or lint command for the plugin, run it. Otherwise report manual UXP validation.

---

## Output required

When finished, report:

```text
Changed files
New plugin UI structure
Which controls are in Main
Which controls are in Settings
Which controls are in Advanced
Confirmation that export behavior was unchanged
Manual validation results
```
