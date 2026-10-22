# One project format: folder + handle `.sbd`

Status: approved (Owner, 2026-10-22), in progress.

**Owner decision (2026-10-22): no backward compatibility.** Every existing project (Layout 1 `.sbd`, Layout 1 folder, Layout 2 zip-handle) is a throwaway test. Drop the converter and all migration paths; opening an old project fails with a clear "unsupported old format" message. Decisions 4 and 5 and step 2 below are superseded by this.

## Why

Three storage models are live at once, and the newest one stores its metadata twice.

| Model | Where it is used | Cost |
|---|---|---|
| Layout 1 `.sbd` zip | Every real Owner project (`Untitled.sbd` 47 MB, `Storyboard/promptonly.sbd` 221 MB, `Storyboard.sbd` 204 MB) | Opening extracts to `%TEMP%`. Every flush re-zips the whole project. Unsaved work lives only in `%TEMP%` until the next flush (default 5 min). OneDrive has already produced two 46 MB conflict copies (`Untitled-DESKTOP-3T72OT3*.sbd`). 36 `storyboarder-*` husks are in `%TEMP%`. |
| Layout 1 folder | `New` with a non-`.sbd` path; old `Storyboard_Project/`; most tests (`create_project` in 22 test files) | A second set of code paths |
| Layout 2 | Default for `New .sbd` since enablement; only `hoo/` (test) exists | Binaries in folders (good). Metadata lives in `.storyboarder/work/*.json` **and** again as a zip in `X.sbd`. Reconciling the two copies needs `state.json` (`global_revision`, `committed_revision`, `commit_id`), the commit/recover machinery, and `dirty` + flush. `work/` still contains empty Layout 1 dirs. Backups live in two places. |

Storage code is about 4,400 lines (`project_document`, `project_convert`, `project_save_as`, `project_layout`, `file_transactions`, `project_transaction`), plus 293 layout branches across 15 modules. Every new feature has to handle both layouts (for example `generation_video_relative`).

## Outcome

One format. A project is a folder:

```
MyProject/
├─ MyProject.sbd        small handle: what you double-click / pick in Open / see in Recents
├─ Images/  PSD/  Blender/  Exports/  Videos/
└─ .storyboarder/       the only copy of metadata, plus app-private data (backups, transactions)
```

Done means all of the following:

- Every accepted mutation is durable when the request returns. No `dirty` state and no deferred flush. Save becomes "already saved", and Save As copies the folder.
- Each piece of metadata exists in one place on disk.
- Opening a project never extracts anything to `%TEMP%`.
- Opening a Layout 1 `.sbd` or folder offers a one-time conversion into a new sibling folder. The original file is never modified.
- Layout 1 runtime code is gone: pack/extract, working roots, `sweep_orphaned_working_roots`, dirty/flush, and every `layout ==` branch outside the converter. A read-only Layout 1 loader remains for the converter only.
- `scripts/verify_dev.py` passes. A copy of the Owner's real `Untitled.sbd` converts and shows identical board count, images, PSDs, scenes and generation history.

## Decisions

1. **The `.sbd` is a handle, not a second copy of the metadata.**
   - It holds identity only, for example `{format, project_id}`, and optionally a cover image. Shots, settings, scenes and generation records live only under `.storyboarder/`.
   - This changes what I told the Owner earlier, which was "the `.sbd` *is* all text data".
   - Reason: about 10 modules (`scene2d`, `scene3d`, `generation_service`, `comfy_cloud`, `reference_segments`, …) write JSON files directly under `metadata_root`. Making the `.sbd` the single store would mean routing every writer through a new document API. Making the files the store and the `.sbd` a pointer removes the duplication without touching those writers.
   - Rejected alternative: keep the JSON zip and commit it on every mutation. It still keeps two copies and the revision reconciliation.
   - Implementer's choice: the handle's encoding (JSON vs a tiny zip) and whether Recents reads a cover from the handle or the first board image. Keep the `.sbd` extension and file association either way.
2. **Keep per-mutation rollback; drop the document-commit layer.**
   - `layout2_mutation_transaction` (snapshot work, restore on exception or crash) is the only thing that makes a multi-file mutation atomic. Keep it. Snapshotting only the metadata files is fine if that is simpler.
   - Delete `commit_layout2_document`, `validate_layout2_document`, `recover_layout2_work`, `state.json`, `commit_id`, `committed_revision`, `advance_layout2_work_revision`'s document side, and `validate_layout2_source_lineage`.
3. **Keep one monotonically increasing `storage_revision` in `project.json`.** The Photoshop plugin uses it as `X-Storyboarder-Context-Revision` (optimistic concurrency, `plugin_service.py:66`), and `blender_bridge` restores it on failure. It is a counter, not a commit pointer.
4. **Conversion is a prompt on open, not silent.**
   - Text: "This project uses the old single-file format. Convert to a project folder? The original file is kept unchanged."
   - Destination: `<parent>/<stem>/<stem>.sbd`. Never merge into an existing folder; on collision, ask for a location.
   - Build on `project_convert.materialize_layout1_to_layout2`, which already copies assets, remaps paths, writes `converted_from` and refuses to merge. Extend it to Layout 1 folder projects; today `can_convert_to_layout2` accepts only `.sbd`.
   - Declining leaves the project unopened. Layout 1 is not kept as an editable format.
5. **Existing Layout 2 projects (`hoo/`, and any created since enablement) open without conversion.** On first open, rewrite their `.sbd` as a handle (the metadata is already in `work/`), then delete `state.json`.
6. **`New` always creates a project folder.** Remove the `create_project` / `create_document` Layout 1 creators and the non-`.sbd` branch in `method_new_project`.

Implementer's choice: whether to rename `.storyboarder/work/` (for example to `.storyboarder/data/`). If renamed, decision 5 must move it. Also open: whether to remove the empty Layout 1 dirs (`shots/`, `references/`, `scripts/`, `scene3d/`, `backups/`) that `_ensure_project_dirs` creates under `work/`. One backups location only.

## Order

Each step is one commit and must pass `verify_dev` on its own.

1. **Simplify Layout 2 in place.**
   - Handle `.sbd`, no commit layer, no `dirty`/flush for Layout 2.
   - Topbar Save shows saved state; autosave interval setting goes away.
   - Recents works from the handle.
   - Decision 5 upgrade.
   - Shared contract to settle first: the project payload fields the frontend reads (`dirty`, `can_convert_to_layout2`, `storage_revision`). Change them together with `frontend/src/state/*` and `projectCapabilities.ts`.
2. **Conversion on open** (decision 4), including Layout 1 folders. Test it against a *copy* of a real document in the scratchpad.
3. **Remove the Layout 1 runtime.**
   - Delete pack/extract, working roots, the layout branches in the 15 modules, `metadata_transaction`'s Layout 1 path, and Layout 1 creators.
   - Move test fixtures from `create_project` to a Layout 2 fixture helper. This is the largest step by line count; it can be split by module, but each sub-commit must stay green.
   - Keep a single startup sweep of old `%TEMP%/storyboarder-*` dirs for one release, then delete it.
4. **Docs.**
   - Update `PROJECTCONTEXT.md` §2 (supersede the Layout 2 slice plan), `docs/current_architecture.md`, `DECISIONS.md` (new entry), `OWNER_HANDBOOK.md` (what a project looks like, conversion, OneDrive note) and the plugin README.

## Risks and unknowns

- **Photoshop plugin version.**
  - The installed plugin is **0.6.7** (`%APPDATA%\Adobe\UXP\Plugins\External\local.storyboard.manager.preview-export_0.6.7`). It speaks protocol v1, and `plugin_service` returns 426 for Layout 2.
  - The repo has 0.7.0. The Owner must install 0.7.0 before using converted projects. Say so in the conversion prompt or the release note.
  - The plugin's offline mode (`panel.js` reads `project.json` from a picked folder) only works for Layout 1. Confirm it can be dropped, or make it fail with a clear message.
- **Blender session.** `blender_bridge` already supports Layout 2 (session copy under the project folder, manifest). Re-test open → edit in Blender → save → camera import on a converted project.
- **OneDrive.**
  - Per-file sync replaces whole-file sync, which is the main win.
  - New risk: a partially synced folder on another machine, for example `shots.json` arriving before its PNG. That must show as a missing image, not a crash. Existing integrity rules already tolerate missing linked artwork; add a test.
  - Opening the same project on two machines at once is still last-writer-wins per file. Out of scope; note it in the handbook.
- **Disk use.** Conversion writes the expanded size, roughly 140 MB for `Untitled.sbd`, into OneDrive next to the original. The prompt should show the size.
- **Rollback cost.** The per-mutation snapshot copies `work/`. Generation and video-take JSON accumulate there. Measure on a converted copy of `promptonly.sbd` (the largest). If a mutation exceeds about 50 ms, snapshot only the files the mutation enlists.
- **Background writers.** `comfy_cloud._run` and other threads write generation records outside a request. They must keep taking `PROJECT_LOCK` and writing atomically. They no longer need to set `dirty`.

What would change the plan: if the plugin's offline mode turns out to be in real use, or if step 3 shows a Layout 1 behaviour with no Layout 2 equivalent. Stop and raise it with the Owner instead of keeping the branch.

## Verify

- `scripts/verify_dev.py` after every step.
- Scenario checks on throwaway projects in the scratchpad (never the Owner's real files):
  - create → add boards / import image / PSD round trip → kill the process mid-mutation → reopen: no torn state.
  - Convert a copy of `Untitled.sbd` and of `Storyboard/promptonly.sbd`. Compare board count, image and PSD hashes, scenes2d/3d, and generation/video records against the source.
  - Photoshop plugin 0.7.0 edits a board in a converted project.
  - Blender session round trip.
  - A Comfy Cloud video take writes to `Videos/Generated/`.
  - Recents shows name, board count and thumbnail.
- After step 3: `grep -rn "LAYOUT_1\|pack_document\|extract_document\|working_root" storyboard_tool` returns only the converter's read path.
