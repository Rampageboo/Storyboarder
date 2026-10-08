# Comic storyboard workflow

Storyboarder adds a Comic workspace for chapters, single pages, double-page spreads, and long scroll sections. Artwork, references, authored continuity, workflow status, generation requests, and accepted results remain attached to existing boards. A comic panel is a placement of one board, with editable position, size, crop behavior, border, and explicit reading order.

## Contract and ownership

- Canonical layout: `settings.json` → `comic_document`, included in existing project storage, save, recovery, Save As, and Layout 1/2 document serialization. The project response exposes a normalized view as `comic_document`.
- Structure: document → chapters; ordered pages link to a chapter; ordered panels link to a board ID.
- Old projects default to an empty comic without changing their boards or routes.
- One board has at most one placement, so its generation context is unambiguous. Duplicate a board to author another variant. Removing a placement/page preserves its underlying boards.
- Deleting a board hides its placements in the normalized layout; restoring the board can recover them until the next explicit layout update removes them.
- Page dimensions and panel rectangles are stored in pixels. Reading direction does not implicitly reorder authored panels. Spreads include a centered binding guide; panels can deliberately cross it. The guide is absent from exports.

## UI and persistence

Layout mode supports blank chapters/pages, direct rectangle drawing (R), selecting/moving placements (V), eight resize handles, optional 24 px grid snapping, fit-relative zoom, horizontal/vertical splitting, board/panel duplication, entering precise geometry, contain/cover fitting, panel borders, page ordering, panel reading order, and layout undo/redo. Page, Panel, Lettering, and AI inspector tabs keep geometry and prompt editing separate. No layout templates are included, following the Owner's clarified direction.

Splitting preserves the original board in the first reading-order half and creates a blank board in the second. A vertical RTL split reads the right half first. The page gutter controls the split gap, and too-small splits are disabled. Polygon splits use half-plane clipping and retain their real boundaries; arbitrary knife splits order pieces top-to-bottom. Locking prevents moving, resizing, cutting or unplacing the locked placement. Duplication uses the existing authored-board/artwork duplication path. Layout undo preserves all created boards; it restores placements rather than deleting project artwork. New panel, split and duplicate operations use the existing project transition guard and flush their layout before releasing it, preventing cross-project changes during asynchronous board creation.

Read mode displays the chapter in page order without grid, handles, binding guide or labels. Artwork reuses the native drawing canvas and generation controls at panel dimensions. Numeric fields commit on blur/Enter and cancel on Escape, so intermediate typed digits are not saved as geometry.

Layout edits have a 600 ms debounce, paused during canvas gestures. Editing remains available during an in-flight layout save; a newer draft receives the acknowledged revision and is saved separately, retaining its dirty state until acknowledged. A registered draft flusher joins the existing project-save and transition mechanism. Save layout, Ctrl+S, switching workspaces, and changing projects flush layouts and board drafts. Revision and project-path checks reject conflicting or cross-project updates. Failed saves leave the draft in place, stop automatic retries, and allow explicit retry/correction or discarding the draft. Invalid geometry cannot silently shrink/crop stored panel rectangles.

Layout updates use existing serialized metadata transactions, including legacy rollback and Layout 2 work-state recovery. Per-panel artwork sizes also flow through accepted-generation storage, thumbnails, native drawing, new PSD canvases, reference backgrounds, and Photoshop context. Already-existing artwork/PSDs are not automatically rewritten when a panel is resized.

## Prompts and result freshness

Comic style → chapter prompt → page prompt → automatic panel details or manual panel prompt → extra instructions. Negative prompts and requested variants remain per board. Requests also retain existing character/scene bibles, reference snapshots, and continuity. Preview compiled prompt creates no generation request and reads scene metadata without triggering migrations.

Comic snapshots include chapter/page/panel context and use panel width/height. Requests instruct providers to render one panel; dialogue is planning context and lettering stays separate. Layout/prompt/context edits mark active results stale. Result reconciliation and acceptance compare the captured context and generation input revision to current inputs, so a late result cannot clear the stale flag. Approval and freshness remain separate.

## Exports and limits

- Export PNG writes the full selected page/spread/scroll section to the existing exports directory.
- Chapter ZIP contains ordered PNGs and `comic-prompts.json`, scoped to the selected chapter and its placed boards.
- Exports composite background, accepted generation, and transparent artwork in order. Each layer is fit independently to the panel; UI numbers, binding guides, and selection outlines are excluded.
- Writes are staged and atomically replace the previous export only after success. Open export recomputes a project-local export path and opens the already-written file.
- Convex polygon boundaries and editable bubble/caption/plain-text lettering are supported. Print bleed/CMYK and automatic story-to-panel breakdown remain outside this version.
- Page width ≤ 8,192 px, height ≤ 32,000 px, area ≤ 64 million pixels. Longer scrolls use multiple sections. Existing generation providers may impose lower limits.

## Verification

Tests are owned by the Verifier agent in this task. The focused suite in `tests/test_comic.py` covers storage layouts, input/geometry validation, revision/project conflicts, prompt inheritance, actual PNG pixels, mixed image sizes, stale results, PSD/reference dimensions, read-only previews, scoped chapter archives, and failed writes. Browser checks use an isolated generated project, never a user production document.

The geometry checks in `scripts/qa_comic_geometry.cjs` cover all resize directions, page bounds, minimum panel size, odd split sizes, spacing, RTL order and snapping.

The visual design retains the existing charcoal theme, amber selection, compact system UI typography, thin borders and white paper. The initial image mockup informed the three-pane structure, Page/Panel/AI tabs, page thumbnails, selected handles and binding guide. The Owner then removed the template direction; the implemented tool strip and blank-canvas workflow supersede the mockup's template gallery. UI text, diagrams and controls are native React/CSS/SVG; no mockup pixels are app assets.

The final completion message records the completed test/build/UI checks and any remaining host-specific gaps. Production frontend output is rebuilt into `storyboard_tool/web/dist`, matching the existing desktop launch path.


### Recorded results

- Comic backend: `.venv\Scripts\python.exe -m pytest tests/test_comic.py -q` — 50 passed in 21.00 s.
- Direct geometry: `node.exe scripts/qa_comic_geometry.cjs` — 25 checks passed. Covers eight resize directions, fixed opposite edges, boundaries, minimum size, splitting and snapping.
- Production build: `npm.cmd run build` — exit 0. The existing large-chunk warning remains. Scoped lint passes for the comic workspace, preview, layout helpers and persistence hook; existing unrelated App lint errors were not refactored.
- Broad backend regression: 1161 passed, 2 skipped, 3 failed, 31 subtests passed. The two smoke subtests expect absent favicon.svg/icons.svg, but these assets predate this change. The Blender broker authorization case failed in the full run and passed when rerun alone (1 passed in 4.11 s). No unrelated files or test expectations were changed.
- Browser checks used isolated generated boards: actual native drawing saved at 552×358, reopened with two editable layers, and retained its PNG hash. Chapters/pages/prompts survive Home close and Recent reopen. A deliberately stale revision caused 409, preserved the draft and blocked workspace switching until discard/reload.
- Direct tools: actual mouse rectangle created a 300×200 panel at (100,100); SE resize reached 350×240; NW resize preserved opposite edges and reached (70,80,380,260); grid move snapped to (96,96). H/V split gaps were 32 px, Undo/Redo restored layouts, original board/prompt survived, and duplication preserved manual/negative inputs. Zoom changed display size, not geometry. Read hid handles, grid and labels.
- Host-specific gaps: real Photoshop UI and external model inference were not exercised. Dirty native-drawing Cancel displayed its confirmation, but browser automation could not reliably observe the final confirmation state; saved pixels remained unchanged. Browser UI verification used Chrome after the in-app browser's dialog observation blocked further interaction. The desktop pywebview host itself was not acceptance-tested.

## Manual tools expansion

The Owner prioritized animation and comic editing while pausing new AI work. Existing AI capabilities remain accessible separately; this change adds no generation pipeline or layout templates.

- Panel boundaries optionally store 3–8 normalized convex vertices, preserving their shape on resize. Intersecting/degenerate/out-of-range polygons are rejected before persistence. Knife (K) clips against two offset half-planes to produce a real angled gutter. Vertex handles reshape the boundary directly. Original images remain unchanged.
- Artwork scale and normalized X/Y offsets are separate from placement position/size. The browser transforms each original image layer around the panel center; PNG export uses bounded affine resampling and the same polygon clipping rather than creating an unbounded zoomed bitmap. Full-resolution image previews avoid thumbnail crops.
- Shift/Ctrl selection, group dragging, edge/center alignment, equal-gap distribution and selection locking use one layout history step per operation. Locked panels are excluded from movement/alignment and prevent pacing-space shifts that would move them.
- Page lettering is independent of board artwork: bubble, caption or free text; editable position/size, CJK/newline wrapping, horizontal or right-to-left vertical columns, ink/fill, outline and tail. Both SVG preview and PNG exports include it. Overflow is signaled instead of silently shrinking font size. Font rendering uses Microsoft YaHei on Windows; hosts without a CJK font require one for readable CJK export.
- Page mode, paper color, safe margin, chapter assignment and ordering are editable. Scroll pacing shifts later panels/lettering and extends or shrinks the section while preventing overlap and canvas overflow. Read has 360/640/960 px width choices; guides remain absent from exported pixels.
- Chapter PDF preserves each page/spread/scroll section aspect ratio as one PDF page, scaling very long pages to stay within 14,400 points. It embeds rendered raster pages; editable source remains the Storyboarder document. CBZ contains only ordered PNGs for comic readers. ZIP continues to include the chapter manifest. All formats use the existing staged atomic write path.

Animation Play now uses a monotonic frame timeline: FPS, precise playhead/timecode, single-frame step, scrub, loop, speed, safe-area overlay, dialogue and action/camera review. Timing uses positive half-up frame rounding with at least one frame per board. Editing frame counts updates the canonical duration_seconds; shared-route timing remains shared. Finite positive durations, including one frame at 24 or 60 FPS, survive shot updates and project reloads without a 0.1-second clamp. Timing JSON and reference-segment/capture offsets also retain these short durations. Preview navigation does not rewrite board metadata every playback frame.

Route exports select canonical route IDs in authored order, preserve global board labels and use a hashed route-specific filename suffix. Download and Open recompute the same route scope, reject mixing route and board-range scope, and never reinterpret a route as the globally sorted range. Both encoder paths use the same rounded durations; a short shot is no longer forced to 0.5 seconds. Routes can be reordered by drag or Earlier/Later while retaining DAG validation.

Design references inspected publicly: [OpenKoma](https://github.com/Reuben-Sun/OpenKoma) for true panel geometry and non-destructive cropping; [Manga Editor Desu](https://github.com/new-sankaku/manga-editor-desu) for knife/vertex/lettering workflows. These are interaction references; no third-party project source or templates were copied into this implementation.

The recorded results above describe the earlier baseline. Current expansion verification is recorded separately in the Verifier's external QA evidence:

- Related backend suites: 277 passed and 26 subtests passed. Both ffmpeg and OpenCV outputs were decoded to verify one-frame holds and exact board transitions at 24/60 FPS. The actual shot-update/save/reopen path preserves one-frame durations. Route order, board-range scope and matching export download/Open paths were verified.
- Geometry, alignment, frame timeline, duration contracts and SVG/PNG CJK wrap parity: 68 direct checks passed.
- Latest production build succeeded (`index-B2cvG271.js`). Scoped lint passed for the changed comic, story/timeline, duration and capture helpers. Broader lint of the reference-assignment component retains four existing render-time ref assignments verified against HEAD; they were not changed by this duration repair.
- Real Chrome mouse/keyboard checks passed for vertices, diagonal knife, independent crop, dialogue drag/resize/vertical text, locking, multi-selection/group move/align, Undo/Redo, scroll spacing and locked downstream content, reader widths/spread display, and PNG/PDF/CBZ controls. Edits during a deliberately delayed layout PUT were retained and saved. New pages reset their scroll position and accept direct drawing immediately after a long-scroll section.
- Animatic checks passed for frame stepping, focused-button shortcuts, single-frame input/save/reload, route reorder, scrub, loop, speed, workspace-switch stop and Edit board selecting the actual playhead board. The inspector explicitly identifies the selected board being edited while preview navigation remains independent.
- Browser verification used an isolated generated project with the existing installed Chrome and bundled Playwright after the in-app browser control provider timed out. The pywebview desktop host, real Photoshop UI and external AI inference were not exercised by this manual-tool QA.
