# Storyboard Tool — Stability Contract

Defines what each file type owns, what operations may mutate it, how missing
generated files are recovered, and what the manual smoke-test checklist covers.

---

## 1. Frozen asset ownership

| File | Owner | May be written by |
|---|---|---|
| `<id>_preview.png` | Artist artwork preview | Drawing save, image import, PSD sync, PSD recovery |
| `<id>.psd` | Artist source canvas | Canvas create, source import, PSD recovery |
| `<id>_background.png` | Reference background plate | Reference-apply flows (`_apply_reference_frame_to_shot`, `_apply_model_capture_to_shot`) only |
| `<id>_thumb.png` | Display cache | `_refresh_thumbnail_for_shot`, `_set_shot_preview_paths` |
| `<id>_annotations.json` | Annotations | Annotation API |
| `<id>_notes.json` | Notes snapshot | `_ensure_shot_files` (init only) |
| `shots.json` | Shot metadata | `save_shots`, `save_shots_json` (atomic) |
| `settings.json` | Project settings | `save_settings` (atomic) |
| `project.json` | Project manifest | `save_project` (atomic) |
| `storyboard_session.json` | UI session state | `write_session` (atomic) |

**Hard invariant:** `image_path` and `preview_image_path` on a `Shot` must NEVER
point to `<id>_background.png`.  The background plate is a reference plate; the
metadata fields are artwork-only.  `validate_project_integrity()` checks this.

---

## 2. Allowed mutations per operation

| Operation | Writes | Must NOT touch |
|---|---|---|
| Apply reference (image/video/3D) | `_background.png`, `_thumb.png` | `_preview.png`, `image_path`, `preview_image_path`, `source_file_path` |
| Drawing save (data URL) | `_preview.png`, `image_path`, `preview_image_path`, `_thumb.png` | `_background.png`, `source_file_path` |
| Image import (upload) | `_preview.png`, `_background.png` (copy), artwork paths, `_thumb.png` | `source_file_path`, `source_sync_mtime` |
| Source PSD import | `<id>.psd`, `_preview.png`, artwork paths, `source_sync_mtime` | `_background.png` |
| PSD sync | `_preview.png`, artwork paths, `_thumb.png`, `source_sync_mtime` | `_background.png`, `source_file_path` |
| Delete segment | `_background.png` removed, `_thumb.png` removed | `_preview.png` for PSD-backed shots |
| Delete segment (legacy bake) | `_background.png`, `_thumb.png`, `_preview.png` removed | `source_file_path` |
| Delete image | `_background.png` removed, artwork paths cleared | `source_file_path`, `_preview.png` if owned by PSD |

---

## 3. Atomic file writes

All critical file writes use a **temp file + `os.replace()`** pattern so a
crash or disk-full condition never leaves a corrupt file at the final path:

- `_atomic_write_json()` — `project.json`, `shots.json`, `settings.json`
- `write_session()` — `storyboard_session.json`
- `create_thumbnail()` — `_thumb.tmp.png` → `_thumb.png`
- `copy_and_convert_image()` / `copy_and_convert_image_stream()` — `*.tmp.png` → `*.png`
- `save_png_data_url()` — `*.tmp.png` → `*.png`
- `_apply_reference_frame_to_shot()` / `_apply_model_capture_to_shot()` — `*.tmp.png` → `_background.png`
- `import_source_file_stream()` — `*.psd.tmp` → `*.psd`
- `recover_shot_source_psd()` — `*.rebuilt.psd` → source PSD (original backed up to `_history/`)

---

## 4. Recovery for missing generated files

| Missing file | Impact | Recovery |
|---|---|---|
| `_thumb.png` | Filmstrip shows blank card | Re-generated on next `_refresh_thumbnail_for_shot` call or `sync_shot` |
| `_preview.png` (no PSD) | Board view shows blank | Import a new image or run PSD sync |
| `_preview.png` (PSD exists) | Board view shows blank | `sync_shot` re-exports from PSD |
| `_annotations.json` | Annotations panel empty | Re-created as `[]` by `_annotation_path()` in `app_state` |
| `_notes.json` | Notes panel empty | Re-created by `_ensure_shot_files` on next project open |
| `shots.json` (CSV present) | Load from legacy CSV | `open_project` migrates CSV → JSON non-destructively |
| `settings.json` | Default settings | `_load_settings` falls back to `DEFAULT_SETTINGS` |
| `storyboard_session.json` | Recent projects cleared | `read_session` returns `default_session()` |

`validate_project_integrity()` reports missing source files, duplicate shot IDs,
path traversal, and background-in-metadata violations.  It never raises — issues
are returned as a list for the caller to decide how to surface them.

---

## 5. Dirty-state guard

`app_state._refresh_project_from_disk()` checks `app.state.dirty` before
reloading from disk.  If the user has unsaved changes, the reload is skipped.
All API endpoints that mutate project state must set `app.state.dirty = True` or
call `_autosave()` before returning.

---

## 6. Manual smoke-test checklist

Before each release:

- [ ] Create a new project in a fresh directory; verify project.json + settings.json written
- [ ] Add 3 shots; verify shot dirs and annotation files created
- [ ] Upload an image to a shot; verify `_preview.png` written and displayed in board view
- [ ] Apply a reference image to a shot; verify `_background.png` created, preview unchanged
- [ ] Delete the reference segment; verify `_background.png` removed, preview intact
- [ ] Open in Photoshop, draw, sync; verify `_preview.png` updated, `_background.png` unchanged
- [ ] Duplicate a shot; verify new shot has blank artwork paths
- [ ] Reorder shots; save and reopen; verify order preserved
- [ ] Delete a shot; save and reopen; verify shot is gone
- [ ] Run `python -m unittest discover -s tests` — all non-integration tests pass
- [ ] Run `cd frontend && npm run build` — TypeScript compiles clean
