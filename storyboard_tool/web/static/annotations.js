// Annotation overlay subsystem: layout, drawing, persistence and pointer input
// for the per-shot annotation canvas.
//
// Loaded as a classic script BEFORE app.js (see APP_SCRIPTS in main.js) so that
// the exported globals (drawAnnotations, loadAnnotations, annotationCache, ...)
// exist before app.js runs its deferred startup render, and so the top-level
// pointer listeners can attach to `el.annotationCanvas` after core/bootstrap.js
// has populated `el`. Cross-module helpers it relies on (selectedShot,
// showDialog, api, state, el) resolve at call time from the shared global scope.

const annotationCache = new Map();

function layoutAnnotationCanvas() {
  if (!el.canvasBoard || !el.previewBox || !el.annotationCanvas) return;
  const surfaceRect = el.canvasBoard.getBoundingClientRect();
  const boxRect = el.previewBox.getBoundingClientRect();
  const left = surfaceRect.left - boxRect.left;
  const top = surfaceRect.top - boxRect.top;
  el.annotationCanvas.style.left = `${left}px`;
  el.annotationCanvas.style.top = `${top}px`;
  el.annotationCanvas.style.width = `${surfaceRect.width}px`;
  el.annotationCanvas.style.height = `${surfaceRect.height}px`;
}

async function promptAnnotationText() {
  return showDialog({
    title: "Text label",
    hint: "Enter the text to place on the frame.",
    input: {
      label: "Text",
      value: "",
      placeholder: "Label text…",
    },
    validate: (value) => (value ? null : "Enter label text."),
    actions: [
      { label: "Cancel", value: null },
      { label: "OK", value: "ok", primary: true },
    ],
  });
}

async function loadAnnotations(shotId) {
  if (!shotId) {
    state.annotations = [];
    drawAnnotations();
    return;
  }
  if (annotationCache.has(shotId)) {
    state.annotations = annotationCache.get(shotId);
    if (state.selectedShotId !== shotId) return;
    updateAnnotationControls();
    drawAnnotations();
    return;
  }
  try {
    const result = await api(`/api/shots/${shotId}/annotations`, { silent: true });
    if (state.selectedShotId !== shotId) return;
    state.annotations = result.annotations || [];
    annotationCache.set(shotId, state.annotations);
    updateAnnotationControls();
    drawAnnotations();
  } catch {
    if (state.selectedShotId !== shotId) return;
    if (!annotationCache.has(shotId)) state.annotations = [];
    updateAnnotationControls();
    drawAnnotations();
  }
}

async function saveAnnotations() {
  const shot = selectedShot();
  if (!shot) return;
  await api(`/api/shots/${shot.shot_id}/annotations`, {
    method: "PUT",
    body: JSON.stringify({ annotations: state.annotations }),
  });
}

function updateAnnotationControls() {
  if (el.annotationCanvas) {
    el.annotationCanvas.style.pointerEvents = "none";
  }
}

function resizeCanvas() {
  layoutAnnotationCanvas();
  const rect = el.canvasBoard.getBoundingClientRect();
  const ratio = window.devicePixelRatio || 1;
  el.annotationCanvas.width = Math.max(1, Math.round(rect.width * ratio));
  el.annotationCanvas.height = Math.max(1, Math.round(rect.height * ratio));
  el.annotationCanvas.style.width = `${rect.width}px`;
  el.annotationCanvas.style.height = `${rect.height}px`;
  const ctx = el.annotationCanvas.getContext("2d");
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  return ctx;
}

function drawAnnotations() {
  const ctx = resizeCanvas();
  ctx.clearRect(0, 0, el.annotationCanvas.width, el.annotationCanvas.height);
  if (!state.annotationsVisible) return;
  state.annotations.forEach((annotation) => drawAnnotation(ctx, annotation));
  if (state.drawing) drawAnnotation(ctx, state.drawing.preview);
}

function drawAnnotation(ctx, annotation) {
  const rect = imageDrawRect();
  if (!rect) return;
  const start = denormalize(annotation.start, rect);
  const end = denormalize(annotation.end, rect);
  ctx.save();
  ctx.lineWidth = 3;
  ctx.strokeStyle = annotation.type === "highlight" ? "rgba(255, 210, 0, 0.8)" : "#ff3b30";
  ctx.fillStyle = annotation.type === "highlight" ? "rgba(255, 210, 0, 0.28)" : "#ff3b30";
  if (annotation.type === "line" || annotation.type === "arrow") {
    ctx.beginPath();
    ctx.moveTo(start.x, start.y);
    ctx.lineTo(end.x, end.y);
    ctx.stroke();
    if (annotation.type === "arrow") drawArrowHead(ctx, start, end);
  } else if (annotation.type === "box" || annotation.type === "highlight") {
    const x = Math.min(start.x, end.x);
    const y = Math.min(start.y, end.y);
    const w = Math.abs(end.x - start.x);
    const h = Math.abs(end.y - start.y);
    if (annotation.type === "highlight") ctx.fillRect(x, y, w, h);
    ctx.strokeRect(x, y, w, h);
  } else if (annotation.type === "circle") {
    const cx = (start.x + end.x) / 2;
    const cy = (start.y + end.y) / 2;
    const rx = Math.abs(end.x - start.x) / 2;
    const ry = Math.abs(end.y - start.y) / 2;
    ctx.beginPath();
    ctx.ellipse(cx, cy, rx, ry, 0, 0, Math.PI * 2);
    ctx.stroke();
  } else if (annotation.type === "text") {
    ctx.font = "18px Arial";
    ctx.fillText(annotation.text || "Text", start.x, start.y);
  }
  ctx.restore();
}

function drawArrowHead(ctx, start, end) {
  const angle = Math.atan2(end.y - start.y, end.x - start.x);
  const size = 13;
  ctx.beginPath();
  ctx.moveTo(end.x, end.y);
  ctx.lineTo(end.x - size * Math.cos(angle - Math.PI / 6), end.y - size * Math.sin(angle - Math.PI / 6));
  ctx.lineTo(end.x - size * Math.cos(angle + Math.PI / 6), end.y - size * Math.sin(angle + Math.PI / 6));
  ctx.closePath();
  ctx.fill();
}

function imageDrawRect() {
  const image = el.canvasBoard.querySelector(".canvas-board-art, .canvas-board-stack img, img");
  if (!image) return null;
  const imageRect = image.getBoundingClientRect();
  const boxRect = el.previewBox.getBoundingClientRect();
  return {
    x: imageRect.left - boxRect.left,
    y: imageRect.top - boxRect.top,
    width: imageRect.width,
    height: imageRect.height,
  };
}

function pointerToNormalized(event) {
  const rect = imageDrawRect();
  if (!rect) return null;
  const boxRect = el.previewBox.getBoundingClientRect();
  const x = Math.min(Math.max(event.clientX - boxRect.left, rect.x), rect.x + rect.width);
  const y = Math.min(Math.max(event.clientY - boxRect.top, rect.y), rect.y + rect.height);
  return {
    x: (x - rect.x) / rect.width,
    y: (y - rect.y) / rect.height,
  };
}

function denormalize(point, rect) {
  return {
    x: rect.x + point.x * rect.width,
    y: rect.y + point.y * rect.height,
  };
}

function syncAnnotationLayout() {
  layoutAnnotationCanvas();
  drawAnnotations();
}

el.annotationCanvas.addEventListener("pointerdown", async (event) => {
  if (state.annotationTool === "select") return;
  const start = pointerToNormalized(event);
  if (!start) return;
  el.annotationCanvas.setPointerCapture(event.pointerId);
  const type = state.annotationTool;
  if (type === "text") {
    const text = await promptAnnotationText();
    if (el.annotationCanvas.hasPointerCapture(event.pointerId)) {
      el.annotationCanvas.releasePointerCapture(event.pointerId);
    }
    if (!text) return;
    state.annotations.push({ type, start, end: start, text });
    saveAnnotations();
    drawAnnotations();
    updateAnnotationControls();
    return;
  }
  state.drawing = { type, start, preview: { type, start, end: start } };
});

el.annotationCanvas.addEventListener("pointermove", (event) => {
  if (!state.drawing) return;
  const end = pointerToNormalized(event);
  if (!end) return;
  state.drawing.preview = { type: state.drawing.type, start: state.drawing.start, end };
  drawAnnotations();
});

el.annotationCanvas.addEventListener("pointerup", async (event) => {
  if (!state.drawing) return;
  const end = pointerToNormalized(event);
  if (end) {
    state.annotations.push({ type: state.drawing.type, start: state.drawing.start, end });
    await saveAnnotations();
  }
  state.drawing = null;
  updateAnnotationControls();
  drawAnnotations();
});

window.addEventListener("resize", syncAnnotationLayout);

if (el.previewBox && typeof ResizeObserver !== "undefined") {
  new ResizeObserver(syncAnnotationLayout).observe(el.previewBox);
}


// --- module global bridge (auto) ---
Object.assign(globalThis, {
  annotationCache,
  layoutAnnotationCanvas,
  promptAnnotationText,
  loadAnnotations,
  saveAnnotations,
  updateAnnotationControls,
  resizeCanvas,
  drawAnnotations,
  drawAnnotation,
  drawArrowHead,
  imageDrawRect,
  pointerToNormalized,
  denormalize,
  syncAnnotationLayout,
});
