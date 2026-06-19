// Layer operation helpers: placement, linked smart-object management, board
// background sync, and template layer setup. All functions here issue
// Photoshop batchPlay calls or use the UXP layer DOM — they must be called
// inside executeAsModal (runModal) where noted.
//
// Depends on: layer_roles.js (loaded first via index.html).
// Runtime deps on panel.js globals: getShotFolderEntry, boardBackgroundSigByShot,
//   detectShotFromDocument, setStatus, runModal.

function captureActiveLayerIds(doc) {
  try {
    return (doc?.activeLayers || []).map((layer) => layer.id);
  } catch {
    return [];
  }
}

function restoreActiveLayersByIds(doc, ids) {
  if (!doc || !ids?.length) {
    return;
  }
  const byId = new Map();
  const walk = (layers) => {
    for (const layer of layers || []) {
      byId.set(layer.id, layer);
      if (layer.layers?.length) {
        walk(layer.layers);
      }
    }
  };
  walk(doc.layers);
  const layers = ids.map((id) => byId.get(id)).filter(Boolean);
  if (layers.length) {
    try {
      doc.activeLayers = layers;
    } catch {
      // Selection restore is best-effort.
    }
  }
}

async function createNamedLayerAtTopInModal(doc, name) {
  await photoshop.action.batchPlay(
    [
      {
        _obj: "make",
        _target: [{ _ref: "layer" }],
      },
    ],
    { synchronousExecution: true },
  );
  await renameActiveLayer(name);
  const layer = app.activeDocument.activeLayers[0] || null;
  if (layer) {
    await layer.move(doc, photoshop.constants.ElementPlacement.PLACEATBEGINNING);
  }
  return layer;
}

async function ensureLayerTemplateInModal(doc) {
  if (!doc) {
    return [];
  }
  const created = [];
  for (const name of [...TEMPLATE_LAYER_NAMES].reverse()) {
    if (!findLayerByName(doc, name)) {
      const layer = await createNamedLayerAtTopInModal(doc, name);
      if (layer) {
        created.push(layer);
      }
    }
  }
  const rough = findLayerByName(doc, "Rough") || created[created.length - 1] || null;
  if (rough) {
    app.activeDocument.activeLayers = [rough];
  }
  return created;
}

async function ensureDrawingLayerInModal(doc) {
  const created = await ensureLayerTemplateInModal(doc);
  if (created.length) {
    return created[created.length - 1];
  }
  if (!doc || hasDrawingLayer(doc)) {
    return null;
  }
  return createNamedLayerAtTopInModal(doc, DRAWING_LAYER_NAME);
}

async function ensureTemplateLayersForActiveDocument() {
  if (!app.activeDocument) {
    throw new Error("Open a shot canvas first.");
  }
  let createdCount = 0;
  await runModal("Ensure template layers", async () => {
    const created = await ensureLayerTemplateInModal(app.activeDocument);
    createdCount = created.length;
  });
  setStatus(
    createdCount
      ? `Created ${createdCount} missing template layer(s).`
      : "Template layers already exist.",
  );
}

async function deleteLayersInModal(layers) {
  for (const layer of layers) {
    try {
      await layer.delete();
    } catch {
      try {
        await photoshop.action.batchPlay(
          [
            {
              _obj: "delete",
              _target: [{ _ref: "layer", _id: layer.id }],
            },
          ],
          { synchronousExecution: true },
        );
      } catch {
        // Skip layers that Photoshop refuses to delete.
      }
    }
  }
}

async function clearOverlayLayersInModal(doc) {
  const overlayLayers = collectOverlayLayers(doc.layers);
  if (overlayLayers.length) {
    await deleteLayersInModal(overlayLayers);
  }
}

async function renameActiveLayer(name) {
  await photoshop.action.batchPlay(
    [
      {
        _obj: "set",
        _target: [{ _ref: "layer", _enum: "ordinal", _value: "targetEnum" }],
        to: { _obj: "layer", name },
      },
    ],
    { synchronousExecution: true },
  );
}

async function setActiveLayerOpacity(percent) {
  await photoshop.action.batchPlay(
    [
      {
        _obj: "set",
        _target: [{ _ref: "layer", _enum: "ordinal", _value: "targetEnum" }],
        to: {
          _obj: "layer",
          opacity: { _unit: "percentUnit", _value: percent },
        },
      },
    ],
    { synchronousExecution: true },
  );
}

async function placeFileEntryAsLayer(entry) {
  const token = await fs.createSessionToken(entry);
  await photoshop.action.batchPlay(
    [
      {
        _obj: "placeEvent",
        null: { _path: token, _kind: "local" },
        linked: false,
        freeTransformCenterState: { _enum: "quadCenterState", _value: "QCSAverage" },
      },
    ],
    { synchronousExecution: true },
  );
  return app.activeDocument.activeLayers[0];
}

async function placeFileEntryAsLinkedLayer(entry) {
  const token = await fs.createSessionToken(entry);
  // Place as a LINKED smart object. Photoshop resolves the session token to the
  // entry's REAL absolute path at place-time and bakes THAT path into the PSD's
  // linked-SO record (not the ephemeral token), so the link survives close+reopen
  // as long as the source stays at `<shot>/<shot>_background.png` (a permanent
  // location). `linked: true` is the ONE key that distinguishes linked from
  // embedded — the old `Lnkd: true` was a redundant alias of the same typeID, and
  // the placedLayerConvertToLinked/relink fallbacks only masked failures, so both
  // are gone. Verification now happens via readSmartObjectLinkInfo after placing.
  await photoshop.action.batchPlay(
    [
      {
        _obj: "placeEvent",
        ID: 1,
        null: { _path: token, _kind: "local" },
        linked: true,
        freeTransformCenterState: { _enum: "quadCenterState", _value: "QCSAverage" },
        offset: {
          _obj: "offset",
          horizontal: { _unit: "pixelsUnit", _value: 0 },
          vertical: { _unit: "pixelsUnit", _value: 0 },
        },
      },
    ],
    { synchronousExecution: true },
  );
  return app.activeDocument.activeLayers[0];
}

// Read a layer's smart-object link state via batchPlay (the UXP DOM exposes no
// smart-object link API). Returns the GROUND TRUTH of what Photoshop actually
// stored, so the plugin can report it instead of silently shipping a broken link.
async function readSmartObjectLinkInfo(layer) {
  const empty = { isSmartObject: false, linked: false, linkMissing: false, linkPath: "" };
  if (!app.activeDocument || !layer) {
    return empty;
  }
  try {
    const [result] = await photoshop.action.batchPlay(
      [
        {
          _obj: "get",
          _target: [
            { _property: "smartObject" },
            { _ref: "layer", _id: layer.id },
          ],
        },
      ],
      { synchronousExecution: true },
    );
    const so = result && result.smartObject;
    if (!so) {
      return empty;
    }
    let linkPath = "";
    try {
      // Broken links sometimes omit `link` entirely — gate truth on linkMissing,
      // never on the presence of `link`.
      if (so.link && so.link._path) {
        linkPath = String(so.link._path);
      }
    } catch {
      // `link` absent/unreadable on a broken link.
    }
    return {
      isSmartObject: true,
      linked: Boolean(so.linked),
      linkMissing: Boolean(so.linkMissing),
      linkPath,
    };
  } catch {
    // `get smartObject` rejects when the layer is not a smart object at all.
    return empty;
  }
}

// Surface the real link state of the `SB bg` layer to the status line + console so
// the artist (and we) can SEE whether linking actually took, instead of guessing.
async function reportBoardBackgroundLinkStatus(layer) {
  const info = await readSmartObjectLinkInfo(layer);
  if (!info.isSmartObject) {
    setStatus("⚠ SB bg is not a smart object (raster/embedded) — NOT linked.");
  } else if (!info.linked) {
    setStatus("⚠ SB bg placed as EMBEDDED, not linked.");
  } else if (info.linkMissing) {
    setStatus("⚠ SB bg link is MISSING/broken — check the background file path.");
  } else {
    setStatus(`SB bg linked → ${info.linkPath || "(linked, path hidden)"}`);
  }
  console.log("[SB bg] link status", info);
  return info;
}

// Relink an EXISTING placed smart-object layer to `entry`. Only works when the
// layer is already a smart object; a raster `SB bg` (e.g. baked by an older backend
// build) cannot be relinked, so we return false and let the caller delete + re-place
// it as a fresh linked smart object.
async function relinkLayerToEntry(entry, layer) {
  const doc = app.activeDocument;
  if (!doc || !entry || !layer) {
    return false;
  }
  const before = await readSmartObjectLinkInfo(layer);
  if (!before.isSmartObject) {
    return false;
  }
  const previousActiveIds = captureActiveLayerIds(doc);
  const token = await fs.createSessionToken(entry);
  try {
    doc.activeLayers = [layer];
    await photoshop.action.batchPlay(
      [
        {
          _obj: "placedLayerRelinkToFile",
          layerID: layer.id,
          null: { _path: token, _kind: "local" },
        },
      ],
      { synchronousExecution: true },
    );
  } catch {
    return false;
  } finally {
    restoreActiveLayersByIds(doc, previousActiveIds);
  }
  const after = await readSmartObjectLinkInfo(layer);
  return after.isSmartObject && after.linked && !after.linkMissing;
}

function layerPixelSize(layer) {
  const bounds = layer?.bounds;
  if (!bounds) {
    return { width: 0, height: 0, left: 0, top: 0 };
  }
  return {
    width: bounds.right - bounds.left,
    height: bounds.bottom - bounds.top,
    left: bounds.left,
    top: bounds.top,
  };
}

async function fitLayerToDocumentInModal(layer) {
  const doc = app.activeDocument;
  if (!doc || !layer) {
    return;
  }
  doc.activeLayers = [layer];
  const docWidth = doc.width;
  const docHeight = doc.height;
  const initial = layerPixelSize(layer);
  if (initial.width <= 0 || initial.height <= 0) {
    return;
  }
  const scale = Math.min(docWidth / initial.width, docHeight / initial.height) * 100;
  if (Math.abs(scale - 100) > 0.01) {
    await layer.scale(scale, scale, photoshop.constants.AnchorPosition.TOPLEFT);
  }
  const fitted = layerPixelSize(layer);
  const dx = (docWidth - fitted.width) / 2 - fitted.left;
  const dy = (docHeight - fitted.height) / 2 - fitted.top;
  if (Math.abs(dx) > 0.01 || Math.abs(dy) > 0.01) {
    await layer.translate(dx, dy);
  }
}

async function resolveBoardBackgroundEntry(shotId) {
  const folder = await getShotFolderEntry(shotId);
  // The board background (`SB bg`) reference is ONLY the dedicated background
  // file. Never fall back to the shot's preview — that preview is the artist's
  // own drawing, and importing it as `SB bg` would duplicate the drawing as a
  // reference layer (and resurrect it after the reference is deleted).
  try {
    return await folder.getEntry(`${shotId}_background.png`);
  } catch {
    return null;
  }
}

function findBoardBackgroundLayer(doc) {
  for (const layer of doc.layers || []) {
    if (isBoardBackgroundLayer(layer)) {
      return layer;
    }
  }
  return null;
}

async function removeBoardBackgroundLayerInModal(doc) {
  const layers = collectBoardBackgroundLayers(doc.layers);
  if (layers.length) {
    await deleteLayersInModal(layers);
  }
}

async function setLayerVisibilityInModal(layer, visible) {
  if (!layer) {
    return;
  }
  app.activeDocument.activeLayers = [layer];
  await photoshop.action.batchPlay(
    [
      {
        _obj: "set",
        _target: [{ _ref: "layer", _enum: "ordinal", _value: "targetEnum" }],
        to: {
          _obj: "layer",
          visible: visible,
        },
      },
    ],
    { synchronousExecution: true },
  );
}

// Single source of truth for the `SB bg` reference position: directly above the
// canvas-colour base (`Background`), and therefore below the artwork. Callers
// invoke this instead of moving `SB bg` themselves.
async function ensureBoardBackgroundStackOrderInModal(doc) {
  const background = findBackgroundLayer(doc);
  const sbBg = findBoardBackgroundLayer(doc);
  if (!sbBg) {
    return;
  }
  if (background) {
    await sbBg.move(background, photoshop.constants.ElementPlacement.PLACEBEFORE);
  } else {
    await sbBg.move(doc, photoshop.constants.ElementPlacement.PLACEATEND);
  }
}

async function updateLinkedSmartObjectInModal(layer) {
  const doc = app.activeDocument;
  if (!doc || !layer) {
    return false;
  }
  const previousActiveIds = captureActiveLayerIds(doc);
  try {
    doc.activeLayers = [layer];
    try {
      await photoshop.action.batchPlay(
        [{ _obj: "placedLayerUpdateModified" }],
        { synchronousExecution: true },
      );
      return true;
    } catch {
      await photoshop.action.batchPlay(
        [{ _obj: "placedLayerUpdateAllModified" }],
        { synchronousExecution: true },
      );
      return true;
    }
  } catch {
    return false;
  } finally {
    restoreActiveLayersByIds(doc, previousActiveIds);
  }
}

async function finalizeRecoveredShotInModal(shotId) {
  const doc = app.activeDocument;
  if (!doc) {
    return;
  }
  await syncBoardBackgroundFromDisk(shotId, true);
  await ensureBoardBackgroundStackOrderInModal(doc);
  await ensureDrawingLayerInModal(doc);
}

async function importBoardBackgroundInModal(shotId, entry = null, options = {}) {
  const resolvedEntry = entry || (await resolveBoardBackgroundEntry(shotId));
  if (!resolvedEntry) {
    return false;
  }
  const doc = app.activeDocument;
  if (!doc) {
    throw new Error("No active Photoshop document.");
  }

  const previousActiveIds = captureActiveLayerIds(doc);
  const existingLayer = findBoardBackgroundLayer(doc);
  if (existingLayer) {
    if (!options.forceRelink) {
      await ensureBoardBackgroundStackOrderInModal(doc);
      restoreActiveLayersByIds(doc, previousActiveIds);
      return false;
    }
    if (await relinkLayerToEntry(resolvedEntry, existingLayer)) {
      await reportBoardBackgroundLinkStatus(existingLayer);
      await ensureBoardBackgroundStackOrderInModal(doc);
      restoreActiveLayersByIds(doc, previousActiveIds);
      return true;
    }
    // Not a relinkable smart object (raster `SB bg` from an older build) — replace.
    await removeBoardBackgroundLayerInModal(doc);
  }
  const placedLayer = await placeFileEntryAsLinkedLayer(resolvedEntry);
  if (placedLayer) {
    await fitLayerToDocumentInModal(placedLayer);
  }
  await renameActiveLayer(SB_BG_LAYER_NAME);
  // Position is owned by the single stack-order authority below — no inline move.
  await ensureBoardBackgroundStackOrderInModal(doc);
  if (placedLayer) {
    await reportBoardBackgroundLinkStatus(placedLayer);
  }
  restoreActiveLayersByIds(doc, previousActiveIds);
  return true;
}

async function boardBackgroundSignature(entry) {
  // A signature that only changes when the file actually changes. Returns null
  // when it cannot be determined — callers must treat null as "no evidence of
  // change" and never re-import on it (mtime via fileUnixMtime is unreliable
  // because it falls back to Date.now(), which would loop forever).
  try {
    const metadata = await entry.getMetadata();
    const parts = [];
    if (metadata?.dateModified) {
      parts.push(`m:${metadata.dateModified.getTime()}`);
    } else if (metadata?.modificationDate) {
      parts.push(`m:${metadata.modificationDate.getTime()}`);
    }
    if (typeof metadata?.size === "number") {
      parts.push(`s:${metadata.size}`);
    }
    if (parts.length) {
      return parts.join("|");
    }
  } catch {
    // Metadata unavailable.
  }
  return null;
}

async function boardBackgroundRefreshNeeded(shotId, force = false) {
  // Linked `SB bg` layers should survive ordinary file changes. A changed file
  // asks Photoshop to update linked content in place; the plugin only creates a
  // missing layer or removes a stale layer when the source file disappears.
  const doc = app.activeDocument;
  if (!doc) {
    return false;
  }
  const entry = await resolveBoardBackgroundEntry(shotId);
  const hasLayer = !!findBoardBackgroundLayer(doc);
  if (!entry) {
    return hasLayer; // Stale layer with no source file → remove it.
  }
  if (!hasLayer) {
    return true;
  }
  if (force) {
    return true;
  }
  const signature = await boardBackgroundSignature(entry);
  if (signature === null) {
    return false; // Cannot tell → assume unchanged, never loop.
  }
  const lastSignature = boardBackgroundSigByShot.get(shotId);
  if (lastSignature === undefined || lastSignature === null) {
    boardBackgroundSigByShot.set(shotId, signature);
    return false;
  }
  return signature !== lastSignature;
}

async function syncBoardBackgroundFromDisk(shotId, force = false) {
  const doc = app.activeDocument;
  if (!doc) {
    return false;
  }
  if (detectShotFromDocument() !== shotId) {
    return false;
  }

  const entry = await resolveBoardBackgroundEntry(shotId);
  if (!entry) {
    boardBackgroundSigByShot.delete(shotId);
    await removeBoardBackgroundLayerInModal(doc);
    return false;
  }

  if (!(await boardBackgroundRefreshNeeded(shotId, force))) {
    return false;
  }

  const signature = await boardBackgroundSignature(entry);
  const existingLayer = findBoardBackgroundLayer(doc);
  if (existingLayer) {
    if (force) {
      const relinked = await importBoardBackgroundInModal(shotId, entry, { forceRelink: true });
      if (relinked && signature !== null) {
        boardBackgroundSigByShot.set(shotId, signature);
      }
      return relinked;
    }
    const updated = await updateLinkedSmartObjectInModal(existingLayer);
    await ensureBoardBackgroundStackOrderInModal(doc);
    if (updated) {
      if (signature !== null) {
        boardBackgroundSigByShot.set(shotId, signature);
      }
      return true;
    }
    setStatus("SB bg link update failed; use manual relink/update.");
    return false;
  }
  const imported = await importBoardBackgroundInModal(shotId, entry);
  if (imported && signature !== null) {
    boardBackgroundSigByShot.set(shotId, signature);
  }
  return imported;
}

async function moveLayerBelowReference(layer, referenceLayer) {
  const constants = photoshop.constants;
  if (referenceLayer) {
    await layer.move(referenceLayer, constants.ElementPlacement.PLACEAFTER);
    return;
  }
  await layer.move(app.activeDocument, constants.ElementPlacement.PLACEATEND);
}
