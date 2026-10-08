# Storyboarder

Storyboarder is an open-source desktop pre-production and storyboard management application for filmmakers, animators, game developers, and independent creators.

It provides a structured workspace for planning shots, managing visual references, coordinating Photoshop-based drawing workflows, reviewing boards, assembling simple animatics, and exporting production-ready storyboard materials. The project is designed to keep creative decisions explicit, editable, and locally controlled.

> Storyboarder manages storyboards, comic layouts, AI prompts, generation requests, and reviewed results. Generation uses the configured external workflow; the application does not bundle an image-generation engine.

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
- Plan comic chapters using single pages, double-page spreads, and long scroll sections
- Draw comic panels directly, move and resize them with handles, split or duplicate them, and control spacing, cropping and explicit reading order
- Manage inherited comic/chapter/page prompts plus per-panel automatic or manual instructions and negative prompts
- Export full-size comic PNGs or chapter ZIPs containing ordered PNGs and prompt metadata
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
- Preview route animatics with a frame-based timeline, scrubber, single-frame stepping, loop and playback speed
- Use the bottom thumbnail timeline to select, arrange, and edit shot duration
- Scrub the animatic with the progress bar above the frame strip
- Export storyboard PDFs with one-shot, two-shot, or thumbnail layouts
- Export shot lists, contact sheets, image sequences, and timing JSON

The Photoshop workflow creates project-local PSD source files plus PNG previews, opens PSDs in Photoshop when configured, and auto-syncs previews when linked files change on disk. The Comic workspace also reuses the in-app drawing editor and existing generation queue. Automatic script-to-comic planning remains a future feature.

## Comic workflow

Open a project and select **Comic** in the left navigation. Add a chapter, then choose **+ Page**, **+ Spread**, or **+ Long scroll**. Pages start blank. Select **Draw panel** (R) and drag a rectangle directly on the page to create a panel and its board. **Select / move** (V) moves panels; eight handles resize them. **Snap · 24px** assists alignment; **Zoom** enlarges the working view without changing export dimensions. Escape cancels a gesture.

The inspector separates **Page**, **Panel**, **Lettering**, and **AI** controls. In **Panel**, use **Place board** to reuse an existing board, enter exact coordinates and dimensions (Enter or blur to apply), choose artwork fit/borders, and set numbered reading order. **Split horizontal/vertical** keeps the original board in the first half and creates a blank board in the second, using the page spacing as the gap. **Duplicate panel & board** copies authored instructions and artwork through the existing board duplication workflow. Undo/redo restores placements; boards created by these operations remain available even after a placement is undone.

**Artwork** opens the native drawing canvas and existing generation queue/results for the selected panel. Comic style, chapter, and page prompts are inherited by each request; the request uses the panel's actual dimensions. Editing these inputs marks existing results stale, including results that arrive after the edit.

Use **Read** for an uninterrupted chapter preview. **Export PNG** writes the selected page/spread/scroll section into the project's exports folder; **Chapter ZIP** writes ordered full-size PNGs and `comic-prompts.json` for the selected chapter. **Open export** opens the saved file in the operating system. Comic layout drafts save after editing pauses and are flushed by **Save layout**, **Ctrl+S**, and project/workspace transitions. Invalid layouts remain editable and cannot be exported until corrected.

Use **Edit vertices** to reshape a panel into a convex polygon and **Knife** (K) to drag an angled split. **Crop / pan** (C) moves artwork inside a fixed boundary; artwork zoom and offsets are independent of panel geometry. **Lettering** adds editable bubbles, captions and free text with horizontal/vertical writing, tail position, colors and overflow feedback. Shift/Ctrl-click selects multiple panels for group movement, alignment, spacing and locking. Page controls insert/remove long-scroll breathing room and show safe/binding guides; Read can use phone, tablet or desktop width. **More exports** adds chapter PDF and CBZ. Print bleed/CMYK preparation and automatic story-to-panel breakdown are not implemented. A single scroll section is limited to 32,000 pixels in height and 64 million pixels total; longer chapters can use multiple sections.

## Animation timing

In **Board → Play**, choose FPS, scrub the timecode, step one frame, loop, and review at a slower speed. The current board duration accepts exact frame counts (Enter/blur applies, Escape cancels). Durations remain shared by every route using that board. **Export route MP4** preserves the selected route order and writes a separate file; short shots retain their frame count rather than being stretched to half a second. Playback speed, safe guides and the playhead are preview controls. Route cards support dragging to place a board before another and Earlier/Later actions; edits that would create cycles are rejected. Native drawing, camera/action notes, references and the existing storyboard exports remain available.

## Photoshop UXP Bridge

A starter Photoshop UXP plugin is included in `photoshop_uxp_plugin/`.

Use Adobe UXP Developer Tool to load that folder as a development plugin. The panel can save the active Photoshop document into a selected shot folder as:

```text
shot_001.psd
shot_001_preview.png
```

Basic workflow:

1. In Storyboarder, select a shot.
2. Click `+` on a board in the filmstrip or `Ps` to create/open the PSD in Photoshop.
3. Draw and save in Photoshop.
4. Return to Storyboarder. The preview auto-syncs on window focus, shot change, or every few seconds.

Optional UXP workflow:

1. Keep Storyboard Tool running with the project open, then open Storyboard Bridge in Photoshop.
2. Open or activate a linked shot PSD from Storyboard Tool or the plugin.
3. Click `Export preview` or `Export + next`; Layout 2 paths come from the linked backend context.

## Project Structure

**New Project** asks whether to create a **Video** or **Comic** project before choosing
the `.sbd` location. The choice is saved with the project and selects its initial
workspace; both workspaces remain available.

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

## Canvas Color

Open **Canvas** in the top bar to choose a grayscale canvas color with the black-to-white brightness slider and hex input (default `#E8E8E8`). The color is saved in `settings.json`, used for new PSD canvases, shown on the in-app drawing canvas, and shared with the Photoshop UXP plugin via `.storyboard_bridge.json`.

## Run

```bash
pip install -r requirements.txt
python main.py
```

This opens a **desktop app window** via pywebview. The local FastAPI server is an internal implementation detail; do not open the app in a system browser.

The app stores new projects as a portable folder containing a metadata-only `.sbd` plus editable asset directories. New/Open Project dialogs use native file pickers handled by the internal server.

## Roadmap

Planned areas of development include:

- Stronger project validation, recovery, and automated test coverage
- Improved review, annotation, and shot-status workflows
- More robust packaging and cross-platform installation
- Expanded import and export interoperability
- Optional Blender and Unreal Engine integration
- Optional AI-assisted shot breakdown, planning, continuity checks, metadata drafting, and workflow automation

AI-assisted features will be designed as reviewable production aids rather than black-box replacements for creative decisions.

## Contributing

Contributions, issue reports, documentation improvements, and workflow feedback are welcome. Before submitting a substantial change, open an issue describing the problem, proposed behavior, and expected user workflow.

Please keep contributions focused on reproducible production workflows, clear local project data, and creator control. See [CONTRIBUTING.md](CONTRIBUTING.md) for the initial contribution guidelines.

## License

Storyboarder is released under the [MIT License](LICENSE).
