# CODEX_TASK.md — Harden desktop focus state and remove remaining UUID/dead Quick Note UI

Repository:

```text
Rampageboo/Storyboarder
```

Base commit:

```text
444776d6184eb2815ffbb5d8fae8b51f1b09ae8a
```

## Goal

Complete a focused reliability and cleanup pass after the startup-splash and Photoshop UXP UI changes.

The current implementation already fixes the primary window-geometry regression:

```text
normal Storyboarder window
→ Photoshop Export preview
→ Storyboarder keeps its custom size and position

maximized Storyboarder window
→ Photoshop Export preview
→ Storyboarder remains maximized
```

Preserve that behavior.

Fix the remaining issues:

```text
1. Track the actual current minimized/maximized/restored state of the pywebview window.

2. Restore the window only when it is genuinely minimized.

3. Remove the incorrect assumption that pywebview Window exposes a callable focus() method.

4. Make /api/app/focus diagnostics reflect the real operations performed.

5. Remove Shot UUIDs from normal connection and sync status text.

6. Keep Quick Note intentionally removed and delete its remaining dead frontend/plugin code.
```

This is not a UI redesign.

---

# Product decisions to preserve

Do not change:

```text
Starter minimum-visible timing
Starter Ready state
Starter fade behavior
Starter appearance

current Storyboard Work layout
current Storyboard Bridge layout
Shot and Scene 2D shared panel structure
Shot dropdown labels
Scene 2D navigation
export sections
status buttons
onion skin
Advanced section

Shot export behavior
Scene 2D export behavior
Focus Storyboarder after export checkbox
heartbeat logic
work-context logic
filesystem paths
UUID identity
```

Quick Note has intentionally been removed because it caused Shot and Scene 2D layouts to have inconsistent heights.

Do not reintroduce Quick Note in this task.

---

# Part 1 — Track the live desktop window state

## Current issue

The focus helper currently reads:

```python
window.minimized
```

as though it represents the current operating-system window state.

In pywebview 6.2.1 this is primarily an initial window configuration value and is not a reliable live minimized-state query.

pywebview does expose window events:

```text
window.events.minimized
window.events.maximized
window.events.restored
window.events.shown
```

Use these events to maintain application-owned runtime state.

---

## Add explicit runtime state

In the desktop startup path, initialize:

```python
app.state.main_window_state = "normal"
```

Allowed values:

```text
normal
maximized
minimized
```

A small dataclass or enum is acceptable, but a validated string is sufficient.

Attach handlers after creating the main pywebview window:

```python
def _mark_minimized(*_args):
    app.state.main_window_state = "minimized"

def _mark_maximized(*_args):
    app.state.main_window_state = "maximized"

def _mark_restored(*_args):
    app.state.main_window_state = "normal"

def _mark_shown(*_args):
    if app.state.main_window_state not in {"maximized", "minimized"}:
        app.state.main_window_state = "normal"
```

Register:

```python
window.events.minimized += _mark_minimized
window.events.maximized += _mark_maximized
window.events.restored += _mark_restored
window.events.shown += _mark_shown
```

Use the event-registration style already supported by this project and pywebview version.

Do not resize or move the window inside these handlers.

---

## Keep state consistent after programmatic restore

When the focus helper successfully restores a minimized window:

```python
app.state.main_window_state = "normal"
```

Do not wait indefinitely for a later event before updating state.

If restore fails, keep the state as `minimized`.

---

# Part 2 — Refactor desktop focus helper around real pywebview behavior

## Current incorrect assumption

The current helper tries:

```python
window.focus()
```

Real pywebview `Window` uses `focus` as a configuration value; it is not reliably a callable public focus method.

On the Windows backend, `window.show()` already performs the equivalent of:

```text
Show
Activate
```

Do not model tests around a fake callable `window.focus()` API.

---

## Required helper contract

Refactor to something equivalent to:

```python
def _focus_desktop_window(
    window,
    *,
    window_state: str = "normal",
) -> dict[str, Any]:
    ...
```

The helper must:

```text
1. Restore only when window_state == "minimized".
2. Never restore a normal window.
3. Never restore a maximized window.
4. Call show() as the best-effort visibility/activation request.
5. Never call resize(), move(), maximize(), or an assumed focus() method.
6. Never fail the completed Photoshop export merely because activation failed.
```

Suggested implementation behavior:

```python
restored = False
shown = False
activation_requested = False
errors = []

if window_state == "minimized":
    try:
        window.restore()
        restored = True
    except Exception as exc:
        errors.append("restore_failed")

try:
    window.show()
    shown = True
    activation_requested = True
except Exception:
    errors.append("show_failed")
```

Do not call `window.restore()` when `window_state` is `normal` or `maximized`.

---

# Part 3 — Update method_app_focus

Use the application-maintained state:

```python
window_state = getattr(
    self.app.state,
    "main_window_state",
    "normal",
)
```

Then call the focus helper.

After a successful minimized restore:

```python
self.app.state.main_window_state = "normal"
```

Return structured diagnostics such as:

```json
{
  "ok": true,
  "shown": true,
  "activation_requested": true,
  "restored_from_minimized": false,
  "window_state_before": "maximized",
  "window_state_after": "maximized"
}
```

For a minimized window successfully restored:

```json
{
  "ok": true,
  "shown": true,
  "activation_requested": true,
  "restored_from_minimized": true,
  "window_state_before": "minimized",
  "window_state_after": "normal"
}
```

Do not claim:

```json
"focused": true
```

unless there is a real API result proving focus.

For backward compatibility, `focused` may remain in the response, but define it conservatively:

```python
focused = activation_requested
```

and document that it means an activation request was issued, not that the OS guaranteed foreground focus.

Alternatively deprecate it while keeping the field.

Do not expose native handles.

---

# Part 4 — Preserve geometry explicitly

Before performing the activation request, optionally read the current geometry for diagnostics only:

```python
width
height
x
y
```

Do not write it back during the ordinary focus path.

The focus implementation must never call:

```text
resize
set_window_size
move
maximize
restore for normal/maximized windows
```

Acceptance behavior:

```text
custom normal size:
  unchanged

custom normal position:
  unchanged

maximized:
  remains maximized

minimized:
  restored to its previous normal geometry when supported
```

Do not reset a restored window to the application’s initial 1440 × 900 dimensions.

---

# Part 5 — Correct desktop-focus tests

Replace fake tests that expose a callable:

```python
window.focus
```

with a fake matching the real pywebview surface:

```python
window.restore = MagicMock()
window.show = MagicMock()
window.resize = MagicMock()
window.move = MagicMock()
window.maximize = MagicMock()
```

There should be no fake callable `focus()`.

---

## Required test cases

### Normal state

```python
result = _focus_desktop_window(window, window_state="normal")
```

Assert:

```text
restore not called
show called once
resize not called
move not called
maximize not called
restored_from_minimized == false
```

### Maximized state

```python
result = _focus_desktop_window(window, window_state="maximized")
```

Assert:

```text
restore not called
show called once
window_state_after remains maximized
```

### Minimized state

```python
result = _focus_desktop_window(window, window_state="minimized")
```

Assert:

```text
restore called once
show called once
restored_from_minimized == true
window_state_after == normal
```

### Restore failure

Assert:

```text
show is still attempted
restored_from_minimized == false
window state does not falsely become normal
structured result returned
```

### Show failure

Assert:

```text
no exception escapes
activation_requested == false
geometry methods remain untouched
```

---

# Part 6 — Test desktop event tracking

Add a focused helper for registering or updating state so the logic can be tested without launching an actual WinForms desktop.

Suggested pure functions:

```python
def _set_main_window_state(app, state: str) -> None:
    ...

def _get_main_window_state(app) -> str:
    ...
```

Test:

```text
shown from unknown → normal
minimized → minimized
restored → normal
maximized → maximized
shown must not incorrectly replace maximized with normal
```

Where practical, use fake event objects to confirm the handlers are attached.

Do not require a visible GUI during pytest.

---

# Part 7 — Remove UUID from normal Plugin connection text

## Current issue

The Bridge connection row still uses the active Shot ID:

```js
const label = shotId || live.project_name || "project";
setLinkStatus(`Linked · ${label}`);
```

For UUID-based shots this displays unreadable values.

Normal UI must never show raw Shot UUIDs.

---

## Required connection text

The compact connection row should always describe the project connection:

```text
Linked · Storyboard_Project
```

Use:

```js
const projectLabel =
  context?.project_name ||
  live.project_name ||
  "Storyboarder";

setLinkStatus(`Linked · ${projectLabel}`);
```

Do not substitute the active Shot ID.

Scene 2D and Shot mode should use the same project-level connection text.

---

# Part 8 — Human-readable sync status

Replace:

```text
Synced: <shot UUID>
```

with:

```text
Synced · 16. Untitled shot
```

or:

```text
Synced · 4. Look at the moon
```

Use existing helpers:

```js
shotWorkItemById()
formatShotDisplayLabel()
shotDisplayLabel()
```

Suggested:

```js
const workItem = shotWorkItemById(shotId);
const displayLabel = workItem
  ? formatShotDisplayLabel(workItem)
  : shotDisplayLabel(shotId, currentShotIndex(), currentShotFromProjectData()?.title);

setStatus(`Synced · ${displayLabel}`);
```

Do not expose the UUID as a fallback.

When no semantic label is available:

```text
Synced · Shot
```

is preferable to a UUID.

Raw IDs may appear only inside Advanced diagnostics or console logs.

---

# Part 9 — Remove remaining normal-UI UUID fallbacks

Audit visible text paths including:

```text
connection row
sync status
focused-tab status
open-tab errors
current work indicator
Shot selector
Shot card
```

User-facing success text should use:

```text
Shot number
Shot title
Perspective title
Scene title
```

not UUID.

Internal logs may retain canonical IDs.

Error messages may include a technical ID only when necessary for diagnosing a missing file, preferably after a human-readable label.

---

# Part 10 — Keep Quick Note intentionally removed

Quick Note has been deliberately removed to keep Shot and Scene 2D Bridge layouts consistent.

Do not restore:

```text
quickNoteText
addQuickNote
shotCardHint
quick-note-row
quick-note-input
Add note button
```

Remove remaining dead references from JavaScript:

```js
$("addQuickNote")?.addEventListener(...)
$("quickNoteText")
$("shotCardHint")
addQuickNoteViaBackend()
```

Remove unused constants, helper functions, CSS selectors, and comments that exist only for Quick Note.

Do not remove backend comment/note APIs because they may still be used by Storyboarder itself or future UI.

Only remove dead Photoshop UXP entry points.

---

# Part 11 — Preserve equal Shot and Scene 2D panel heights

Do not add mode-specific permanent form rows that make one mode substantially taller.

Shot and Scene 2D must continue using:

```text
connection row
context card
export section
status footer
Advanced
```

Shot-only metadata sections may remain conditional.

No permanent Quick Note textarea should return.

If Quick Note is reconsidered in a future task, it should be placed below the export section as a collapsed optional tool, not inside the primary context card. Do not implement that now.

---

# Part 12 — Starter

Do not modify the current Starter implementation unless a test exposes a real defect.

Preserve:

```text
MinimumVisibleMs = 1000
ReadyHoldMs = 180
FadeDurationMs = 160
Ready status
application icon
error state
Escape support
120-second timeout
```

This task does not need another Starter visual redesign.

---

# Likely files

```text
storyboard_tool/desktop.py
storyboard_tool/backend_service.py

photoshop_uxp_plugin/panel.js
photoshop_uxp_plugin/backend_client.js
photoshop_uxp_plugin/work_item_paths.js
photoshop_uxp_plugin/style.css
photoshop_uxp_plugin/index.html

tests/test_desktop_focus.py
tests/test_photoshop_bridge.py
tests/test_plugin_work_item_paths.mjs
```

Change additional files only when required for event-state tracking.

---

# Required commands

Run focused tests:

```powershell
.venv\Scripts\python.exe -m pytest tests/test_desktop_focus.py -q
.venv\Scripts\python.exe -m pytest tests/test_photoshop_bridge.py -q
.venv\Scripts\python.exe -m pytest tests/test_plugin_work_items.py -q

node --test tests/test_plugin_work_item_paths.mjs
```

Run all backend tests:

```powershell
.venv\Scripts\python.exe -m pytest tests/ -q
```

Build frontend:

```powershell
cd frontend
npm.cmd run build
```

Do not claim tests passed unless they were actually run.

---

# Manual validation

## Window geometry

With `Focus Storyboarder after export` enabled:

### Custom normal window

```text
resize Storyboarder to an obvious custom size
move it to a distinct position
switch to Photoshop
Export preview
confirm size and position remain unchanged
```

### Maximized window

```text
maximize Storyboarder
switch to Photoshop
Export preview
confirm it remains maximized
```

### Minimized window

```text
minimize Storyboarder
Export preview
confirm it restores and activates when supported
confirm it returns to its previous normal geometry
confirm it does not reset to 1440 × 900
```

Test both:

```text
Shot Export preview
Scene 2D Export preview
```

---

## Plugin text

In Shot mode confirm:

```text
connection row shows project name
sync footer shows Shot number and title
dropdown shows Shot number and title
no raw UUID appears in normal UI
```

In Scene 2D mode confirm:

```text
connection row still shows project name
Scene and Perspective titles remain readable
no Shot UUID remains visible
```

---

## Quick Note

Confirm:

```text
no Quick Note textarea
no Add note button
no empty spacing where Quick Note used to be
no console error caused by missing Quick Note elements
Shot and Scene 2D layouts remain consistent
```

---

# Acceptance criteria

Complete only when:

```text
- normal and maximized focus requests never call restore
- minimized state is tracked from real pywebview events
- minimized focus restores exactly once
- no resize or move operation occurs during focus
- tests model the real pywebview API
- normal Plugin UI displays no Shot UUID
- connection row displays project name
- sync status displays Shot number and title
- Quick Note remains removed
- dead Quick Note plugin code is removed
- Shot and Scene 2D panel layout consistency is preserved
- existing Starter behavior remains unchanged
```

---

# Suggested commit

```text
fix: track desktop window state and clean plugin labels
```

---

# Output required

Report:

```text
Changed files

Desktop focus:
  tracked window states
  event handlers
  restore decision
  show/activation behavior
  response diagnostics
  geometry preservation

Plugin text:
  connection label rule
  sync label rule
  UUID visibility audit

Quick Note:
  removed dead listeners
  removed dead functions
  removed dead CSS/markup references

Focused test results
Full pytest result
Node test result
Frontend build result
Manual normal-window validation
Manual maximized-window validation
Manual minimized-window validation
Manual Shot and Scene 2D text validation
Known limitations
Final commit SHA
```
