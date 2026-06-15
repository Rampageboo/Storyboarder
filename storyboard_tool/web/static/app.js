const inspectorFields = [
  el.title,
  el.scene,
  el.sequence,
  el.status,
  el.description,
  el.actionNote,
  el.cameraNote,
  el.cameraAngle,
  el.cameraFocalLength,
  el.cameraLocation,
  el.cameraRotation,
  el.characterNote,
  el.dialogue,
  el.lightingNote,
  el.transitionNote,
  el.durationSeconds,
  el.tags,
];

window.addEventListener("beforeunload", (event) => {
  if (state.project?.dirty) {
    event.preventDefault();
    event.returnValue = "";
  }
});

const advancedPanel = document.querySelector(".advanced-panel");
const shotPanel = document.querySelector(".shot-panel");

function updateShotPanelScrollMode() {
  shotPanel?.classList.toggle("shot-panel-advanced-open", Boolean(advancedPanel?.open));
}

advancedPanel?.querySelector("summary")?.addEventListener("click", (event) => {
  event.preventDefault();
  advancedPanel.open = !advancedPanel.open;
});

advancedPanel?.addEventListener("toggle", () => {
  updateShotPanelScrollMode();
  requestAnimationFrame(syncAnnotationLayout);
  saveAppSessionSoon();
});

updateShotPanelScrollMode();

el.saveProject.addEventListener("click", async () => {
  await flushSelectedShot();
  await api("/api/project/save", { method: "POST" }).then(setProject);
  showToast("Project saved.");
});

el.linkPhotoshop?.addEventListener("click", () => relinkPhotoshopBridge());
el.openBlender?.addEventListener("click", () => openProjectInBlender());
el.openBlenderScene?.addEventListener("click", () => openProjectInBlender());

el.importImage.addEventListener("click", () => el.imageFile.click());
el.addReference.addEventListener("click", () => el.referenceFile.click());
el.importSource.addEventListener("click", () => el.sourceFile.click());
el.refreshPreview.addEventListener("click", () => {
  const shot = selectedShot();
  if (shot) syncShot(shot.shot_id, true);
});

el.imageFile.addEventListener("change", async () => {
  const shot = selectedShot();
  const file = el.imageFile.files[0];
  if (!shot || !file) return;
  const form = new FormData();
  form.append("file", file);
  await api(`/api/shots/${shot.shot_id}/image`, { method: "POST", body: form, headers: {} }).then(setProject);
  selectShot(shot.shot_id);
  el.imageFile.value = "";
});

el.referenceFile.addEventListener("change", async () => {
  const shot = selectedShot();
  const file = el.referenceFile.files[0];
  if (!shot || !file) return;
  const form = new FormData();
  form.append("file", file);
  await api(`/api/shots/${shot.shot_id}/references`, { method: "POST", body: form, headers: {} }).then(setProject);
  selectShot(shot.shot_id);
  el.referenceFile.value = "";
});

el.sourceFile.addEventListener("change", async () => {
  const shot = selectedShot();
  const file = el.sourceFile.files[0];
  if (!shot || !file) return;
  const form = new FormData();
  form.append("file", file);
  await api(`/api/shots/${shot.shot_id}/source`, { method: "POST", body: form, headers: {} }).then(setProject);
  selectShot(shot.shot_id);
  el.sourceFile.value = "";
});

el.canvasBoard.addEventListener("contextmenu", (event) => {
  const shot = selectedShot();
  if (!shot || !state.project) return;
  event.preventDefault();
  showShotContextMenu(shot.shot_id, event.clientX, event.clientY);
});

el.removeImage.addEventListener("click", async () => {
  const shot = selectedShot();
  if (!shot) return;
  await api(`/api/shots/${shot.shot_id}/image`, { method: "DELETE" }).then(setProject);
  selectShot(shot.shot_id);
});

el.addComment.addEventListener("click", addComment);
el.commentText.addEventListener("keydown", (event) => {
  if (event.key === "Enter") addComment();
});

inspectorFields.forEach((field) => {
  field.addEventListener("input", () => {
    const shot = selectedShot();
    if (!shot) return;
    readInspectorIntoShot(shot);
    state.project.dirty = true;
    renderBoardInfo();
    renderTimeline();
    window.clearTimeout(state.saveTimer);
    state.saveTimer = window.setTimeout(saveSelectedShot, 350);
  });
});

async function syncShot(shotId, force = false, { silent = false } = {}) {
  if (!shotId) return;
  if (state.isSyncing) return;
  state.isSyncing = true;
  if (!silent) refreshAppStatus();
  try {
    const result = await api(`/api/shots/${shotId}/sync?force=${force}`, { method: "POST", silent });
    if (state.selectedShotId !== shotId) return;
    const syncResult = result.result || {};
    if (state.project && result.shots && !state.project.dirty) {
      applyProjectShotsFromServer(result);
    }
    if (syncResult.synced) {
      setProject(result, false);
      state.selectedShotId = shotId;
      if (!silent) showSyncStatus(syncResult.message || "Synced preview from Photoshop.");
      renderPreview(selectedShot());
      if (typeof patchTimelineActiveState === "function") patchTimelineActiveState(shotId);
      else renderTimeline();
    } else if (force && !silent) {
      showSyncStatus(syncResult.message || "No changes to sync.");
      renderTimeline();
    } else if (!silent) {
      showSyncStatus("");
    }
  } catch {
    if (!silent) showSyncStatus("");
  } finally {
    state.isSyncing = false;
    if (!silent) refreshAppStatus();
  }
}

function showSyncStatus(message) {
  if (!el.syncStatus) return;
  el.syncStatus.textContent = message || "";
  el.syncStatus.classList.toggle("synced", Boolean(message));
  if (message) {
    setAppStatus(message, { temporary: true, ms: 3500 });
  } else {
    refreshAppStatus();
  }
}

async function addComment() {
  const shot = selectedShot();
  const text = el.commentText.value.trim();
  if (!shot || !text) return;
  await api(`/api/shots/${shot.shot_id}/comments`, {
    method: "POST",
    body: JSON.stringify({ text }),
  }).then(setProject);
  el.commentText.value = "";
  selectShot(shot.shot_id);
}

async function resolveComment(commentId, resolved) {
  const shot = selectedShot();
  if (!shot) return;
  await api(`/api/shots/${shot.shot_id}/comments/${commentId}`, {
    method: "PATCH",
    body: JSON.stringify({ resolved }),
  }).then(setProject);
  selectShot(shot.shot_id);
}

async function flushSelectedShot() {
  window.clearTimeout(state.saveTimer);
  if (state.project?.dirty) {
    await saveSelectedShot();
  }
}

async function saveSelectedShot() {
  const shot = selectedShot();
  if (!shot) return;
  await saveShot(shot);
}

async function saveShot(shot) {
  await api(`/api/shots/${shot.shot_id}`, {
    method: "PATCH",
    body: JSON.stringify({
      title: shot.title,
      scene: shot.scene,
      sequence: shot.sequence,
      status: shot.status,
      description: shot.description,
      action_note: shot.action_note,
      camera_note: shot.camera_note,
      camera_data: shot.camera_data || {},
      character_note: shot.character_note,
      dialogue: shot.dialogue,
      lighting_note: shot.lighting_note,
      transition_note: shot.transition_note,
      duration_seconds: shot.duration_seconds,
      tags: shot.tags,
    }),
  }).then((project) => {
    setProject(project, false);
    if (shot.shot_id === state.selectedShotId) {
      state.selectedShotId = shot.shot_id;
    }
  });
}

function getRecentProjects() {
  try {
    const items = JSON.parse(localStorage.getItem("recent_projects") || "[]");
    return Array.isArray(items) ? items.filter(Boolean) : [];
  } catch {
    return [];
  }
}

let sessionSaveTimer = null;

function saveAppSessionSoon() {
  window.clearTimeout(sessionSaveTimer);
  sessionSaveTimer = window.setTimeout(() => {
    saveAppSession().catch(() => {});
  }, 400);
}

async function saveAppSession() {
  captureTimelineScroll();
  const payload = {
    ui_theme: getStoredUiTheme(),
  };
  if (state.project?.project_json_path) {
    payload.last_project_json_path = state.project.project_json_path;
    payload.selected_shot_id = state.selectedShotId || "";
    payload.timeline_scroll_left = state.timelineScrollLeft;
    payload.status_filter = state.statusFilter || "";
    payload.revision_only = state.revisionOnly;
    payload.advanced_panel_open = Boolean(advancedPanel?.open);
  }
  const session = await api("/api/app/session", {
    method: "PUT",
    body: JSON.stringify(payload),
    silent: true,
  });
  if (Array.isArray(session.recent_projects) && session.recent_projects.length) {
    localStorage.setItem("recent_projects", JSON.stringify(session.recent_projects));
  }
}

async function relinkPhotoshopBridge() {
  if (!state.project) {
    showToast("Open a project first.");
    return;
  }
  try {
    await publishLiveBridge();
    const status = await api("/api/bridge/relink", { method: "POST" });
    updateBridgeLinkStatus(status);
    showToast("Photoshop link published.");
  } catch (error) {
    renderPsBridgeState("error", error.message || "Link failed");
    showToast(error.message || "Could not publish Photoshop link.");
  }
}

async function restoreLastProjectOnStartup() {
  const withStartupTimeout = (promise, ms, label) =>
    Promise.race([
      promise,
      new Promise((_, reject) => {
        window.setTimeout(() => reject(new Error(`${label} timed out`)), ms);
      }),
    ]);

  try {
    window.setStartupProgress?.(78, "Restoring session…", "Reading saved session");
    const session = await withStartupTimeout(
      api("/api/app/session", { silent: true, bypassBridge: true }),
      8000,
      "Session"
    );
    if (Array.isArray(session.recent_projects) && session.recent_projects.length) {
      localStorage.setItem("recent_projects", JSON.stringify(session.recent_projects));
    }
    state.statusFilter = String(session.status_filter || "");
    state.revisionOnly = Boolean(session.revision_only);
    if (session.ui_theme) applyUiTheme(session.ui_theme);
    if (advancedPanel) {
      advancedPanel.open = Boolean(session.advanced_panel_open);
      updateShotPanelScrollMode();
    }
    if (el.revisionFilter) el.revisionFilter.checked = state.revisionOnly;
    const path = String(session.last_project_json_path || "").trim();
    if (!path) {
      render();
      return;
    }
    window.setStartupProgress?.(86, "Opening project…", pathBasename(path));
    const project = await withStartupTimeout(
      api("/api/project/open", {
        method: "POST",
        body: JSON.stringify({ project_json_path: path }),
        silent: true,
        bypassBridge: true,
      }),
      30000,
      "Project open"
    );
    state.timelineScrollLeft = Math.max(0, Math.round(Number(session.timeline_scroll_left) || 0));
    state.timelineScrollPendingRestore = true;
    setProject(project);
    clearUndoStack();
    const shotId = String(session.selected_shot_id || "").trim();
    window.setStartupProgress?.(94, "Restoring view…", shotId ? formatShotId(shotId) : "Default board");
    if (shotId && project.shots?.some((shot) => shot.shot_id === shotId)) {
      await selectShot(shotId);
    } else {
      render();
    }
    showToast(`Restored ${project.name}`);
  } catch (error) {
    console.warn("Session restore skipped:", error);
  }
}

async function openBlenderSettingsDialog() {
  const current =
    state.project?.settings?.blender_path || localStorage.getItem("blender_path_default") || "";
  let candidates = [];
  let templateExists = false;
  try {
    const result = await api("/api/system/blender-candidates");
    candidates = result.candidates || [];
    templateExists = Boolean(result.template_exists);
  } catch {
    candidates = [];
  }
  const blenderPath = await showDialog({
    title: "Blender path",
    hint: templateExists
      ? "Choose blender.exe, or the Blender install folder (Steam / Blender Foundation)."
      : "Choose blender.exe or install folder. Also place scene_template.blend in storyboard_tool/assets/.",
    input: {
      label: "Path",
      value: current,
      placeholder: "e.g. ...\\Steam\\steamapps\\common\\Blender\\blender.exe",
      clearLabel: "Clear (auto-detect)",
    },
    browse: "blender",
    list: {
      title: "Detected installations",
      items: candidates.map((path) => ({
        name: pathBasename(path),
        path,
        subtitle: pathDirname(path),
      })),
    },
    actions: [
      { label: "Cancel", value: null },
      { label: "Save", value: "save", primary: true },
    ],
  });
  if (blenderPath === null) return;
  try {
    if (state.project) {
      await api("/api/project/settings", {
        method: "PATCH",
        body: JSON.stringify({ blender_path: blenderPath }),
      }).then(setProject);
    }
    if (blenderPath) {
      localStorage.setItem("blender_path_default", blenderPath);
    } else {
      localStorage.removeItem("blender_path_default");
    }
    renderBlenderMenuStatus();
    showToast(
      blenderPath
        ? `Blender path saved: ${blenderPath}`
        : "Path cleared. Blender will be auto-detected when possible.",
    );
  } catch {
    // api() already shows the error toast.
  }
}

async function openProjectInBlender() {
  if (!state.project) return;
  try {
    const result = await api("/api/project/scene3d/open-blender", { method: "POST" });
    setProject(result, false);
    renderBlenderMenuStatus();
    if (state.scene3dEditor) {
      state.scene3dEditor.setBlendFilePath(result.settings?.scene3d?.blend_file_path);
    }
    const label = result.relative_path || result.path || "scene.blend";
    showToast(`Opened in Blender: ${label}`);
  } catch {
    // api() already shows the error toast.
  }
}

function renderBlenderMenuStatus() {
  if (!el.blMenuSummary) return;
  el.blMenuSummary.classList.remove("bl-ok", "bl-warn");
  if (!state.project) {
    if (el.blMenuStatus) el.blMenuStatus.textContent = "No project open";
    el.blMenuSummary.title = "Blender";
    return;
  }
  const blendPath = state.project.settings?.scene3d?.blend_file_path || "scene3d/scene.blend";
  const hasBlender =
    state.project.settings?.blender_path || localStorage.getItem("blender_path_default");
  if (blendPath) {
    el.blMenuSummary.classList.add("bl-ok");
    if (el.blMenuStatus) {
      el.blMenuStatus.textContent = hasBlender ? blendPath : `${blendPath} · set Blender path`;
    }
    el.blMenuSummary.title = hasBlender ? `Scene: ${blendPath}` : "Set Blender path in Settings";
  } else {
    el.blMenuSummary.classList.add("bl-warn");
    if (el.blMenuStatus) el.blMenuStatus.textContent = "Add scene_template.blend to assets/";
    el.blMenuSummary.title = "Missing scene template";
  }
}

async function openPhotoshopSettingsDialog() {
  const current =
    state.project?.settings?.photoshop_path || localStorage.getItem("photoshop_path_default") || "";
  let candidates = [];
  try {
    const result = await api("/api/system/photoshop-candidates");
    candidates = result.candidates || [];
  } catch {
    candidates = [];
  }
  const photoshopPath = await showDialog({
    title: "Photoshop path",
    hint: "Choose the local Photoshop executable. Leave empty to use the system default app for PSD files.",
    input: {
      label: "Path",
      value: current,
      placeholder: "e.g. C:\\Program Files\\Adobe\\Adobe Photoshop 2024\\Photoshop.exe",
      clearLabel: "Clear (use system default)",
    },
    browse: "photoshop",
    list: {
      title: "Detected installations",
      items: candidates.map((path) => ({
        name: pathBasename(path),
        path,
        subtitle: pathDirname(path),
      })),
    },
    actions: [
      { label: "Cancel", value: null },
      { label: "Save", value: "save", primary: true },
    ],
  });
  if (photoshopPath === null) return;
  try {
    if (state.project) {
      await api("/api/project/settings", {
        method: "PATCH",
        body: JSON.stringify({ photoshop_path: photoshopPath }),
      }).then(setProject);
    }
    if (photoshopPath) {
      localStorage.setItem("photoshop_path_default", photoshopPath);
    } else {
      localStorage.removeItem("photoshop_path_default");
    }
    showToast(
      photoshopPath
        ? `Photoshop path saved: ${photoshopPath}`
        : "Path cleared. PSD files will open with the system default app.",
    );
  } catch {
    // api() already shows the error toast.
  }
}

function applyProjectShotsFromServer(project) {
  if (!state.project || !project?.shots) return;
  const selectedId = state.selectedShotId;
  state.project.shots = project.shots;
  if (typeof project.dirty === "boolean") {
    state.project.dirty = project.dirty;
  }
  if (selectedId && !state.project.shots.some((shot) => shot.shot_id === selectedId)) {
    state.selectedShotId = state.project.shots[0]?.shot_id || null;
  }
}

function setProject(project, shouldRender = true) {
  if (!project) {
    state.project = null;
    state.scene3dLoadedKey = null;
    stopLiveBridgeHeartbeat();
    stopBridgeStatusPolling();
    stopSyncPolling();
    if (shouldRender) render();
    return;
  }
  const prevProjectPath = state.project?.project_json_path || null;
  state.project = project;
  if (project.project_json_path !== prevProjectPath) {
    state.scene3dLoadedKey = null;
  }
  if (!project.shots.some((shot) => shot.shot_id === state.selectedShotId)) {
    state.selectedShotId = project.shots[0]?.shot_id || null;
  }
  const storedDefault = localStorage.getItem("photoshop_path_default") || "";
  if (!project.settings.photoshop_path && storedDefault) {
    project.settings.photoshop_path = storedDefault;
  }
  const blenderDefault = localStorage.getItem("blender_path_default") || "";
  if (!project.settings.blender_path && blenderDefault) {
    project.settings.blender_path = blenderDefault;
  }
  if (project.project_json_path) {
    rememberProjectPath(project.project_json_path);
  }
  fillStatusOptions();
  el.pdfLayout.value = project.settings?.pdf_layout || "two_per_page";
  if (typeof restoreRefSegmentFromProject === "function") restoreRefSegmentFromProject();
  if (project.settings?.canvas_background_color) {
    rememberCanvasColor(project.settings.canvas_background_color);
  }
  applyCanvasAspectRatio(getProjectCanvasSize(project));
  applyCanvasColor();
  refreshMissingFiles();
  startSyncPolling();
  startLiveBridgeHeartbeat();
  startBridgeStatusPolling();
  saveAppSessionSoon();
  if (shouldRender) {
    requestAnimationFrame(() => render());
  }
}

let selectShotSeq = 0;
let pendingShotSyncTimer = null;

function scheduleRenderForShotChange(seq) {
  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      if (seq !== selectShotSeq) return;
      renderForShotChange();
      if (isScene3dOpen() && state.scene3dEditor && state.selectedShotId) {
        const shot = state.project?.shots.find((item) => item.shot_id === state.selectedShotId);
        const time = shot?.camera_data?.scene3d_time;
        if (time != null && time !== "" && !Number.isNaN(Number(time))) {
          state.scene3dEditor.setAnimationTime(Number(time));
        }
        state.scene3dEditor.refreshBoardPreview();
      }
    });
  });
}

function renderForShotChange() {
  const shots = state.project?.shots || [];
  const shot = selectedShot();
  renderBoardInfo();
  renderInspector(shot);
  renderPreview(shot);
  renderReferences(shot);
  if (typeof renderReferenceLinks === "function") renderReferenceLinks();
  renderFileStatus(shot);
  renderComments(shot);
  updateTimelineMeta(shots, state.selectedShotId);
  updateAnnotationControls();
  drawAnnotations();
  refreshAppStatus();
}

function scheduleBackgroundSync(shotId, seq) {
  window.clearTimeout(pendingShotSyncTimer);
  if (!shotId) return;
  pendingShotSyncTimer = window.setTimeout(() => {
    if (seq !== selectShotSeq || state.selectedShotId !== shotId) return;
    syncShot(shotId, false, { silent: true });
  }, 280);
}

async function selectShot(shotId, shouldRender = true) {
  const seq = ++selectShotSeq;
  state.selectedShotId = shotId;
  if (typeof patchTimelineActiveState === "function") patchTimelineActiveState(shotId, { force: true });
  if (shotId && annotationCache.has(shotId)) {
    state.annotations = annotationCache.get(shotId);
  } else {
    state.annotations = [];
  }
  saveAppSessionSoon();
  if (shouldRender) scheduleRenderForShotChange(seq);
  window.setTimeout(() => loadAnnotations(shotId), 0);
  scheduleBackgroundSync(shotId, seq);
}

function selectedShot() {
  return state.project?.shots.find((shot) => shot.shot_id === state.selectedShotId) || null;
}

function readInspectorIntoShot(shot) {
  shot.title = el.title.value;
  shot.scene = el.scene.value;
  shot.sequence = el.sequence.value;
  shot.status = el.status.value || "Draft";
  shot.description = el.description.value;
  shot.action_note = el.actionNote.value;
  shot.camera_note = el.cameraNote.value;
  const location = el.cameraLocation.value;
  const rotationText = el.cameraRotation.value;
  shot.camera_data = {
    ...(shot.camera_data || {}),
    angle: el.cameraAngle.value,
    focal_length: el.cameraFocalLength.value,
    location,
    rotation_text: rotationText,
  };
  const position = parseCameraVec(location);
  if (position) shot.camera_data.position = position;
  const rotation = parseCameraVec(rotationText);
  if (rotation) shot.camera_data.rotation = rotation;
  shot.character_note = el.characterNote.value;
  shot.dialogue = el.dialogue.value;
  shot.lighting_note = el.lightingNote.value;
  shot.transition_note = el.transitionNote.value;
  shot.duration_seconds = Number(el.durationSeconds.value || 3);
  shot.tags = el.tags.value.split(",").map((tag) => tag.trim()).filter(Boolean);
}

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
  updateAnnotationControls();
  drawAnnotations();
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

function renderPreview(shot) {
  applyCanvasColor();
  layoutAnnotationCanvas();
  el.canvasBoard.querySelectorAll("img, .canvas-placeholder").forEach((node) => node.remove());
  el.canvasBoard.classList.remove("canvas-openable");
  if (!state.project) {
    renderCanvasPlaceholder("No project open");
    return;
  }
  if (!shot) {
    renderCanvasPlaceholder("No shot selected");
    return;
  }
  el.canvasBoard.classList.add("canvas-openable");
  const hasPreview = hasArtworkPreview(shot);
  const hasSource = Boolean(shot.source_file_path);
  const displayUrl = shotCanvasDisplayUrl(shot);
  if (!hasPreview && !displayUrl) {
    if (hasSource) {
      renderCanvasPlaceholder("Click to open in Photoshop");
    } else {
      renderCanvasPlaceholder("Click to create canvas and open in Photoshop");
    }
    return;
  }
  const image = document.createElement("img");
  image.alt = shot.shot_id;
  image.src = displayUrl || shotPreviewUrl(shot);
  image.onerror = () => {
    el.canvasBoard.querySelectorAll("img, .canvas-placeholder").forEach((node) => node.remove());
    renderCanvasPlaceholder("Preview file missing");
    layoutAnnotationCanvas();
    drawAnnotations();
  };
  image.onload = () => {
    layoutAnnotationCanvas();
    updateAnnotationControls();
    drawAnnotations();
  };
  el.canvasBoard.appendChild(image);
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

try {
  bindTimelineEvents();
  bindAnimaticEvents();
  bindThemeUi();
  bindToolbarMenus();
  bindUndoUi();
  window.setStartupProgress?.(58, "Storyboard Tool", "Applying layout");
  applyCanvasColor();
  refreshAppStatus();
  window.setStartupProgress?.(66, "Storyboard Tool", "Restoring session");
  window.setTimeout(() => {
    restoreLastProjectOnStartup()
      .catch((error) => {
        console.warn("Startup session restore failed:", error);
      })
      .finally(() => {
        window.finishStartupOverlay?.("Ready");
      });
  }, 0);
} catch (error) {
  console.error("Startup init failed:", error);
  window.failStartupOverlay?.("Startup failed");
}
