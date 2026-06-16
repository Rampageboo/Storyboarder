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
  const prevStamp =
    state.selectedShotId === shotId && selectedShot() ? previewCacheKey(selectedShot()) : "";
  const prevTimelineStamp = (() => {
    const shot = state.project?.shots?.find((item) => item.shot_id === shotId);
    return shot ? timelineCacheKey(shot) : "";
  })();
  try {
    const result = await api(`/api/shots/${shotId}/sync?force=${force}`, { method: "POST", silent });
    const syncResult = result.result || {};
    const mergedShot = mergeSyncedShotFromServer(result, shotId);
    if (state.project && result.shots && !state.project.dirty) {
      applyProjectShotsFromServer(result);
    }
    const syncedShot = state.project?.shots?.find((item) => item.shot_id === shotId);
    const syncedStamp = syncedShot ? timelineCacheKey(syncedShot) : "";
    const previewUpdated = Boolean(
      syncResult.synced || mergedShot || (syncedStamp && syncedStamp !== prevTimelineStamp)
    );
    if (previewUpdated) {
      if (typeof refreshTimelineAfterPreviewSync === "function") {
        refreshTimelineAfterPreviewSync(shotId);
      } else if (typeof renderTimeline === "function") {
        renderTimeline(state.selectedShotId);
      }
    }
    if (state.selectedShotId !== shotId) return;
    const stampChanged =
      selectedShot() && previewCacheKey(selectedShot()) !== prevStamp;
    if (syncResult.synced) {
      setProject(result, false);
      state.selectedShotId = shotId;
      if (!silent) showSyncStatus(syncResult.message || "Synced preview from Photoshop.");
      renderPreview(selectedShot());
    } else if (stampChanged) {
      if (!state.project?.dirty) {
        setProject(result, false);
      }
      renderPreview(selectedShot());
      if (!silent) showSyncStatus("Synced preview from Photoshop.");
    } else if (force && !silent) {
      showSyncStatus(syncResult.message || "No changes to sync.");
      if (!previewUpdated && typeof renderTimeline === "function") renderTimeline(shotId);
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

function mergeSyncedShotFromServer(result, shotId) {
  if (!state.project?.shots || !result?.shots) return false;
  const remote = result.shots.find((item) => item.shot_id === shotId);
  const local = state.project.shots.find((item) => item.shot_id === shotId);
  if (!remote || !local) return false;
  let changed = false;
  for (const key of [
    "preview_image_path",
    "image_path",
    "thumbnail_path",
    "source_file_path",
    "source_sync_mtime",
    "preview_disk_mtime",
    "thumbnail_disk_mtime",
    "has_board_background",
  ]) {
    if (remote[key] != null && remote[key] !== local[key]) {
      local[key] = remote[key];
      changed = true;
    }
  }
  return changed;
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
  if (typeof patchRefSegmentUi === "function") patchRefSegmentUi();
  updateAnnotationControls();
  scheduleTimelineViewportRender(state.selectedShotId);
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
  if (shotId) ensureTimelineShowsShot(shotId);
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

// --- module global bridge (auto) ---
Object.assign(globalThis, {
  inspectorFields,
  advancedPanel,
  shotPanel,
  updateShotPanelScrollMode,
  syncShot,
  showSyncStatus,
  addComment,
  resolveComment,
  flushSelectedShot,
  saveSelectedShot,
  saveShot,
  getRecentProjects,
  sessionSaveTimer,
  saveAppSessionSoon,
  saveAppSession,
  restoreLastProjectOnStartup,
  applyProjectShotsFromServer,
  setProject,
  selectShotSeq,
  pendingShotSyncTimer,
  scheduleRenderForShotChange,
  renderForShotChange,
  scheduleBackgroundSync,
  selectShot,
  selectedShot,
  readInspectorIntoShot,
});
