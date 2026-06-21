# CODEX_TASK.md — Immediate startup splash + real startup performance pass

Repo: `Rampageboo/Storyboarder`

Work from the latest active branch containing at least:

```text
e9e3fb272effd49f2521e9cf4069f099a59b9f31
```

## Goal

Improve Storyboarder startup in two ways:

1. **Perceived responsiveness**

   * Show a lightweight native starter/splash immediately after the user launches Storyboarder.
   * The user must see visible feedback before Python, FastAPI, pywebview, React, and project loading finish.

2. **Actual startup time**

   * Remove unnecessary image decoding and duplicate filesystem work from the critical startup path.
   * Avoid loading Scene 2D / Scene 3D data before those workspaces are opened.
   * Reduce duplicate startup API calls.

Use the startup model in `Rampageboo/YoloWorkBench` as a conceptual reference:

```text
launcher-level native splash
+ unique ready marker
+ backend/main UI startup in parallel
+ close splash when UI is genuinely ready
+ timeout safety fallback
```

Do not copy YoloWorkBench implementation blindly because Storyboarder uses Python + FastAPI + pywebview rather than Tauri.

---

# Scope boundary

This task may modify:

```text
launch scripts
storyboard_tool/desktop.py
storyboard_tool/api.py
storyboard_tool/backend_service.py
storyboard_tool/app_state.py
storyboard_tool/session_store.py
frontend startup/project context
frontend Scene 2D / Scene 3D loading behavior
frontend missing-files loading behavior
tests related to startup/bootstrap/cache
```

Do not modify:

```text
photoshop_uxp_plugin/*
PSD creation or recovery
SB bg behavior
preview export behavior
shot layer behavior
PDF/animatic/export output
Scene 2D storage format
Scene 3D storage format
reference segment semantics
```

This is a startup/responsiveness pass only.

---

# Part A — Immediate native starter window

## Required user experience

Current behavior:

```text
User launches app
→ no visible response
→ Python/FastAPI starts
→ pywebview appears later
```

Target behavior:

```text
User launches app
→ native starter appears almost immediately
→ Storyboarder starts in background
→ starter shows activity/status
→ React UI becomes usable
→ starter closes
```

The starter should not claim fake numeric progress.

Use an indeterminate animated bar or spinner.

Suggested content:

```text
Storyboarder

Starting local service…
Loading project…
Preparing workspace…
```

---

# A1. Implement a lightweight Windows starter

Add a lightweight Windows-only starter similar in principle to:

```text
YoloWorkBench/scripts/launch-splash.ps1
```

Suggested file:

```text
scripts/launch-storyboarder-splash.ps1
```

Use:

```text
System.Windows.Forms
System.Drawing
```

The splash must:

```text
- appear before the main Python application is launched
- be centered
- use the Storyboarder icon if available
- be borderless or visually minimal
- show Storyboarder title
- show an indeterminate progress animation
- show rotating status messages
- be draggable if borderless
- close on Escape as a safety escape hatch
- never permanently trap the desktop
```

Suggested size:

```text
420–480px wide
240–320px high
```

Do not make it unnecessarily complex.

---

# A2. Add a launcher entrypoint

Inspect the existing user-facing startup scripts first.

Integrate the starter into the actual Windows startup path used by the project.

Suggested pattern:

```text
launch_storyboarder.bat or launch_storyboarder.ps1

1. Generate a unique launch token.
2. Start launch-storyboarder-splash.ps1 asynchronously.
3. Pass the launch token to the Storyboarder Python process.
4. Start the normal Storyboarder desktop application.
```

The splash must start **before** the Python process imports FastAPI, Pillow, OpenCV, psd-tools, reportlab, or other heavy modules.

Do not start the splash from deep inside `desktop.py` after all Python imports have already happened.

---

# A3. Use per-launch token files

Do not use one fixed ready file such as:

```text
%TEMP%\storyboarder-launch-ready
```

Use a unique token per launch.

Example environment variable:

```text
STORYBOARDER_LAUNCH_TOKEN=<random-token>
```

Example files:

```text
%TEMP%\storyboarder-launch-<token>.ready
%TEMP%\storyboarder-launch-<token>.pid
%TEMP%\storyboarder-launch-<token>.status
```

Requirements:

```text
- stale files from an old crash must not close a new splash
- two simultaneous launches must not interfere with each other
- temporary marker files should be cleaned up when possible
- missing token must be handled safely
```

Use a secure random token or UUID.

---

# A4. Splash status communication

The starter may rotate generic stages based on elapsed time:

```text
Starting Storyboarder…
Starting local service…
Loading project…
Preparing workspace…
```

Optionally allow the main process to update a small status marker file.

Do not block launch waiting for status updates.

The starter should poll approximately every:

```text
150–300ms
```

It should close when either:

```text
1. the exact launch token ready marker exists, or
2. the main Storyboarder window is visibly present and large enough
```

The token ready marker is the primary signal.

Visible-window detection is only a fallback.

---

# A5. Close splash only when the UI is actually ready

Do not close the splash merely because FastAPI started.

Correct sequence:

```text
FastAPI server ready
→ pywebview loads React
→ React project bootstrap finishes
→ Welcome screen or Board workspace renders
→ browser paints at least one frame
→ frontend reports ui-ready
→ backend writes the token-specific ready marker
→ splash closes
```

Add a small endpoint or desktop bridge method, for example:

```text
POST /api/app/ui-ready
```

The frontend should call it once per application launch.

Suggested frontend logic:

```ts
useEffect(() => {
  if (initialLoading) return

  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      void reportUiReady()
    })
  })
}, [initialLoading])
```

The double `requestAnimationFrame` is intended to allow the Welcome or Board UI to paint before dismissing the starter.

The endpoint must:

```text
- read STORYBOARDER_LAUNCH_TOKEN
- validate the token format
- write only the corresponding ready marker
- behave as a safe no-op when no launch token exists
- never expose arbitrary filesystem writes
```

Do not accept a client-provided path.

---

# A6. Timeout and failure safety

The starter must have safety behavior.

Suggested timing:

```text
30 seconds:
  show “Startup is taking longer than expected…”

120 seconds:
  keep the window closable
  do not lock the user out
```

If the main process exits early:

```text
- the splash must eventually detect failure or timeout
- the user must be able to close it with Escape
```

Do not use broad `taskkill` commands that could kill unrelated PowerShell processes.

If force-closing the splash process is required:

```text
- use its exact PID
- validate image/process identity
- tolerate the splash already having closed
```

---

# Part B — Real startup performance

Before optimizing, add lightweight timing instrumentation.

Use:

```python
time.perf_counter()
```

Log startup stages at debug/info level.

Required stages:

```text
desktop process entered
FastAPI app imported
internal server thread started
server ready
pywebview window created
React bootstrap requested
session loaded
project opened
project payload built
frontend UI-ready received
```

Do not log on every render.

Output should make it possible to see:

```text
process → server ready
server ready → React request
project load duration
project payload duration
UI-ready duration
```

---

# B1. Remove full image analysis from the critical project payload path

## Current problem

`storyboard_tool/app_state.py::_shot_payload()` currently performs expensive image inspection for every shot:

```python
is_solid_color_image(preview_path)
image_has_transparency(preview_path)
```

This may decode every preview image during startup.

The project payload should not reopen and decode every preview on every application launch.

## Required solution

Introduce a persistent preview-analysis cache.

Cache identity must include:

```text
normalized preview path
mtime_ns
file size
```

Cached values:

```text
has_artwork_preview
preview_has_transparency
```

Suggested storage location:

```text
reuse an existing project cache/metadata directory if one exists
```

If no cache convention exists, use a clearly isolated project cache file such as:

```text
<project>/workspace/cache/preview_analysis.json
```

Do not mix it into `shots.json`.

Requirements:

```text
- cache reads must be cheap
- cache corruption must be ignored safely
- cache writes must be atomic
- cache failure must never prevent project opening
- changed image mtime or file size invalidates the entry
- missing preview removes or ignores the entry
```

## Critical startup rule

During initial project payload generation:

```text
- use valid cached results when available
- do not synchronously decode every uncached preview
```

For an uncached preview, return a safe provisional state, then analyze it later.

Suggested provisional behavior:

```text
has_artwork_preview = preview file exists
preview_has_transparency = false or null/unknown
```

Preserve frontend compatibility.

Do not break CanvasBoard composite rendering.

---

# B2. Deferred preview analysis

Add a deferred/background analysis path for previews that do not have valid cache entries.

Possible implementation:

```text
GET or POST /api/project/preview-analysis/refresh
```

or a background task started after bootstrap.

Requirements:

```text
- initial Board UI must not wait for all previews to be decoded
- analyze only stale/missing cache entries
- process incrementally
- avoid excessive CPU/disk spikes
- update cache after analysis
- frontend may refresh project metadata when analysis finishes
```

Prefer batching or bounded work.

Do not spawn one unbounded thread per shot.

A simple sequential background worker is acceptable.

---

# B3. Create one bootstrap endpoint

## Current problem

Frontend startup currently performs a sequence similar to:

```text
get app session
get current project
if no project:
  open last project
```

This causes additional round trips and may build project payload more than once.

## Required endpoint

Add:

```text
GET /api/app/bootstrap
```

Suggested response:

```json
{
  "session": {},
  "project": {},
  "opened_last_project": true,
  "startup_timings": {}
}
```

Behavior:

```text
1. Read app session.
2. If a project is already open, return it.
3. Otherwise, if session.last_project_json_path exists:
   - try to open it once
   - return the opened project
4. If no project is available:
   - return project: null
5. Do not treat “no previous project” as an error.
6. If the previous path is invalid:
   - clear or ignore it safely
   - return project: null
   - provide a non-fatal warning if useful
```

The project payload should be built only once for this bootstrap request.

Update `ProjectContext.reloadProject()` to use this bootstrap endpoint.

Keep existing session/project endpoints for backward compatibility.

---

# B4. Lazy-load Scene 2D and Scene 3D

## Current problem

Scene 2D and Scene 3D components currently request data during initial mounting, even if the user remains in Board mode.

Scene 2D may request:

```text
listScene2D
listScene3D
```

Scene 3D separately requests:

```text
listScene3D
```

This creates unnecessary startup work and duplicate Scene 3D requests.

## Required behavior

Do not fetch Scene 2D or Scene 3D data during initial Board startup.

Load them on first activation:

```text
first click Scene 2D
→ load Scene 2D collection
→ load Scene 3D link options

first click Scene 3D
→ load Scene 3D collection
→ initialize editor only when needed
```

After first load:

```text
- preserve data and selection state
- do not reload on every workspace switch
- refresh only when project changes or an explicit mutation requires it
```

If the workspace-mode refactor has already landed, use its `active` or `workspaceMode` state.

If it has not landed, implement lazy loading in a way that remains compatible with the upcoming workspace-mode refactor.

Do not create the WebGL editor during Board startup.

---

# B5. Deduplicate missing-files scans

## Current problem

CanvasBoard and BoardStrip may independently request missing-file information.

This can scan the same project filesystem multiple times immediately after startup.

## Required solution

Move missing-file state into a shared location, preferably `ProjectContext`.

Suggested state:

```ts
missingFilesByShot
missingFilesLoading
refreshMissingFiles()
```

CanvasBoard and BoardStrip must read the same result.

Only one request may be in flight at a time.

Initial missing-file scan should be deferred until after first paint.

Suggested scheduling:

```ts
if ('requestIdleCallback' in window) {
  requestIdleCallback(() => refreshMissingFiles())
} else {
  setTimeout(() => refreshMissingFiles(), 500)
}
```

Requirements:

```text
- do not block initialLoading on missing-file scan
- refresh after operations that materially change file paths
- avoid scanning on every React render
- preserve missing-file warnings once loaded
```

---

# B6. Do not start Photoshop during critical startup

Keep existing Photoshop preheat behavior compatible, but it must not compete with initial project/UI loading.

Required behavior:

```text
- never launch Photoshop before frontend UI-ready
- preferably wait for browser idle or at least 10 seconds after UI-ready
- cancel or postpone preheat if the user is actively interacting
- if Photoshop is already linked, do nothing
```

Do not remove the user setting.

Do not make Photoshop preheat part of `initialLoading`.

---

# B7. Avoid unnecessary project reloads

Review frontend and backend startup paths for duplicate calls to:

```text
getProject()
openProject()
listScene3D()
listScene2D()
getMissingFiles()
```

During a normal warm startup with a valid last project, target:

```text
1 bootstrap request
1 deferred missing-files request
0 Scene 2D requests until Scene 2D is opened
0 Scene 3D requests until Scene 3D is opened
0 preview image decodes on the synchronous critical path
```

Do not introduce a fragile global singleton solely to meet these numbers.

---

# Part C — Main window behavior

The starter solves the initial no-feedback period.

Do not add a second pywebview splash window.

Keep one main pywebview window.

The main window may remain hidden until its URL is ready if this can be done safely.

Once shown:

```text
- show maximized/restored state as before
- do not flash a white empty window
- preserve existing saved window state behavior
```

Set an appropriate dark background before React paints.

If pywebview does not safely support hidden-until-ready in the current architecture, keep the existing behavior and rely on the native starter.

Do not risk window lifecycle stability for a minor visual improvement.

---

# Tests

## Backend tests

Add tests for bootstrap:

```text
1. No open project and no session path:
   project is null.

2. Existing open project:
   returned without reopening.

3. Valid last_project_json_path:
   project is opened and returned.

4. Missing/invalid previous project path:
   non-fatal result with project null.

5. Project payload built only once per bootstrap request where practical to assert.
```

Add tests for preview cache:

```text
1. Cache miss does not block startup with full image decoding.
2. Valid path + mtime_ns + size cache entry is reused.
3. Changed mtime invalidates cache.
4. Changed size invalidates cache.
5. Corrupt cache JSON is ignored.
6. Cache write is atomic.
7. Missing preview does not crash.
8. Actual analysis produces the correct booleans.
```

Add tests for UI-ready marker:

```text
1. No token → safe no-op.
2. Valid token → writes only the expected temp marker.
3. Invalid token characters → rejected or ignored.
4. Client cannot supply arbitrary filesystem path.
```

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests/ -q
```

## Frontend validation

Run:

```powershell
cd frontend
npm.cmd run build
```

If frontend tests exist, run them.

---

# Manual startup validation

Test both development and packaged/normal desktop launch where available.

## Starter behavior

```text
1. Launch Storyboarder.
2. Confirm the starter appears almost immediately.
3. Confirm no console window flashes unnecessarily.
4. Confirm status animation remains responsive.
5. Confirm main UI eventually appears.
6. Confirm starter closes only after Welcome or Board UI paints.
7. Press Escape on starter and confirm it closes safely.
8. Kill the main process during startup and confirm starter is still closable.
9. Leave stale old marker files and confirm a new launch is not affected.
10. Launch two instances and confirm their markers do not interfere.
```

## Startup performance

Measure:

```text
cold launch with no project
warm launch with last project
project with 10 shots
project with 100+ shots
project with large transparent previews
project stored on a slower drive
```

Confirm:

```text
- initial UI does not synchronously decode every preview
- Board becomes visible before missing-file scan completes
- Scene 2D is not loaded until selected
- Scene 3D and WebGL editor are not loaded until selected
- Scene 3D list is not requested twice at startup
- Photoshop does not launch before UI-ready
```

---

# Performance acceptance criteria

Do not promise a fixed millisecond target across all computers.

Required qualitative targets:

```text
- visible starter appears within roughly one second under normal Windows conditions
- user never experiences an unexplained blank wait
- warm project startup performs no full preview-image analysis on the critical path
- Board/Welcome UI is usable before optional health checks finish
- Scene 2D/3D startup work is deferred until requested
```

Log measured before/after timing results.

---

# Reliability requirements

Startup optimization must not compromise data integrity.

Do not:

```text
- skip loading project.json correctness checks
- mutate shot data merely to make startup faster
- silently discard invalid project data
- run concurrent writes to the same cache file
- allow background workers to outlive project switches and write to the wrong project
- allow a stale launch token to dismiss a new starter
```

When the project changes while background preview analysis is running:

```text
- cancel, invalidate, or safely ignore results for the old project
```

---

# Files likely affected

Possible files:

```text
scripts/launch-storyboarder-splash.ps1
launch_storyboarder.bat or existing launcher script
storyboard_tool/desktop.py
storyboard_tool/api.py
storyboard_tool/backend_service.py
storyboard_tool/app_state.py
storyboard_tool/session_store.py
storyboard_tool/preview_analysis_cache.py
frontend/src/api.ts
frontend/src/state/ProjectContext.tsx
frontend/src/App.tsx
frontend/src/components/CanvasBoard.tsx
frontend/src/components/BoardStrip.tsx
frontend/src/components/Scene2DPanel.tsx
frontend/src/components/Scene3DPanel.tsx
frontend/src/components/Topbar.tsx
tests/test_bootstrap.py
tests/test_preview_analysis_cache.py
tests/test_ui_ready.py
```

Reuse existing architecture and naming where appropriate.

Do not create unnecessary abstractions merely to match this suggested list.

---

# Implementation order

Implement in this order:

```text
1. Add startup timing instrumentation.
2. Add unique-token native starter and ready handshake.
3. Add bootstrap endpoint and frontend bootstrap call.
4. Remove synchronous all-preview decoding from project payload.
5. Add persistent preview-analysis cache and deferred analysis.
6. Deduplicate and defer missing-files scan.
7. Lazy-load Scene 2D and Scene 3D.
8. Move Photoshop preheat after UI-ready/idle.
9. Run full tests and manual startup validation.
```

Do not combine unrelated UI redesign work into this commit.

---

# Output required

When finished, report:

```text
Changed files

Starter:
- how it is launched before Python
- token/marker design
- status behavior
- ready handshake
- timeout/failure behavior

Real startup improvements:
- bootstrap endpoint behavior
- preview-analysis cache design
- what was removed from the synchronous critical path
- missing-files deduplication
- Scene 2D/3D lazy-loading behavior
- Photoshop preheat timing

Measurements:
- before/after timing
- cold launch
- warm launch
- representative project size

Validation:
- backend tests
- frontend build
- manual starter checks
- known limitations
```
