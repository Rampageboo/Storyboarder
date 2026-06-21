# CODEX_TASK.md — Complete Storyboarder startup responsiveness and preview-analysis lifecycle

Repo: `Rampageboo/Storyboarder`

Base:

```text
Use the commit produced by the Scene 2D migration reliability task.
It must contain 08dafe37b77c60f5e2c67c41faabfd6a2abb3def.
```

## Goal

Complete the startup optimization introduced in `08dafe...`.

The existing implementation has useful foundations:

```text
single-round-trip bootstrap
UI-ready endpoint
per-launch token marker
native WinForms splash
deferred missing-file scan
Scene 2D / Scene 3D lazy loading
persistent preview-analysis cache
background preview-analysis endpoint
```

However, three parts are incomplete:

```text
1. The splash starts after virtual-environment and dependency checks,
   so launch feedback is not truly immediate.

2. Preview analysis is implemented on the backend,
   but the frontend does not reliably start it after first paint.

3. When background analysis completes,
   the current project UI is not notified to reload the real results.
```

Fix these without changing Photoshop plugin behavior.

---

# Scope

Likely files:

```text
launch_storyboarder.bat
scripts/launch-storyboarder-splash.ps1

storyboard_tool/api.py
storyboard_tool/backend_service.py
storyboard_tool/app_state.py
storyboard_tool/runtime_state.py
storyboard_tool/live_bridge.py
storyboard_tool/desktop.py
storyboard_tool/preview_analysis_cache.py

frontend/src/api/system.ts
frontend/src/state/ProjectContext.tsx
frontend/src/state/LiveBridgeContext.tsx
frontend/src/App.tsx

tests/test_bootstrap.py
tests/test_preview_analysis_cache.py
tests/test_ui_ready.py
new startup/preview-analysis lifecycle tests if needed
```

Do not modify:

```text
photoshop_uxp_plugin/*
Scene 2D UUID model
Scene 2D migration
Scene 3D storage
shot PSD structure
SB bg behavior
shot preview export behavior
reference segment semantics
```

---

# Part 1 — Show the splash before all Python/venv work

Current launcher broadly does:

```text
check/create venv
activate venv
import dependencies
possibly pip install
generate token
show splash
launch app
```

Change it to:

```text
cd to repository root
generate per-launch token
start splash immediately
then validate/create venv
then validate/install dependencies
then launch Storyboarder
```

The splash must appear before:

```text
py -m venv
python --version
activate.bat
python -c "import ..."
pip install
python main.py
```

The user should receive visible feedback even on:

```text
first launch
broken virtual environment
missing dependencies
slow dependency import
dependency installation
```

---

# Part 2 — Launcher status communication

Use the existing per-launch token.

Add a token-specific status marker:

```text
%TEMP%\storyboarder-launch-<token>.status
```

The launcher may update it with simple status strings:

```text
Preparing Python environment…
Checking dependencies…
Installing dependencies…
Starting Storyboarder…
```

Requirements:

```text
- status content is plain text only
- no arbitrary path is accepted from the frontend
- status writes are best-effort
- launch must not block if status write fails
- stale token files must not affect a different launch
```

The splash should read this status file at its existing low polling interval.

If there is no status file, retain elapsed-time fallback messages.

Do not display fake percentages.

---

# Part 3 — Failure handling for launcher setup

If venv creation, activation, dependency installation, or Python launch fails:

```text
- write a clear failure message to the token status file
- keep the splash visible briefly or change it into an error state
- provide a Close button
- keep Escape functional
- ensure the batch process returns a non-zero exit code
```

Suggested splash error state:

```text
Storyboarder could not start

Failed to install Python dependencies.
Check logs/desktop.log for details.

[Close]
```

Do not leave an indeterminate progress bar running for 120 seconds after a known fatal error.

A token-specific failure marker may be used:

```text
%TEMP%\storyboarder-launch-<token>.failed
```

Clean it after the splash exits where practical.

---

# Part 4 — Main-window fallback for splash dismissal

The ready marker remains the primary success signal.

Add a safe secondary signal so the TopMost splash does not cover an already usable Storyboarder window for up to 120 seconds if `/api/app/ui-ready` fails.

Preferred options, in order:

```text
Option A:
desktop.py writes the same token ready marker from a pywebview loaded/shown callback
after the main window is genuinely visible.

Option B:
the splash detects a visible Storyboarder top-level window with a plausible size.

Option C:
a separate desktop-visible marker is written by the Python process.
```

Do not close the splash merely when FastAPI starts.

Acceptable fallback timing:

```text
React UI-ready marker = primary
visible pywebview main window after load = fallback
120-second timeout = last resort
```

Avoid broad process enumeration or killing unrelated processes.

---

# Part 5 — Preview-analysis frontend API

Add typed frontend API methods for:

```text
POST /api/project/preview-analysis/refresh
GET  /api/project/preview-analysis/status
```

The refresh result should include:

```json
{
  "ok": true,
  "status": "started",
  "task_id": "...",
  "project_path": "...",
  "revision": 12
}
```

Possible statuses:

```text
no_project
started
already_running
complete
failed
stale_project
```

Do not expose arbitrary filesystem paths as writable inputs.

---

# Part 6 — Per-project analysis jobs

Replace the single global preview-analysis lock with project-aware job state.

Problem with one global lock:

```text
Project A analysis is running
→ user opens Project B
→ Project B request receives already_running
→ Project B may never retry
```

Manage jobs by stable project identity, preferably normalized project root.

Each job should track:

```text
task_id
project_root
state
started_at
completed_at
decoded_count
error
revision
```

Requirements:

```text
- only one active analysis job per project
- different projects may not corrupt each other
- a worker captures the intended project/root at task creation
- switching active project does not cause it to update the wrong project
- stale worker completion must not announce a change for the wrong active project
- failed workers release their running state
```

Concurrency may remain conservative; correctness is more important than maximizing parallelism.

---

# Part 7 — Automatic analysis trigger

After initial UI paint and `reportUiReady()`, schedule preview analysis outside the critical rendering path.

Suggested order:

```text
bootstrap completes
→ Welcome or Board renders
→ two requestAnimationFrame ticks
→ report UI ready
→ requestIdleCallback / delayed callback
→ request preview analysis
```

Do not delay splash closure waiting for image analysis.

Do not block project opening on preview decoding.

Only trigger when a project is open.

When switching projects:

```text
schedule analysis for the new project
do not reuse an old project task result
```

If refresh returns `already_running`, subscribe to or poll the existing task instead of abandoning the lifecycle.

---

# Part 8 — Analysis completion notification

When the worker completes and saves cache:

```text
increment a preview-analysis revision
publish a lightweight change event
```

Suggested bridge payload:

```json
{
  "preview_analysis": {
    "revision": 8,
    "project_path": "D:/.../Storyboard_Project",
    "state": "complete",
    "decoded_count": 14,
    "task_id": "..."
  }
}
```

The frontend should react only when:

```text
event project_path matches the currently open project
revision is newer than the last handled revision
state is complete
```

Then perform one controlled project refresh:

```text
GET /api/project
```

This refresh should update:

```text
has_artwork_preview
preview_has_transparency
```

Do not reset:

```text
selected shot
workspace mode
timeline scroll
Scene 2D selection
Scene 3D selection
unsaved shot drafts
```

Because replacing project data can conflict with local unsaved drafts, use the existing safe merge/refresh mechanism.

Do not silently discard unsaved edits.

If the existing `refreshProjectFromBridge()` discards undo/redo or affects selection unnecessarily, add a narrower preview-analysis refresh path that merges only server-computed preview fields and disk mtimes.

---

# Part 9 — Correct provisional preview state

On cache miss, the current provisional values are:

```text
has_artwork_preview = true
preview_has_transparency = false
```

This can temporarily misclassify a blank preview as artwork.

Add an explicit analysis state to shot payloads:

```text
preview_analysis_state:
  missing
  provisional
  cached
```

Suggested behavior:

```text
no preview file:
  has_artwork_preview = false
  preview_analysis_state = missing

preview file, cache hit:
  real cached values
  preview_analysis_state = cached

preview file, cache miss:
  provisional values
  preview_analysis_state = provisional
```

Frontend should avoid presenting a provisional result as certain.

For example, do not show a definitive “artwork exists” warning solely from a provisional result.

Keep backward-compatible existing boolean fields.

---

# Part 10 — Cache lifecycle

Keep cache identity based on:

```text
normalized path
mtime_ns
file size
```

Add or verify:

```text
- stale cache entries are ignored
- corrupt cache returns empty state safely
- atomic writes use uniquely named temporary files
- concurrent writers cannot replace each other with partial data
- orphaned entries may be pruned periodically
```

Current fixed `.tmp` naming can collide if two writes occur concurrently.

Use a unique sibling temporary file and `os.replace`.

Do not make cache write failure break project use.

---

# Part 11 — Analysis after preview changes

The lifecycle must also work after Photoshop or another process updates a preview.

When project/plugin revision indicates preview files changed:

```text
- cache lookup naturally misses due to mtime/size
- schedule analysis for uncached changed previews
- notify frontend on completion
- refresh computed preview fields once
```

Avoid creating an infinite loop:

```text
project refresh
→ trigger analysis
→ zero files decoded
→ revision change
→ project refresh
→ trigger analysis ...
```

Only emit a completion revision when:

```text
a job state meaningfully changed
or at least one cache entry changed
```

For zero-work analysis, mark the task complete but do not repeatedly cause UI reloads.

---

# Part 12 — Startup timing instrumentation

Preserve existing timing instrumentation.

Add useful stages where missing:

```text
launcher splash started
venv check started/completed
dependency check started/completed
Python app entered
server ready
bootstrap requested
session loaded
project opened
project payload built
frontend UI-ready received
preview analysis scheduled
preview analysis completed
```

Do not log on every render or every polling tick.

Include elapsed milliseconds where practical.

Do not log full sensitive filesystem contents unnecessarily.

---

# Part 13 — Tests

## Launcher/splash tests

Where fully automated WinForms testing is impractical, test pure/token/file logic and document manual validation.

Required automated checks where feasible:

```text
1. Token-specific status/ready/failure paths are derived safely.
2. Invalid token cannot escape TEMP directory.
3. Different tokens do not interfere.
4. Fatal launcher state does not wait for normal timeout.
5. Ready marker still closes the matching splash.
```

## Preview analysis tests

Add tests for:

```text
1. Initial bootstrap does not decode preview images synchronously.
2. Frontend/API refresh starts a background job.
3. Cache miss becomes cached after worker completion.
4. Completion increments revision.
5. Status endpoint reports running and complete states.
6. Same-project duplicate request returns existing task information.
7. Project A worker cannot announce Project B revision.
8. Opening Project B while Project A runs still allows B analysis.
9. Worker failure releases job state.
10. Cache write failure does not crash the worker lifecycle.
11. Corrupt cache is handled safely.
12. Changed mtime invalidates cached values.
13. Zero-work job does not trigger an infinite revision loop.
14. Temporary cache file names are collision-safe.
```

## Frontend behavior

Add focused tests if the project already has frontend test infrastructure.

Otherwise verify through build plus manual smoke tests.

---

# Manual smoke test

Run the actual user-facing launcher:

```powershell
.\launch_storyboarder.bat
```

Do not validate only with:

```powershell
python main.py
```

Manual scenarios:

```text
1. Normal warm launch:
   splash appears immediately
   main app appears
   splash closes after UI paint

2. Missing/broken venv simulation:
   splash appears before venv work

3. Missing dependency simulation:
   splash shows environment/dependency status

4. Known startup failure:
   splash enters visible error state
   Escape and Close work

5. UI-ready request failure simulation:
   visible-main-window fallback closes splash

6. Project with many previews:
   Board renders before preview analysis finishes
   background analysis completes
   artwork/transparency states update automatically

7. Switch projects during analysis:
   no cross-project UI refresh
   both projects remain analysable

8. No project:
   Welcome UI appears
   splash closes
   no preview-analysis request loops
```

---

# Commands

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests/test_bootstrap.py -q
.venv\Scripts\python.exe -m pytest tests/test_preview_analysis_cache.py -q
.venv\Scripts\python.exe -m pytest tests/test_ui_ready.py -q
.venv\Scripts\python.exe -m pytest tests/ -q

cd frontend
npm.cmd run build
```

Do not claim WinForms behavior is verified unless the launcher was manually run.

---

# Commit boundary

Create one focused commit.

Suggested commit message:

```text
fix: complete startup and preview analysis lifecycle
```

Do not include Photoshop plugin or Scene 2D migration changes.

---

# Output required

Report:

```text
Changed files
New launcher execution order
Splash status and failure behavior
Splash fallback close behavior
Preview-analysis API and job model
How automatic analysis is scheduled
Completion revision/event design
How frontend project state is refreshed safely
Cache atomic-write changes
Tests run
Frontend build result
Manual launcher scenarios tested
Known limitations
Commit SHA
```
