// Preview export and post-save project update helpers.
// Includes both shot-mode (transparent foreground) and Scene 2D (composite) export.
//
// Depends on: layer_roles.js, layer_sync.js, backend_client.js (loaded first).
// Runtime deps on panel.js globals: activeShotId, ensureShotStructure,
//   getShotPsdEntry, runModal, setStatus, saveProjectJson, currentShotId,
//   fileUnixMtime, writeEntryText, linkedFromStoryboard, projectData,
//   canvasColor, canvasWidth, canvasHeight, projectRoot.

async function exportPreviewInModal(folder, shotId) {
  const doc = app.activeDocument;
  // Export only the artist's strokes on transparency. Hide the canvas-color fill
  // (Background), the board background reference (SB bg), and onion-skin overlays
  // (SB ref:) — Storyboard Tool paints the canvas color behind the PNG in-app.
  const previousActiveIds = captureActiveLayerIds(doc);
  const hiddenLayers = [];
  for (const layer of collectExportHiddenLayers(doc)) {
    if (layer.visible) {
      await setLayerVisibilityInModal(layer, false);
      hiddenLayers.push(layer);
    }
  }
  try {
    const file = await folder.createFile(`${shotId}_preview.png`, { overwrite: true });
    await app.activeDocument.saveAs.png(file, {}, true);
    return file;
  } finally {
    for (const layer of hiddenLayers) {
      await setLayerVisibilityInModal(layer, true);
    }
    restoreActiveLayersByIds(doc, previousActiveIds);
  }
}

async function exportDrawingPreview() {
  // Export drawing preview for Storyboard Tool only. PSD is saved by the artist
  // with Photoshop's native Ctrl+S — UXP saveAs.psd overwrite often corrupts files.
  const shotId = activeShotId();
  const ctx = typeof activeWorkContext === "function" ? activeWorkContext() : null;
  if (linkedFromStoryboard && ctx?.kind === "shot" && ctx.shot_id && ctx.shot_id !== shotId) {
    throw new Error("The active Photoshop document does not match the selected shot.");
  }
  setSelectedShotId(shotId);
  const folder = await ensureShotStructure(shotId);
  await runModal("Export drawing", async () => {
    await exportPreviewInModal(folder, shotId);
  });
  return shotId;
}

function setSaveButtonsBusy(busy) {
  const stayBtn = document.getElementById("saveAndStay");
  const nextBtn = document.getElementById("saveAndNext");
  if (stayBtn) stayBtn.disabled = busy;
  if (nextBtn) nextBtn.disabled = busy;
}

let _isSaving = false;

async function saveCurrentShotGuarded() {
  if (_isSaving) return;
  _isSaving = true;
  setSaveButtonsBusy(true);
  try {
    await saveCurrentShot();
  } finally {
    _isSaving = false;
    setSaveButtonsBusy(false);
  }
}

async function saveAndGoNextGuarded() {
  if (_isSaving) return;
  _isSaving = true;
  setSaveButtonsBusy(true);
  try {
    await saveAndGoNext();
  } finally {
    _isSaving = false;
    setSaveButtonsBusy(false);
  }
}

async function saveCurrentShot() {
  const shotId = await exportDrawingPreview();
  await updateProjectAfterSave(shotId);
  if (typeof focusStoryboardAfterPreviewExportIfEnabled === "function") {
    focusStoryboardAfterPreviewExportIfEnabled();
  }
  setStatus(
    `Preview exported for ${shotId}. Press Ctrl+S in Photoshop to save the PSD.`,
  );
}

async function updateProjectAfterSave(shotId = currentShotId(), folder = null) {
  const resolvedFolder = folder || (await ensureShotStructure(shotId));
  const psdFile = await getShotPsdEntry(resolvedFolder, shotId);
  let previewFile = null;
  try {
    previewFile = await resolvedFolder.getEntry(`${shotId}_preview.png`);
  } catch {
    previewFile = null;
  }
  if (psdFile) {
    await writeBridgeFiles(shotId, `shots/${shotId}/${shotId}.psd`, resolvedFolder);
  }
  if (linkedFromStoryboard) {
    const payload = await requestStoryboardApi(`/api/plugin/shots/${encodeURIComponent(shotId)}/export-preview`, {
      method: "POST",
      body: JSON.stringify({
        source_file_path: psdFile ? `shots/${shotId}/${shotId}.psd` : "",
        preview_image_path: previewFile ? `shots/${shotId}/${shotId}_preview.png` : "",
      }),
    });
    if (payload?.context) {
      applyPluginContext(payload.context);
    } else {
      await refreshProjectDataFromBackend();
    }
    return;
  }
  let mtime = 0;
  if (previewFile) {
    mtime = Math.max(mtime, await fileUnixMtime(previewFile));
  }
  if (psdFile) {
    mtime = Math.max(mtime, await fileUnixMtime(psdFile));
  }
  if (!mtime) {
    mtime = Date.now() / 1000;
  }
  if (projectData) {
    const shot = (projectData.shots || []).find((item) => item.shot_id === shotId);
    if (shot) {
      const previous = Number(shot.source_sync_mtime || 0);
      if (mtime <= previous) {
        mtime = previous + 0.001;
      }
      applySavedPaths(shot, shotId, mtime, Boolean(psdFile));
      await saveProjectJson();
    }
  }
  await requestShotSync(shotId, true);
}

// ── Scene 2D export (Part 9) ──────────────────────────────────────────────
// Unlike shot export, Scene 2D preserves ALL user layers (background, artwork,
// any reference). Only plugin-owned overlay layers (SB ref:) are hidden.

async function exportScene2DCompositeInModal(folder, perspectiveId) {
  const doc = app.activeDocument;
  const previousActiveIds = captureActiveLayerIds(doc);
  const hiddenLayers = [];
  // Only hide plugin overlay layers (SB ref:) — keep background and user layers
  for (const layer of doc.layers) {
    const name = String(layer.name || "");
    if (name.startsWith("SB ref:") && layer.visible) {
      await setLayerVisibilityInModal(layer, false);
      hiddenLayers.push(layer);
    }
  }
  try {
    const file = await folder.createFile(`preview.png`, { overwrite: true });
    await app.activeDocument.saveAs.png(file, {}, true);
    return file;
  } finally {
    for (const layer of hiddenLayers) {
      await setLayerVisibilityInModal(layer, true);
    }
    restoreActiveLayersByIds(doc, previousActiveIds);
  }
}

async function exportScene2DPerspectivePreview() {
  const ctx = activeScene2DContext();
  if (!ctx) {
    throw new Error("No active Scene 2D perspective. Open one from Storyboarder first.");
  }
  if (ctx.perspective_type === "image") {
    throw new Error("Image perspectives are read-only. Convert to PSD in Storyboarder to edit.");
  }
  if (!app.activeDocument) {
    throw new Error("No active Photoshop document.");
  }
  const activePath = await documentNativePath(app.activeDocument);
  if (!activePath || !sameNativePath(activePath, ctx.source_native_path)) {
    throw new Error(
      "The active Photoshop document does not match this Scene 2D Perspective. Activate the correct source.psd tab before exporting.",
    );
  }
  const { scene_id, perspective_id } = ctx;

  // Resolve the perspective folder via UXP filesystem
  const perspFolder = await resolvePerspectiveFolder(scene_id, perspective_id);
  if (!perspFolder) {
    throw new Error("Could not resolve the perspective folder. Is the project folder accessible?");
  }

  await runModal("Export Scene 2D preview", async () => {
    await exportScene2DCompositeInModal(perspFolder, perspective_id);
  });

  if (!linkedFromStoryboard) {
    setStatus(`Preview exported for ${scene_id}/${perspective_id}.`);
    return;
  }

  const payload = await requestStoryboardApi(
    `/api/plugin/scenes2d/${encodeURIComponent(scene_id)}/perspectives/${encodeURIComponent(perspective_id)}/export-preview`,
    { method: "POST" }
  );
  if (payload?.work_context) {
    applyWorkContext(payload.work_context);
  }
  await refreshProjectDataFromBackend();
  setStatus(`Scene 2D preview exported.`);

  if (typeof focusStoryboardAfterPreviewExportIfEnabled === "function") {
    focusStoryboardAfterPreviewExportIfEnabled();
  }
}

async function resolvePerspectiveFolder(sceneId, perspectiveId) {
  if (!projectRoot) return null;
  try {
    const scenes2dDir = await projectRoot.getEntry("scenes2d");
    const sceneDir = await scenes2dDir.getEntry(sceneId);
    const perspectivesDir = await sceneDir.getEntry("perspectives");
    try {
      return await perspectivesDir.getEntry(perspectiveId);
    } catch {
      return await perspectivesDir.createFolder(perspectiveId);
    }
  } catch {
    return null;
  }
}

let _isScene2DSaving = false;

async function saveScene2DGuarded() {
  if (_isScene2DSaving) return;
  _isScene2DSaving = true;
  const stayBtn = document.getElementById("scene2dSaveAndStay");
  const nextBtn = document.getElementById("scene2dSaveAndNext");
  if (stayBtn) stayBtn.disabled = true;
  if (nextBtn) nextBtn.disabled = true;
  try {
    await exportScene2DPerspectivePreview();
  } finally {
    _isScene2DSaving = false;
    if (stayBtn) stayBtn.disabled = false;
    if (nextBtn) nextBtn.disabled = false;
  }
}

async function saveAndGoNextScene2DGuarded() {
  if (_isScene2DSaving) return;
  _isScene2DSaving = true;
  const stayBtn = document.getElementById("scene2dSaveAndStay");
  const nextBtn = document.getElementById("scene2dSaveAndNext");
  if (stayBtn) stayBtn.disabled = true;
  if (nextBtn) nextBtn.disabled = true;
  try {
    await exportAndGoNextScene2D();
  } finally {
    _isScene2DSaving = false;
    if (stayBtn) stayBtn.disabled = false;
    if (nextBtn) nextBtn.disabled = false;
  }
}

async function exportAndGoNextScene2D() {
  const ctx = activeScene2DContext();
  if (!ctx) throw new Error("No active Scene 2D perspective.");

  // Step 1: export current perspective
  await exportScene2DPerspectivePreview();

  // Step 2: ask backend for next perspective
  const { scene_id, perspective_id } = ctx;
  const payload = await requestStoryboardApi(
    `/api/plugin/scenes2d/${encodeURIComponent(scene_id)}/perspectives/${encodeURIComponent(perspective_id)}/next-perspective`,
    { method: "POST" }
  );

  if (payload?.at_end || !payload?.next_perspective) {
    setStatus("Last perspective in this scene.");
    return;
  }

  const next = payload.next_perspective;
  // Step 3: open or focus the next PSD perspective
  const opened = await requestStoryboardApi(
    `/api/project/scenes2d/${encodeURIComponent(scene_id)}/perspectives/${encodeURIComponent(next.id)}/open`,
    { method: "POST" }
  );
  if (opened?.work_context) {
    applyWorkContext(opened.work_context);
  }
  setStatus(`Moved to next perspective: ${next.title || next.id}`);
}

function applySavedPaths(shot, shotId, mtime, hasPsd = true) {
  if (hasPsd) {
    shot.source_file_path = `shots/${shotId}/${shotId}.psd`;
  }
  shot.preview_image_path = `shots/${shotId}/${shotId}_preview.png`;
  shot.image_path = shot.preview_image_path;
  shot.thumbnail_path = `shots/${shotId}/${shotId}_thumb.png`;
  shot.source_sync_mtime = mtime;
}

async function writeBridgeFiles(shotId, sourcePath, folder = null) {
  const resolvedFolder = folder || (await ensureShotStructure(shotId));
  const payload = {
    canvas_background_color: canvasColor,
    canvas_width: canvasWidth,
    canvas_height: canvasHeight,
    shot_id: shotId,
    source_file_path: sourcePath,
    last_saved_at: new Date().toISOString(),
  };
  await writeEntryText(
    await resolvedFolder.createFile("storyboard_bridge.json", { overwrite: true }),
    JSON.stringify(payload, null, 2),
  );
  await writeEntryText(await resolvedFolder.createFile("canvas_color.txt", { overwrite: true }), `${canvasColor}\n`);
  if (projectRoot) {
    await writeEntryText(
      await projectRoot.createFile("storyboard_bridge.json", { overwrite: true }),
      JSON.stringify(payload, null, 2),
    );
    await writeEntryText(
      await projectRoot.createFile("canvas_color.txt", { overwrite: true }),
      `${canvasColor}\n`,
    );
  }
}
