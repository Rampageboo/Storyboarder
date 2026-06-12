const state = {
  project: null,
  selectedShotId: null,
  saveTimer: null,
  missingFiles: [],
  statusFilter: "",
  revisionOnly: false,
  animaticTimer: null,
  animaticStartedAt: 0,
  animaticOffset: 0,
  timelineCursor: 0,
  annotations: [],
  annotationTool: "select",
  annotationsVisible: true,
  drawing: null,
  syncPollTimer: null,
  liveBridgeTimer: null,
  bridgeStatusTimer: null,
  isSyncing: false,
  scene3dEditor: null,
};

const el = {
  newProject: document.querySelector("#newProject"),
  openProject: document.querySelector("#openProject"),
  saveProject: document.querySelector("#saveProject"),
  setCanvas: document.querySelector("#setCanvas"),
  linkPhotoshop: document.querySelector("#linkPhotoshop"),
  psMenuSummary: document.querySelector("#psMenuSummary"),
  psMenuStatus: document.querySelector("#psMenuStatus"),
  setPhotoshop: document.querySelector("#setPhotoshop"),
  openBlender: document.querySelector("#openBlender"),
  setBlender: document.querySelector("#setBlender"),
  blMenuSummary: document.querySelector("#blMenuSummary"),
  blMenuStatus: document.querySelector("#blMenuStatus"),
  openBlenderScene: document.querySelector("#openBlenderScene"),
  pdfLayout: document.querySelector("#pdfLayout"),
  exportPdf: document.querySelector("#exportPdf"),
  exportShotList: document.querySelector("#exportShotList"),
  exportContactSheet: document.querySelector("#exportContactSheet"),
  exportTiming: document.querySelector("#exportTiming"),
  exportImageSequence: document.querySelector("#exportImageSequence"),
  boardInfo: document.querySelector("#boardInfo"),
  boardCount: document.querySelector("#boardCount"),
  projectStats: document.querySelector("#projectStats"),
  syncStatus: document.querySelector("#syncStatus"),
  statusFilter: document.querySelector("#statusFilter"),
  revisionFilter: document.querySelector("#revisionFilter"),
  addShot: document.querySelector("#addShot"),
  shotContextMenu: document.querySelector("#shotContextMenu"),
  prevShot: document.querySelector("#prevShot"),
  nextShot: document.querySelector("#nextShot"),
  previewBox: document.querySelector("#previewBox"),
  canvasSurface: document.querySelector("#canvasSurface"),
  canvasBoard: document.querySelector("#canvasBoard"),
  drawingCanvas: document.querySelector("#drawingCanvas"),
  annotationCanvas: document.querySelector("#annotationCanvas"),
  importImage: document.querySelector("#importImage"),
  removeImage: document.querySelector("#removeImage"),
  addReference: document.querySelector("#addReference"),
  importSource: document.querySelector("#importSource"),
  relinkPreview: document.querySelector("#relinkPreview"),
  openPreview: document.querySelector("#openPreview"),
  refreshPreview: document.querySelector("#refreshPreview"),
  imageFile: document.querySelector("#imageFile"),
  referenceFile: document.querySelector("#referenceFile"),
  sourceFile: document.querySelector("#sourceFile"),
  fileStatus: document.querySelector("#fileStatus"),
  referenceStrip: document.querySelector("#referenceStrip"),
  playAnimatic: document.querySelector("#playAnimatic"),
  stopAnimatic: document.querySelector("#stopAnimatic"),
  timeDisplay: document.querySelector("#timeDisplay"),
  progressSlider: document.querySelector("#progressSlider"),
  timelineStrip: document.querySelector("#timelineStrip"),
  dialogColorSection: document.querySelector("#dialogColorSection"),
  dialogColorGray: document.querySelector("#dialogColorGray"),
  dialogColorHex: document.querySelector("#dialogColorHex"),
  dialogColorPreview: document.querySelector("#dialogColorPreview"),
  shotLabel: document.querySelector("#shotLabel"),
  shotId: document.querySelector("#shotId"),
  title: document.querySelector("#title"),
  scene: document.querySelector("#scene"),
  sequence: document.querySelector("#sequence"),
  status: document.querySelector("#status"),
  description: document.querySelector("#description"),
  actionNote: document.querySelector("#actionNote"),
  cameraNote: document.querySelector("#cameraNote"),
  cameraAngle: document.querySelector("#cameraAngle"),
  cameraFocalLength: document.querySelector("#cameraFocalLength"),
  cameraLocation: document.querySelector("#cameraLocation"),
  cameraRotation: document.querySelector("#cameraRotation"),
  characterNote: document.querySelector("#characterNote"),
  dialogue: document.querySelector("#dialogue"),
  lightingNote: document.querySelector("#lightingNote"),
  transitionNote: document.querySelector("#transitionNote"),
  durationSeconds: document.querySelector("#durationSeconds"),
  tags: document.querySelector("#tags"),
  commentList: document.querySelector("#commentList"),
  commentText: document.querySelector("#commentText"),
  addComment: document.querySelector("#addComment"),
  toast: document.querySelector("#toast"),
  dialogModal: document.querySelector("#dialogModal"),
  dialogTitle: document.querySelector("#dialogTitle"),
  dialogHint: document.querySelector("#dialogHint"),
  dialogInputSection: document.querySelector("#dialogInputSection"),
  dialogInputLabel: document.querySelector("#dialogInputLabel"),
  dialogInput: document.querySelector("#dialogInput"),
  dialogBrowseBtn: document.querySelector("#dialogBrowseBtn"),
  dialogError: document.querySelector("#dialogError"),
  dialogListSection: document.querySelector("#dialogListSection"),
  dialogListTitle: document.querySelector("#dialogListTitle"),
  dialogList: document.querySelector("#dialogList"),
  dialogFooter: document.querySelector("#dialogFooter"),
  openScene3d: document.querySelector("#openScene3d"),
  scene3dModal: document.querySelector("#scene3dModal"),
  scene3dRoot: document.querySelector("#scene3dRoot"),
  saveScene3d: document.querySelector("#saveScene3d"),
  importScene3d: document.querySelector("#importScene3d"),
  scene3dFile: document.querySelector("#scene3dFile"),
};

const dialogState = {
  resolve: null,
  browse: null,
  validate: null,
  hasInput: false,
  listItems: [],
};

const contextMenuState = {
  shotId: null,
};

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
});

updateShotPanelScrollMode();

el.shotContextMenu?.querySelectorAll("[data-shot-action]").forEach((button) => {
  button.addEventListener("click", async () => {
    const shotId = contextMenuState.shotId;
    hideShotContextMenu();
    if (!shotId) return;
    if (button.dataset.shotAction === "duplicate") {
      await duplicateShotById(shotId);
      return;
    }
    if (button.dataset.shotAction === "delete") {
      await deleteShotById(shotId);
    }
  });
});

document.addEventListener("click", (event) => {
  if (el.shotContextMenu?.contains(event.target)) return;
  hideShotContextMenu();
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") hideShotContextMenu();
});
document.addEventListener("scroll", () => hideShotContextMenu(), true);

document.querySelectorAll("[data-dialog-cancel]").forEach((node) => {
  node.addEventListener("click", () => closeDialog(null));
});
el.dialogModal.addEventListener("keydown", (event) => {
  if (event.key === "Escape") closeDialog(null);
  if (event.key === "Enter" && dialogState.hasInput && !event.shiftKey) {
    const primary = el.dialogFooter.querySelector(".btn-primary");
    if (primary && document.activeElement === el.dialogInput) {
      event.preventDefault();
      primary.click();
    }
  }
});
el.dialogBrowseBtn.addEventListener("click", () => browseFromDialog());

el.newProject.addEventListener("click", () => openNewProjectDialog());
el.openProject.addEventListener("click", () => openOpenProjectDialog());

el.saveProject.addEventListener("click", async () => {
  await flushSelectedShot();
  await api("/api/project/save", { method: "POST" }).then(setProject);
  showToast("Project saved.");
});

el.setCanvas.addEventListener("click", () => openCanvasSettingsDialog());
el.openScene3d.addEventListener("click", () => openScene3dModal());
el.saveScene3d.addEventListener("click", () => saveScene3dData());
el.importScene3d.addEventListener("click", () => el.scene3dFile.click());
el.scene3dFile.addEventListener("change", () => importBlenderScene(el.scene3dFile.files?.[0]));
document.querySelectorAll("[data-scene3d-close]").forEach((node) => {
  node.addEventListener("click", () => closeScene3dModal());
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !el.scene3dModal.hidden) {
    closeScene3dModal();
  }
});
el.linkPhotoshop?.addEventListener("click", () => relinkPhotoshopBridge());
el.setPhotoshop?.addEventListener("click", () => openPhotoshopSettingsDialog());
el.openBlender?.addEventListener("click", () => openProjectInBlender());
el.setBlender?.addEventListener("click", () => openBlenderSettingsDialog());
el.openBlenderScene?.addEventListener("click", () => openProjectInBlender());

el.exportPdf.addEventListener("click", async () => {
  await flushSelectedShot();
  const result = await api("/api/export/pdf", {
    method: "POST",
    body: JSON.stringify({ layout: el.pdfLayout.value || "two_per_page" }),
  });
  showToast(`PDF exported: ${result.path}`);
  window.open(result.download_url, "_blank");
});

el.exportShotList.addEventListener("click", () => runDownloadExport("/api/export/shot-list"));
el.exportContactSheet.addEventListener("click", () => runDownloadExport("/api/export/contact-sheet"));
el.exportTiming.addEventListener("click", () => runDownloadExport("/api/export/timing"));
el.exportImageSequence.addEventListener("click", async () => {
  await flushSelectedShot();
  const result = await api("/api/export/image-sequence", { method: "POST" });
  showToast(`Image sequence exported: ${result.path}`);
});

el.addShot.addEventListener("click", () => addShot());

async function addShot(afterShotId = null) {
  await flushSelectedShot();
  const body = afterShotId ? { after_shot_id: afterShotId } : {};
  const result = await api("/api/shots", { method: "POST", body: JSON.stringify(body) });
  setProject(result);
  await selectShot(result.shot.shot_id);
  scrollTimelineToShot(result.shot.shot_id);
  showToast(boardAddedToast(result.shot.shot_id));
}

function formatShotId(shotId) {
  const value = String(shotId || "");
  if (value.length <= 12) return value;
  return `${value.slice(0, 8)}…`;
}

function boardAddedToast(shotId) {
  const shots = state.project?.shots || [];
  const index = shots.findIndex((shot) => shot.shot_id === shotId);
  const position = index >= 0 ? index + 1 : shots.length;
  const label = formatShotId(shotId);
  if (position !== shots.length) {
    return `Board inserted at #${position} (${label})`;
  }
  return `Board added: ${label}`;
}

function scrollTimelineToShot(shotId, behavior = "smooth") {
  if (!shotId || !el.timelineStrip) return;
  requestAnimationFrame(() => {
    const item = el.timelineStrip.querySelector(`[data-shot-id="${shotId}"]`);
    if (!item) return;
    item.scrollIntoView({ behavior, block: "nearest", inline: "nearest" });
  });
}

function createTimelineInsertButton(afterShotId) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "timeline-insert-shot";
  button.title = "Insert board here";
  button.textContent = "+";
  button.addEventListener("click", async (event) => {
    event.stopPropagation();
    stopAnimatic();
    await addShot(afterShotId);
  });
  return button;
}

el.prevShot.addEventListener("click", () => navigateShot(-1));
el.nextShot.addEventListener("click", () => navigateShot(1));
el.importImage.addEventListener("click", () => el.imageFile.click());
el.addReference.addEventListener("click", () => el.referenceFile.click());
el.importSource.addEventListener("click", () => el.sourceFile.click());
el.refreshPreview.addEventListener("click", () => {
  const shot = selectedShot();
  if (shot) syncShot(shot.shot_id, true);
});

el.statusFilter.addEventListener("change", () => {
  state.statusFilter = el.statusFilter.value;
  renderTimeline();
});

el.revisionFilter.addEventListener("change", () => {
  state.revisionOnly = el.revisionFilter.checked;
  renderTimeline();
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

el.relinkPreview.addEventListener("click", () => openRelinkPreviewDialog());

el.previewBox.addEventListener("click", (event) => {
  if (state.annotationTool !== "select") return;
  if (!event.target.closest("#canvasBoard")) return;
  if (!el.canvasBoard.classList.contains("canvas-openable")) return;
  openShotInPhotoshop();
});

el.canvasBoard.addEventListener("contextmenu", (event) => {
  const shot = selectedShot();
  if (!shot || !state.project) return;
  event.preventDefault();
  showShotContextMenu(shot.shot_id, event.clientX, event.clientY);
});

el.openPreview.addEventListener("click", async () => {
  const shot = selectedShot();
  if (!shot) return;
  const result = await api(`/api/shots/${shot.shot_id}/open-preview`, { method: "POST" });
  showToast(`Opened: ${result.path}`);
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

el.playAnimatic.addEventListener("click", playAnimatic);
el.stopAnimatic.addEventListener("click", stopAnimatic);
el.progressSlider.addEventListener("input", () => {
  state.timelineCursor = Number(el.progressSlider.value || 0);
  stopAnimatic(false);
  selectShotAtTime(state.timelineCursor);
  renderTimeline();
  syncScene3dTimeline();
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

function navigateShot(delta) {
  const shots = state.project?.shots || [];
  if (!shots.length) return;
  const currentIndex = shots.findIndex((shot) => shot.shot_id === state.selectedShotId);
  const nextIndex = Math.min(Math.max((currentIndex < 0 ? 0 : currentIndex) + delta, 0), shots.length - 1);
  selectShot(shots[nextIndex].shot_id);
}

async function syncShot(shotId, force = false) {
  if (!shotId || state.isSyncing) return;
  state.isSyncing = true;
  try {
    const result = await api(`/api/shots/${shotId}/sync?force=${force}`, { method: "POST" });
    const syncResult = result.result || {};
    if (state.project && result.shots && !state.project.dirty) {
      applyProjectShotsFromServer(result);
    }
    if (syncResult.synced) {
      setProject(result, false);
      state.selectedShotId = shotId;
      showSyncStatus(syncResult.message || "Synced preview from Photoshop.");
      renderPreview(selectedShot());
      renderTimeline();
    } else if (force) {
      showSyncStatus(syncResult.message || "No changes to sync.");
      renderTimeline();
    } else {
      showSyncStatus("");
    }
  } catch {
    showSyncStatus("");
  } finally {
    state.isSyncing = false;
  }
}

function showSyncStatus(message) {
  if (!el.syncStatus) return;
  el.syncStatus.textContent = message || "";
  el.syncStatus.classList.toggle("synced", Boolean(message));
}

function startSyncPolling() {
  stopSyncPolling();
  state.syncPollTimer = window.setInterval(() => {
    if (state.selectedShotId) {
      syncShot(state.selectedShotId);
    }
  }, 3000);
}

function stopSyncPolling() {
  window.clearInterval(state.syncPollTimer);
  state.syncPollTimer = null;
}

window.addEventListener("focus", async () => {
  if (state.selectedShotId) {
    syncShot(state.selectedShotId);
    return;
  }
  if (state.project && !state.project.dirty) {
    try {
      const project = await api("/api/project", { silent: true });
      if (project?.shots) {
        applyProjectShotsFromServer(project);
        renderTimeline();
        renderBoardInfo();
      }
    } catch {
      // Ignore background refresh errors.
    }
  }
});

async function runDownloadExport(url) {
  await flushSelectedShot();
  const result = await api(url, { method: "POST" });
  showToast(`Exported: ${result.path}`);
  if (result.download_url) window.open(result.download_url, "_blank");
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
  if (!state.project?.project_json_path) return;
  const session = await api("/api/app/session", {
    method: "PUT",
    body: JSON.stringify({
      last_project_json_path: state.project.project_json_path,
      selected_shot_id: state.selectedShotId || "",
    }),
    silent: true,
  });
  if (Array.isArray(session.recent_projects) && session.recent_projects.length) {
    localStorage.setItem("recent_projects", JSON.stringify(session.recent_projects));
  }
}

async function publishLiveBridge() {
  if (!state.project) return;
  await api("/api/bridge/live", {
    method: "PUT",
    body: JSON.stringify({ selected_shot_id: state.selectedShotId || "" }),
    silent: true,
  });
}

function startLiveBridgeHeartbeat() {
  stopLiveBridgeHeartbeat();
  publishLiveBridge().catch(() => {});
  state.liveBridgeTimer = window.setInterval(() => {
    publishLiveBridge().catch(() => {});
  }, 2000);
}

function stopLiveBridgeHeartbeat() {
  window.clearInterval(state.liveBridgeTimer);
  state.liveBridgeTimer = null;
}

function renderPsBridgeState(mode, message) {
  if (!el.psMenuSummary) return;
  el.psMenuSummary.classList.remove("ps-ok", "ps-error");
  if (mode === "ok") {
    el.psMenuSummary.classList.add("ps-ok");
  } else if (mode === "error") {
    el.psMenuSummary.classList.add("ps-error");
  }
  if (el.psMenuStatus) {
    el.psMenuStatus.textContent = message;
  }
  el.psMenuSummary.title = message;
}

function updateBridgeLinkStatus(status) {
  if (!status?.project_open) {
    renderPsBridgeState("idle", "No project open");
    return;
  }
  if (status.plugin_linked) {
    renderPsBridgeState("ok", "Photoshop linked");
    return;
  }
  renderPsBridgeState("error", "Waiting for Photoshop plugin");
}

async function refreshBridgeLinkStatus() {
  try {
    const status = await api("/api/bridge/status", { silent: true });
    updateBridgeLinkStatus(status);
  } catch {
    renderPsBridgeState("error", "Bridge offline");
  }
}

function startBridgeStatusPolling() {
  stopBridgeStatusPolling();
  refreshBridgeLinkStatus().catch(() => {});
  state.bridgeStatusTimer = window.setInterval(() => {
    refreshBridgeLinkStatus().catch(() => {});
  }, 2500);
}

function stopBridgeStatusPolling() {
  window.clearInterval(state.bridgeStatusTimer);
  state.bridgeStatusTimer = null;
  renderPsBridgeState("idle", "No project open");
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
  try {
    await whenDesktopBridgeReady();
    const session = await api("/api/app/session", { silent: true });
    if (Array.isArray(session.recent_projects) && session.recent_projects.length) {
      localStorage.setItem("recent_projects", JSON.stringify(session.recent_projects));
    }
    const path = String(session.last_project_json_path || "").trim();
    if (!path) return;
    const project = await api("/api/project/open", {
      method: "POST",
      body: JSON.stringify({ project_json_path: path }),
      silent: true,
    });
    setProject(project);
    const shotId = String(session.selected_shot_id || "").trim();
    if (shotId && project.shots?.some((shot) => shot.shot_id === shotId)) {
      await selectShot(shotId);
    }
    showToast(`Restored ${project.name}`);
  } catch (error) {
    console.warn("Session restore skipped:", error);
  }
}

function rememberProjectPath(projectJsonPath) {
  const recent = [projectJsonPath, ...getRecentProjects().filter((item) => item !== projectJsonPath)].slice(0, 10);
  localStorage.setItem("recent_projects", JSON.stringify(recent));
}

function pathBasename(value) {
  return value.split(/[/\\]/).pop() || value;
}

function pathDirname(value) {
  return value.replace(/[/\\][^/\\]+$/, "");
}

function setDialogError(message) {
  if (!message) {
    el.dialogError.hidden = true;
    el.dialogError.textContent = "";
    return;
  }
  el.dialogError.hidden = false;
  el.dialogError.textContent = message;
}

function renderDialogList(items, activePath, onSelect) {
  el.dialogList.innerHTML = "";
  if (!items.length) {
    el.dialogList.innerHTML = '<div class="dialog-item-empty">No matches found. Use Browse to pick a path.</div>';
    return;
  }
  const normalized = (activePath || "").trim().toLowerCase();
  items.forEach((item) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `dialog-item ${item.path?.toLowerCase() === normalized ? "active" : ""}`;
    button.dataset.path = item.path || "";
    button.innerHTML = `<span class="dialog-item-name">${escapeHtml(item.name || pathBasename(item.path))}</span><span class="dialog-item-path">${escapeHtml(item.subtitle || pathDirname(item.path))}</span>`;
    button.addEventListener("click", () => onSelect(item.path));
    el.dialogList.appendChild(button);
  });
}

function highlightDialogList(path) {
  const normalized = (path || "").trim().toLowerCase();
  el.dialogList.querySelectorAll(".dialog-item").forEach((button) => {
    button.classList.toggle("active", button.dataset.path?.toLowerCase() === normalized);
  });
}

function setDialogSections({ input = false, list = false, color = false } = {}) {
  el.dialogInputSection.hidden = !input;
  el.dialogListSection.hidden = !list;
  el.dialogColorSection.hidden = !color;
  if (!color) teardownCanvasColorControls();
}

function closeDialog(result) {
  el.dialogModal.hidden = true;
  setDialogSections();
  setDialogError("");
  const resolve = dialogState.resolve;
  dialogState.resolve = null;
  resolve?.(result);
  dialogState.browse = null;
  dialogState.validate = null;
  dialogState.hasInput = false;
  dialogState.listItems = [];
}

function showDialog(config) {
  return new Promise((resolve) => {
    dialogState.resolve = resolve;
    dialogState.browse = config.browse || null;
    dialogState.validate = config.validate || null;
    dialogState.listItems = config.list?.items || [];
    dialogState.hasInput = Boolean(config.input);

    el.dialogTitle.textContent = config.title || "";
    el.dialogHint.textContent = config.hint || "";
    el.dialogHint.hidden = !config.hint;
    setDialogSections({ input: Boolean(config.input), list: Boolean(config.list), color: false });

    if (config.input) {
      el.dialogInputLabel.textContent = config.input.label || "Path";
      el.dialogInput.value = config.input.value || "";
      el.dialogInput.placeholder = config.input.placeholder || "";
      el.dialogBrowseBtn.hidden = !config.browse;
    } else {
      el.dialogBrowseBtn.hidden = true;
    }

    if (config.list) {
      el.dialogListTitle.textContent = config.list.title || "";
      renderDialogList(config.list.items || [], config.input?.value || "", (path) => {
        if (config.input) el.dialogInput.value = path;
        setDialogError("");
        highlightDialogList(path);
      });
    } else {
      el.dialogList.innerHTML = "";
    }

    el.dialogFooter.innerHTML = "";
    if (config.input?.clearLabel) {
      const clearButton = document.createElement("button");
      clearButton.type = "button";
      clearButton.textContent = config.input.clearLabel;
      clearButton.addEventListener("click", () => {
        el.dialogInput.value = "";
        setDialogError("");
        highlightDialogList("");
      });
      el.dialogFooter.appendChild(clearButton);
    }

    const spacer = document.createElement("span");
    spacer.className = "modal-spacer";
    el.dialogFooter.appendChild(spacer);

    (config.actions || []).forEach((action) => {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = action.label;
      if (action.primary) button.classList.add("btn-primary");
      if (action.danger) button.classList.add("btn-danger");
      button.addEventListener("click", async () => {
        if (action.value === null || action.value === "cancel") {
          closeDialog(null);
          return;
        }
        if (config.input) {
          const value = el.dialogInput.value.trim();
          if (dialogState.validate) {
            const error = dialogState.validate(value);
            if (error) {
              setDialogError(error);
              return;
            }
          }
          if (action.submitValue !== undefined) {
            closeDialog(action.submitValue);
            return;
          }
          closeDialog(value);
          return;
        }
        closeDialog(action.value);
      });
      el.dialogFooter.appendChild(button);
    });

    setDialogError("");
    el.dialogModal.hidden = false;
    if (config.input) {
      el.dialogInput.focus();
      el.dialogInput.oninput = () => {
        setDialogError("");
        highlightDialogList(el.dialogInput.value.trim());
      };
    }
  });
}

async function browseFromDialog() {
  const browseMap = {
    folder: "/api/system/browse-folder",
    "project-json": "/api/system/browse-project-json",
    photoshop: "/api/system/browse-photoshop",
    blender: "/api/system/browse-blender",
  };
  const endpoint = browseMap[dialogState.browse];
  if (!endpoint) return;
  el.dialogBrowseBtn.disabled = true;
  setDialogError("Opening file picker…");
  try {
    const result = await api(endpoint, { method: "POST", silent: true });
    setDialogError("");
    if (result.cancelled) return;
    el.dialogInput.value = result.path || "";
    highlightDialogList(result.path || "");
  } catch (error) {
    const message =
      error.message === "Not Found"
        ? "Browse API unavailable. Restart the app (python main.py) and try again."
        : error.message;
    setDialogError(message);
  } finally {
    el.dialogBrowseBtn.disabled = false;
  }
}

async function confirmUnsaved() {
  if (!state.project?.dirty) return true;
  const choice = await showDialog({
    title: "Unsaved changes",
    hint: "This project has unsaved changes. Save before continuing?",
    actions: [
      { label: "Cancel", value: null },
      { label: "Don't save", value: "discard" },
      { label: "Save and continue", value: "save", primary: true },
    ],
  });
  if (!choice) return false;
  if (choice === "save") {
    await flushSelectedShot();
    await api("/api/project/save", { method: "POST" }).then(setProject);
  }
  return true;
}

async function openNewProjectDialog() {
  if (!(await confirmUnsaved())) return;
  const parentPath = await showDialog({
    title: "New project",
    hint: "Choose a parent folder. A Storyboard_Project folder will be created inside it. Leave empty to use the current working directory.",
    input: {
      label: "Parent folder",
      value: localStorage.getItem("last_project_parent") || "",
      placeholder: "Empty = ./Storyboard_Project",
    },
    browse: "folder",
    actions: [
      { label: "Cancel", value: null },
      { label: "Create", value: "create", primary: true },
    ],
  });
  if (parentPath === null) return;
  try {
    await api("/api/project/new", {
      method: "POST",
      body: JSON.stringify({ path: parentPath || null }),
    }).then(setProject);
    if (parentPath) localStorage.setItem("last_project_parent", parentPath);
    showToast("Project created.");
  } catch {
    // api() already toasts
  }
}

async function openOpenProjectDialog() {
  if (!(await confirmUnsaved())) return;
  const recent = getRecentProjects();
  const projectJsonPath = await showDialog({
    title: "Open project",
    hint: "Choose a project.json file or pick from recent projects.",
    input: {
      label: "project.json path",
      value: recent[0] || "",
      placeholder: "e.g. D:\\MyProject\\Storyboard_Project\\project.json",
    },
    browse: "project-json",
    list: recent.length
      ? {
          title: "Recent projects",
          items: recent.map((path) => ({
            name: pathBasename(pathDirname(path)) || pathBasename(path),
            path,
            subtitle: pathDirname(path),
          })),
        }
      : undefined,
    validate: (value) => (value ? null : "Choose a project.json file."),
    actions: [
      { label: "Cancel", value: null },
      { label: "Open", value: "open", primary: true },
    ],
  });
  if (!projectJsonPath) return;
  try {
    await api("/api/project/open", {
      method: "POST",
      body: JSON.stringify({ project_json_path: projectJsonPath }),
    }).then(setProject);
    rememberProjectPath(projectJsonPath);
    showToast("Project opened.");
  } catch {
    // api() already toasts
  }
}

const canvasColorState = {
  gray: 232,
  wired: false,
  previewing: false,
  savedColor: "#E8E8E8",
};

const CANVAS_COLOR_STORAGE_KEY = "storyboard_canvas_color";

function canvasColor() {
  const fromProject = state.project?.settings?.canvas_background_color;
  if (fromProject) return normalizeHexColor(fromProject);
  const stored = localStorage.getItem(CANVAS_COLOR_STORAGE_KEY);
  return normalizeHexColor(stored || "#E8E8E8");
}

function hasArtworkPreview(shot) {
  return Boolean(shot?.preview_image_path || shot?.image_path);
}

function timelineThumbStyle(shot) {
  const color = canvasColor();
  if (!hasArtworkPreview(shot)) {
    return `style="background-color:${color}"`;
  }
  return `style="background-color:${color};background-image:url('/api/shots/${shot.shot_id}/thumbnail?t=${Date.now()}')"`;
}

function applyCanvasColor(hex = canvasColor()) {
  const color = normalizeHexColor(hex);
  document.documentElement.style.setProperty("--canvas-color", color);
  if (el.canvasBoard) {
    el.canvasBoard.style.setProperty("background-color", color, "important");
  }
}

function isValidHexColor(value) {
  return /^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/.test(String(value || "").trim());
}

function normalizeHexColor(value, fallback = "#E8E8E8") {
  const candidate = String(value || "").trim();
  if (!isValidHexColor(candidate)) return fallback;
  if (candidate.length === 4) {
    const chars = candidate.slice(1);
    return `#${chars.split("").map((char) => char + char).join("").toUpperCase()}`;
  }
  return candidate.toUpperCase();
}

function hexToRgb(hex) {
  const normalized = normalizeHexColor(hex).slice(1);
  return {
    r: parseInt(normalized.slice(0, 2), 16),
    g: parseInt(normalized.slice(2, 4), 16),
    b: parseInt(normalized.slice(4, 6), 16),
  };
}

function rgbToHex(r, g, b) {
  const toHex = (value) => Math.max(0, Math.min(255, Math.round(value))).toString(16).padStart(2, "0");
  return `#${toHex(r)}${toHex(g)}${toHex(b)}`.toUpperCase();
}

function hexToGrayLevel(hex) {
  const { r, g, b } = hexToRgb(hex);
  return Math.round((r + g + b) / 3);
}

function grayLevelToHex(level) {
  const gray = Math.max(0, Math.min(255, Math.round(level)));
  return rgbToHex(gray, gray, gray);
}

function currentCanvasColorHex() {
  return grayLevelToHex(canvasColorState.gray);
}

function syncCanvasColorUi() {
  const hex = currentCanvasColorHex();
  if (el.dialogColorGray) el.dialogColorGray.value = String(canvasColorState.gray);
  if (el.dialogColorHex) el.dialogColorHex.value = hex;
  if (el.dialogColorPreview) el.dialogColorPreview.style.background = hex;
  if (canvasColorState.previewing) applyCanvasColor(hex);
}

function setCanvasColorFromHex(hex) {
  canvasColorState.gray = hexToGrayLevel(normalizeHexColor(hex));
  syncCanvasColorUi();
}

function onCanvasGrayInput() {
  canvasColorState.gray = Number(el.dialogColorGray.value || 0);
  setDialogError("");
  syncCanvasColorUi();
}

function onCanvasHexInput() {
  const value = el.dialogColorHex.value.trim();
  if (!isValidHexColor(value)) {
    setDialogError("Enter a valid hex color like #E8E8E8.");
    return;
  }
  setDialogError("");
  setCanvasColorFromHex(value);
}

function setupCanvasColorControls(initialHex) {
  teardownCanvasColorControls();
  setCanvasColorFromHex(initialHex);
  el.dialogColorGray.addEventListener("input", onCanvasGrayInput);
  el.dialogColorHex.addEventListener("input", onCanvasHexInput);
  canvasColorState.wired = true;
}

function teardownCanvasColorControls() {
  if (!canvasColorState.wired) return;
  el.dialogColorGray.removeEventListener("input", onCanvasGrayInput);
  el.dialogColorHex.removeEventListener("input", onCanvasHexInput);
  canvasColorState.wired = false;
}

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

async function createCanvasForShot(shotId) {
  const backgroundColor = canvasColor();
  const project = await api(`/api/shots/${shotId}/canvas`, {
    method: "POST",
    body: JSON.stringify({
      width: 1920,
      height: 1080,
      background_color: backgroundColor,
    }),
  });
  rememberCanvasColor(project?.settings?.canvas_background_color || backgroundColor);
  setProject(project, false);
  state.selectedShotId = shotId;
  applyCanvasColor();
  render();
  showToast(`Canvas created (${backgroundColor}). Click preview to open in Photoshop.`);
}

function finishCanvasColorPreview(savedColor) {
  canvasColorState.previewing = false;
  applyCanvasColor(savedColor);
}

function openCanvasColorDialog() {
  return new Promise((resolve) => {
    const initialColor = canvasColor();
    canvasColorState.savedColor = initialColor;
    canvasColorState.previewing = true;

    dialogState.resolve = (result) => {
      finishCanvasColorPreview(result ? normalizeHexColor(result) : initialColor);
      resolve(result);
    };
    dialogState.browse = null;
    dialogState.validate = null;
    dialogState.hasInput = false;

    el.dialogTitle.textContent = "Canvas color";
    el.dialogHint.textContent =
      "Sets the drawing canvas color for new boards, the in-app canvas, and Photoshop via Storyboard Bridge.";
    el.dialogHint.hidden = false;
    setDialogSections({ color: true });
    setupCanvasColorControls(initialColor);

    el.dialogFooter.innerHTML = "";
    const spacer = document.createElement("span");
    spacer.className = "modal-spacer";
    el.dialogFooter.appendChild(spacer);

    const cancelButton = document.createElement("button");
    cancelButton.type = "button";
    cancelButton.textContent = "Cancel";
    cancelButton.addEventListener("click", () => closeDialog(null));
    el.dialogFooter.appendChild(cancelButton);

    const saveButton = document.createElement("button");
    saveButton.type = "button";
    saveButton.textContent = "Save";
    saveButton.classList.add("btn-primary");
    saveButton.addEventListener("click", () => {
      const hex = currentCanvasColorHex();
      if (!isValidHexColor(hex)) {
        setDialogError("Enter a valid hex color like #E8E8E8.");
        return;
      }
      closeDialog(hex);
    });
    el.dialogFooter.appendChild(saveButton);

    setDialogError("");
    el.dialogModal.hidden = false;
    el.dialogColorGray.focus();
  });
}

function rememberCanvasColor(hex) {
  const normalized = normalizeHexColor(hex);
  localStorage.setItem(CANVAS_COLOR_STORAGE_KEY, normalized);
  if (state.project) {
    state.project.settings = state.project.settings || {};
    state.project.settings.canvas_background_color = normalized;
  }
  return normalized;
}

async function saveCanvasColorToServer(normalized) {
  return api("/api/project/canvas-color", {
    method: "POST",
    body: JSON.stringify({ color: normalized }),
  });
}

async function openCanvasSettingsDialog() {
  if (!state.project) return;
  const selectedColor = await openCanvasColorDialog();
  if (selectedColor === null) return;
  const normalized = rememberCanvasColor(selectedColor);
  applyCanvasColor(normalized);
  renderPreview(selectedShot());
  try {
    const result = await saveCanvasColorToServer(normalized);
    const saved = rememberCanvasColor(result.color || result.settings?.canvas_background_color || normalized);
    if (result.settings) {
      state.project.settings = { ...state.project.settings, ...result.settings };
    } else {
      state.project.settings = { ...state.project.settings, canvas_background_color: saved };
    }
    if (Array.isArray(result.shots)) {
      state.project.shots = result.shots;
    }
    applyCanvasColor(saved);
    render();
    publishLiveBridge().catch(() => {});
    showToast(`Canvas color saved: ${saved}`);
  } catch (error) {
    applyCanvasColor();
    showToast(error.message || "Could not save canvas color. Restart the app and try again.");
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
    el.blMenuSummary.title = hasBlender ? `Scene: ${blendPath}` : "Set Blender path in Bl Setup";
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

async function openShotInPhotoshop() {
  const shot = selectedShot();
  if (!shot || !state.project) return;
  if (!shot.source_file_path) {
    await createCanvasForShot(shot.shot_id);
  }
  const current = selectedShot();
  if (!current?.source_file_path) return;
  const result = await api(`/api/shots/${current.shot_id}/open-source`, { method: "POST" });
  showToast(`Opened in Photoshop: ${result.path}`);
}

async function duplicateShotById(shotId) {
  if (!state.project) return;
  await flushSelectedShot();
  const result = await api(`/api/shots/${shotId}/duplicate`, { method: "POST" });
  setProject(result);
  await selectShot(result.shot.shot_id);
  scrollTimelineToShot(result.shot.shot_id);
}

async function deleteShotById(shotId) {
  const shot = state.project?.shots.find((item) => item.shot_id === shotId);
  if (!shot) return;
  const confirmed = await showDialog({
    title: "Delete shot",
    hint: `Delete ${shot.shot_id}? Shot files will remain on disk.`,
    actions: [
      { label: "Cancel", value: null },
      { label: "Delete", value: "delete", primary: true, danger: true },
    ],
  });
  if (confirmed !== "delete") return;
  await api(`/api/shots/${shot.shot_id}`, { method: "DELETE" }).then(setProject);
  showToast(`Deleted ${shot.shot_id}.`);
}

function hideShotContextMenu() {
  if (!el.shotContextMenu) return;
  el.shotContextMenu.hidden = true;
  contextMenuState.shotId = null;
}

function showShotContextMenu(shotId, clientX, clientY) {
  if (!el.shotContextMenu || !state.project) return;
  contextMenuState.shotId = shotId;
  el.shotContextMenu.hidden = false;
  el.shotContextMenu.style.visibility = "hidden";
  const menuRect = el.shotContextMenu.getBoundingClientRect();
  const maxLeft = Math.max(8, window.innerWidth - menuRect.width - 8);
  const maxTop = Math.max(8, window.innerHeight - menuRect.height - 8);
  el.shotContextMenu.style.left = `${Math.min(clientX, maxLeft)}px`;
  el.shotContextMenu.style.top = `${Math.min(clientY, maxTop)}px`;
  el.shotContextMenu.style.visibility = "";
  el.shotContextMenu.querySelectorAll("button").forEach((button) => {
    button.disabled = !shotId;
  });
}

async function openRelinkPreviewDialog() {
  const shot = selectedShot();
  if (!shot) return;
  const relativePath = await showDialog({
    title: "Relink preview",
    hint: "Enter a project-relative path, e.g. shots/shot_001/shot_001_preview.png",
    input: {
      label: "Relative path",
      value: shot.preview_image_path || shot.image_path || "",
      placeholder: "shots/shot_001/shot_001_preview.png",
    },
    validate: (value) => (value ? null : "Enter a relative path."),
    actions: [
      { label: "Cancel", value: null },
      { label: "OK", value: "ok", primary: true },
    ],
  });
  if (!relativePath) return;
  try {
    await api(`/api/shots/${shot.shot_id}/relink-preview`, {
      method: "POST",
      body: JSON.stringify({ relative_path: relativePath }),
    }).then(setProject);
    selectShot(shot.shot_id);
    showToast("Preview relinked.");
  } catch {
    // api() already toasts
  }
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
    stopLiveBridgeHeartbeat();
    stopBridgeStatusPolling();
    stopSyncPolling();
    if (shouldRender) render();
    return;
  }
  state.project = project;
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
  if (project.settings?.canvas_background_color) {
    rememberCanvasColor(project.settings.canvas_background_color);
  }
  applyCanvasColor();
  refreshMissingFiles();
  startSyncPolling();
  startLiveBridgeHeartbeat();
  startBridgeStatusPolling();
  saveAppSessionSoon();
  if (shouldRender) render();
}

async function selectShot(shotId, shouldRender = true) {
  state.selectedShotId = shotId;
  state.annotations = [];
  saveAppSessionSoon();
  if (shotId) await syncShot(shotId);
  if (shouldRender) render();
  loadAnnotations(shotId);
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

  el.setCanvas.disabled = !hasProject;
  el.openScene3d.disabled = !hasProject;
  el.openBlender.disabled = !hasProject;
  el.setBlender.disabled = !hasProject;
  el.linkPhotoshop.disabled = !hasProject;
  el.setPhotoshop.disabled = !hasProject;

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
}

function filteredShots() {
  const shots = state.project?.shots || [];
  return shots.filter((shot) => {
    if (state.statusFilter && shot.status !== state.statusFilter) return false;
    if (state.revisionOnly && !(shot.comments || []).some((comment) => !comment.resolved)) return false;
    return true;
  });
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
  if (!hasPreview) {
    if (hasSource) {
      renderCanvasPlaceholder("Click to open in Photoshop");
    } else {
      renderCanvasPlaceholder("Click to create canvas and open in Photoshop");
    }
    return;
  }
  const image = document.createElement("img");
  image.alt = shot.shot_id;
  image.src = `/api/shots/${shot.shot_id}/image?t=${Date.now()}`;
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
    const image = document.createElement("img");
    image.alt = "Reference";
    image.src = `/api/files?path=${encodeURIComponent(path)}&t=${Date.now()}`;
    el.referenceStrip.appendChild(image);
  });
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

function renderTimeline(activeShotId = state.selectedShotId) {
  el.timelineStrip.innerHTML = "";
  const shots = state.project?.shots || [];
  const total = totalDuration(shots);
  const current = Math.min(currentAnimaticSeconds(), total);
  el.timeDisplay.textContent = `${current.toFixed(1)}s / ${total.toFixed(1)}s`;
  el.progressSlider.max = total.toFixed(1);
  el.progressSlider.value = current.toFixed(1);
  let cursor = 0;
  shots.forEach((shot, index) => {
    const duration = Number(shot.duration_seconds || 3);
    const start = cursor;
    const end = cursor + duration;
    cursor = end;

    const filteredOut =
      (state.statusFilter && shot.status !== state.statusFilter) ||
      (state.revisionOnly && !(shot.comments || []).some((comment) => !comment.resolved));
    const item = document.createElement("button");
    item.className = `timeline-shot ${shot.shot_id === activeShotId ? "active" : ""}${
      filteredOut ? " timeline-shot-filtered" : ""
    }`;
    item.draggable = true;
    item.dataset.shotId = shot.shot_id;
    item.dataset.index = String(index);
    item.style.width = `${Math.max(132, duration * 58)}px`;
    const thumbnailStyle = timelineThumbStyle(shot);
    const dialoguePreview = shot.dialogue
      ? `<span class="timeline-dialogue">${escapeHtml(shot.dialogue.slice(0, 40))}</span>`
      : "";
    item.innerHTML = `
      <div class="timeline-thumb" ${thumbnailStyle}>${hasArtworkPreview(shot) ? "" : ""}</div>
      <div class="timeline-meta">
        <strong>#${index + 1} ${escapeHtml(formatShotId(shot.shot_id))} ${escapeHtml(shot.title || "")}</strong>
        ${dialoguePreview}
        <div class="timeline-duration-row">
          <input class="timeline-duration" type="number" min="0.1" step="0.1" value="${duration.toFixed(1)}" aria-label="Duration seconds" />
          <span>s</span>
        </div>
        <span class="timeline-range">${start.toFixed(1)}s - ${end.toFixed(1)}s</span>
      </div>
    `;
    item.addEventListener("click", () => {
      stopAnimatic();
      selectShot(shot.shot_id);
    });
    item.addEventListener("contextmenu", (event) => {
      event.preventDefault();
      stopAnimatic();
      selectShot(shot.shot_id);
      showShotContextMenu(shot.shot_id, event.clientX, event.clientY);
    });
    item.addEventListener("dragstart", (event) => {
      event.dataTransfer.setData("text/plain", shot.shot_id);
      event.dataTransfer.effectAllowed = "move";
    });
    item.addEventListener("dragover", (event) => {
      event.preventDefault();
      item.classList.add("drag-over");
    });
    item.addEventListener("dragleave", () => {
      item.classList.remove("drag-over");
    });
    item.addEventListener("drop", async (event) => {
      event.preventDefault();
      item.classList.remove("drag-over");
      const draggedShotId = event.dataTransfer.getData("text/plain");
      if (draggedShotId && draggedShotId !== shot.shot_id) {
        await reorderShot(draggedShotId, shot.shot_id);
      }
    });
    const durationInput = item.querySelector(".timeline-duration");
    durationInput.addEventListener("click", (event) => event.stopPropagation());
    durationInput.addEventListener("change", async (event) => {
      event.stopPropagation();
      const value = Math.max(0.1, Number(durationInput.value || 3));
      shot.duration_seconds = value;
      if (shot.shot_id === state.selectedShotId) {
        el.durationSeconds.value = value;
      }
      state.project.dirty = true;
      await saveShot(shot);
      renderTimeline(activeShotId);
    });
    el.timelineStrip.appendChild(item);
    el.timelineStrip.appendChild(createTimelineInsertButton(shot.shot_id));
  });
}

function playAnimatic() {
  const shots = state.project?.shots || [];
  if (!shots.length) return;
  state.animaticStartedAt = performance.now();
  state.animaticOffset = Number(el.progressSlider.value || state.timelineCursor || 0);
  window.clearInterval(state.animaticTimer);
  state.animaticTimer = window.setInterval(tickAnimatic, 120);
  tickAnimatic();
}

function stopAnimatic(resetProgress = true) {
  window.clearInterval(state.animaticTimer);
  state.animaticTimer = null;
  if (resetProgress) {
    state.timelineCursor = 0;
    state.animaticOffset = 0;
    el.progressSlider.value = "0";
  } else {
    state.timelineCursor = Number(el.progressSlider.value || state.timelineCursor || 0);
  }
  renderTimeline();
}

function tickAnimatic() {
  const shots = state.project?.shots || [];
  const elapsed = currentAnimaticSeconds();
  const total = totalDuration(shots);
  if (elapsed >= total) {
    state.timelineCursor = 0;
    stopAnimatic();
    return;
  }
  state.timelineCursor = elapsed;
  syncScene3dTimeline();
  let cursor = 0;
  for (const shot of shots) {
    cursor += Number(shot.duration_seconds || 3);
    if (elapsed < cursor) {
      if (state.selectedShotId !== shot.shot_id) {
        state.selectedShotId = shot.shot_id;
        render();
        loadAnnotations(shot.shot_id);
      } else {
        renderTimeline(shot.shot_id);
      }
      return;
    }
  }
}

function currentAnimaticSeconds() {
  if (!state.animaticTimer) return state.timelineCursor || 0;
  return state.animaticOffset + (performance.now() - state.animaticStartedAt) / 1000;
}

function totalDuration(shots) {
  return shots.reduce((total, shot) => total + Number(shot.duration_seconds || 3), 0);
}

function selectShotAtTime(seconds) {
  const shots = state.project?.shots || [];
  let cursor = 0;
  for (const shot of shots) {
    cursor += Number(shot.duration_seconds || 3);
    if (seconds <= cursor) {
      state.selectedShotId = shot.shot_id;
      render();
      loadAnnotations(shot.shot_id);
      return;
    }
  }
  if (shots.length) {
    state.selectedShotId = shots[shots.length - 1].shot_id;
    render();
    loadAnnotations(state.selectedShotId);
  }
}

async function reorderShot(draggedShotId, targetShotId) {
  const shots = state.project?.shots || [];
  let from = shots.findIndex((shot) => shot.shot_id === draggedShotId);
  const to = shots.findIndex((shot) => shot.shot_id === targetShotId);
  if (from < 0 || to < 0 || from === to) return;
  stopAnimatic();
  while (from > to) {
    await api(`/api/shots/${draggedShotId}/move-up`, { method: "POST" }).then(setProject);
    from -= 1;
  }
  while (from < to) {
    await api(`/api/shots/${draggedShotId}/move-down`, { method: "POST" }).then(setProject);
    from += 1;
  }
  selectShot(draggedShotId);
}

function textNode(value) {
  const span = document.createElement("span");
  span.textContent = value;
  return span;
}

async function loadAnnotations(shotId) {
  if (!shotId) {
    state.annotations = [];
    drawAnnotations();
    return;
  }
  try {
    const result = await api(`/api/shots/${shotId}/annotations`);
    if (state.selectedShotId === shotId) {
      state.annotations = result.annotations || [];
      updateAnnotationControls();
      drawAnnotations();
    }
  } catch {
    state.annotations = [];
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
  const image = el.canvasBoard.querySelector("img");
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

function syncAnnotationLayout() {
  layoutAnnotationCanvas();
  drawAnnotations();
}

window.addEventListener("resize", syncAnnotationLayout);

if (el.previewBox && typeof ResizeObserver !== "undefined") {
  new ResizeObserver(syncAnnotationLayout).observe(el.previewBox);
}

let desktopBridgeReady = null;

function whenDesktopBridgeReady() {
  if (!window.pywebview) return Promise.resolve(null);
  if (window.pywebview.api?.request) return Promise.resolve(window.pywebview.api);
  if (!desktopBridgeReady) {
    desktopBridgeReady = new Promise((resolve) => {
      const finish = () => {
        resolve(window.pywebview?.api?.request ? window.pywebview.api : null);
      };
      window.addEventListener("pywebviewready", finish, { once: true });
      window.setTimeout(finish, 2000);
    });
  }
  return desktopBridgeReady;
}

async function bridgeUpload(bridge, url, formData) {
  const file = formData.get("file");
  if (!file || typeof file.arrayBuffer !== "function") {
    throw new Error("No file selected");
  }
  const buffer = await file.arrayBuffer();
  const bytes = Array.from(new Uint8Array(buffer));
  return bridge.upload_multipart(url, file.name, file.type || "application/octet-stream", bytes);
}

async function api(url, options = {}) {
  const { silent = false, headers: customHeaders, ...fetchOptions } = options;
  const bridge = await whenDesktopBridgeReady();

  if (bridge) {
    try {
      const method = (fetchOptions.method || "GET").toUpperCase();
      if (fetchOptions.body instanceof FormData) {
        return await bridgeUpload(bridge, url, fetchOptions.body);
      }
      const body =
        fetchOptions.body && typeof fetchOptions.body !== "string"
          ? JSON.stringify(fetchOptions.body)
          : fetchOptions.body || null;
      return await bridge.request(method, url, body);
    } catch (error) {
      const message = error?.message || String(error);
      if (!silent) showToast(message);
      throw error instanceof Error ? error : new Error(message);
    }
  }

  const headers = customHeaders ?? { "Content-Type": "application/json" };
  const response = await fetch(url, { ...fetchOptions, headers });
  if (!response.ok) {
    let message = response.statusText;
    try {
      const payload = await response.json();
      message = payload.detail || message;
    } catch {
      // Keep the HTTP status text when the server does not return JSON.
    }
    if (!silent) showToast(message);
    throw new Error(message);
  }
  return response.json();
}

function showToast(message) {
  el.toast.textContent = message;
  el.toast.hidden = false;
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => {
    el.toast.hidden = true;
  }, 3500);
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function formatCameraVec(value, asDegrees = false) {
  if (!Array.isArray(value) || value.length < 3) return "";
  return value
    .slice(0, 3)
    .map((item) => {
      const num = Number(item) || 0;
      return asDegrees ? num.toFixed(1) : num.toFixed(2);
    })
    .join(", ");
}

function parseCameraVec(text) {
  if (!text || typeof text !== "string") return null;
  const parts = text.split(",").map((item) => Number(item.trim()));
  if (parts.length < 3 || parts.some((item) => Number.isNaN(item))) return null;
  return parts.slice(0, 3);
}

function getShotCameraForScene3d() {
  const shot = selectedShot();
  if (!shot) return null;
  const data = { ...(shot.camera_data || {}) };
  if (!data.position && data.location) {
    data.position = parseCameraVec(data.location);
  }
  if (!data.rotation && data.rotation_text) {
    data.rotation = parseCameraVec(data.rotation_text);
  } else if (!Array.isArray(data.rotation) && typeof data.rotation === "string") {
    data.rotation = parseCameraVec(data.rotation);
  }
  if (!data.fov && data.focal_length) {
    const focal = Number(data.focal_length);
    if (!Number.isNaN(focal) && focal > 0) {
      const sensor = 36;
      data.fov = (2 * Math.atan(sensor / (2 * focal)) * 180) / Math.PI;
    }
  }
  return data.position ? data : null;
}

function applyShotCameraFromScene3d(cameraState) {
  const shot = selectedShot();
  if (!shot || !cameraState) return;
  const positionText = formatCameraVec(cameraState.position);
  const targetText = formatCameraVec(cameraState.target);
  const rotationText = formatCameraVec(cameraState.rotation, true);
  shot.camera_data = {
    ...(shot.camera_data || {}),
    position: cameraState.position,
    target: cameraState.target,
    rotation: cameraState.rotation,
    rotation_text: rotationText,
    fov: cameraState.fov,
    focal_length: String(cameraState.focal_length ?? ""),
    location: positionText,
    angle: targetText,
  };
  saveShot(shot).then(() => {
    renderInspector(shot);
    showToast("已保存镜头相机到当前分镜");
  });
}

async function loadScene3DEditorClass() {
  if (loadScene3DEditorClass.cached) return loadScene3DEditorClass.cached;
  try {
    const module = await import("./scene3d.js");
    loadScene3DEditorClass.cached = module.Scene3DEditor;
    return loadScene3DEditorClass.cached;
  } catch (error) {
    console.error("Failed to load 3D scene module:", error);
    showToast("3D 模块加载失败，请重启应用。New/Open 功能不受影响。");
    throw error;
  }
}

async function openScene3dModal() {
  if (!state.project) return;
  el.scene3dModal.hidden = false;
  if (!state.scene3dEditor) {
    let Scene3DEditor;
    try {
      Scene3DEditor = await loadScene3DEditorClass();
    } catch {
      el.scene3dModal.hidden = true;
      return;
    }
    state.scene3dEditor = new Scene3DEditor(el.scene3dRoot, {
      getShotCamera: () => getShotCameraForScene3d(),
      onApplyShotCamera: (cameraState) => applyShotCameraFromScene3d(cameraState),
      onImportBlender: () => el.scene3dFile.click(),
      onOpenBlender: () => openProjectInBlender(),
      onMessage: (message) => showToast(message),
      getTimelineSeconds: () => currentAnimaticSeconds(),
      getTimelineTotal: () => totalDuration(state.project?.shots || []),
    });
  }
  await state.scene3dEditor.loadSceneData(state.project.settings?.scene3d || null);
  state.scene3dEditor.setBlendFilePath(state.project.settings?.scene3d?.blend_file_path);
  syncScene3dTimeline();
}

async function importBlenderScene(file) {
  if (!file || !state.project) return;
  const formData = new FormData();
  formData.append("file", file);
  try {
    const bridge = await whenDesktopBridgeReady();
    let result;
    if (bridge) {
      result = await bridgeUpload(bridge, "/api/project/scene3d/import", formData);
    } else {
      const response = await fetch("/api/project/scene3d/import", { method: "POST", body: formData });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload.detail || response.statusText);
      }
      result = await response.json();
    }
    setProject(result, false);
    if (state.scene3dEditor) {
      await state.scene3dEditor.loadSceneData(result.scene3d || result.settings?.scene3d || null);
      syncScene3dTimeline();
    }
    showToast(`已导入 Blender 场景：${file.name}`);
  } catch (error) {
    showToast(error?.message || String(error));
  } finally {
    el.scene3dFile.value = "";
  }
}

function syncScene3dTimeline() {
  if (el.scene3dModal.hidden || !state.scene3dEditor) return;
  const shots = state.project?.shots || [];
  state.scene3dEditor.syncTimelineTime(currentAnimaticSeconds(), totalDuration(shots));
}

function closeScene3dModal() {
  el.scene3dModal.hidden = true;
}

async function saveScene3dData() {
  if (!state.project || !state.scene3dEditor) return;
  const scene3d = state.scene3dEditor.exportSceneData();
  await api("/api/project/settings", {
    method: "PATCH",
    body: JSON.stringify({ scene3d }),
  }).then((project) => {
    setProject(project, false);
    showToast("3D 场景已保存");
  });
}

applyCanvasColor();
render();
restoreLastProjectOnStartup().catch((error) => {
  console.warn("Startup session restore failed:", error);
});
