// Shot/board rendering: inspector, preview, references, comments, status.
// Reads shared state/el/api from globalThis (installed by init_globals).

function render() {
  const hasProject = Boolean(state.project);
  const shot = selectedShot();

  el.openScene3d.disabled = !hasProject;
  el.openBlender.disabled = !hasProject;
  el.linkPhotoshop.disabled = !hasProject;

  [
    el.saveProject,
    el.pdfLayout,
    el.exportPdf,
    el.exportShotList,
    el.exportContactSheet,
    el.exportTiming,
    el.exportImageSequence,
    el.addShot,
    el.statusFilter,
    el.revisionFilter,
    el.playAnimatic,
    el.stopAnimatic,
    el.progressSlider,
    el.prevShot,
    el.nextShot,
    el.setRefVideo,
  ].forEach((button) => {
    button.disabled = !hasProject;
  });
  [
    el.importImage,
    el.removeImage,
    el.addReference,
    el.importSource,
    el.relinkPreview,
    el.openPreview,
    el.refreshPreview,
  ].forEach((button) => {
    button.disabled = !shot;
  });
  [el.shotId, el.commentText, el.addComment, ...inspectorFields].forEach((field) => {
    field.disabled = !shot;
  });

  renderBoardInfo();
  renderBlenderMenuStatus();
  renderInspector(shot);
  renderPreview(shot);
  renderReferences(shot);
  if (typeof renderReferenceLinks === "function") renderReferenceLinks();
  renderFileStatus(shot);
  renderComments(shot);
  renderTimeline();
  if (typeof patchRefSegmentUi === "function") patchRefSegmentUi();
  updateAnnotationControls();
}

function renderBoardInfo() {
  const project = state.project;
  const shot = selectedShot();
  if (!project) {
    el.boardInfo.textContent = "No project open";
    el.boardCount.textContent = "Board — of —";
    el.projectStats.textContent = "0 BOARDS";
    if (el.shotLabel) el.shotLabel.textContent = "Shot —";
    refreshAppStatus();
    return;
  }
  const shots = project.shots;
  const index = shots.findIndex((item) => item.shot_id === state.selectedShotId);
  const scenes = new Set(shots.map((item) => item.scene).filter(Boolean));
  el.boardInfo.textContent = `${project.name}${project.dirty ? " *" : ""}`;
  el.boardCount.textContent =
    shot && index >= 0
      ? `Board ${index + 1} / ${shots.length}  |  ${formatShotId(shot.shot_id)}`
      : `${shots.length} boards`;
  el.projectStats.textContent = `${shots.length} BOARDS${scenes.size ? `, ${scenes.size} SCENES` : ""}`;
  if (el.shotLabel) {
    el.shotLabel.textContent = shot ? `Shot: ${shot.title || shot.shot_id}` : "No shot selected";
  }
  refreshAppStatus();
}

function renderInspector(shot) {
  el.shotId.value = shot?.shot_id || "";
  el.title.value = shot?.title || "";
  el.scene.value = shot?.scene || "";
  el.sequence.value = shot?.sequence || "";
  el.status.value = shot?.status || "Draft";
  el.description.value = shot?.description || "";
  el.actionNote.value = shot?.action_note || "";
  el.cameraNote.value = shot?.camera_note || "";
  const cameraData = shot?.camera_data || {};
  el.cameraAngle.value = cameraData.angle || formatCameraVec(cameraData.target) || "";
  el.cameraFocalLength.value =
    cameraData.focal_length != null ? String(cameraData.focal_length) : "";
  el.cameraLocation.value = cameraData.location || formatCameraVec(cameraData.position) || "";
  el.cameraRotation.value =
    cameraData.rotation_text ||
    (Array.isArray(cameraData.rotation) ? formatCameraVec(cameraData.rotation, true) : cameraData.rotation) ||
    "";
  el.characterNote.value = shot?.character_note || "";
  el.dialogue.value = shot?.dialogue || "";
  el.lightingNote.value = shot?.lighting_note || "";
  el.transitionNote.value = shot?.transition_note || "";
  el.durationSeconds.value = shot?.duration_seconds ?? 3.0;
  el.tags.value = (shot?.tags || []).join(", ");
}

function renderCanvasPlaceholder(message) {
  const placeholder = document.createElement("span");
  placeholder.className = "canvas-placeholder";
  placeholder.textContent = message;
  el.canvasBoard.appendChild(placeholder);
}

let previewRenderSeq = 0;

function previewLayerKey(shot) {
  if (!shot) return "";
  const { background, artwork } = shotCanvasLayerUrls(shot);
  return `${shot.shot_id}|${background}|${artwork}`;
}

function clearCanvasBoardContent() {
  el.canvasBoard.querySelectorAll("img, .canvas-placeholder, .canvas-board-stack").forEach((node) => node.remove());
}

function finishPreviewRender() {
  layoutAnnotationCanvas();
  updateAnnotationControls();
  drawAnnotations();
}

function clearAnnotationOverlay() {
  if (!el.annotationCanvas) return;
  const ctx = resizeCanvas();
  ctx.clearRect(0, 0, el.annotationCanvas.width, el.annotationCanvas.height);
}

function mountCanvasBoardStack(shot, layers) {
  const stack = document.createElement("div");
  stack.className = "canvas-board-stack";
  stack.dataset.previewKey = previewLayerKey(shot);
  layers.forEach((layer) => {
    const image = document.createElement("img");
    image.className = layer.className;
    image.alt = layer.alt;
    image.src = layer.url;
    stack.appendChild(image);
  });
  clearCanvasBoardContent();
  el.canvasBoard.appendChild(stack);
  finishPreviewRender();
}

function preloadPreviewLayer(url) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.addEventListener("load", () => resolve(url));
    image.addEventListener("error", () => reject(new Error("preview load failed")));
    image.src = url;
  });
}

function renderPreviewPlaceholder(shot) {
  if (shot.source_file_path) {
    renderCanvasPlaceholder("Click to open in Photoshop");
  } else {
    renderCanvasPlaceholder("Click to create canvas and open in Photoshop");
  }
}

function renderPreview(shot) {
  applyCanvasColor();
  layoutAnnotationCanvas();
  el.canvasBoard.classList.remove("canvas-openable");
  if (!state.project) {
    previewRenderSeq += 1;
    clearCanvasBoardContent();
    renderCanvasPlaceholder("No project open");
    finishPreviewRender();
    return;
  }
  if (!shot) {
    previewRenderSeq += 1;
    clearCanvasBoardContent();
    renderCanvasPlaceholder("No shot selected");
    finishPreviewRender();
    return;
  }
  el.canvasBoard.classList.add("canvas-openable");
  const { background, artwork } = shotCanvasLayerUrls(shot);
  if (!background && !artwork) {
    previewRenderSeq += 1;
    clearCanvasBoardContent();
    renderPreviewPlaceholder(shot);
    finishPreviewRender();
    return;
  }

  const layerKey = previewLayerKey(shot);
  const existingStack = el.canvasBoard.querySelector(".canvas-board-stack");
  if (existingStack?.dataset.previewKey === layerKey) {
    finishPreviewRender();
    return;
  }

  const seq = ++previewRenderSeq;
  clearAnnotationOverlay();

  (async () => {
    const [bgUrl, artUrl] = await Promise.all([
      background ? preloadPreviewLayer(background).catch(() => null) : Promise.resolve(null),
      artwork ? preloadPreviewLayer(artwork).catch(() => null) : Promise.resolve(null),
    ]);
    if (seq !== previewRenderSeq || selectedShot()?.shot_id !== shot.shot_id) return;

    if (artwork && !artUrl) {
      clearCanvasBoardContent();
      renderCanvasPlaceholder("Preview file missing");
      finishPreviewRender();
      return;
    }

    const layers = [];
    if (bgUrl) {
      layers.push({ url: bgUrl, className: "canvas-board-layer canvas-board-bg", alt: "" });
    }
    if (artUrl) {
      layers.push({ url: artUrl, className: "canvas-board-layer canvas-board-art", alt: shot.shot_id });
    }
    if (!layers.length) {
      clearCanvasBoardContent();
      renderPreviewPlaceholder(shot);
      finishPreviewRender();
      return;
    }
    mountCanvasBoardStack(shot, layers);
  })();
}

function renderReferences(shot) {
  el.referenceStrip.innerHTML = "";
  if (!shot?.reference_image_paths?.length) {
    el.referenceStrip.textContent = shot ? "No reference images" : "";
    return;
  }
  shot.reference_image_paths.forEach((path) => {
    const item = document.createElement("div");
    item.className = "reference-item";
    const image = document.createElement("img");
    image.alt = "Reference";
    image.src = `/api/files?path=${encodeURIComponent(path)}&t=${Date.now()}`;
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "reference-remove";
    remove.title = "Remove reference";
    remove.setAttribute("aria-label", "Remove reference");
    remove.textContent = "×";
    remove.addEventListener("click", async (event) => {
      event.preventDefault();
      event.stopPropagation();
      await removeReferenceImage(shot.shot_id, path);
    });
    item.append(image, remove);
    el.referenceStrip.appendChild(item);
  });
}

async function removeReferenceImage(shotId, path) {
  const shot = state.project?.shots?.find((item) => item.shot_id === shotId);
  if (!shot) return;
  const previousPaths = [...(shot.reference_image_paths || [])];
  try {
    await api(`/api/shots/${shotId}/references`, {
      method: "DELETE",
      body: JSON.stringify({ path }),
    }).then(setProject);
    pushUndo({
      type: "remove_reference",
      shot_id: shotId,
      paths: previousPaths,
      selectedShotId: state.selectedShotId,
    });
    renderReferences(selectedShot());
  } catch {
    // api() already toasts
  }
}

function renderFileStatus(shot) {
  el.fileStatus.innerHTML = "";
  if (!shot) return;
  const missing = state.missingFiles.filter((item) => item.shot_id === shot.shot_id);
  const preview = shot.preview_image_path || shot.image_path ? `Preview: ${escapeHtml(shot.preview_image_path || shot.image_path)}` : "No preview image";
  const source = shot.source_file_path ? `Source: ${escapeHtml(shot.source_file_path)}` : "No source file linked";
  const lines = [preview, source];
  if (missing.length) {
    lines.push(`<span class="missing">Missing: ${missing.map((item) => escapeHtml(item.field)).join(", ")}</span>`);
  }
  el.fileStatus.innerHTML = lines.join("<br>");
}

function renderComments(shot) {
  el.commentList.innerHTML = "";
  if (!shot) return;
  (shot.comments || []).forEach((comment) => {
    const row = document.createElement("div");
    row.className = `comment-item ${comment.resolved ? "resolved" : ""}`;
    const text = document.createElement("span");
    text.textContent = comment.text;
    const button = document.createElement("button");
    button.textContent = comment.resolved ? "Reopen" : "Resolve";
    button.addEventListener("click", () => resolveComment(comment.id, !comment.resolved));
    row.append(text, button);
    el.commentList.appendChild(row);
  });
}

function fillStatusOptions() {
  const statuses = state.project?.statuses || ["Draft", "In Progress", "Review", "Approved", "Final"];
  el.status.innerHTML = "";
  el.statusFilter.innerHTML = '<option value="">All status</option>';
  statuses.forEach((status) => {
    const option = document.createElement("option");
    option.value = status;
    option.textContent = status;
    el.status.appendChild(option);
    const filterOption = document.createElement("option");
    filterOption.value = status;
    filterOption.textContent = status;
    el.statusFilter.appendChild(filterOption);
  });
  el.statusFilter.value = state.statusFilter;
}

async function refreshMissingFiles() {
  if (!state.project) {
    state.missingFiles = [];
    return;
  }
  try {
    const result = await api("/api/project/missing-files");
    state.missingFiles = result.missing_files || [];
    renderFileStatus(selectedShot());
  } catch {
    state.missingFiles = [];
  }
}

// --- module global bridge (auto) ---
Object.assign(globalThis, {
  render,
  renderBoardInfo,
  renderInspector,
  renderCanvasPlaceholder,
  renderPreview,
  renderReferences,
  removeReferenceImage,
  renderFileStatus,
  renderComments,
  fillStatusOptions,
  refreshMissingFiles,
});
