# Prototype Instructions

Run the local server yourself and open the preview in the browser available to this environment. Do not give the user server-start instructions when you can run it.

Before making substantial visual changes, use the Product Design plugin's `get-context` skill when the visual source is unclear or no longer matches the current goal. When the user gives durable prototype-specific design feedback, preferences, or decisions, record them in `AGENTS.md`.

When implementing from a selected generated mock, treat that image as the source of truth for layout, component anatomy, density, spacing, color, typography, visible content, and hierarchy.

Build app UI in `src/`. Keep `.openai/hosting.json`, `worker/index.js`, `scripts/prepare-sites-build.mjs`, and `tests/sites-worker.test.mjs` intact so the same local prototype can be handed to Sites. Before a Sites handoff, run `npm run build` and `npm run test:sites`; the build must leave `dist/client/index.html`, `dist/server/index.js`, and `dist/.openai/hosting.json`.

# Selected product direction

- User selected displayed option 2, Drawing Desk, on 2026-09-22.
- Source image: C:/Users/JieYin/.codex/visualizations/2026/07/28/019fa905-807b-7f40-b1de-ab9ceaa5f35c/storyboard-design-20260922/02-drawing-desk.png.
- Keep the dark Studio palette, gold active route, left story graph, central drawing, right generation/layers/references, and bottom current route.
- This is an independent session-only prototype. No production project writes, migration, persistence, or real ComfyUI calls. Label examples and disconnected generation honestly.
- Story edges are not generation dependencies. Route IDs and ordered shot IDs, never canvas position, determine playback. Branch at a merge preserves the chosen route prefix.
- Generated original artwork lives in public/assets. Functional drawing uses a canvas, graph rendering uses React Flow, and icons use Phosphor.
