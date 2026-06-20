# CODEX_TASK.md — Storyboarder: targeted reliability fixes

Repo: `Rampageboo/Storyboarder`. Work from the latest default branch.

## Read this first — philosophy

This is a **single-user local desktop storyboard tool that already works.** Do not use this task as permission to redesign the architecture.

The goal is to fix three concrete reliability problems:

1. A real crash in 3D/model reference apply caused by a wrong variable name.
2. A real operational risk where GLB/GLTF import overwrites the current scene file non-atomically.
3. A small settings edge case where `ref_segment_video: null` can produce a backend 500.

Do **not** split large files just because they are large. Do **not** refactor `ProjectContext.tsx`, `backend_service.py`, or `project_manager.py`. Do **not** change the Photoshop/PSD ownership model.

Each prompt is independent. Run one prompt, validate, commit, then stop.

## Hard constraints — all prompts

- No new dependencies.
- No rewrite.
- No broad cleanup.
- No frontend behavior changes unless a prompt explicitly requires it.
- Preserve canonical storage:
  - `shots.json` remains canonical.
  - `shots.csv` compatibility must remain.
- Preserve asset ownership:
  - `<shot_id>_preview.png` = artist artwork / foreground preview.
  - `<shot_id>_background.png` = reference plate.
  - `<shot_id>_thumb.png` = display cache.
  - Never set `_background.png` as `image_path` or `preview_image_path`.
- Do not touch Photoshop smart-object / PSD internals.
- Prefer focused regression tests over broad architecture changes.
- Use existing helpers and patterns where possible.
- Keep commits small and reviewable.

## Validation baseline

For backend changes:

```powershell
.venv\Scripts\python.exe -m pytest tests/ -q
```

If you add or modify frontend code, also run:

```powershell
cd frontend
npm run build
```

No frontend test runner exists; the build only type-checks. Keep frontend changes minimal.

---

## Prompt A — Fix model-capture reference apply crash

```text
You are working in https://github.com/Rampageboo/Storyboarder on the latest default branch.

Task: Fix the real backend crash in model-capture / 3D reference apply. Do not refactor unrelated reference-segment logic.

Verified facts:
- The function `apply_model_captures_to_boards()` in `storyboard_tool/reference_segments.py` defines an inner `apply_board(...)`.
- Inside that inner function, the code assigns:
  `shot.ref_segment_time = round(segment_offset, 3)`
- `segment_offset` is not defined in that scope.
- The available value is `segment_time`.
- This can crash after some board image files have already been written, leaving disk files and project metadata partially out of sync.
- The frontend model-reference apply flow calls the backend route that reaches this function.

Required changes:
1. Add a focused regression test first.
   - Put it in `tests/test_reference_segments.py` unless an existing better test file already exists.
   - The test should call `apply_model_captures_to_boards()` with a minimal project, a small board range, and valid minimal PNG capture data.
   - The test must fail before the fix because of the undefined `segment_offset`.
2. Fix the bug by using the correct variable:
   - Replace the undefined `segment_offset` reference with `segment_time`.
   - Do not change the surrounding apply flow.
   - Do not change the image ownership model.
3. The test should verify the important behavior:
   - The call succeeds without exception.
   - The expected board background files are written.
   - `shot.ref_segment_type` is `"model"`.
   - `shot.ref_segment_time` is stamped from the supplied capture timing.
   - An `undo_token` is returned.
   - Undo restore still works for the applied boards, using the existing undo helper if available.

Do NOT:
- Rewrite `_apply_ref_segment_template()`.
- Change image/video reference apply behavior.
- Change frontend code.
- Change PSD handling.
- Add new dependencies.

Validation:
- `.venv\Scripts\python.exe -m pytest tests/test_reference_segments.py -q`
- `.venv\Scripts\python.exe -m pytest tests/ -q`

Output:
- Changed files.
- Exact bug fixed.
- Test added.
- Validation results.
```

---

## Prompt B — Make Scene3D GLB/GLTF import atomic

```text
You are working in https://github.com/Rampageboo/Storyboarder on the latest default branch.

Task: Make Scene3D model import use atomic replacement so a failed import cannot corrupt the existing `scene3d/scene.glb` or `scene3d/scene.gltf`.

Verified facts:
- `storyboard_tool/external_tools.py` has `import_scene3d_stream(...)`.
- It currently writes uploaded GLB/GLTF bytes directly to the final destination, such as:
  `scene3d/scene.glb`
- Other file-writing paths in the project already use the safer pattern:
  write to a sibling temp file, then `os.replace(...)` into the final path.
- Direct overwrite is risky: if writing fails halfway, the previous model file may be truncated or corrupted.

Required changes:
1. Update `import_scene3d_stream(...)` to write to a temporary file in the same directory as the final destination.
2. Only replace the final model file after the temporary write succeeds.
3. Use `os.replace(...)` or the project's existing atomic-write pattern.
4. Clean up the temporary file on failure.
5. Preserve current behavior:
   - Supported suffixes stay the same.
   - Final filename stays the same.
   - Returned project-relative path stays the same.
   - Settings updates stay the same.
   - Existing successful import behavior stays the same.
6. Add a focused test if there is already test coverage around external tools or scene import.
   - If no suitable test harness exists, add the smallest practical unit test.
   - The test should verify that an existing scene file is not destroyed if the temp-write step fails.
   - Use monkeypatching if needed.
   - Do not introduce complex integration fixtures.

Do NOT:
- Change Blender launch behavior.
- Change reference-segment model apply behavior.
- Change frontend code.
- Change project settings schema.
- Add file validation beyond the existing accepted suffix behavior unless already present.

Validation:
- `.venv\Scripts\python.exe -m pytest tests/ -q`

Output:
- Changed files.
- Atomic-write strategy used.
- Whether a regression test was added, and what it covers.
- Validation results.
```

---

## Prompt C — Guard `ref_segment_video: null` in settings update

```text
You are working in https://github.com/Rampageboo/Storyboarder on the latest default branch.

Task: Fix the small backend settings edge case where `ref_segment_video: null` can produce a 500 error.

Verified facts:
- The frontend type allows `ref_segment_video?: RefSegmentVideoSettings | null`.
- The backend request schema allows `ref_segment_video` to be present as a nullable value.
- In `storyboard_tool/backend_service.py`, `method_update_settings(...)` reads:
  `segment = data.get("ref_segment_video")`
  and later calls `segment.get(...)`.
- If the caller sends `"ref_segment_video": null`, `segment` is `None`, so `.get(...)` raises an exception.
- This should be handled as a normal settings clear/update case, not as an internal server error.

Required changes:
1. Normalize `ref_segment_video` before reading from it.
   - If the value is a dict, use it.
   - If the value is `None`, treat it as clearing / empty settings according to the existing surrounding behavior.
   - If the value is another invalid type, preserve existing validation behavior as much as possible.
2. Do not redesign the entire settings patch system.
3. Add a focused backend test.
   - The test should send or call a settings update with `ref_segment_video: null`.
   - It should assert that the backend does not return / raise a 500.
   - It should assert the resulting settings state is the intended cleared/empty state.
4. Keep the response shape unchanged.

Do NOT:
- Extract a new settings service.
- Rewrite `method_update_settings(...)`.
- Change unrelated settings keys.
- Change frontend types unless the backend fix proves the current frontend type is wrong.
- Add new dependencies.

Validation:
- `.venv\Scripts\python.exe -m pytest tests/test_error_handling.py tests/test_api_errors.py tests/ -q`
  If those targeted files do not exist or are not relevant, run:
  `.venv\Scripts\python.exe -m pytest tests/ -q`

Output:
- Changed files.
- How `null` is now handled.
- Test added.
- Validation results.
```

---

## Recommended execution order

1. **Prompt A** first. It fixes the highest-risk real crash.
2. **Prompt B** second. It protects user GLB/GLTF files from partial overwrite.
3. **Prompt C** third. It removes a small but real settings edge-case 500.

Commit after each prompt. Do not combine unrelated prompts into one large patch unless explicitly asked.

---

## Out of scope — intentionally not doing

Do not add any of the following unless there is a new reproduced bug or a direct user feature request:

- Split `ProjectContext.tsx`.
- Split `backend_service.py`.
- De-facade `project_manager.py`.
- Add a domain-exception architecture layer.
- Rework Photoshop / PSD smart-object internals.
- Replace pywebview.
- Replace FastAPI.
- Add packaging / updater infrastructure.
- Add broad CI infrastructure.
- Reformat frontend files.
- Rename large modules for aesthetics.
- Change the route response shape.
- Change the `shots.json` / `shots.csv` storage contract.

## Rule going forward

Touch code only to fix a reproduced bug, protect user data, or implement a requested feature.

"Large file" is not a bug.
"Could be cleaner" is not a task.
"Architecture review suggested it" is not enough justification.
