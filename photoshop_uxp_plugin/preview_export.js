// Preview export and post-save project update helpers.
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
  setSelectedShotId(shotId);
  const folder = await ensureShotStructure(shotId);
  await runModal("Export drawing", async () => {
    await exportPreviewInModal(folder, shotId);
  });
  return shotId;
}

async function saveCurrentShot() {
  const shotId = await exportDrawingPreview();
  await updateProjectAfterSave(shotId);
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
