# CODEX_TASK.md — Polish Photoshop UXP layout and use human-readable Shot labels

Repository:

```text
Rampageboo/Storyboarder
```

Base commit:

```text
450c1a433e9af6438d21454aabfaed45f5827cbb
```

## Goal

Perform a focused visual-polish pass on the two Photoshop UXP panels:

```text
Storyboard Work
Storyboard Bridge
```

The broad information architecture is now correct. Do not redesign it again.

Fix:

```text
- inconsistent padding and alignment
- duplicated panel headings
- excessive blank space
- different Shot and Scene 2D layout structures
- inconsistent button grids
- nested card borders
- visible UUIDs in Shot selectors and context labels
- poor dropdown presentation
```

Shot and Scene 2D modes must use the same layout skeleton, spacing system, control sizing, and context-card structure.

Only their content should differ.

---

# Do not change functional architecture

Preserve:

```text
two UXP panels
active-document path matching
work-context routing
heartbeat behavior
disconnected/manual mode behavior
Scene 2D export checks
Shot export behavior
Export & next
quick notes
status editing
onion skin
SB bg behavior
Perspective move transaction
```

Do not modify Scene 2D workspace frontend layout.

Do not change UUID identity or filesystem paths.

---

# Part 1 — Add semantic Shot navigation fields to backend work items

Update:

```text
storyboard_tool/plugin_service.py
PluginBridgeService.work_items()
```

Shot work items must contain:

```json
{
  "kind": "shot",
  "key": "shot:<shot-id>",
  "shot_id": "<shot-id>",
  "shot_title": "Close up",
  "index": 16,
  "count": 58,
  "previous_key": "shot:<previous-shot-id>",
  "next_key": "shot:<next-shot-id>",
  "source_file_path": "...",
  "source_native_path": "...",
  "preview_image_path": "..."
}
```

Rules:

```text
index is one-based
count is the total number of Shots
index follows current project Shot order
shot_title may be an empty string
previous_key is empty for the first Shot
next_key is empty for the final Shot
```

Keep:

```text
shot_id
key
path fields
```

as canonical internal identity.

Do not expose UUID as the intended visible label.

Do not hard-code the final UI string in the backend.

The plugin should format the semantic data.

---

# Part 2 — Human-readable Shot labels

Add a pure formatting helper:

```js
function formatShotDisplayLabel(item) {
  const index = Number(item?.index || 0);
  const title = String(item?.shot_title || "").trim();
  return title
    ? `${index}. ${title}`
    : `${index}. Untitled shot`;
}
```

Examples:

```text
1. Copy
2. Untitled shot
16. Look at the moon
```

Do not display:

```text
71cca9b8...
851cb840...
shot UUID
```

UUID remains the internal select value:

```html
<option value="shot:<uuid>">16. Untitled shot</option>
```

The same visible label should be used consistently in:

```text
Shot dropdown
current Shot indicator
navigation status
Bridge context header where appropriate
```

The full UUID may remain in Advanced diagnostics only.

---

# Part 3 — Match Shot and Scene 2D work-item schemas

Use a common navigation model:

```text
kind
key
index
count
previous_key
next_key
primary title
secondary title
```

Mapping:

```text
Shot:
  primary title = shot_title or Untitled shot
  secondary title = Shot {index} of {count}

Scene 2D:
  primary title = perspective_title
  secondary title = scene_title
```

Avoid separate ad-hoc navigation rules where one mode uses array indices and the other uses backend keys.

---

# Part 4 — Create one shared Work-panel layout skeleton

Both Shot and Scene 2D Work modes must render into the same visual structure:

```text
.context-navigation
  .context-breadcrumb
  .context-selector
  .navigation-grid
  .open-focus-grid
  .context-secondary-controls
```

Target structure:

```text
SHOT
[ 16. Untitled shot                         ▾ ]

[ ← Previous ] [ Next → ]

[ Open ]       [ Focus tab ]
```

Scene 2D:

```text
SCENE 2D · Maps
[ Building A                               ▾ ]

[ ← Previous ] [ Next → ]

[ Open perspective ] [ Focus tab ]
```

Do not create different margins or button sizes for Shot and Scene 2D.

Mode-specific controls such as Onion Skin appear below the shared shell.

---

# Part 5 — Remove duplicate internal panel headings

Photoshop already displays the docked panel tab title:

```text
Storyboard Work
Storyboard Bridge
```

Do not repeat a large `Storyboard Work` heading inside the panel.

Replace it with a compact context eyebrow where needed:

```text
SHOT
SCENE 2D · Maps
UNLINKED DOCUMENT
```

Remove the large empty block currently created by the repeated heading and divider.

The first useful control should begin near the top of the panel body.

---

# Part 6 — Establish one spacing system

Define shared CSS tokens:

```css
:root {
  --uxp-panel-padding: 12px;
  --uxp-section-gap: 12px;
  --uxp-control-gap: 8px;
  --uxp-control-height: 34px;
  --uxp-card-padding: 10px;
  --uxp-card-radius: 7px;
}
```

Apply consistently.

Required rules:

```text
panel left/right padding: 12px
major section gap: 12px
controls inside a section: 8px
button and select height: 34px
context-card internal padding: 10px
```

Every primary element must align to the same left and right edges:

```text
dropdown
context card
button rows
export card
Advanced section
Connection section
```

Avoid arbitrary values such as separate `margin-left: 6px`, `14px`, `18px` on individual mode sections.

---

# Part 7 — Use reliable box sizing

Apply:

```css
*,
*::before,
*::after {
  box-sizing: border-box;
}
```

For all panel controls:

```css
button,
select,
input,
textarea {
  width: 100%;
  min-width: 0;
}
```

Prevent:

```text
dropdown wider than its card
button edges not aligning
nested panel overflow
horizontal scrolling caused by padding
```

---

# Part 8 — Standardize the two-column action grid

Use one reusable class:

```css
.action-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 8px;
}
```

Use it for:

```text
Previous / Next
Open / Focus tab
other paired actions
```

Do not use manually calculated widths.

At very narrow panel widths:

```css
@media (max-width: 250px) {
  .action-grid {
    grid-template-columns: 1fr;
  }
}
```

Both buttons in one row must have:

```text
same height
same width
same radius
same text alignment
```

---

# Part 9 — Unify Bridge context cards

Shot and Scene 2D should use the same card shell:

```text
.context-card
  .context-type
  .context-heading-row
  .context-primary-title
  .context-secondary-title
  .context-meta
```

Shot example:

```text
SHOT
Untitled shot                         Draft
16 / 58 · 3.0s
```

Scene 2D example:

```text
SCENE 2D
Building A                            PSD
Maps · 3 / 4
```

Use identical:

```text
padding
border
radius
title size
badge position
metadata spacing
```

Do not let Shot use a large multi-row card while Scene 2D uses a separate compact design language.

Optional Shot details such as Action or Notes may appear below the common header inside collapsible or compact rows.

---

# Part 10 — Simplify card borders

Avoid:

```text
panel border
inside card border
inside export card border
inside button outline
```

Use hierarchy through surface and spacing.

Recommended:

```text
one subtle border per context card
one subtle border per export section
no border around every text row
```

Connected status should remain a compact line, not another large bordered card.

---

# Part 11 — Dropdown component

The current native `<select>` popup may use a large white operating-system menu.

First inspect the Photoshop UXP runtime and manifest.

Preferred solution:

```text
use a supported UXP Spectrum dropdown/menu component
```

only when the project’s current UXP runtime supports it reliably.

Use the same dropdown implementation for:

```text
Shot selector
Perspective selector
```

Requirements:

```text
dark closed control
human-readable labels
keyboard accessible
selected option visible
long labels use ellipsis
no UUID in normal display
```

Do not introduce an unsupported web popover implementation.

When Spectrum dropdown is not safely available, retain native `<select>` behavior but:

```text
fix its closed-state size and alignment
use human-readable labels
avoid custom absolute menus
```

OS-native popup coloring is less important than reliable selection behavior.

---

# Part 12 — Typography hierarchy

Use:

```text
context eyebrow: 10–11px, uppercase/muted
primary title: 14px semibold
secondary metadata: 11–12px
button text: 12px
status/footer: 10–11px
```

Avoid:

```text
duplicate large headings
very low-contrast grey labels
title and metadata using the same weight
```

Long titles must use:

```css
overflow: hidden;
text-overflow: ellipsis;
white-space: nowrap;
```

Add the full title through `title` where supported.

---

# Part 13 — Export-section consistency

Shot:

```text
[ Export & next ]
[ Export preview ]

□ Auto-add at end
□ Focus Storyboarder after export
```

Scene 2D:

```text
[ Export & next perspective ]
[ Export preview ]

□ Focus Storyboarder after export
```

Use the same:

```text
section padding
button height
button width
vertical gap
checkbox alignment
```

Do not use `Export_next` with an underscore in visible UI.

Visible strings must be:

```text
Export & next
Export & next perspective
```

---

# Part 14 — Footer and Advanced sections

The synced status, Advanced disclosure, Connection section, and Layers section must align with the main panel content.

Use the same horizontal inset as context and export cards.

Do not let the scrollbar overlap text or controls.

Collapsed sections should have a consistent row height and disclosure alignment.

---

# Part 15 — Responsive validation

Validate both panels at:

```text
220px
260px
320px
380px
```

Required behavior:

```text
no horizontal overflow
no clipped buttons
no floating labels outside sections
dropdown remains usable
two-column grid stacks only when necessary
scrollbar does not cover content
Shot and Scene 2D retain the same alignment
```

Test both panels independently; do not assume they are docked side by side.

---

# Part 16 — Tests

Add backend tests confirming Shot work items contain:

```text
shot_title
index
count
previous_key
next_key
```

Test:

```text
first Shot
middle Shot
last Shot
empty title
non-empty title
```

Add Node tests for:

```js
formatShotDisplayLabel()
```

Expected:

```text
{ index: 1, shot_title: "Copy" }
→ "1. Copy"

{ index: 16, shot_title: "" }
→ "16. Untitled shot"
```

Verify option values remain canonical keys rather than labels.

---

# Likely files

```text
storyboard_tool/plugin_service.py

photoshop_uxp_plugin/index.html
photoshop_uxp_plugin/style.css
photoshop_uxp_plugin/panel.js
photoshop_uxp_plugin/backend_client.js
photoshop_uxp_plugin/work_item_paths.js

tests/test_plugin_scene2d.py
tests/test_plugin_work_item_paths.mjs
```

Do not modify Scene 2D move recovery in this task.

---

# Commands

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests/test_plugin_scene2d.py -q
.venv\Scripts\python.exe -m pytest tests/test_photoshop_bridge.py -q
.venv\Scripts\python.exe -m pytest tests/ -q

node --test tests/test_plugin_work_item_paths.mjs

cd frontend
npm.cmd run build
```

Reload both UXP panels in Photoshop.

---

# Manual validation

Validate Shot mode:

```text
dropdown shows Shot number and title
no visible UUID
blank title becomes Untitled shot
Previous / Next align
Open / Focus align
Bridge context card aligns with Scene 2D
Export section has consistent padding
```

Validate Scene 2D mode:

```text
Scene breadcrumb and Perspective dropdown align with Shot mode
same button dimensions
same context-card shell
same export spacing
no floating or misplaced Scene title
```

Validate panel widths:

```text
220px
260px
320px
380px
```

Do not claim visual validation passed without opening Photoshop.

---

# Acceptance criteria

Complete only when:

```text
- normal UI shows no Shot UUIDs
- dropdown shows Shot index plus title
- blank title has a readable fallback
- Shot and Scene 2D share the same layout skeleton
- all major controls align to the same horizontal edges
- padding and vertical rhythm are consistent
- action grids have equal columns
- export sections use consistent spacing
- no horizontal overflow at supported panel widths
- existing plugin behavior remains unchanged
```

---

# Output required

Report:

```text
Changed files
Backend Shot work-item schema
Shot label formatting rule
Shared Work-panel structure
Shared Bridge context-card structure
Spacing tokens
Dropdown implementation decision
Responsive behavior
Backend test results
Node test results
Manual Photoshop validation
Known limitations
Final commit SHA
```
