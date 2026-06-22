# CODEX_TASK.md — Strengthen the startup splash and preserve window geometry on plugin focus

Repository:

```text
Rampageboo/Storyboarder
```

Base commit:

```text
450c1a433e9af6438d21454aabfaed45f5827cbb
```

## Goal

Fix two desktop-shell issues:

1. The native Storyboarder startup splash is now too brief to have a visible branded presence.
2. Focusing Storyboarder after a Photoshop preview export changes the Storyboarder window from its current size/maximized state back to its normal/default size.

This is a focused desktop-shell task.

Do not change Photoshop export behavior, Scene 2D data, Shot data, or plugin context logic.

---

# Part 1 — Give the startup splash a visible but fast presence

## Current behavior

The PowerShell splash closes immediately when the per-launch `.ready` marker appears.

On a fast startup, the splash may only flash for a fraction of a second.

Do not slow down Python startup or backend initialization.

Only adjust the splash presentation lifecycle.

---

## Required timing model

Add explicit constants near the top of:

```text
scripts/launch-storyboarder-splash.ps1
```

Suggested values:

```powershell
$MinimumVisibleMs = 1000
$ReadyHoldMs = 180
$FadeDurationMs = 160
```

Required behavior:

```text
Splash appears immediately
→ launcher and application continue starting normally
→ ready marker arrives
→ splash remains visible until MinimumVisibleMs has elapsed
→ display a short Ready state
→ fade out and close
```

If startup already took longer than the minimum:

```text
ready marker
→ Ready state for approximately 150–200ms
→ fade out
→ close
```

Do not add a fixed `Start-Sleep` to:

```text
launch_storyboarder.bat
Python startup
desktop.py
```

The application must continue loading concurrently.

---

## Ready state

When the `.ready` marker appears:

```text
title remains Storyboarder
status changes to Ready
progress indicator stops or becomes complete
status color changes to a restrained success tone
```

Optional text:

```text
Ready
Opening workspace…
```

Do not instantly close before the ready state is rendered.

---

## Fade-out

Use the WinForms form opacity for a short fade:

```powershell
$form.Opacity
```

Implement it through a timer rather than a blocking sleep.

Requirements:

```text
fade only after ready
fatal error state must not fade automatically
Escape must still close immediately
120-second timeout must still work
```

Do not create overlapping timers that can close or dispose the form twice.

---

# Part 2 — Improve the splash visual identity

Keep the current dark native WinForms approach, but make the splash look intentional rather than like a temporary diagnostic window.

Use the existing:

```text
storyboard_tool/assets/icon.ico
```

Display a visible application mark near the title.

Suggested composition:

```text
[ 56–64px icon ]  Storyboarder
                  Local storyboard workspace

                  Preparing workspace…
                  ━━━━━━━━━━━━━━━━━━━━━
```

Requirements:

```text
icon and title align vertically
consistent left and right padding
status remains readable
progress bar remains subtle
no large white Windows controls
no excessive gradients or glow
```

Retain:

```text
borderless window
dragging
TopMost while starting
error state
Close button
Escape support
status-file messages
token isolation
```

Do not turn the starter into a large marketing screen.

---

# Part 3 — Do not change window geometry when focusing Storyboarder

## Current problem

`StoryboardBackendService.method_app_focus()` currently invokes:

```python
restore()
show()
focus()
```

for every focus request.

A normal or maximized window must not be restored merely because Photoshop requested focus.

---

## Required focus contract

Calling:

```text
POST /api/app/focus
```

must preserve:

```text
current width
current height
current position
maximized state
normal state
```

It may change only:

```text
visibility
foreground focus
minimized state when positively detected
```

---

## Replace unconditional restore

Do not loop unconditionally through:

```python
("restore", "show", "focus")
```

Implement a dedicated helper, for example:

```python
def _focus_desktop_window(window) -> dict[str, Any]:
    ...
```

Preferred behavior:

```text
1. If the window is known to be minimized:
     restore it once.

2. Otherwise:
     do not call restore.

3. Call show only when needed or as a non-geometry-changing best effort.

4. Call focus.

5. Never call resize, move, maximize, or restore for a normal/maximized window.
```

When the current pywebview backend does not expose a reliable minimized-state query:

```text
prefer show + focus
do not call restore speculatively
```

Preserving geometry is more important than guessing.

---

## Do not modify the Plugin focus request

Keep:

```text
Focus Storyboarder after export
POST /api/app/focus
```

The bug belongs in the desktop focus implementation, not the export workflow.

The same focus endpoint should work for:

```text
Shot preview export
Scene 2D preview export
other future bring-to-front requests
```

---

# Part 4 — Focus response diagnostics

Return useful non-sensitive information:

```json
{
  "ok": true,
  "focused": true,
  "shown": true,
  "restored_from_minimized": false
}
```

Do not return native window handles.

Log failed focus methods at debug level.

A focus failure must not make the completed export fail.

---

# Part 5 — Automated tests

## Splash lifecycle

Keep existing UI-ready marker tests.

Add testable timing logic where practical, or isolate the close-decision calculation into a small PowerShell helper.

Test these decisions:

```text
ready at 200ms:
  close no earlier than MinimumVisibleMs + ReadyHoldMs

ready after 2 seconds:
  only ReadyHoldMs plus fade remains

fatal error:
  no automatic ready fade

timeout:
  still closes safely
```

Do not require a visible WinForms desktop in normal backend pytest.

---

## Desktop focus tests

Add tests using a fake window object.

### Normal window

Fake exposes:

```python
restore
show
focus
```

Expected:

```text
show/focus may be called
restore must not be called
```

### Maximized window

Expected:

```text
focus succeeds
restore is not called
maximized state remains unchanged
```

### Positively detected minimized window

Expected:

```text
restore is called exactly once
focus is called
```

### Failure behavior

If focus raises:

```text
endpoint still returns a structured best-effort result
no geometry method is attempted afterward
```

---

# Part 6 — Manual validation

## Starter

Launch using:

```powershell
.\launch_storyboarder.bat
```

Verify:

```text
splash is clearly visible
icon/title/status feel intentional
fast startup still completes quickly
Ready state appears briefly
fade is smooth
main React window is ready when splash disappears
fatal launcher state still remains visible
Escape still closes the splash
```

## Plugin focus geometry

Test with `Focus Storyboarder after export` enabled.

### Maximized Storyboarder

```text
maximize Storyboarder
switch to Photoshop
Export preview
Storyboarder receives focus
Storyboarder remains maximized
```

### Custom normal size

```text
resize Storyboarder to a distinct non-default size
move it to a distinct screen position
switch to Photoshop
Export preview
Storyboarder receives focus
size and position remain unchanged
```

### Minimized Storyboarder

```text
minimize Storyboarder
Export preview
Storyboarder is restored and focused when supported
it does not reset to 1440 × 900 unnecessarily
```

Test both:

```text
Shot Export preview
Scene 2D Export preview
```

---

# Likely files

```text
scripts/launch-storyboarder-splash.ps1
storyboard_tool/backend_service.py
tests/test_ui_ready.py
new or existing desktop-focus test file
```

Modify `storyboard_tool/desktop.py` only if a reliable minimized-state helper requires desktop-window state tracking.

Do not modify:

```text
photoshop_uxp_plugin/preview_export.js
photoshop_uxp_plugin/backend_client.js
Shot export semantics
Scene 2D export semantics
window default startup size
saved window-state format
```

---

# Commands

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests/test_ui_ready.py -q
.venv\Scripts\python.exe -m pytest tests/ -q

cd frontend
npm.cmd run build
```

Run the actual launcher and Photoshop tests manually.

Do not claim splash or focus behavior passed without running the desktop application.

---

# Acceptance criteria

Complete only when:

```text
- the starter is visibly present during fast startup
- it does not impose a long artificial delay
- ready state is shown before close
- splash closes only after the minimum visible duration
- app focus no longer changes a maximized window to normal size
- app focus preserves custom normal size and position
- minimized recovery is best-effort and does not affect normal windows
- Shot and Scene 2D exports still complete normally
```

---

# Output required

Report:

```text
Changed files
Starter minimum-visible timing
Ready-state and fade behavior
Visual identity changes
Focus method call order
How minimized state is detected
Geometry-preservation behavior
Automated test results
Manual launcher validation
Manual Shot export focus validation
Manual Scene 2D export focus validation
Known limitations
Final commit SHA
```
