# Storyboard Bridge UXP Plugin

Photoshop panel for drawing storyboards without switching back to Storyboard Tool after every shot.

## Install (development)

1. Install **Adobe UXP Developer Tool**
2. **Add Plugin** → select this `photoshop_uxp_plugin` folder
3. Click **Load** or **Watch**
4. Restart Photoshop
5. Open **Plugins → Storyboard Bridge**

## Protocol v2 and Layout 2

Plugin 0.7.0 negotiates protocol v2 with `explicit_asset_paths_v2`. When a
Layout 2 project is linked, every asset is opened or written through the exact
role path supplied by Storyboarder; the plugin does not derive a shot folder or
write project metadata offline. Preview exports use a short-lived backend write
intent and transaction inbox. Native Photoshop saves remain available for an
already-open canonical PSD; after Ctrl+S, the plugin reconnects the save to its
work key and source role so Storyboarder can validate the canonical file.

## Recommended workflow (stay in Photoshop)

1. Open Storyboard Tool once and open your project (for the shot list and canvas color).
2. In Photoshop, open **Storyboard Bridge**.
3. Click **Choose project folder** → your `Storyboard_Project` folder (the one with `project.json`).
4. Pick a shot from the dropdown, or click **Open / create canvas**.
5. Draw on the 16:9 canvas.
6. Click **Save & next shot**:
   - Exports `shot_XXX_preview.png` for Storyboard Tool
   - Saves the open document with Photoshop's native save (use **Ctrl+S** for the PSD on disk)
   - Reports the export to the Storyboard Tool backend, which updates `shots.json` and regenerates `shots.csv`
   - Closes the current document and opens the next shot in the **same Photoshop window**
   - Creates a new shot automatically when you reach the end (toggle **Auto-add shot at end**)

Storyboard Tool polls for file changes in the background, so previews and new shots appear when you switch back — no manual sync required.

## Buttons

| Button | Action |
|--------|--------|
| **Choose project folder** | Load `project.json` and shot list |
| **Open / create canvas** | Open existing PSD or create a new canvas at the project size |
| **Save** | Export transparent drawing preview to Storyboard Tool (`shot_XXX_preview.png`). **Does not overwrite the PSD** — press **Ctrl+S** in Photoshop to save layers. |
| **Save & next shot** | Export preview, native-save the open document (Ctrl+S equivalent), then move to the next shot |

## Canvas color

Storyboard Tool stores `canvas_background_color` in `settings.json`. The plugin reads `canvas_color.txt` / `storyboard_bridge.json` and can fill the **Background** layer to match.

## Save = export the drawing; you keep the PSD with Ctrl+S

The plugin **never saves or overwrites the `.psd`** — UXP `saveAs` overwrites often produced *"Could not open … because of a program error"* files. Instead:

- **Save** exports only the drawing preview (`shot_XXX_preview.png`) for Storyboard Tool. You save the PSD yourself with **Ctrl+S** in Photoshop.
- **Save & next** exports the preview and moves to the next shot, but **leaves the current shot's tab open** (no auto-save, no close) so unsaved strokes are never discarded — switch back to it and **Ctrl+S** when ready.
- The only `.psd` the plugin ever writes is the **first-time file for a brand-new canvas** (so the shot has a linked file); it never overwrites an existing one.

Saves always target the shot shown in the **active Photoshop tab** (from the tab's filename, not the dropdown — boards reorder and the dropdown can drift). The **Now editing** banner shows exactly which shot a save goes to; if the active tab isn't a recognized shot, saving is refused rather than guessing.

> Note: switching shots with **Open canvas** / the dropdown still closes the previous tab — Ctrl+S before switching if it has unsaved strokes.

## PSD recovery (broken files)

To recover a PSD Photoshop refuses to open:
- **Rebuild from layers** — when opening a shot whose PSD Photoshop refuses to open, the panel asks Storyboard Tool to rebuild it. Storyboard Tool reads the file with `psd_tools` (which tolerates files Photoshop rejects) and assembles a **brand-new, clean PSD** (so Photoshop can open it) that keeps each layer's pixels, **blend mode, opacity, and visibility**, plus layer order and names. (Text/smart-object editability and masks are not retained — those rasterise to pixels.)  The broken original is backed up under `_history/` first, then the rebuilt PSD is re-opened automatically.
- **Flatten fallback** — if the layer-preserving rebuild *still* won't open, the panel automatically retries with a flattened rebuild: every layer is baked to its rendered appearance with normal blend/opacity — the most robust path.
- **Report PS error (manual)** — if Photoshop shows *"Could not open … because of a program error"*, select the shot and click **Recover broken PSD**. This runs the same rebuild (layers-preserving first, flatten if needed) and re-opens the shot. Recovery needs Storyboard Tool running with the project open (`POST /api/shots/{id}/recover-source`, optional `?preserve_layers=false` to force flatten).
- **Last resort** — if even `psd_tools` can't read the file, the panel keeps the broken copy in `_history/` and creates a fresh canvas so you can keep working.

## No duplicate tabs (open from Storyboard Tool)

The plugin reports the shot ids of every open Photoshop tab back to Storyboard Tool in its heartbeat (`open_shot_ids`). With that, Storyboard Tool:

- Marks shots that are currently open in Photoshop with a green **PS** badge in its timeline.
- When you press **Open in Photoshop** for a shot that is *already* open, it does **not** launch Photoshop again. Instead it sends a one-shot focus request and the plugin switches to that existing tab — no confusing duplicate. Shots that aren't open yet still open the normal way.

The focus request carries a monotonic token; the plugin acts only when the token changes (and adopts the current token as a baseline on connect), so ordinary bridge polling never yanks your tabs.

## Now editing indicator

Shot canvases are saved under their shot id (e.g. `65aa7ea6…b1358dbc.psd`), so Photoshop tabs show unreadable filenames. The panel shows a **Now editing** banner that maps the active tab to its position and title — e.g. `Editing shot 12/30 · Bedroom wide (65aa7ea6…)`. It updates automatically when you switch tabs in Photoshop (polled, no modal). If the front tab is not a tracked shot, it says so instead.

## Canvas layer setup

Every shot canvas the plugin creates starts with a ready-to-draw stack:

- **`Layer 1`** — a blank, transparent drawing layer on top, left selected so you can draw immediately.
- **`SB bg`** *(optional)* — the board background reference image, when the shot has one.
- **Background** — the canvas-color fill at the project canvas size (from `settings.json` / live bridge).

So a new file opens as **Layer 1 → `SB bg` → Background** (top to bottom in the Layers panel). If you open an older shot that has no drawing layer, the plugin adds `Layer 1` for you. There is always exactly one `SB bg`; duplicates are removed on every sync. **Save** does not add or fill the canvas-color `Background` layer — use **Apply canvas color** when you want that fill in Photoshop.

## Board background (`SB bg`)

The board background reference is taken **only** from the dedicated `shot_XXX_background.png` file — never from the shot preview, because the preview is the artist's own drawing (using it as `SB bg` would duplicate the drawing as a reference layer and resurrect it after the reference is deleted). If a shot has `shot_XXX_background.png`, the plugin:

- **Creates canvas** — places the background as a reference layer named `SB bg` beneath `Layer 1`, above the canvas color.
- **Keeps it up to date** — automatically re-reads the file from disk (compares modification time) and replaces `SB bg` whenever Storyboard Tool regenerates it. Background syncs never steal your active layer, so adding or drawing on a new layer is safe at any time.
- **Save** — exports `shot_XXX_preview.png` only (hides `Background`, `SB bg`, and `SB ref:`). Press **Ctrl+S** in Photoshop to save the PSD.
- **Open / switch shot** — force-refreshes the background from disk so Storyboard Tool edits are picked up.
- **Photoshop open / document switch** — listens for `open` and `select` events and refreshes the background only when the file actually changed.

## Overlay previous shots (`SB ref:`)

Onion-skin layers stacked under your canvas are named `SB ref:` and kept out of the exported preview, just like `SB bg`. The full PSD still keeps every layer.

## Notes

- Prefer this plugin over **Ps** in Storyboard Tool for daily drawing — **Ps** launches a new Photoshop window via the OS; the plugin reuses the current session.
- Version **0.5.0** adds project-aware save and **Save & next shot**.
