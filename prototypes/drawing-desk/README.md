# Drawing Desk — option 2 interactive prototype

Independent React prototype of the selected drawing-centric storyboard design. It does not change the production frontend or project document format.

## Run locally

`npm.cmd install` then `npm.cmd run dev -- --host 127.0.0.1 --port 4173 --strictPort`.

Open http://127.0.0.1:4173/. No account, server API or model is required.

## Included

- Draggable story graph, three routes with shared start and merged ending.
- Branch creation from a selected shot. New branches end independently.
- Per-shot pencil/eraser strokes, undo/redo, zoom, layered candidate adoption and PNG export.
- Imported PNG/JPEG/WebP candidates and clearly labelled generated sample art.
- Route-based playback; graph coordinates never define playback order.

All edits are in memory for this session. Reload resets the demo. Export important images before refreshing. ComfyUI is NOT connected; prompt and adherence fields do not send jobs.

Drawing initially fills the workspace with a centered, scrollable close view. Scroll or zoom out to reach the rest of the canvas. Playback fits the complete frame; PNG exports always contain the complete 1672 × 941 drawing without stretching imported images.

## Engineering boundaries

- `story-model.js`: immutable graph and route operations, stable shot IDs.
- `DrawingCanvas.jsx`: input and image composition only; parent owns stroke history.
- `App.jsx`: session state and workflow UI, no production API dependency.
- `tests/story-model.test.mjs`: model regression tests.

## Asset provenance

Three original pencil storyboard images generated with the built-in image generation tool on 2026-09-22 for this prototype. The dialogue image uses option 2 as composition reference. No source UI is flattened into the implementation.

## Verification

See `design-qa.md` for actual checks and remaining gaps. Build output is not visual acceptance.
