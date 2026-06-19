// Layer name constants and pure layer-role detection helpers.
//
// Two distinct "background" layers, easy to confuse:
//   CANVAS_BG_LAYER_NAME ("Background") — the solid canvas-colour base at the
//     very bottom (the locked Photoshop Background, or a layer we explicitly
//     named so).
//   SB_BG_LAYER_NAME ("SB bg") — the board reference image, a LINKED smart
//     object sitting directly above the canvas base and below the artwork.
// Both are hidden from the storyboard preview export; neither is the artist's art.
const OVERLAY_LAYER_PREFIX = "SB ref:";
const SB_BG_LAYER_NAME = "SB bg";
const CANVAS_BG_LAYER_NAME = "Background";
const DRAWING_LAYER_NAME = "Layer 1";
const TEMPLATE_LAYER_NAMES = ["Rough"];
const DEFAULT_OVERLAY_OPACITY = 45;

function isCanvasBackgroundLayer(layer) {
  if (!layer) {
    return false;
  }
  return Boolean(layer.isBackgroundLayer) || String(layer.name || "") === CANVAS_BG_LAYER_NAME;
}

function isBoardBackgroundLayer(layer) {
  return Boolean(layer) && String(layer.name || "") === SB_BG_LAYER_NAME;
}

function isOverlayLayer(layer) {
  return Boolean(layer) && String(layer.name || "").startsWith(OVERLAY_LAYER_PREFIX);
}

// Any layer the plugin manages on the artist's behalf — i.e. NOT their artwork:
// the canvas-colour base, the board reference, or an onion-skin overlay.
function isManagedLayer(layer) {
  return isCanvasBackgroundLayer(layer) || isBoardBackgroundLayer(layer) || isOverlayLayer(layer);
}

function collectOverlayLayers(layers, output = []) {
  for (const layer of layers || []) {
    if (String(layer.name || "").startsWith(OVERLAY_LAYER_PREFIX)) {
      output.push(layer);
    }
    if (layer.layers?.length) {
      collectOverlayLayers(layer.layers, output);
    }
  }
  return output;
}

function collectBoardBackgroundLayers(layers, output = []) {
  for (const layer of layers || []) {
    if (isBoardBackgroundLayer(layer)) {
      output.push(layer);
    }
    if (layer.layers?.length) {
      collectBoardBackgroundLayers(layer.layers, output);
    }
  }
  return output;
}

function collectExportHiddenLayers(doc) {
  // Hide everything that is not the artist's artwork so the exported preview is
  // strokes only: canvas base, board reference, and onion-skin overlays.
  const output = [];
  const walk = (layers) => {
    for (const layer of layers || []) {
      if (isManagedLayer(layer)) {
        output.push(layer);
      }
      if (layer.layers?.length) {
        walk(layer.layers);
      }
    }
  };
  walk(doc?.layers);
  // Safety net: some documents expose the locked base only via doc.backgroundLayer
  // and may not enumerate it above — make sure it is hidden regardless.
  const canvasLayer = findBackgroundLayer(doc);
  if (canvasLayer && !output.includes(canvasLayer)) {
    output.push(canvasLayer);
  }
  return output;
}

function findLayerByName(doc, name) {
  const target = String(name || "");
  const walk = (layers) => {
    for (const layer of layers || []) {
      if (String(layer.name || "") === target) {
        return layer;
      }
      if (layer.layers?.length) {
        const found = walk(layer.layers);
        if (found) {
          return found;
        }
      }
    }
    return null;
  };
  return walk(doc?.layers);
}

function findBackgroundLayer(doc) {
  // The canvas-color base is ONLY the locked Background layer or a layer we
  // explicitly named "Background". Never fall back to an arbitrary bottom layer:
  // that could be `SB bg` (the reference) or the artist's drawing, and filling
  // it with the canvas color would destroy the reference / artwork.
  try {
    if (doc.backgroundLayer) {
      return doc.backgroundLayer;
    }
  } catch {
    // Some documents do not expose backgroundLayer.
  }

  for (const layer of doc.layers || []) {
    if (isCanvasBackgroundLayer(layer)) {
      return layer;
    }
  }

  return null;
}

function hasDrawingLayer(doc) {
  // A "drawing" layer is anything that is not a plugin-managed layer.
  for (const layer of doc?.layers || []) {
    if (!isManagedLayer(layer)) {
      return true;
    }
  }
  return false;
}
