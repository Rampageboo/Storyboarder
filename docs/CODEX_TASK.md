# CODEX_TASK.md — Redesign Scene 2D as a canvas-first floating-island workspace

Repo:

```text
Rampageboo/Storyboarder
```

Base commit:

```text
788a78ccbda831d0513decb9d6ee9df696ea7c06
```

## Goal

Redesign the existing Scene 2D workspace from a vertically stacked form page into a canvas-first visual workspace.

The current layout contains:

```text
top full-width Scene editor
horizontal Perspective strip
central preview
full-width zoom bar
bottom full-width Perspective editor
```

This creates excessive vertical chrome and makes the preview feel secondary.

The new Scene 2D workspace must prioritize the visual preview.

Target layout:

```text
┌────────────────────────────────────────────────────────────┐
│ Scene 2D                                                   │
├──────────────┬─────────────────────────────────────────────┤
│ Scene /      │                                             │
│ Perspective  │                 CANVAS                      │
│ rail         │                                             │
│              │                           ┌──────────────┐   │
│ [thumb 1]    │                           │ Inspector    │   │
│ [thumb 2]    │                           │ floating     │   │
│ [+]          │                           │ island       │   │
│              │                           └──────────────┘   │
│              │                                             │
│              │          ┌─────────────────────┐            │
│              │          │ Fit  −  slider  +   │            │
│              │          └─────────────────────┘            │
└──────────────┴─────────────────────────────────────────────┘
```

---

# Core principles

```text
canvas first
no full-width editing banners
progressive disclosure
one selected Scene
one selected Perspective
minimal permanent chrome
floating controls over the workspace
```

Do not remove existing Scene 2D functionality.

Only reorganize and restyle it.

---

# Part 1 — Remove the top and bottom full-width editors

Remove the current permanent top Scene editing section containing:

```text
Scene title
Description
Linked Scene 3D
Save scene
Delete scene
```

Remove the current permanent bottom Perspective editing section containing:

```text
Perspective title
Perspective linked Scene 3D
Linked state banner
Save perspective
Open in Photoshop
Refresh preview
Set primary
Add to References
Delete perspective
```

Do not delete these capabilities.

Move them into the floating Inspector island.

The canvas must no longer be vertically compressed between two editing forms.

---

# Part 2 — Main workspace shell

Use a stable layout such as:

```css
.scene2d-workspace {
  display: grid;
  grid-template-columns: 180px minmax(0, 1fr);
  height: 100%;
  min-height: 0;
  overflow: hidden;
}
```

Suggested dimensions:

```text
left rail:
  168–196 px

canvas workspace:
  fills all remaining width and height

floating inspector:
  280–320 px
  top-right
  16–24 px inset

floating zoom island:
  bottom-center
  16–24 px bottom inset
```

The preview workspace must grow and shrink with the window.

Avoid fixed preview heights.

---

# Part 3 — Left navigation rail

The left rail should combine Scene selection and Perspective navigation without becoming another form panel.

## Scene selector

At the top of the rail, add a compact Scene selector.

Preferred structure:

```text
[ Scene 2D 1          ▾ ] [ + ]
```

The selector may be:

```text
compact dropdown
or
compact vertical Scene list
```

Do not use large Scene cards with descriptions.

Each Scene entry should show:

```text
Scene title
Perspective count
selected state
```

Add Scene should remain accessible through:

```text
small + button
```

Additional Scene actions should move to the Inspector or an overflow menu:

```text
Rename
Duplicate if currently supported
Delete
Link Scene 3D
```

## Perspective rail

Below the Scene selector, display Perspectives vertically.

Each Perspective item should contain:

```text
thumbnail
short title
primary marker when applicable
PSD/Image type badge only when useful
selected state
```

Target item size:

```text
thumbnail width: 112–136 px
thumbnail aspect ratio: match project canvas
title: one line with ellipsis
```

Add Perspective should be a visual `+` tile below the items.

Support existing Perspective selection.

Do not expose UUIDs.

---

# Part 4 — Perspective ordering

Allow Perspectives to be reordered vertically by drag-and-drop only if backend ordering is already supported or can be added safely without changing identity.

If ordering is not currently persisted:

```text
do not fake drag-and-drop
retain the existing order
leave a clear TODO
```

Never derive order from UUID.

Never rename files during reordering.

---

# Part 5 — Canvas workspace

The central area must be treated as an editor viewport rather than a card.

Requirements:

```text
fills available area
dark neutral workspace background
subtle checkerboard only where transparency needs to be communicated
preview centered
preview respects zoom and fit mode
preview can pan when larger than viewport
no permanent border-heavy container around the whole workspace
```

Use a clean viewport structure:

```text
canvas viewport
  └─ transform/pan layer
       └─ preview image
```

Preserve existing:

```text
Fit
25–200% zoom
zoom percentage
preview refresh behavior
```

Do not distort image aspect ratio.

---

# Part 6 — Compact canvas title overlay

Add a small non-blocking title overlay in the top-left of the canvas.

Example:

```text
Living Room
Door View · 2 of 4
```

It should not be a full-width banner.

Suggested appearance:

```text
transparent or lightly surfaced
no heavy border
scene title as secondary text
Perspective title as primary text
pointer-events none unless it contains an overflow button
```

Do not duplicate the full Inspector content.

---

# Part 7 — Floating Inspector island

Add a floating Inspector island in the top-right of the canvas workspace.

Suggested style:

```css
position: absolute;
top: 18px;
right: 18px;
width: min(300px, calc(100% - 36px));
border-radius: 14px;
background: rgba(...);
backdrop-filter: blur(...);
border: 1px solid var(--border);
box-shadow: 0 12px 36px rgba(...);
```

Do not use excessive translucency that harms readability.

## Collapsed state

The Inspector must support collapse.

Collapsed appearance:

```text
[ Scene / Perspective title ] [ expand icon ]
```

Remember collapse state for the current session.

## Inspector structure

Use two compact sections:

```text
SCENE
PERSPECTIVE
```

Do not show all controls simultaneously as large form fields.

### Scene section

Display:

```text
Scene title
Description
Linked Scene 3D
Save
Delete in overflow/destructive area
```

Recommended interaction:

```text
title:
  compact text input

description:
  collapsed by default
  expandable textarea

Linked Scene 3D:
  compact select

Save:
  only visually emphasized when fields are dirty
```

Delete should not sit beside Save as an equal primary action.

Place destructive actions inside:

```text
••• overflow menu
or
bottom Danger section
```

### Perspective section

Display:

```text
Perspective title
Perspective type
Primary state
Linked Scene 3D override
```

Actions:

```text
Open in Photoshop
Refresh preview
Set primary
Add to References
Delete Perspective
```

Visual priority:

```text
Primary:
  Open in Photoshop

Secondary:
  Refresh preview
  Add to References

State action:
  Set primary

Destructive:
  Delete Perspective
```

Do not give all actions equal button weight.

---

# Part 8 — Floating zoom island

Replace the current full-width zoom toolbar with a compact floating island at the bottom center.

Suggested contents:

```text
[ Fit ] [ − ] [ slider ] [ + ] [ 100% ]
```

Optional:

```text
Reset
```

Do not show both a `Fit` button and an additional duplicated `Fit` text label.

Suggested width:

```text
300–420 px
```

The island should remain usable at narrow widths.

Responsive compact version:

```text
[ Fit ] [ − ] [ 100% ] [ + ]
```

Slider may hide below a breakpoint.

---

# Part 9 — Action feedback

Replace permanent green “Linked” banners with compact contextual feedback.

Use:

```text
small status row inside Inspector
temporary toast
small dot/badge
```

Examples:

```text
Photoshop linked
Preview updated
Preview out of date
PSD missing
Image Perspective
```

Do not reserve a full-width row for ordinary success state.

Errors must remain clearly visible.

---

# Part 10 — Empty states

## No Scene

Show centered empty state in the canvas:

```text
No Scene 2D groups yet
Create a Scene to begin organizing Perspectives.

[Create Scene]
```

## Scene without Perspectives

Show:

```text
No Perspectives in this Scene

[Create PSD Perspective]
[Import image/PSD]
```

Do not leave a blank checkerboard canvas with disabled controls.

---

# Part 11 — Responsive behavior

At narrower widths:

```text
Inspector:
  may become a right drawer
  or reduce to a collapsed icon island

left rail:
  may shrink to icon/thumbnail mode

zoom island:
  use compact mode
```

Do not revert to top/bottom full-width forms.

At very narrow desktop widths, a drawer is acceptable.

---

# Part 12 — Accessibility

Requirements:

```text
all icon-only buttons have aria-label
visible keyboard focus
minimum practical click target around 30–34 px
tooltips for ambiguous icons
Escape closes menus/drawers
Inspector collapse is keyboard accessible
```

Do not rely on color alone for selected/primary state.

---

# Part 13 — Visual system

Reuse current Storyboarder dark theme tokens where possible.

Target character:

```text
professional creative tool
dense but calm
Photoshop / Blender style workspace
not a web admin dashboard
```

Avoid:

```text
large dashboard cards
full-width bordered form sections
excessive headings
multiple gold primary buttons
heavy gradients
neon glow
glassmorphism that reduces legibility
```

Use gold accent only for:

```text
current selection
dirty/save state
primary action
active slider
```

---

# Part 14 — Preserve behavior

The redesign must retain:

```text
Scene selection
Scene creation
Scene editing
Scene deletion
Scene 3D linking

Perspective selection
Perspective creation
image/PSD import
Perspective editing
Perspective deletion
Set primary
Add to References
Open in Photoshop
Refresh preview

preview fit
zoom
current selection persistence
plugin preview auto-refresh
UUID-based identity
```

Do not change:

```text
Scene/Perspective API contracts
UUID model
filesystem layout
Photoshop work-context behavior
plugin export behavior
Scene 3D architecture
```

---

# Files likely affected

```text
frontend/src/components/Scene2DPanel.tsx
frontend/src/styles.css
or the current component-specific Scene 2D stylesheet

small reusable components if justified:
  FloatingIsland
  IconButton
  OverflowMenu
```

Avoid creating a broad design-system rewrite.

---

# Manual validation

Test:

```text
one Scene / one Perspective
multiple Scenes
many Perspectives requiring vertical scroll
PSD Perspective
image Perspective
long Scene title
long Perspective title
long Description
no linked Scene 3D
linked Scene 3D
primary Perspective
plugin preview update
narrow desktop window
large desktop window
```

Verify:

```text
canvas gains substantially more vertical space
no permanent top editor banner
no permanent bottom editor banner
Inspector does not cover essential image content unnecessarily
zoom island remains reachable
selection does not reset during edits
```

---

# Commands

Run:

```powershell
cd frontend
npm.cmd run build
```

Run relevant frontend tests where available.

Do not claim visual validation passed without launching the desktop app.

---

# Output required

Report:

```text
Changed files
New workspace structure
Left rail behavior
Floating Inspector behavior
Floating zoom island behavior
Responsive breakpoints
Preserved functionality
Frontend build result
Manual visual validation
Known limitations
Final commit SHA
```
