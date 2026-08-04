# Graph Report - D:\MyProjects\Storyboarder  (2026-08-04)

## Corpus Check
- 251 files · ~459,977 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 4917 nodes · 14255 edges · 180 communities (161 shown, 19 thin omitted)
- Extraction: 98% EXTRACTED · 2% INFERRED · 0% AMBIGUOUS · INFERRED: 279 edges (avg confidence: 0.54)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- Tests
- Frontend
- Storyboard
- Tests
- Frontend
- Storyboard
- Storyboard
- Storyboard
- Frontend
- Frontend
- Tests
- Frontend
- Tests
- Storyboard
- Tests
- Tests
- Storyboard
- Tests
- Tests
- Tests
- Tests
- Storyboard
- Tests
- Tests
- Frontend
- Tests
- Photoshop
- Tests
- Frontend
- Frontend
- Frontend
- Tests
- Storyboard
- Tests
- Tests
- Storyboard
- Storyboard
- Tests
- Storyboard
- Tests
- Frontend
- Frontend
- Storyboard
- Storyboard
- Frontend
- Tests
- Tests
- Tests
- Frontend
- Tests
- Frontend
- Tests
- Tests
- Tests
- Photoshop
- Storyboard
- Storyboard
- Photoshop
- Storyboard
- Tests
- Storyboard
- Tests
- Tests
- Tests
- Tests
- Photoshop
- Storyboard
- Tests
- Tests
- Tests
- Tests
- Storyboard
- Tests
- Tests
- Photoshop
- Photoshop
- Storyboard
- Storyboard
- Tests
- Storyboard
- Tests
- Photoshop
- Photoshop
- Storyboard
- Frontend
- Storyboard
- Tests
- Storyboard
- Tests
- Storyboard
- Frontend
- Frontend
- Frontend
- Photoshop
- Tests
- Storyboard
- Tests
- Storyboard
- Tests
- Frontend
- Frontend
- Storyboard
- Storyboard
- Tests
- Storyboard
- Frontend
- Storyboard
- Tests
- Photoshop
- Scripts
- Tests
- Tests
- Tests
- Tests
- Tests
- Photoshop
- Storyboard
- Storyboard
- Storyboard
- Spikes
- Storyboard
- Spikes
- Storyboard
- Storyboard
- Tests
- Frontend
- Storyboard
- Tests
- Frontend
- Photoshop
- Storyboard
- Tests
- Tests
- Tests
- Tests
- Frontend
- Storyboard
- Photoshop
- Storyboard
- Storyboard
- Storyboard
- Frontend
- Tests
- Tests
- Tests
- Tests
- Storyboard
- Storyboard
- Storyboard
- Tests
- Scripts
- Storyboard
- Tests
- Tests
- Tests
- Tests
- Tests
- Storyboard
- Storyboard
- Storyboard
- Storyboard
- Frontend
- Spikes
- Spikes
- Storyboard
- Storyboard
- Tests
- Frontend
- Frontend
- Storyboard
- Storyboard

## God Nodes (most connected - your core abstractions)
1. `Project` - 496 edges
2. `StoryboardBackendService` - 177 edges
3. `requestJson()` - 128 edges
4. `Shot` - 127 edges
5. `Scene3DEditor` - 103 edges
6. `create_app()` - 72 edges
7. `app_error()` - 64 edges
8. `_fake_window()` - 53 edges
9. `materialize_layout1_to_layout2()` - 52 edges
10. `_focus_desktop_window()` - 51 edges

## Surprising Connections (you probably didn't know these)
- `_Layout2BpyManager` --uses--> `StoryboardBackendService`  [INFERRED]
  tests/test_layout2_scenes.py → storyboard_tool/backend_service.py
- `_FakeBpyManager` --uses--> `BpyViewportError`  [INFERRED]
  tests/test_bpy_viewport.py → storyboard_tool/bpy_viewport.py
- `_Layout2BpyManager` --uses--> `BpyViewportError`  [INFERRED]
  tests/test_layout2_scenes.py → storyboard_tool/bpy_viewport.py
- `_Layout2BpyManager` --uses--> `BpyViewportManager`  [INFERRED]
  tests/test_layout2_scenes.py → storyboard_tool/bpy_viewport.py
- `TestApplyReferenceFrameToShot` --uses--> `Shot`  [INFERRED]
  tests/test_board_asset_model.py → storyboard_tool/models.py

## Import Cycles
- 2-file cycle: `frontend/src/components/ReferenceAssignmentPopover.tsx -> frontend/src/components/ReferenceAssignmentPopover3dApply.tsx -> frontend/src/components/ReferenceAssignmentPopover.tsx`

## Communities (180 total, 19 thin omitted)

### Community 0 - "Tests"
Cohesion: 0.06
Nodes (132): Project, Path, Expanded metadata/work root (the historical ``root_path``)., Portable project folder; identical to ``root_path`` for Layout 1., _load_scene2d_for_conversion(), Read supported Layout 1 Scene2D metadata without invoking its disk migration., project_path_for(), Return a canonical layout-owned project path for a static role. (+124 more)

### Community 1 - "Frontend"
Cohesion: 0.04
Nodes (80): advancePlaybackTime(), AnimationClip, AnimationHintInput, buildAnimationHint(), buildTimelineUiState(), clampAnimationTime(), collectAnimatedNodeNames(), computeClipDuration() (+72 more)

### Community 2 - "Storyboard"
Cohesion: 0.05
Nodes (8): Any, Rebuild a broken (Photoshop-unopenable) source PSD from its layers., Business logic shared by every REST route and the desktop bridge., Single-round-trip startup: read session and describe the recent documents.…, Return to Home: flush the document, then drop it from app state. The flush is…, Trigger background preview analysis for the current project. Returns…, Return the current preview-analysis job status for the open project., StoryboardBackendService

### Community 3 - "Tests"
Cohesion: 0.09
Nodes (73): add_shot(), cleanup_document_working_root(), create_document(), open_project(), Create a user-visible single-file project backed by a private work tree., Best-effort removal of a private expanded `.sbd` work tree., _app_for(), _legacy_project() (+65 more)

### Community 4 - "Frontend"
Cohesion: 0.09
Nodes (3): Scene3DEditor, Scene3DEditorCallbacks, formatWorkspaceFileName()

### Community 5 - "Storyboard"
Cohesion: 0.08
Nodes (60): _analysis_project(), _conversion_uuid(), _input_inventory(), Layout2ConvertError, Layout2ConvertResult, _mapped_scene2d_path(), materialize_layout1_to_layout2(), _migrate_generation() (+52 more)

### Community 6 - "Storyboard"
Cohesion: 0.08
Nodes (67): accept_candidate_as_codex_layer(), _append_prompt_line(), _apply_request_state(), _build_generation_plan(), build_request_snapshot(), _candidates_dir(), _canonical_hash(), clear_pending_queue_requests() (+59 more)

### Community 7 - "Storyboard"
Cohesion: 0.07
Nodes (61): Protocol, Project integrity validation. validate_project_integrity reports structural and…, _casefold_directory_inventory(), ensure_layout_enabled(), generation_asset_relative(), _is_within(), layout1_project_root(), LayoutDisabledError (+53 more)

### Community 8 - "Frontend"
Cohesion: 0.06
Nodes (32): ReferenceModelCaptureOptions, ReferenceModelPreview, ReferenceModelPreviewCanvas, ReferenceModelPreviewHandle, ReferenceModelPreviewProps, applyModelCaptures(), ApplyModelCapturesOptions, ModelCaptureFrameFn (+24 more)

### Community 9 - "Frontend"
Cohesion: 0.07
Nodes (54): Scene3dWireframeMode, Scene3DEditorConstructor, Scene3DEditorInstance, initWorkspaceEditorThree(), InitWorkspaceEditorThreeOptions, ThreeModule, ThreeObject, WorkspaceEditorThreeBoot (+46 more)

### Community 10 - "Tests"
Cohesion: 0.09
Nodes (10): _is_uuid(), _quiet(), Verifier must reject Perspective order differences (not sorted-ID comparison)., Verifier must reject differing source_file_path in scene meta., Verifier must raise if source preview existed before but is gone after save., If reading the restored file raises OSError, metadata_verified must be False., If shutil.rmtree(new_dir) fails after verified rollback, error must mention…, source copy succeeds, preview copy fails → HTTP 500, full rollback. (+2 more)

### Community 11 - "Frontend"
Cohesion: 0.08
Nodes (59): requestJson(), createQueueBatchRequests(), convertProject(), createProject(), getMissingFiles(), getProject(), importScene3d(), openProject() (+51 more)

### Community 12 - "Tests"
Cohesion: 0.06
Nodes (13): _make_project(), Project stability tests — Core Stability Pass. Covers: -…, Duplicate must not share the original shot's PSD path. (add_shot always creates…, delete_shot is metadata-only — it must NOT remove the shot directory., Integrity check must pass after add → reorder → delete → restore., Background file survives save/reload; image_path must NOT point to it., If the stream copy raises mid-write, the pre-existing file must be left intact…, A successful import writes the file; use a non-PSD suffix to skip PSD parsing. (+5 more)

### Community 13 - "Storyboard"
Cohesion: 0.08
Nodes (60): FastAPI, _read_launch_token(), _shutdown_reference_cleanup(), AddShotRequest, AnimaticExportRequest, AnnotationSaveRequest, ApplyRefSegmentRequest, AppSessionUpdateRequest (+52 more)

### Community 14 - "Tests"
Cohesion: 0.08
Nodes (19): _focus_desktop_window(), Focus a pywebview window without changing its geometry. window_state: the…, _fake_window(), FocusDesktopWindowMaximizedTests, FocusDesktopWindowMinimizedFromMaximizedTests, FocusDesktopWindowMinimizedFromNormalTests, FocusDesktopWindowNormalTests, FocusDesktopWindowRestoreFailureTests (+11 more)

### Community 15 - "Tests"
Cohesion: 0.07
Nodes (43): getBridgeStatus(), listScene2D(), updateSettings(), getAnnotations(), recoverShotSource(), relinkPreview(), saveAnnotations(), uploadShotSource() (+35 more)

### Community 16 - "Storyboard"
Cohesion: 0.09
Nodes (56): normalize_reference_fit_mode(), apply_model_captures_to_boards(), apply_ref_segment_3d_to_boards(), apply_ref_segment_image_to_boards(), _apply_ref_segment_template(), apply_ref_segment_to_boards(), _board_bake_assets(), clear_active_reference_video() (+48 more)

### Community 17 - "Tests"
Cohesion: 0.05
Nodes (13): _make_png(), _make_project(), Shot, Focused tests for reference_segments domain module. Covers: -…, Return the bytes of a valid PNG image (uses PIL)., TestApplyImageSegment, TestApplyModelCaptures, TestClearActiveReference (+5 more)

### Community 18 - "Tests"
Cohesion: 0.10
Nodes (14): _is_uuid(), MigrationCommitVerificationTests, Path, _quiet(), P1-3: Verify settings/reference links before crash-recovery roll-forward. These…, Call list_scenes2d to trigger _recover_uuid_migration()., Journal=metadata_committing, UUID scenes valid, settings still references…, scene_id is UUID but perspective_id is still legacy → rollback. (+6 more)

### Community 19 - "Tests"
Cohesion: 0.06
Nodes (19): atomic_copy_file(), Copy *source* to *destination* via a sibling temp file. Uses temp +…, Copy the board background file to its canonical location atomically., _save_board_background_copy(), _make_png_bytes(), _make_project(), File transaction safety regression tests. Verifies that multi-file operations…, If thumbnail generation fails, image_path / preview_image_path must still be… (+11 more)

### Community 20 - "Tests"
Cohesion: 0.07
Nodes (22): shots_json_path(), After import_image_for_shot and save/reload, no metadata path points to…, _make_project(), shots.json must have a top-level version key (structured format)., project.json must never contain an inline 'shots' key after a modern save., open_project must load from shots.json and ignore shots.csv when both exist., open_project must fall back to shots.csv for legacy CSV-only projects., open_project creates shots.json for a legacy CSV-only project (non-destructive). (+14 more)

### Community 21 - "Storyboard"
Cohesion: 0.05
Nodes (8): app_error(), HTTPException, Return an HTTPException carrying a structured body. The ``api.create_app``…, ExportServiceMixin, Any, Export generation, download lookups, and project file serving., Resolve (project view, filename suffix) for a whole or partial export.…, Validate a range spec for the export dialog, without exporting anything. Keeps…

### Community 22 - "Tests"
Cohesion: 0.07
Nodes (14): get_missing_media(), missing_files(), _make_png_bytes(), _make_project(), Path, Tests for project asset lifecycle: creation, import, deletion, and missing-file…, TestAddShot, TestCreateProject (+6 more)

### Community 23 - "Tests"
Cohesion: 0.07
Nodes (16): _add_shot(), _make_project(), Shot, TestClient, Every export the modal offers must accept a board range. A generating export…, Exports identify a board by its position in the strip, never by its UUID. The…, TestBoardNumbersNotUuids, TestCheckExportExists (+8 more)

### Community 24 - "Frontend"
Cohesion: 0.09
Nodes (47): addScene2DPerspectiveToReferences(), addScene2DToReferences(), createScene2D(), createScene2DPerspective(), deleteScene2D(), deleteScene2DPerspective(), duplicateScene2DPerspective(), importScene2DPerspective() (+39 more)

### Community 25 - "Tests"
Cohesion: 0.16
Nodes (44): create_app(), Persist the project. Metadata (project.json/shots.json/settings) is always…, save_project(), create_scene(), create_scene(), _Layout2BpyManager, _project(), MonkeyPatch (+36 more)

### Community 26 - "Photoshop"
Cohesion: 0.08
Nodes (47): applyCanvasBackground(), applyCanvasBackgroundInModal(), attachPanelContent(), backupExistingPsd(), boardBackgroundSigByShot, clearScene2DWorkNavigation(), copyPsdToHistory(), createCanvasBackgroundLayerInModal() (+39 more)

### Community 27 - "Tests"
Cohesion: 0.10
Nodes (14): HeartbeatFreshnessTests, PluginScene2DTests, Path, _quiet(), Plugin Scene 2D integration tests (CODEX_TASK Part 16). Tests the boundary…, Inject an image perspective directly into scenes2d.json (creation API only…, P1-1: Authoritative plugin work-key state via file vs HTTP heartbeat freshness., Write a file heartbeat that will be read by live_bridge.read_plugin_heartbeat(). (+6 more)

### Community 28 - "Frontend"
Cohesion: 0.08
Nodes (40): BpyCameraPathRequest, BpyCameraPathResult, BpyViewportStatus, createBpyCameraPath(), getBpyViewportStatus(), saveBpyScene(), startBpyViewport(), stopBpyViewport() (+32 more)

### Community 29 - "Frontend"
Cohesion: 0.04
Nodes (47): eslint, @eslint/js, eslint-plugin-react-hooks, eslint-plugin-react-refresh, dependencies, react, react-dom, @tauri-apps/api (+39 more)

### Community 30 - "Frontend"
Cohesion: 0.10
Nodes (42): applyRefSegment(), applyRefSegment3d(), applyRefSegmentImage(), applyRefSegmentModelCaptures(), ApplyRefSegmentRequest, deleteProjectReference(), deleteRefSegment(), RefSegment3dCapture (+34 more)

### Community 31 - "Tests"
Cohesion: 0.09
Nodes (45): codex_layer_filename(), fit_image_to_canvas(), Scale uniformly to fit inside the canvas, centered (matches in-app object-fit:…, Resolve an exact layout-owned shot asset role., resolve_shot_asset(), _contained_project_path(), get_shot_board_background_path(), get_shot_codex_layer_path() (+37 more)

### Community 32 - "Storyboard"
Cohesion: 0.07
Nodes (40): ae(), _applyProgramLighting(), b(), _calibrateImportedLights(), ce(), _collectImportedCameras(), _collectObjectColorKeys(), de() (+32 more)

### Community 33 - "Tests"
Cohesion: 0.09
Nodes (42): duplicate_shot(), _ensure_shot_files(), _open_expanded_project(), Reload project.json from disk when the plugin or another tool updated it., reload_project_if_changed(), atomic_write_text(), ensure_project_dirs(), load_settings() (+34 more)

### Community 35 - "Storyboard"
Cohesion: 0.10
Nodes (44): Exception, _annotation_path(), _autosave(), convert_active_project_to_layout2(), _dialog_initial_dir(), _ensure_transition_runtime(), _find_shot(), _persist_app_session() (+36 more)

### Community 36 - "Storyboard"
Cohesion: 0.15
Nodes (14): _file_header(), PluginBridgeService, Any, FastAPI, HTTPException, Path, Shot, Return the next PSD Perspective in the same Scene group. (+6 more)

### Community 37 - "Tests"
Cohesion: 0.05
Nodes (4): skipIf, create_blank_psd(), TestCreateBlankPsdAtomicWrite, StoryboardSmokeTests

### Community 38 - "Storyboard"
Cohesion: 0.10
Nodes (44): copy_and_convert_image_stream(), BinaryIO, add_reference_image_stream(), _apply_model_capture_to_shot(), cleanup_orphan_reference_images(), collect_reference_image_paths(), delete_shot(), import_image_for_shot() (+36 more)

### Community 39 - "Tests"
Cohesion: 0.06
Nodes (14): Shot, mutate_project(), In-memory project-state snapshot and rollback. Provides a single context…, Snapshot and conditionally restore in-memory project state. On enter: deep-…, TestGenerationAuthoringCompatibility, _make_project(), Tests for project_transaction and atomic save in project_manager., Simulates a ref-apply partial mutation followed by rollback. (+6 more)

### Community 40 - "Frontend"
Cohesion: 0.09
Nodes (38): applyObjectColorPreview(), applyWireframeModeToRoots(), cacheOriginalMaterials(), clearWireframeOverlays(), createWireframeResources(), disposePreviewMaterials(), generateObjectColor(), generateObjectColorHex() (+30 more)

### Community 41 - "Frontend"
Cohesion: 0.08
Nodes (30): apiBase(), initApiBase(), isTauri(), BridgeStatusPayload, LiveBridgeUpdate, PluginChange, PreviewAnalysisEvent, publishLiveBridge() (+22 more)

### Community 42 - "Storyboard"
Cohesion: 0.12
Nodes (40): _touch_live_bridge(), active_work_context(), focus_token(), focus_work_context(), generation_result_revision(), get_preview_analysis_job(), init_bridge_state(), live_focus_shot_id() (+32 more)

### Community 43 - "Storyboard"
Cohesion: 0.18
Nodes (40): Resolve Scene 3D JSON below metadata in Layout 2., scene3d_metadata_path(), active_scene(), configure_blend_preview(), _default_display_settings(), delete_scene(), _delete_scene_layout2(), ensure_active_scene() (+32 more)

### Community 44 - "Frontend"
Cohesion: 0.15
Nodes (33): openShotPreview(), removeShotImage(), removeShotLayer(), shotBoardBackgroundUrl(), shotCodexLayerUrl(), shotImageUrl(), shotThumbnailUrl(), uploadShotImage() (+25 more)

### Community 45 - "Tests"
Cohesion: 0.08
Nodes (21): _ProjectFixture, Path, _quiet(), Plugin/backend integration regression tests. Covers the boundary between the…, POST /api/plugin/shots/<id>/focus must set live_selected_shot_id in app state.…, focus endpoint must return a full context object with shots, canvas, bridge., Focusing a shot must not change image_path / preview_image_path., Focusing a shot must not change has_board_background or background paths. (+13 more)

### Community 46 - "Tests"
Cohesion: 0.10
Nodes (38): Check project data for structural and ownership violations. Returns a list of…, validate_project_integrity(), ensure_no_casefold_collisions(), parse_project_manifest(), project_relative_posix(), ProjectLayoutSpec, Any, Validate the schema/layout fields in a project manifest. Versions 1-3 remain… (+30 more)

### Community 47 - "Tests"
Cohesion: 0.11
Nodes (13): get_scene3d_file_path(), import_scene3d_stream(), BinaryIO, _make_png(), _make_project(), _png_data_url(), Path, Tests for Scene3D backend: capture apply, file import, and boundary conditions. (+5 more)

### Community 48 - "Frontend"
Cohesion: 0.08
Nodes (33): addComment(), duplicateShot(), importImagePath(), removeShotReference(), resolveComment(), restoreShot(), saveShotDrawing(), setShotReferencePaths() (+25 more)

### Community 49 - "Tests"
Cohesion: 0.12
Nodes (18): _add_image_segment(), _make_project(), _make_ref_image(), Path, Shot, Core invariant: apply must never overwrite the artist's drawing., image_path / preview_image_path must stay empty after reference apply when no…, When the board already has artwork, display paths must not be changed by apply. (+10 more)

### Community 50 - "Frontend"
Cohesion: 0.11
Nodes (32): acceptGenerationCandidate(), createCodexBatchRequests(), createGenerationRequest(), CreateGenerationRequestOptions, deleteGenerationRequest(), listGenerationRequests(), pullGenerationResults(), QueueBatchRequestResponse (+24 more)

### Community 51 - "Tests"
Cohesion: 0.23
Nodes (35): materialize_layout2_save_as(), Publish a complete validated snapshot with one directory rename., _app_for(), _layout2_project(), MonkeyPatch, parametrize, Path, test_layout1_save_as_keeps_existing_document_flow() (+27 more)

### Community 52 - "Tests"
Cohesion: 0.10
Nodes (10): _make_client(), TestClient, _quiet(), A non-decodable image upload is a client error (400), not a server 500. Pillow…, TestCorruptUploadError, TestExportError, TestInvalidProjectOperation, TestMediaNotFoundError (+2 more)

### Community 53 - "Tests"
Cohesion: 0.13
Nodes (15): _get_main_window_restore_state(), Set the application-owned runtime window state., Set the state the window should restore to (normal or maximized only)., Return the restore state (what to come back to after un-minimizing), defaulting…, _set_main_window_restore_state(), _set_main_window_state(), _set_main_window_state / _get_main_window_state., _set_main_window_restore_state / _get_main_window_restore_state. (+7 more)

### Community 54 - "Photoshop"
Cohesion: 0.13
Nodes (34): activeDocumentKey(), applyLiveBridge(), chooseProjectFolder(), chooseShotFolder(), compactText(), currentShotFromProjectData(), currentShotIndex(), currentShotIndexLabel() (+26 more)

### Community 55 - "Storyboard"
Cohesion: 0.12
Nodes (17): FastAPI, AppErrorCode, Structured application error codes and factory. Every app-level error has a…, browse_blender_executable(), browse_folder(), browse_photoshop_executable(), browse_project_json(), browse_project_save() (+9 more)

### Community 56 - "Storyboard"
Cohesion: 0.12
Nodes (27): Thin entry point for PyInstaller — wraps storyboard_tool.sidecar_main. Do not…, _configure_windows_asyncio_noise(), _configure_windows_taskbar_identity(), _ignore_connection_reset(), _load_window_state(), _log_stage(), open_desktop_window(), Path (+19 more)

### Community 57 - "Photoshop"
Cohesion: 0.14
Nodes (28): activeScene2DContext(), activeWorkContext(), applyPluginContext(), applyWorkContext(), normalizeShotFromBackend(), notifyBackendShotFocus(), notifyPluginPsdSaved(), pluginHttpError() (+20 more)

### Community 58 - "Storyboard"
Cohesion: 0.15
Nodes (16): BpyViewportError, BpyViewportManager, _free_loopback_port(), manager_for_app(), Any, RuntimeError, Managed headless-Blender viewport for the built-in Scene3D workspace., Flush Blender-owned scene data without stopping the warm viewport. (+8 more)

### Community 59 - "Tests"
Cohesion: 0.11
Nodes (29): _ensure_psd_pixel_budget(), Rebuild a Photoshop-unopenable source PSD from its own layers. Backs the…, recover_shot_source_psd(), can_open_with_psd_tools(), _copy_layer_properties(), _is_plugin_managed_layer_name(), _iter_leaf_layers(), _layer_own_image() (+21 more)

### Community 60 - "Storyboard"
Cohesion: 0.13
Nodes (31): _archive_matches_work(), _cover_bytes(), create_working_root(), _existing_cover(), extract_document(), _extract_layout2_json(), _force_writable(), inspect_document_layout() (+23 more)

### Community 61 - "Tests"
Cohesion: 0.23
Nodes (31): commit_layout2_document(), Layout2RecoveryResult, Recover newer JSON work, otherwise restore the committed archive., Atomically commit the JSON-only work tree to a metadata-only .sbd., recover_layout2_work(), _cover(), _json(), _layout2_project() (+23 more)

### Community 62 - "Tests"
Cohesion: 0.13
Nodes (27): compose_image_to_canvas(), copy_and_convert_image(), create_blank_canvas(), create_thumbnail(), ensure_psd_board_background_layer(), export_psd_composite_to_png(), fill_image_to_canvas(), image_has_transparency() (+19 more)

### Community 63 - "Tests"
Cohesion: 0.13
Nodes (8): _ProjectFixture, _quiet(), Regression test coverage for core professional stability workflows. Tests are…, Base: creates a temp dir + TestClient with a project containing two shots., TestExportWithMissingMedia, TestForbiddenLegacyRoutes, TestRefApplyUndo, TestShotLifecycle

### Community 64 - "Tests"
Cohesion: 0.12
Nodes (5): _project_with_shots(), Shot, In-memory project — no filesystem, for lookup-only tests., TestFindShot, TestUpdateShot

### Community 65 - "Photoshop"
Cohesion: 0.16
Nodes (25): boardBackgroundRefreshNeeded(), boardBackgroundSignature(), captureActiveLayerIds(), clearOverlayLayersInModal(), createNamedLayerAtTopInModal(), deleteLayersInModal(), ensureBoardBackgroundStackOrderInModal(), ensureDrawingLayerInModal() (+17 more)

### Community 66 - "Storyboard"
Cohesion: 0.17
Nodes (26): _find_shot_index(), default_continuity(), default_generation_state(), default_prompt_config(), default_shot_design(), normalize_continuity(), normalize_generation_state(), normalize_prompt_config() (+18 more)

### Community 67 - "Tests"
Cohesion: 0.07
Nodes (5): parametrize, Board range specs — the export dialog's "1-5, 8" field., TestDescribe, TestFilenameSuffix, TestParse

### Community 68 - "Tests"
Cohesion: 0.10
Nodes (10): LogRecord, Path, Configure structured file + console logging for the storyboard_tool package.…, setup_logging(), _ListHandler, _quiet(), Captures log records for assertion in tests., TestBackendExceptionLogging (+2 more)

### Community 69 - "Tests"
Cohesion: 0.21
Nodes (4): Path, _quiet(), Backend tests for shot work-item schema (CODEX_TASK Part 16). Verifies that…, ShotWorkItemsTests

### Community 70 - "Tests"
Cohesion: 0.10
Nodes (14): A newly created shot has no board background plate on disk., A newly created shot has no real artwork preview., has_board_background is True once the _background.png plate is on disk., has_artwork_preview must be False when only the background plate exists (no…, has_artwork_preview is True when a non-solid-color _preview.png exists., Every shot in the context must have a has_board_background key., Every shot in the context must have a has_artwork_preview key., image_path must not reference _background.png in a fresh shot. (+6 more)

### Community 71 - "Storyboard"
Cohesion: 0.19
Nodes (26): _bridge_status_payload(), _plugin_link_state(), _plugin_open_shot_ids(), _plugin_selected_shot_id(), _plugin_work_key_state(), Shot ids the plugin reports as open Photoshop tabs (heartbeat file or HTTP)., (linked, seconds_since_seen, open_shot_ids) — shared by status + open-source., Generic Photoshop work keys reported by the newest heartbeat source. (+18 more)

### Community 72 - "Tests"
Cohesion: 0.12
Nodes (22): blend_template_path(), blender_portable_reference(), ensure_project_blend_file(), get_project_blend_path(), open_blender_scene(), open_project_file(), preheat_photoshop(), Any (+14 more)

### Community 73 - "Tests"
Cohesion: 0.11
Nodes (13): PluginMetadataBoundaryTests, Path, Plugin metadata boundary tests. These tests verify that the backend enforces…, plugin export-preview with path-traversal preview_image_path must return 400., plugin export-preview with path-traversal source_file_path must return 400., plugin export-preview must reject a source_file_path that is not a .psd., plugin psd-saved must reject a source_file_path that is not a .psd., Valid export-preview sets preview_image_path via backend validation. (+5 more)

### Community 74 - "Photoshop"
Cohesion: 0.13
Nodes (26): clampOverlayCountInput(), clampOverlayOpacityInput(), clearOverlayLayers(), documentNativePath(), findOpenDocumentForWorkItem(), focusCurrentPerspectiveTab(), formatShotIdLabel(), getNextShotsForOverlay() (+18 more)

### Community 75 - "Photoshop"
Cohesion: 0.12
Nodes (15): assetNativePathForRole(), assetPathForRole(), assetProjectRelativePathForRole(), findWorkItemByNativePath(), formatShotDisplayLabel(), humanReadableShotLabel(), isExplicitAssetContext(), normalizeNativePath() (+7 more)

### Community 76 - "Storyboard"
Cohesion: 0.26
Nodes (25): _adopt_fresh_session(), attach_process(), begin_session(), bridge_file_path(), cancel_session(), heartbeat_file_path(), _ingest_layout2_session_save(), _ingest_layout2_session_save_locked() (+17 more)

### Community 77 - "Storyboard"
Cohesion: 0.22
Nodes (26): advance_layout2_work_revision(), _atomic_write_bytes(), _atomic_write_json(), enlist_layout2_mutation_paths(), layout2_mutation_transaction(), layout2_state_path(), _layout2_transactions_root(), layout2_work_root() (+18 more)

### Community 78 - "Tests"
Cohesion: 0.08
Nodes (5): Tests for shot_service: create, duplicate, delete, reorder, find, update., TestCreateShot, TestDeleteShot, TestDuplicateShot, TestReorderShots

### Community 79 - "Storyboard"
Cohesion: 0.22
Nodes (24): create_canvas_for_shot(), get_canvas_color(), get_canvas_size(), normalize_canvas_size(), persist_canvas_color(), persist_canvas_size(), _pm(), Path (+16 more)

### Community 80 - "Tests"
Cohesion: 0.13
Nodes (15): _make_client(), _open_project(), PreviewAnalysisStatusTests, TestClient, Tests for per-project preview-analysis job model (Parts 6, 7, 8, 11)., GET /api/bridge/status includes preview_analysis once a job has been created., Shot payload always includes preview_analysis_state., A brand-new shot with no preview file has preview_analysis_state='missing'. (+7 more)

### Community 81 - "Photoshop"
Cohesion: 0.16
Nodes (24): activateDocument(), closeDocumentInModal(), createCanvasDocumentInModal(), createCanvasForShot(), currentShotId(), currentShotRecord(), detectWorkItemFromDocumentByNameOnlyDeprecated(), findOpenDocumentForShot() (+16 more)

### Community 82 - "Photoshop"
Cohesion: 0.14
Nodes (24): activeShotId(), addShotToProject(), createEmptyShot(), ensureShotStructure(), focusStoryboardAfterPreviewExportIfEnabled(), getShotFolderEntry(), getShotPsdEntry(), maybeFocusStoryboardAfterPreviewExport() (+16 more)

### Community 83 - "Storyboard"
Cohesion: 0.14
Nodes (24): _animate(), _applyFollowCamera(), _cacheImportedMaterials(), _cameraMotionProbe(), _cameraMovesOverTime(), _collectAnimatedNodeNames(), _countImportedLights(), Fe() (+16 more)

### Community 84 - "Frontend"
Cohesion: 0.09
Nodes (22): compilerOptions, allowImportingTsExtensions, erasableSyntaxOnly, jsx, lib, module, moduleDetection, moduleResolution (+14 more)

### Community 85 - "Storyboard"
Cohesion: 0.21
Nodes (21): dispatch_tool(), handle_message(), _live_project_json(), main(), _parse_args(), _project(), Any, Namespace (+13 more)

### Community 86 - "Tests"
Cohesion: 0.15
Nodes (10): _make_client(), Path, TestClient, _quiet(), Storage compatibility boundary tests. Verifies the canonical vs legacy storage…, save_shots() must write both shots.json and shots.csv in one call., save_shots() must return the path to shots.json., save_shots must leave no .tmp file after a successful write. (+2 more)

### Community 87 - "Storyboard"
Cohesion: 0.18
Nodes (21): _analyse_uncached_previews(), _project_payload(), Any, Analyse previews that are missing from the cache and update it. Called by the…, _shot_payload(), _cache_file(), get_cached(), _key() (+13 more)

### Community 88 - "Tests"
Cohesion: 0.11
Nodes (9): board_background_filename(), _make_png(), _make_png_with_alpha(), Board asset model tests. Verifies that reference apply flows (image / video-…, Artwork saved AFTER the snapshot must not be clobbered by undo. The snapshot…, Returns a PNG with transparency — simulates an artwork export from Photoshop., TestCreateCanvasAssetOwnership, TestModelCaptureApply (+1 more)

### Community 89 - "Storyboard"
Cohesion: 0.16
Nodes (22): be(), c(), captureFrameDataUrl(), d(), f(), g(), h(), ie() (+14 more)

### Community 90 - "Frontend"
Cohesion: 0.17
Nodes (20): AppliedSegmentMarker, appliedSegmentTooltip(), fileName(), isShotAppliedToSegment(), mergeSpanRuns(), normalizePath(), ParsedSegment, parseSegmentRecord() (+12 more)

### Community 91 - "Frontend"
Cohesion: 0.10
Nodes (20): compilerOptions, allowImportingTsExtensions, erasableSyntaxOnly, lib, module, moduleDetection, moduleResolution, noEmit (+12 more)

### Community 92 - "Frontend"
Cohesion: 0.12
Nodes (12): createEmptyBlenderPlaybackState(), EmptyBlenderPlaybackState, stopWorkspaceMixer(), ThreeObject, WorkspaceImportedCamera, buildCameraSelectOptions(), buildOutlinerEntries(), populateCameraSelectDom() (+4 more)

### Community 93 - "Photoshop"
Cohesion: 0.20
Nodes (19): applySavedPaths(), createFileAtNativePath(), exportAndGoNextScene2D(), exportDrawingPreview(), exportPreviewInModal(), exportPreviewToFileInModal(), exportScene2DCompositeInModal(), exportScene2DCompositeToFileInModal() (+11 more)

### Community 94 - "Tests"
Cohesion: 0.18
Nodes (9): _get_main_window_state(), Best-effort desktop focus. Browser/dev mode is a clean no-op., Return the application-owned runtime window state, defaulting to 'normal'., EventTransitionModelTests, Simulate the event-handler closures; verify both state fields., Apply the desktop.py handler logic for the given event name., The 'restored' event fires when restore() is called during focus-restore.…, Full event sequence: maximized → minimized → restored event → maximized event. (+1 more)

### Community 95 - "Storyboard"
Cohesion: 0.11
Nodes (5): _normalize_upload_bytes(), BinaryIO, Path, Called by the frontend once the Welcome or Board UI has painted. Writes the…, _upload_stream()

### Community 96 - "Tests"
Cohesion: 0.16
Nodes (7): BridgeStatusResponse, PluginContextResponse, Contract fields returned by ``GET /api/bridge/status``. The live bridge payload…, Core contract fields returned by ``GET /api/plugin/context``., PhotoshopBridgeContractTests, Path, _quiet()

### Community 97 - "Storyboard"
Cohesion: 0.12
Nodes (20): A(), _buildDom(), clearBlenderScene(), clearObjects(), _clearWireframeOverlays(), constructor(), dispose(), _disposePreviewMaterials() (+12 more)

### Community 98 - "Tests"
Cohesion: 0.10
Nodes (7): CacheStartupIntegrationTests, CacheUnitTests, Tests for the preview analysis cache (preview_analysis_cache.py)., save_cache writes to a unique sibling temp file then replaces — no stale .tmp…, Two concurrent saves use different temp names — fixed .tmp collisions are…, set_cached on a missing file must not raise., With no cache, project payload returns provisional values (True/False) without…

### Community 99 - "Frontend"
Cohesion: 0.23
Nodes (17): AnimaticOptions, exportAnimatic(), exportContactSheet(), exportImageSequence(), exportPdf(), ExportResult, ExportScope, exportShotList() (+9 more)

### Community 100 - "Frontend"
Cohesion: 0.11
Nodes (18): app, security, windows, build, beforeBuildCommand, beforeDevCommand, devUrl, frontendDist (+10 more)

### Community 101 - "Storyboard"
Cohesion: 0.18
Nodes (18): _data_url(), dedupe(), describe(), _document_thumbnail(), _folder_thumbnail(), forget(), list_recents(), Any (+10 more)

### Community 102 - "Storyboard"
Cohesion: 0.16
Nodes (19): at(), ct(), deleteSelected(), focusSelected(), getCameraState(), goToAnimationStart(), _onKeyDown(), ot() (+11 more)

### Community 103 - "Tests"
Cohesion: 0.15
Nodes (11): BootstrapTests, _make_client(), TestClient, Tests for GET /api/app/bootstrap., Closing flushes the document and clears it from app state., Bootstrap always includes startup_timings with timing keys., Bootstrap with no open project and no session path returns project: null., If a project is already open, bootstrap returns it without re-opening. (+3 more)

### Community 104 - "Storyboard"
Cohesion: 0.14
Nodes (14): Collection, Material, Register Storyboarder's bundled Blender tools for this Blender session., create_camera_path(), _ensure_collection(), _ensure_green_material(), _point_segment_distance(), Object (+6 more)

### Community 105 - "Frontend"
Cohesion: 0.16
Nodes (15): Scene3dViewMode, MissingFilesPayload, OpenProjectRequest, SaveProjectAsRequest, ProjectSettings, ReferenceMediaType, RefSegmentSettings, RefSegmentVideoSettings (+7 more)

### Community 106 - "Storyboard"
Cohesion: 0.27
Nodes (17): persistent, _context_allows_write(), _current_blend_matches_context(), _export_preview(), _heartbeat(), _on_save_post(), _on_save_pre(), _parse_args() (+9 more)

### Community 107 - "Tests"
Cohesion: 0.32
Nodes (17): _png(), _png_bytes(), _project(), MonkeyPatch, Path, Shot, test_atomic_stream_failure_preserves_existing_target(), test_background_failure_preserves_previous_asset_and_cleans_temp() (+9 more)

### Community 108 - "Photoshop"
Cohesion: 0.12
Nodes (16): entrypoints, host, app, minVersion, icons, id, main, manifestVersion (+8 more)

### Community 109 - "Scripts"
Cohesion: 0.31
Nodes (16): check_frontend_build(), check_frontend_lint(), check_py_compile(), check_pytest_full(), check_pytest_smoke(), check_validate_migration(), _label(), main() (+8 more)

### Community 110 - "Tests"
Cohesion: 0.17
Nodes (8): project_blend_path(), Path, Resolve the active Scene3D .blend, falling back to the project template., _FakeBpyManager, Path, test_bpy_viewport_routes_proxy_frames_and_mark_camera_path_dirty(), test_project_blend_path_rejects_escape(), test_project_blend_path_uses_active_attached_blend()

### Community 111 - "Tests"
Cohesion: 0.26
Nodes (10): create_project(), _begin(), _isolated_bridge(), _Process, Path, test_built_in_viewport_refuses_to_start_while_external_blender_owns_scene(), test_external_blender_owns_until_process_and_heartbeat_end(), test_external_blender_session_id_is_cli_argument_safe() (+2 more)

### Community 112 - "Tests"
Cohesion: 0.21
Nodes (3): FocusEndpointTests, TestClient, Integration tests for POST /api/app/focus via TestClient.

### Community 113 - "Tests"
Cohesion: 0.40
Nodes (16): _close_client(), _layout2_client(), MonkeyPatch, parametrize, Path, TestClient, test_layout2_live_bridge_scrubs_legacy_and_focus_paths(), test_layout2_native_psd_reconnect_validates_canonical_role_and_hash() (+8 more)

### Community 114 - "Tests"
Cohesion: 0.15
Nodes (9): _make_client(), TestClient, Tests for POST /api/app/ui-ready., Token over 64 characters is rejected., Without a token the endpoint returns ok and marker_written=False., A valid UUID token causes the ready marker to be written., A token with path-traversal or unusual characters is rejected gracefully., The endpoint accepts no request body; the path comes from the env var only. (+1 more)

### Community 115 - "Photoshop"
Cohesion: 0.24
Nodes (12): asArray(), asNumber(), asObject(), assertStandaloneProjectWriteAllowed(), asString(), loadShotsJson(), normalizeShotRecord(), projectDataFromPayload() (+4 more)

### Community 116 - "Storyboard"
Cohesion: 0.19
Nodes (15): _configure_scene(), main(), _number(), _orbit_camera(), _parse_args(), Namespace, Object, Path (+7 more)

### Community 117 - "Storyboard"
Cohesion: 0.25
Nodes (15): board_label(), export_contact_sheet(), export_image_sequence(), export_shot_list_csv(), export_timing_json(), numbered_shots(), _placeholder_image(), Path (+7 more)

### Community 118 - "Storyboard"
Cohesion: 0.22
Nodes (15): atomic_copy_stream(), atomic_output_directory(), _atomic_write_bytes(), _PathSnapshot, BinaryIO, Path, quarantined_deletions(), Atomic file-copy helpers for cross-file transaction safety. All helpers write… (+7 more)

### Community 119 - "Spikes"
Cohesion: 0.22
Nodes (14): _configure_solid(), _ensure_visible_geometry(), main(), _open_blend(), _parse_args(), Path, Spike: can we render a SOLID-shaded viewport frame from a .blend headlessly,…, The bundled template renders empty (objects out of frame). Inject a… (+6 more)

### Community 120 - "Storyboard"
Cohesion: 0.26
Nodes (6): Event, Region, Context, Draw on the 3D cursor's horizontal plane to create a camera rig., STORYBOARDER_OT_draw_camera_path, STORYBOARDER_PT_camera_path

### Community 121 - "Spikes"
Cohesion: 0.21
Nodes (10): Handler, init_scene(), _inject_demo_geometry_if_empty(), main(), BaseHTTPRequestHandler, Path, Minimal bpy solid-frame render worker (route C, progressive frame streaming).…, The bundled template renders blank (objects out of frame). For a runnable demo,… (+2 more)

### Community 122 - "Storyboard"
Cohesion: 0.37
Nodes (13): check_export_exists(), export_animatic(), export_contact_sheet(), export_image_sequence(), export_pdf(), export_shot_list(), export_timing(), open_export() (+5 more)

### Community 123 - "Storyboard"
Cohesion: 0.20
Nodes (14): _addMeshFromSpec(), addObject(), _applyWireframeMode(), _generateBlenderObjectColor(), loadBlenderFromProject(), loadSceneData(), _normalizeWireframeMode(), nt() (+6 more)

### Community 124 - "Tests"
Cohesion: 0.25
Nodes (13): _app(), parametrize, CORS restriction, per-launch API token gate, and request-size rejection., test_cors_only_reflects_localhost(), test_cross_origin_post_without_token_does_not_mutate(), test_get_requests_do_not_require_token(), test_index_has_no_token_meta_when_unset(), test_index_injects_token_meta() (+5 more)

### Community 125 - "Frontend"
Cohesion: 0.29
Nodes (11): disposeGeometry(), disposeGlbObject(), disposeMaterial(), disposeObject3DNode(), disposeTextureValue(), ThreeObject, WireframeOverlayResources, disposeObject3DRoot() (+3 more)

### Community 126 - "Storyboard"
Cohesion: 0.24
Nodes (13): applyDisplaySettings(), _applyObjectColorPreview(), _applyTransformInputs(), _bindUi(), exportSceneData(), _prepareImportedMaterials(), _programLightingReason(), _scheduleSceneSettingsSave() (+5 more)

### Community 128 - "Frontend"
Cohesion: 0.20
Nodes (10): App, Box, Child, Error, main(), resolve_api_port(), SidecarGuard, Mutex (+2 more)

### Community 129 - "Photoshop"
Cohesion: 0.29
Nodes (9): collectBoardBackgroundLayers(), collectExportHiddenLayers(), findBackgroundLayer(), hasDrawingLayer(), isBoardBackgroundLayer(), isCanvasBackgroundLayer(), isManagedLayer(), isOverlayLayer() (+1 more)

### Community 130 - "Storyboard"
Cohesion: 0.23
Nodes (11): _board_number(), describe(), filename_suffix(), is_contiguous(), parse(), Board range specs for exports — the "Pages: 1-5, 8, 11-13" field. Boards are…, Resolve a range spec to ascending, de-duplicated 0-based board indexes. Accepts…, Name an export after the boards in it, so ranges never overwrite each other.… (+3 more)

### Community 131 - "Tests"
Cohesion: 0.41
Nodes (11): create_layout2_document(), Atomically create a portable Layout 2 folder project., MonkeyPatch, Path, test_create_layout2_document_accepts_a_name_without_suffix(), test_create_layout2_document_cleans_failed_staging(), test_create_layout2_document_honors_feature_gate(), test_create_layout2_document_publishes_portable_folder() (+3 more)

### Community 132 - "Tests"
Cohesion: 0.26
Nodes (3): Unit test the internal helper directly (simulates video-frame apply)., If compose raises mid-write, the previous background must not be corrupted., TestApplyReferenceFrameToShot

### Community 133 - "Tests"
Cohesion: 0.23
Nodes (6): Verify that the backend never modifies the in-PSD SB bg layer. The Photoshop…, sync_psd_board_background must return False — it is a deliberate no-op. The…, sync_psd_board_background must not modify the PSD file on disk. The plugin owns…, sync_psd_board_background must not create a PSD when none exists., sync_psd_board_background must not change any Shot metadata fields., TestSyncPsdBoardBackgroundNoOp

### Community 135 - "Frontend"
Cohesion: 0.33
Nodes (9): captureCanvasPng(), CaptureCanvasPngOptions, isBlankCanvas(), Scene3dCaptureOptions, Scene3dCaptureResult, captureRendererPng(), CaptureRendererPngOptions, ThreeModule (+1 more)

### Community 136 - "Storyboard"
Cohesion: 0.40
Nodes (10): KeepTogether, _camera_summary(), _escape(), export_storyboard_pdf(), _image_flowable(), Path, Shot, _shot_block() (+2 more)

### Community 137 - "Photoshop"
Cohesion: 0.22
Nodes (11): bridgeUrlsFromLive(), cacheBridgeEndpoints(), detectWorkItemFromDocument(), fetchLiveBridgeHttp(), getOpenShotIds(), getOpenWorkKeys(), pollStoryboardBridge(), reconnectStoryboardBridge() (+3 more)

### Community 138 - "Storyboard"
Cohesion: 0.35
Nodes (10): _draw_caption(), _encode_cv2(), _encode_ffmpeg(), export_animatic(), _normalize_frame(), Image, Path, Shot (+2 more)

### Community 139 - "Storyboard"
Cohesion: 0.33
Nodes (8): ImageDraw, _bg_color(), _lerp(), main(), Image, Generate raster app icons from the startup film-strip design., render_icon(), _rounded_rect()

### Community 141 - "Frontend"
Cohesion: 0.25
Nodes (7): description, identifier, permissions, $schema, windows, core:default, main

### Community 142 - "Tests"
Cohesion: 0.25
Nodes (3): When artwork preview exists and is non-solid, thumbnail should exist., When no artwork preview exists, thumbnail falls back to the background plate., TestRefreshThumbnail

### Community 144 - "Tests"
Cohesion: 0.33
Nodes (6): fixture, Path, Shared pytest setup. Opening or creating a `.sbd` expands it into a private…, Delete work trees the run created, keeping ones that predate it. Session-scoped…, _remove_test_working_roots(), _working_roots()

### Community 145 - "Tests"
Cohesion: 0.29
Nodes (4): skipUnless, DevRequirementsTests, InternalDesktopServerTests, Internal desktop server integration tests via Playwright headless Chromium.…

### Community 146 - "Storyboard"
Cohesion: 0.48
Nodes (6): main(), _pick_file(), _pick_folder(), Run native file/folder pickers in a standalone process (main thread)., _safe_initial_dir(), _save_project()

### Community 147 - "Storyboard"
Cohesion: 0.29
Nodes (7): _has_unflushed_work(), _process_is_running(), True when a process with this id exists. Errs toward True., True when the tree holds edits the document does not — i.e. do not delete.…, Reclaim work trees left by crashed or killed sessions. Conservative by design —…, _read_session_marker(), sweep_orphaned_working_roots()

### Community 148 - "Storyboard"
Cohesion: 0.62
Nodes (6): _extract_frame_ffmpeg(), extract_video_frame_to_png(), get_video_duration(), _probe_duration_ffmpeg(), Path, _read_frame_cv2()

### Community 149 - "Tests"
Cohesion: 0.52
Nodes (6): _project_with_boards(), Path, test_animatic_export_endpoint(), test_export_animatic_produces_nonempty_mp4(), test_export_animatic_rejects_empty_project(), test_open_export_missing_returns_404()

### Community 150 - "Scripts"
Cohesion: 0.53
Nodes (5): check_desktop_shell(), check_routes(), check_static_tree(), main(), Verify the desktop shell has no browser-mode artifacts.

### Community 151 - "Storyboard"
Cohesion: 0.40
Nodes (5): BpyCameraPathRequest, BaseModel, FastAPI, FastAPI boundary for the managed built-in Blender viewport., register_bpy_viewport_routes()

### Community 156 - "Tests"
Cohesion: 0.60
Nodes (5): _client_with_shots(), Path, TestClient, test_batch_mutations_validate_all_shots_before_changing_any(), test_batch_update_delete_restore_and_queue()

### Community 157 - "Storyboard"
Cohesion: 0.40
Nodes (5): RefSegment3dCapture, Request, _model_captures_payload(), _plugin_protocol_headers(), Any

### Community 158 - "Storyboard"
Cohesion: 0.70
Nodes (4): _backup_filenames(), _backup_stamps(), _prune_old_backups(), _write_backup()

### Community 159 - "Storyboard"
Cohesion: 0.50
Nodes (4): FileResponse, HTMLResponse, Path, _react_index_response()

### Community 160 - "Storyboard"
Cohesion: 0.50
Nodes (3): Layout2SaveAsError, RuntimeError, A failed stage, including its recoverable staging path when retained.

## Knowledge Gaps
- **216 isolated node(s):** `name`, `private`, `version`, `type`, `dev` (+211 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **19 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Project` connect `Tests` to `Storyboard`, `Tests`, `Tests`, `Storyboard`, `Storyboard`, `Storyboard`, `Storyboard`, `Tests`, `Storyboard`, `Tests`, `Tests`, `Storyboard`, `Tests`, `Tests`, `Tests`, `Tests`, `Tests`, `Tests`, `Tests`, `Storyboard`, `Tests`, `Storyboard`, `Tests`, `Storyboard`, `Tests`, `Storyboard`, `Tests`, `Storyboard`, `Tests`, `Tests`, `Tests`, `Tests`, `Storyboard`, `Tests`, `Storyboard`, `Tests`, `Tests`, `Tests`, `Storyboard`, `Storyboard`, `Tests`, `Storyboard`, `Tests`, `Storyboard`, `Storyboard`, `Tests`, `Tests`, `Tests`, `Tests`, `Tests`, `Storyboard`, `Storyboard`?**
  _High betweenness centrality (0.133) - this node is a cross-community bridge._
- **Why does `Shot` connect `Tests` to `Tests`, `Tests`, `Tests`, `Storyboard`, `Storyboard`, `Storyboard`, `Storyboard`, `Storyboard`, `Tests`, `Storyboard`, `Tests`, `Tests`, `Tests`, `Tests`, `Tests`, `Tests`, `Tests`, `Tests`, `Storyboard`, `Storyboard`, `Tests`, `Storyboard`, `Tests`, `Tests`, `Tests`, `Tests`, `Tests`, `Storyboard`, `Storyboard`, `Tests`, `Tests`, `Storyboard`, `Tests`, `Tests`, `Tests`, `Tests`, `Storyboard`?**
  _High betweenness centrality (0.035) - this node is a cross-community bridge._
- **Why does `StoryboardBackendService` connect `Storyboard` to `Tests`, `Tests`, `Storyboard`, `Storyboard`, `Tests`, `Storyboard`, `Tests`, `Storyboard`, `Tests`, `Storyboard`, `Storyboard`, `Tests`, `Tests`, `Storyboard`?**
  _High betweenness centrality (0.032) - this node is a cross-community bridge._
- **Are the 65 inferred relationships involving `Project` (e.g. with `ProjectTransitionError` and `BpyViewportError`) actually correct?**
  _`Project` has 65 INFERRED edges - model-reasoned connections that need verification._
- **Are the 5 inferred relationships involving `StoryboardBackendService` (e.g. with `AppErrorCode` and `PluginBridgeService`) actually correct?**
  _`StoryboardBackendService` has 5 INFERRED edges - model-reasoned connections that need verification._
- **Are the 62 inferred relationships involving `Shot` (e.g. with `ProjectTransitionError` and `PluginBridgeService`) actually correct?**
  _`Shot` has 62 INFERRED edges - model-reasoned connections that need verification._
- **What connects `name`, `private`, `version` to the rest of the system?**
  _216 weakly-connected nodes found - possible documentation gaps or missing edges._