# Drawing Desk design and engineering QA

final result: passed

## Target and evidence

- Selected visual truth: C:/Users/JieYin/.codex/visualizations/2026/07/28/019fa905-807b-7f40-b1de-ab9ceaa5f35c/storyboard-design-20260922/02-drawing-desk.png
- Local implementation: http://127.0.0.1:4173/
- Exact reference and browser capture: 1487 × 1058 pixels, CSS viewport 1487 × 1058, deviceScaleFactor 1.
- State: Drawing tab, main route, shot 06, Generation inspector, no accepted image or user strokes, 100% workspace zoom.
- Final browser screenshot: .qa/initial-v3.png.
- Full-view comparison: .qa/comparison-v3.jpg; source and actual are in the SAME side-by-side image, each uniformly downsampled to 1115 × 794 for comparison.
- Focused native-density inspector comparison: .qa/comparison-inspector-v3.jpg; source and actual crops x1102/y55/w385/h800, no scale change. Inspected together for text, controls, references and candidate cards.
- Additional rendered evidence: .qa/desktop1366-v3.png at 1366 × 768; .qa/narrow-v3.png at CSS900 × 900, full-page capture; .qa/map-v3.png at1487 ×1058.
- Source and implementation were opened and compared visually, not judged from code alone.

## Findings and comparison history

### Pass 1 — blocked

Evidence: .qa/initial.png and source, compared together in one image input.

- P2: UI labels and graph thumbnails were too small relative to the selected design; the graph left excessive unused vertical space.
- P2: The central full-frame fit left large dark bands above and below the art, materially weakening the drawing-first layout.
- Fixes: increased explicit UI text sizes, enlarged shared nodes, compressed graph columns, reduced fit padding and expanded bottom route cards. Drawing now opens a centered, scrollable close view; playback still fits the full frame. PNG export remains complete 1672 × 941.

### Pass 2 — blocked

Evidence: .qa/initial-v2.png and source combined; .qa/desktop1366-v2.png and .qa/narrow-v2.png were also inspected.

- P2: Resizing the window preserved a stale graph viewport, clipping bottom and right branches.
- Fix: ResizeObserver refits the graph after viewport changes. No route order is derived from visual position.
- P3: Native fonts and functional input controls differ subtly from the generated mock. Kept the existing Studio palette and Windows font stack rather than reproducing raster text.

### Pass 3 — passed

Evidence: .qa/comparison-v3.jpg, .qa/comparison-inspector-v3.jpg, .qa/desktop1366-v3.png and .qa/narrow-v3.png.

No actionable P0/P1/P2 visual findings remain. All branches are visible after resizing, central art fills the drawing workspace without image distortion, and the right inspector remains scrollable on short/narrow viewports. At 900px the inspector moves below the drawing area; no horizontal document overflow was observed.

## Required fidelity surfaces

| Surface | Result |
| --- | --- |
| Fonts and typography | Segoe UI / Microsoft YaHei stack, white primary and muted secondary labels. Increased small labels after pass1. Focused native-size crop confirms readable prompts, tabs and adoption buttons. Raster mock typography is not reproduced pixel-for-pixel; remaining optical differences are P3. |
| Spacing and layout rhythm | Preserved approximately24% graph /50% drawing /26% inspector and full-width bottom route. Compact chrome, thin borders and4px corners retain source hierarchy. Canvas is centered and scrollable in drawing mode; full frame is visible during playback. Responsive graph refit fixes cropped branches. |
| Colors and tokens | Existing Studio dark navy panels, #26303d borders and #d6a84f gold selected states. The source's bright gold is slightly softer here by deliberate reuse of production tokens. Disconnected ComfyUI is neutral/gold, never falsely green/connected. |
| Image quality | Three original generated pencil assets with old-platform, backpack protagonist and dialogue subjects. Correct aspect ratio, no stretched imports, clear thumbnails. Selected UI is built from components, not a flattened screenshot. Graph edges and actual freehand drawing are functional renderers; icons are Phosphor. Reused sample shots are labelled/demo content, not a finished narrative. |
| Copy and content | Chinese workflow labels preserved. Shot06 is consistently station dialogue. ComfyUI explicitly says not connected. Candidates say sample; prompts and layer edits are session-only. Added route selector, export and branch action make source controls executable. |

## Independent engineering review

Boundary: new prototype only. No production API calls, project schema migrations, persisted drawings or changes to the existing Fabric editor.

Single authorities: story graph owns nodes/edges/routes; selected shot and route IDs drive all views; drawings and candidate settings are keyed by shot ID. Graph positions cannot reorder a route.

Reviewed forward/reverse/repeated transitions: new branches from shared and merged nodes, undo/redo, shot changes, modal open/close, playback start/pause/finish, image imports and adoption, asynchronous export.

Task-adjacent issues fixed and regression-tested:

- Branching at a merge previously chose the first route. Explicit current-route prefix is now preserved.
- Pausing on the final frame previously jumped to the beginning. Restart applies only when starting playback.
- Opening an import picker during playback could change the target shot. Target is now fixed before opening and playback pauses.
- Modal focus is contained and restored; opening pauses playback.
- Route auto-scroll is horizontal only, preventing narrow-page jumps.
- Resize refits story graph.
- Vite now ignores .qa outputs after a Windows EBUSY watcher crash during downloaded-image writes.
- Empty favicon request removed; final browser console and HTTP errors are zero.

The canvas keeps in-progress gestures separate and cancels them on shot/tool changes. Erasing affects ink only. Export waits for image loading and rejects generation changes during asynchronous capture. Original sketches remain available beneath adopted images. Failed imports/loading show feedback rather than silently overwriting the source.

## Tests actually run by Verifier

Working directory: D:/MyProjects/Storyboarder/prototypes/drawing-desk

- node --test tests/story-model.test.mjs tests/sites-worker.test.mjs — 13 passed, exit0. Evidence: .qa/unit-tests.log.
- node tests/browser-smoke.mjs — 12 passed, exit0. Evidence: .qa/browser-smoke-results.json and .qa/browser-smoke.log.
- npm.cmd run build — exit0. Evidence: .qa/build.log.
- git diff --check — exit0 from the repository root; existing CRLF warnings only. Untracked prototype files were inspected directly.

Browser coverage: initial UI; actual pixel-changing pencil strokes, undo and redo; per-shot preservation; alternative route and branch-at-merge prefix; graph keyboard/mouse selection and dragging without route mutation; per-shot prompts; playback progression, pause and shot selection; final-frame pause regression; import-picker target stability; adoption and layer visibility; real full-resolution PNG download; modal Tab/Escape and focus restoration. Zero page, console or HTTP errors.

Browser automation used a separately launched headless Edge instance with a fresh Playwright context, after explicit user approval. It did not use the user's browser profile or history.

## Not tested / limitations

- This is an independent prototype, not the production application. No actual ComfyUI job, model installation, project autosave, reopening saved projects, or production export integration has been tested or implemented.
- Reload resets the session. Export important pictures first.
- Tablet/pen pressure, physical hardware, touch ergonomics and sub900px devices were not acceptance-tested.
- Short-height minimap labels shrink to keep all branches in view; the full Map tab supports detailed browsing. A dedicated compact navigator can be refined after layout approval.
- Browser smoke script currently uses the bundled local Playwright path and installed Edge executable; other hosts must adapt those paths.
- Sample art illustrates three scenes reused over the demo graph; it is not a ten-shot production storyboard.

## Implementation checklist

- [x] Selected option2 identity recorded in AGENTS.md and project design proposal.
- [x] Original assets placed; no rasterized UI or fake generation status.
- [x] Main interactions implemented and independently verified.
- [x] Source/actual compared together; responsive recapture performed after fixes.
- [x] Durable QA evidence recorded.
- [x] No commit, push or public deployment performed.

## Follow-up polish

P3: optional denser minimap for short desktop windows; more distinct sample frames; finer optical matching of the native range slider and compact labels. These do not block trying the selected drawing-first workflow.

