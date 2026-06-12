# Storyboard Bridge UXP Plugin

Photoshop panel for drawing storyboards without switching back to Storyboard Tool after every shot.

## Install (development)

1. Install **Adobe UXP Developer Tool**
2. **Add Plugin** → select this `photoshop_uxp_plugin` folder
3. Click **Load** or **Watch**
4. Restart Photoshop
5. Open **Plugins → Storyboard Bridge**

## Recommended workflow (stay in Photoshop)

1. Open Storyboard Tool once and open your project (for the shot list and canvas color).
2. In Photoshop, open **Storyboard Bridge**.
3. Click **Choose project folder** → your `Storyboard_Project` folder (the one with `project.json`).
4. Pick a shot from the dropdown, or click **Open / create canvas**.
5. Draw on the 16:9 canvas.
6. Click **Save & next shot**:
   - Saves `shot_XXX.psd` and `shot_XXX_preview.png`
   - Updates `project.json` on disk
   - Closes the current document and opens the next shot in the **same Photoshop window**
   - Creates a new shot automatically when you reach the end (toggle **Auto-add shot at end**)

Storyboard Tool polls for file changes in the background, so previews and new shots appear when you switch back — no manual sync required.

## Buttons

| Button | Action |
|--------|--------|
| **Choose project folder** | Load `project.json` and shot list |
| **Open / create canvas** | Open existing PSD or create a new 1920×1080 canvas |
| **Save PSD + preview** | Save current shot only |
| **Save & next shot** | Save, then move to the next shot in one step |

## Canvas color

Storyboard Tool stores `canvas_background_color` in `settings.json`. The plugin reads `canvas_color.txt` / `storyboard_bridge.json` and can fill the **Background** layer to match.

## Notes

- Prefer this plugin over **Ps** in Storyboard Tool for daily drawing — **Ps** launches a new Photoshop window via the OS; the plugin reuses the current session.
- Version **0.5.0** adds project-aware save and **Save & next shot**.
