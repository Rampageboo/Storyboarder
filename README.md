# Storyboard Tool

A minimal local storyboard planning app with a React + Vite frontend and a Python FastAPI backend.

## Developer Documentation

- [Current Architecture](docs/current_architecture.md) — desktop launch flow, internal server, pywebview shell, React/Vite bundle, FastAPI routes, backend_service, shot_service, project_manager, project_transaction safety, Scene3D TypeScript source, generated-files policy, and deleted legacy artifacts.

## Features

- Run as a native desktop window
- Create and open JSON-based storyboard projects
- Add, duplicate, delete, and reorder shots
- View shots as a list or thumbnail board
- Group the shot board by scene or sequence
- Filter by status or unresolved review comments
- Track shot status: Draft, In Progress, Review, Approved, Final
- Use Photoshop or the operating system's configured image editor as the drawing canvas
- Store the editor executable path in project settings
- Edit detailed shot metadata, including character, dialogue, lighting, transition, tags, and comments
- Store 3D camera metadata such as angle, focal length, location, and rotation
- Import PNG, JPG, JPEG, and TIFF images
- Convert imported images to project-local PNG preview files
- Generate project-local thumbnails
- Add reference images per shot
- Link optional source files per shot
- Detect missing project files
- Relink a shot preview to a project-relative image path
- Preview selected shot images
- Create a blank shot canvas
- Open linked PSD source files in Photoshop when configured, otherwise in the operating system's default editor
- Auto-sync preview thumbnails from saved PSD or PNG files using file modification time checks
- Add lightweight annotations over the preview: arrows, lines, boxes, circles, text, and highlights
- Save annotations separately from the original image
- Play a simple duration-based animatic in the desktop app
- Use the bottom thumbnail timeline to select, arrange, and edit shot duration
- Scrub the animatic with the progress bar above the frame strip
- Export storyboard PDFs with one-shot, two-shot, or thumbnail layouts
- Export shot lists, contact sheets, image sequences, and timing JSON

This version treats Photoshop as the drawing surface and this app as the storyboard manager. It creates project-local PSD source files plus PNG previews, opens PSDs in Photoshop when configured, and auto-syncs previews when linked files change on disk. Blender or Unreal live capture, video export, cloud sync, and audio features are not implemented.

## Photoshop UXP Bridge

A starter Photoshop UXP plugin is included in `photoshop_uxp_plugin/`.

Use Adobe UXP Developer Tool to load that folder as a development plugin. The panel can save the active Photoshop document into a selected shot folder as:

```text
shot_001.psd
shot_001_preview.png
```

Basic workflow:

1. In Storyboard Tool, select a shot.
2. Click `+` on a board in the filmstrip or `Ps` to create/open the PSD in Photoshop.
3. Draw and save in Photoshop.
4. Return to Storyboard Tool. The preview auto-syncs on window focus, shot change, or every few seconds.

Optional UXP workflow:

1. Keep Storyboard Tool running with the project open, then open Storyboard Bridge in Photoshop.
2. Open or activate a linked shot PSD from Storyboard Tool or the plugin.
3. Click `Export preview` or `Export + next`; Layout 2 paths come from the linked backend context.

## Project Structure

New projects use the portable Layout 2 folder format:

```text
MyProject/
  MyProject.sbd             # metadata-only portable document
  Images/                   # previews, references, generated images
  PSD/                      # editable board and Scene 2D sources
  Blender/                  # Blender scenes, created only when needed
  Exports/
  .storyboarder/
    work/                   # recoverable JSON metadata working state
    state.json              # committed/global revision lineage
```

Keep the folder and its `.sbd` file together when moving or sharing a project.
The `.sbd` stores JSON metadata, while editable and generated assets remain visible
in the sibling directories. Legacy single-file and folder projects remain readable;
for a legacy single-file `.sbd`, use **More > Convert to Layout 2** to create a
source-preserving Layout 2 copy. For a legacy folder project, first use
**Save Project As...** to create a Layout 1 `.sbd`, then convert that document.

## Canvas color

Open **Canvas** in the top bar to choose a grayscale canvas color with the black-to-white brightness slider and hex input (default `#E8E8E8`). The color is saved in `settings.json`, used for new PSD canvases, shown on the in-app drawing canvas, and shared with the Photoshop UXP plugin via `.storyboard_bridge.json`.

## Run

```bash
pip install -r requirements.txt
python main.py
```

This opens a **desktop app window** (via pywebview). The local FastAPI server is an internal implementation detail — do not open the app in a system browser.

The app stores new projects as a portable folder containing a metadata-only `.sbd` plus editable asset directories. New/Open Project dialogs use native file pickers handled by the internal server.
