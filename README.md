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

1. In the Photoshop UXP panel, choose the matching shot folder.
2. Click `Save PSD + Preview`.
3. Storyboard Tool picks up the newest linked file automatically.

## Project Structure

New projects are created as:

```text
Storyboard_Project/
  project.json
  settings.json
  backups/
  shots/
    shot_001/
      shot_001_preview.png
      shot_001_thumb.png
      shot_001_annotations.json
      shot_001_notes.json
      references/
  references/
  images/
  exports/
  scripts/
```

New imported shot images are copied into each shot folder and renamed to match the shot ID, for example `shots/shot_001/shot_001_preview.png`.

## Canvas color

Open **Canvas** in the top bar to choose a grayscale canvas color with the black-to-white brightness slider and hex input (default `#E8E8E8`). The color is saved in `settings.json`, used for new PSD canvases, shown on the in-app drawing canvas, and shared with the Photoshop UXP plugin via `.storyboard_bridge.json`.

## Run

```bash
pip install -r requirements.txt
python main.py
```

This opens a **desktop app window** (via pywebview). The local FastAPI server is an internal implementation detail — do not open the app in a system browser.

The app stores projects as `project.json` plus local image files. New/Open Project dialogs use native file pickers handled by the internal server.
