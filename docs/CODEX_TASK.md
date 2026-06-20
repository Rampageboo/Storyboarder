# CODEX_TASK.md — Storyboarder: delayed Photoshop preheat + focus after export

Repo: `Rampageboo/Storyboarder`.

Work from the latest branch containing:

```text
32fb29977dd1da2dcc6c9a1ac282197a2d6e58c3
```

## Goal

Implement two Photoshop workflow improvements:

1. After preview export from the Photoshop plugin, optionally focus the Storyboarder app.
2. In Storyboarder, implement delayed, cancellable Photoshop preheat after the app/project is fully loaded.

This task is workflow behavior only. Do not redesign the Photoshop plugin panel.

---

# Part A — Plugin export can optionally focus Storyboarder

## Required behavior

Add a plugin-local option:

```text
Focus Storyboarder after preview export
```

Behavior:

* Default: off.
* Stored in plugin-local settings.
* Visible in the Photoshop plugin settings area if one exists.
* If there is no settings area, add a compact checkbox near the Preview export section.
* Do not redesign the whole plugin panel.

When enabled:

* After successful `Export preview`, request Storyboarder to focus its main window.
* After successful `Export & next`, request Storyboarder to focus its main window.
* This must be best-effort:

  * If Storyboarder is unreachable, preview export still counts as successful.
  * If focus is unsupported, backend returns a clean no-op success.
  * Do not block export.

When disabled:

* Export behavior remains unchanged.

## Backend focus endpoint

Add or reuse a small backend endpoint, for example:

```text
POST /api/app/focus
```

Expected behavior:

* In pywebview desktop mode, try to focus/restore the main Storyboarder window.
* In browser/dev mode, return success with `focused: false`.
* Do not require a project to be open.
* Do not mutate project data.
* Never throw 500 if the window handle is unavailable.

Suggested response:

```json
{
  "ok": true,
  "focused": true
}
```

Exact response shape can follow existing API conventions.

---

# Part B — Delayed, cancellable Photoshop preheat in Storyboarder

## Current context

Storyboarder already has this project setting:

```text
preheat_photoshop_on_open
```

It is controlled from the Storyboarder Settings modal.

This setting should remain in Storyboarder, not the Photoshop plugin.

## Required behavior

When Storyboarder starts and a project is fully loaded:

* If `project.settings.preheat_photoshop_on_open === true`, schedule Photoshop preheat.
* Do not launch Photoshop immediately during app startup.
* Wait until Storyboarder UI/project state is loaded.
* Then show a visible countdown in the top-right Photoshop status pill.

Example states:

```text
Photoshop Disconnected
Preheat Photoshop in 5s — click to cancel
Preheating Photoshop…
Photoshop Connected · ...
```

## Countdown behavior

Add a short countdown before launching Photoshop.

Recommended default:

```text
5 seconds
```

Behavior:

* The top-right Photoshop status pill should visibly change during countdown.
* Use a warning/red/attention style for countdown state.
* Clicking the countdown status cancels the pending preheat.
* Cancel only affects the current app session.
* Do not change the saved `preheat_photoshop_on_open` setting when the user cancels once.
* If the user wants to disable preheat permanently, they should do that in Storyboarder Settings.

## Only once per app session

Preheat should run at most once per app session.

Rules:

* One automatic preheat attempt per app session.
* Opening/reloading the same project should not repeatedly trigger Photoshop.
* If user cancels the countdown, do not schedule it again during the same app session.
* If user manually uses Open Canvas / plugin link / other Photoshop workflow later, do not automatically schedule preheat again.

Use an in-memory session flag on the frontend or backend, whichever fits the current architecture better.

## What “preheat Photoshop” means

Use the lightest existing safe mechanism.

Preferred order:

1. If there is already a helper for launching Photoshop without opening a shot PSD, reuse it.
2. Else, if `photoshop_path` is configured and valid, launch the Photoshop executable.
3. Else, if existing Photoshop path detection exists, use it.
4. Else return a clean no-op result.

Important:

* Do not create a shot canvas.
* Do not open a shot PSD.
* Do not modify any PSD.
* Do not modify project data.
* Do not mark project dirty.
* Do not block UI loading.

## Backend preheat endpoint

Add or reuse a small endpoint, for example:

```text
POST /api/app/preheat-photoshop
```

Expected behavior:

* Best-effort.
* Non-blocking or returns quickly.
* Uses current project settings if needed.
* Handles missing Photoshop path without 500.
* Does not require Photoshop plugin to be connected.
* Does not create/modify project files.

Suggested response:

```json
{
  "ok": true,
  "attempted": true,
  "launched": true,
  "message": ""
}
```

Missing Photoshop path should return something like:

```json
{
  "ok": true,
  "attempted": false,
  "launched": false,
  "message": "Photoshop path is not configured."
}
```

Do not treat missing path as fatal.

---

# Part C — Top-right Photoshop status pill states

The top-right status pill already shows Photoshop connection status.

Extend it to represent preheat states.

Required visual states:

```text
Disconnected: grey
Preheat countdown: red / warning / attention color
Preheating: warning / loading state
Connected: existing green connected style
```

Interaction:

* During countdown, clicking the pill cancels the pending preheat.
* In normal disconnected/connected state, clicking the pill should not break existing behavior.
* Tooltip should explain what clicking does during countdown.

Example display:

```text
Preheat Photoshop in 5s — click to cancel
```

or shorter:

```text
Preheat PS in 5s
```

Keep it compact.

Do not make the topbar taller.

---

# Frontend trigger location

Implement the preheat trigger from Storyboarder frontend after project load is complete.

Suggested logic:

```text
if project is loaded
and initialLoading is false
and project.settings.preheat_photoshop_on_open is true
and this app session has not attempted/cancelled preheat:
    start countdown
```

When countdown reaches zero:

```text
call POST /api/app/preheat-photoshop
mark preheat attempted for this session
```

If user cancels:

```text
cancel countdown
mark preheat cancelled for this session
```

Do not trigger preheat from the Photoshop plugin.

---

# Validation

Run frontend build:

```powershell
cd frontend
npm run build
```

If backend routes/helpers are changed, run:

```powershell
.venv\Scripts\python.exe -m pytest tests/ -q
```

## Manual validation — focus after export

```text
1. Open Storyboarder desktop app.
2. Open a project.
3. Open Photoshop and load the UXP plugin.
4. Link plugin to Storyboarder.
5. Enable "Focus Storyboarder after preview export" in the plugin.
6. Click Export preview.
7. Confirm preview export succeeds.
8. Confirm Storyboarder window is focused after export.
9. Repeat with Export & next.
10. Disable the setting.
11. Confirm export still succeeds and Storyboarder is not forcibly focused.
```

## Manual validation — delayed preheat

```text
1. In Storyboarder Settings, enable "Preheat Photoshop when Storyboarder opens".
2. Save settings.
3. Close Storyboarder and Photoshop.
4. Reopen Storyboarder and open/restore the project.
5. Confirm Storyboarder UI loads first.
6. Confirm the top-right Photoshop status pill shows a countdown.
7. Click the countdown pill.
8. Confirm preheat is cancelled and Photoshop does not launch.
9. Restart Storyboarder.
10. Let the countdown finish.
11. Confirm Photoshop launches/preheats.
12. Confirm no shot PSD is created or modified.
13. Confirm preheat does not run again in the same app session.
```

## Regression checks

```text
1. Existing Photoshop connected/disconnected status still works.
2. Existing Export preview still updates Storyboarder.
3. Existing Export & next still advances normally.
4. Open canvas still works.
5. Focus open tab still works.
6. Settings modal still opens.
7. BoardStrip scroll/insert still works.
8. Reference segment slider still works.
9. No backend 500 when Photoshop path is missing.
```

---

# Out of scope

Do not do any of the following:

* Do not redesign the Photoshop plugin panel.
* Do not reorganize the long plugin layout.
* Do not remove existing plugin buttons.
* Do not change preview export image/layer behavior.
* Do not change PSD saving.
* Do not open/create shot PSDs during preheat.
* Do not force-kill or restart Photoshop.
* Do not make preheat mandatory.
* Do not block Storyboarder startup while launching Photoshop.
* Do not change BoardStrip.
* Do not change Reference panel.
* Do not change Reference Segment slider.
* Do not change topbar menu structure except the PS status pill state.
* Do not add new dependencies.

---

# Output required

When finished, report:

```text
Changed files
Where the plugin focus setting is stored
Which export paths trigger focus
Which backend focus/preheat route or helper was added/reused
How the preheat countdown/cancel logic works
How missing Photoshop path is handled
Validation results
```
