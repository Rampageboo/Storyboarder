function referenceModelPath(project) {
  return String(project?.settings?.reference_model_path || "").trim();
}

function referenceSegmentMode(project = state.project) {
  const mode = String(project?.settings?.reference_segment_mode || "").trim().toLowerCase();
  if (mode === "model" || mode === "video" || mode === "image") return mode;
  return referenceModelPath(project) && !activeReferenceVideoPath(project) ? "model" : "video";
}

function referenceImagePath(project) {
  return String(project?.settings?.reference_image_path || "").trim();
}

async function selectReferenceImage(path, { silent = false } = {}) {
  const relativePath = String(path || "").trim();
  if (!relativePath || !state.project) return;
  const ref =
    projectReferences().find((item) => item.path === relativePath) || { path: relativePath, type: "image" };
  const segment = typeof refSegmentActive === "function" ? refSegmentActive() : null;
  if (segment && typeof bindReferenceToActiveSegment === "function") {
    await bindReferenceToActiveSegment(ref);
    if (typeof patchRefSegmentPlayerMode === "function") patchRefSegmentPlayerMode();
    if (typeof navigateOpenRefSegmentOverlay === "function") navigateOpenRefSegmentOverlay("image");
    if (!silent) showToast("图片 Reference 已绑定到当前 Segment");
    return;
  }
  const project = await api("/api/project/settings", {
    method: "PATCH",
    body: {
      reference_image_path: relativePath,
      reference_segment_mode: "image",
    },
    silent,
  });
  setProject(project, false);
  if (typeof restoreRefSegmentFromProject === "function") restoreRefSegmentFromProject();
  if (typeof syncActiveSegmentSourceType === "function") syncActiveSegmentSourceType("image");
  if (typeof clearRefSegmentBindingMode === "function") clearRefSegmentBindingMode();
  if (typeof patchRefSegmentUi === "function") patchRefSegmentUi();
  if (typeof patchRefSegmentPlayerMode === "function") patchRefSegmentPlayerMode();
  if (typeof navigateOpenRefSegmentOverlay === "function") navigateOpenRefSegmentOverlay("image");
  refreshAllReferencePanels();
  if (!silent) showToast("Image reference selected for segment.");
}

async function selectReferenceModel(path, { silent = false } = {}) {
  const relativePath = String(path || "").trim();
  if (!relativePath || !state.project) return;
  const ref =
    projectReferences().find((item) => item.path === relativePath) || { path: relativePath, type: "model" };
  const segment = typeof refSegmentActive === "function" ? refSegmentActive() : null;
  if (segment && typeof bindReferenceToActiveSegment === "function") {
    await bindReferenceToActiveSegment(ref);
    if (typeof patchRefSegmentPlayerMode === "function") patchRefSegmentPlayerMode();
    if (typeof navigateOpenRefSegmentOverlay === "function") navigateOpenRefSegmentOverlay("model");
    if (!silent) showToast("3D Reference 已绑定到当前 Segment");
    return;
  }
  const project = await api("/api/project/settings", {
    method: "PATCH",
    body: {
      reference_model_path: relativePath,
      reference_segment_mode: "model",
    },
    silent,
  });
  setProject(project, false);
  if (typeof restoreRefSegmentFromProject === "function") restoreRefSegmentFromProject();
  if (typeof syncActiveSegmentSourceType === "function") syncActiveSegmentSourceType("model");
  if (typeof clearRefSegmentBindingMode === "function") clearRefSegmentBindingMode();
  if (typeof patchRefSegmentUi === "function") patchRefSegmentUi();
  if (typeof patchRefSegmentPlayerMode === "function") patchRefSegmentPlayerMode();
  if (typeof navigateOpenRefSegmentOverlay === "function") navigateOpenRefSegmentOverlay("model");
  refreshAllReferencePanels();
  if (!silent) showToast("3D reference selected for segment.");
}

async function openReferenceSegmentWorkspace(ref) {
  if (!ref?.path) return;
  const type =
    typeof resolveReferenceType === "function" ? resolveReferenceType(ref, state.project) : ref.type;
  const segment = typeof refSegmentActive === "function" ? refSegmentActive() : null;
  const range = typeof segmentIndices === "function" ? segmentIndices(segment) : null;
  if (!range) {
    showToast("先在时间轴创建 Segment");
    return;
  }

  if (type === "video") {
    await selectReferenceVideo(ref.path, { silent: true });
  } else if (type === "model") {
    await selectReferenceModel(ref.path, { silent: true });
  } else if (type === "image") {
    await selectReferenceImage(ref.path, { silent: true });
  } else {
    openReferencePreview(ref);
    return;
  }

  if (typeof openRefSegmentWindow === "function") {
    openRefSegmentWindow();
  }
}

function bindReferencePanel(container, { showImport = true, compact = false, title, hint } = {}) {
  const segmentBinding =
    typeof activeSegmentReferenceBinding === "function" ? activeSegmentReferenceBinding() : null;
  renderReferenceMediaPanel(container, {
    project: state.project,
    activeVideoPath: activeReferenceVideoPath(state.project),
    activeModelPath: referenceModelPath(state.project),
    activeImagePath: referenceImagePath(state.project),
    activeMode: referenceSegmentMode(state.project),
    boundReferenceId: segmentBinding?.id || "",
    boundReferencePath: segmentBinding?.path || "",
    boundReferenceType: segmentBinding?.type || "",
    disabled: !state.project,
    showImport,
    compact,
    title,
    hint: hint || "单击绑定到当前 Segment · 双击打开工作台",
    onImportClick: triggerProjectReferenceImport,
    onSelect: async (ref) => {
      const type = typeof resolveReferenceType === "function" ? resolveReferenceType(ref, state.project) : ref.type;
      if (type === "video") {
        await selectReferenceVideo(ref.path);
        if (isRefSegmentOverlayOpen() && typeof navigateOpenRefSegmentOverlay === "function") {
          navigateOpenRefSegmentOverlay("video");
        }
        return;
      }
      if (type === "model") {
        await selectReferenceModel(ref.path);
        return;
      }
      if (type === "image") {
        await selectReferenceImage(ref.path);
        if (isRefSegmentOverlayOpen() && typeof navigateOpenRefSegmentOverlay === "function") {
          navigateOpenRefSegmentOverlay("image");
        }
      }
    },
    onPreview: (ref) => openReferenceSegmentWorkspace(ref),
    onDelete: (ref) => deleteProjectReference(ref),
  });
}

function projectReferences() {
  return referenceLinksFromProject(state.project);
}

function refreshAllReferencePanels() {
  renderReferenceLinks();
  renderRefSegmentRefsPanel();
}

async function importProjectReference(file, { setActiveVideo = false, setActiveModel = false, setActiveImage = false } = {}) {
  if (!file || !state.project) return null;
  const form = new FormData();
  form.append("file", file);
  const result = await api("/api/project/references", {
    method: "POST",
    body: form,
    headers: {},
  });
  setProject(result, false);
  if (setActiveVideo && result.reference?.type === "video" && result.reference.path) {
    await selectReferenceVideo(result.reference.path, { silent: true });
  } else if (setActiveModel && result.reference?.type === "model" && result.reference.path) {
    await selectReferenceModel(result.reference.path, { silent: true });
  } else if (setActiveImage && result.reference?.type === "image" && result.reference.path) {
    await selectReferenceImage(result.reference.path, { silent: true });
  } else {
    refreshAllReferencePanels();
  }
  return result.reference || null;
}

async function selectReferenceVideo(path, { silent = false } = {}) {
  const relativePath = String(path || "").trim();
  if (!relativePath || !state.project) return;
  const ref =
    projectReferences().find((item) => item.path === relativePath) || { path: relativePath, type: "video" };
  const segment = typeof refSegmentActive === "function" ? refSegmentActive() : null;
  if (segment && typeof bindReferenceToActiveSegment === "function") {
    await bindReferenceToActiveSegment(ref);
    if (typeof patchRefSegmentPlayerMode === "function") patchRefSegmentPlayerMode();
    if (typeof navigateOpenRefSegmentOverlay === "function") navigateOpenRefSegmentOverlay("video");
    if (!silent) showToast("视频 Reference 已绑定到当前 Segment");
    return;
  }
  const project = await api("/api/project/settings", {
    method: "PATCH",
    body: {
      reference_video_path: relativePath,
      reference_segment_mode: "video",
    },
    silent,
  });
  setProject(project, false);
  if (typeof restoreRefSegmentFromProject === "function") restoreRefSegmentFromProject();
  if (typeof syncActiveSegmentSourceType === "function") syncActiveSegmentSourceType("video");
  if (typeof clearRefSegmentBindingMode === "function") clearRefSegmentBindingMode();
  if (typeof patchRefSegmentUi === "function") patchRefSegmentUi();
  if (typeof patchRefSegmentPlayerMode === "function") patchRefSegmentPlayerMode();
  if (typeof navigateOpenRefSegmentOverlay === "function") navigateOpenRefSegmentOverlay("video");
  refreshAllReferencePanels();
  if (!silent) showToast("Reference video selected for segment.");
}

async function deleteProjectReference(ref) {
  if (!ref?.id) return;
  const confirmed = await showDialog({
    title: "Remove reference",
    hint: `Delete “${referenceDisplayTitle(ref)}” from this project?`,
    actions: [
      { label: "Cancel", value: null },
      { label: "Remove", danger: true, value: "delete" },
    ],
  });
  if (confirmed !== "delete") return;
  const project = await api(`/api/project/references/${encodeURIComponent(ref.id)}`, {
    method: "DELETE",
  });
  setProject(project, false);
  if (typeof restoreRefSegmentFromProject === "function") restoreRefSegmentFromProject();
  if (typeof patchRefSegmentUi === "function") patchRefSegmentUi();
  refreshAllReferencePanels();
  showToast("Reference removed.");
}

function triggerProjectReferenceImport() {
  el.projectReferenceFile?.click();
}

function renderReferenceLinks() {
  bindReferencePanel(el.referenceLinkList, { title: "References", compact: false });
}

function renderRefSegmentRefsPanel() {
  if (!el.refSegmentRefsPanel) return;
  bindReferencePanel(el.refSegmentRefsPanel, {
    title: "References",
    compact: true,
    showImport: true,
    hint: "单击绑定到当前 Segment · 双击打开工作台",
  });
}

el.importProjectReference?.addEventListener("click", triggerProjectReferenceImport);

el.projectReferenceFile?.addEventListener("change", async () => {
  const file = el.projectReferenceFile.files?.[0];
  if (!file) return;
  const name = String(file.name || "").toLowerCase();
  const isModel = name.endsWith(".glb") || name.endsWith(".gltf");
  const isVideo = file.type.startsWith("video/");
  const isImage = file.type.startsWith("image/") || /\.(png|jpe?g|tif|tiff|webp)$/i.test(name);
  try {
    await importProjectReference(file, { setActiveVideo: isVideo, setActiveModel: isModel, setActiveImage: isImage });
    showToast("Reference imported.");
  } catch {
    // api() toasts
  }
  el.projectReferenceFile.value = "";
});
