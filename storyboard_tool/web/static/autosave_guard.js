// Guard legacy inspector autosave so edits are saved by shot_id, not by whichever
// board happens to be selected when the debounce timer fires. This is a small
// compatibility layer for the pre-React frontend.
(() => {
  const SAVE_DELAY_MS = 350;
  const dirtyShotIds = new Set();
  const dirtyShotVersions = new Map();
  let dirtyVersion = 0;
  let saveTimer = 0;
  let flushing = false;

  function getShotById(shotId) {
    return state.project?.shots?.find((shot) => shot.shot_id === shotId) || null;
  }

  function updateDirtyFlag() {
    if (state.project) state.project.dirty = dirtyShotIds.size > 0;
    refreshAppStatus?.();
  }

  function markShotDirty(shotId) {
    if (!shotId) return;
    dirtyVersion += 1;
    dirtyShotIds.add(shotId);
    dirtyShotVersions.set(shotId, dirtyVersion);
    updateDirtyFlag();
  }

  function shotPayload(shot) {
    return {
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
    };
  }

  function mergeSavedShot(project, shotId) {
    if (!state.project?.shots || !project?.shots) return;
    const localIndex = state.project.shots.findIndex((shot) => shot.shot_id === shotId);
    const remote = project.shots.find((shot) => shot.shot_id === shotId);
    if (localIndex < 0 || !remote || dirtyShotIds.has(shotId)) return;
    state.project.shots[localIndex] = { ...state.project.shots[localIndex], ...remote };
  }

  async function saveDirtyShot(shotId) {
    const shot = getShotById(shotId);
    if (!shot) {
      dirtyShotIds.delete(shotId);
      dirtyShotVersions.delete(shotId);
      updateDirtyFlag();
      return;
    }

    const versionAtSaveStart = dirtyShotVersions.get(shotId);
    const project = await api(`/api/shots/${shotId}`, {
      method: "PATCH",
      body: JSON.stringify(shotPayload(shot)),
      silent: true,
    });

    if (dirtyShotVersions.get(shotId) === versionAtSaveStart) {
      dirtyShotIds.delete(shotId);
      dirtyShotVersions.delete(shotId);
      mergeSavedShot(project, shotId);
    }
    updateDirtyFlag();
  }

  function scheduleShotSave(shotId) {
    window.clearTimeout(saveTimer);
    window.clearTimeout(state.saveTimer);
    saveTimer = window.setTimeout(() => {
      saveDirtyShot(shotId).catch((error) => {
        console.warn("Autosave failed:", error);
        showToast?.(error?.message || "Autosave failed");
      });
    }, SAVE_DELAY_MS);
    state.saveTimer = saveTimer;
  }

  async function flushDirtyShots() {
    window.clearTimeout(saveTimer);
    window.clearTimeout(state.saveTimer);
    if (flushing || dirtyShotIds.size === 0) return;
    flushing = true;
    try {
      for (const shotId of [...dirtyShotIds]) {
        await saveDirtyShot(shotId);
      }
    } finally {
      flushing = false;
      updateDirtyFlag();
    }
  }

  function bindInspectorAutosaveGuard() {
    if (!Array.isArray(globalThis.inspectorFields)) return;
    for (const field of globalThis.inspectorFields) {
      field?.addEventListener(
        "input",
        (event) => {
          event.stopImmediatePropagation();
          const shot = selectedShot?.();
          if (!shot) return;
          readInspectorIntoShot(shot);
          markShotDirty(shot.shot_id);
          renderBoardInfo?.();
          renderTimeline?.();
          scheduleShotSave(shot.shot_id);
        },
        true
      );
    }
  }

  async function guardedSaveProject(event) {
    event.preventDefault();
    event.stopImmediatePropagation();
    await flushDirtyShots();
    await api("/api/project/save", { method: "POST" }).then(setProject);
    showToast?.("Project saved.");
  }

  function bindProjectSaveGuard() {
    el.saveProject?.addEventListener("click", guardedSaveProject, true);
  }

  async function uploadSelectedFile(input, urlForShot, fallbackToast = "Upload failed") {
    const shot = selectedShot?.();
    const file = input?.files?.[0];
    if (!shot || !file) return;
    const shotId = shot.shot_id;
    await flushDirtyShots();
    const form = new FormData();
    form.append("file", file);
    await api(urlForShot(shotId), { method: "POST", body: form, headers: {} }).then(setProject);
    await selectShot?.(shotId);
    input.value = "";
    if (fallbackToast) showToast?.(fallbackToast.replace("{shotId}", shotId));
  }

  function bindUploadGuards() {
    el.imageFile?.addEventListener(
      "change",
      async (event) => {
        event.stopImmediatePropagation();
        await uploadSelectedFile(el.imageFile, (shotId) => `/api/shots/${shotId}/image`, "Imported preview for {shotId}");
      },
      true
    );
    el.referenceFile?.addEventListener(
      "change",
      async (event) => {
        event.stopImmediatePropagation();
        await uploadSelectedFile(el.referenceFile, (shotId) => `/api/shots/${shotId}/references`, "Added reference for {shotId}");
      },
      true
    );
    el.sourceFile?.addEventListener(
      "change",
      async (event) => {
        event.stopImmediatePropagation();
        await uploadSelectedFile(el.sourceFile, (shotId) => `/api/shots/${shotId}/source`, "Imported source for {shotId}");
      },
      true
    );
  }

  function bindActionGuards() {
    el.removeImage?.addEventListener(
      "click",
      async (event) => {
        event.preventDefault();
        event.stopImmediatePropagation();
        const shot = selectedShot?.();
        if (!shot) return;
        const shotId = shot.shot_id;
        await flushDirtyShots();
        await api(`/api/shots/${shotId}/image`, { method: "DELETE" }).then(setProject);
        await selectShot?.(shotId);
      },
      true
    );

    el.addComment?.addEventListener("click", guardedAddComment, true);
    el.commentText?.addEventListener(
      "keydown",
      (event) => {
        if (event.key !== "Enter") return;
        guardedAddComment(event);
      },
      true
    );

    document.addEventListener(
      "drop",
      async (event) => {
        if (!hasDropFiles?.(event)) return;
        event.preventDefault();
        event.stopImmediatePropagation();
        hideDropOverlay?.();
        try {
          await flushDirtyShots();
          await handleDroppedFiles?.(event.dataTransfer);
        } catch (error) {
          showToast?.(error?.message || "Drop failed");
        }
      },
      true
    );
  }

  async function guardedAddComment(event) {
    event?.preventDefault?.();
    event?.stopImmediatePropagation?.();
    const shot = selectedShot?.();
    const text = el.commentText?.value?.trim() || "";
    if (!shot || !text) return;
    const shotId = shot.shot_id;
    await flushDirtyShots();
    await api(`/api/shots/${shotId}/comments`, {
      method: "POST",
      body: JSON.stringify({ text }),
    }).then(setProject);
    el.commentText.value = "";
    await selectShot?.(shotId);
  }

  const originalSelectShot = globalThis.selectShot;
  if (typeof originalSelectShot === "function") {
    globalThis.selectShot = async function guardedSelectShot(shotId, shouldRender = true) {
      if (state.selectedShotId && shotId !== state.selectedShotId) {
        await flushDirtyShots();
      }
      return originalSelectShot.call(this, shotId, shouldRender);
    };
  }

  const originalSaveShot = globalThis.saveShot;
  globalThis.saveShot = async function guardedSaveShot(shot) {
    if (!shot?.shot_id) return originalSaveShot?.call(this, shot);
    markShotDirty(shot.shot_id);
    await saveDirtyShot(shot.shot_id);
  };

  globalThis.flushSelectedShot = flushDirtyShots;
  globalThis.saveSelectedShot = async function guardedSaveSelectedShot() {
    const shot = selectedShot?.();
    if (!shot) return;
    markShotDirty(shot.shot_id);
    await saveDirtyShot(shot.shot_id);
  };

  for (const name of ["deleteShotById", "reorderShot", "duplicateShotById", "recoverShotById", "addShot"]) {
    const original = globalThis[name];
    if (typeof original !== "function") continue;
    globalThis[name] = async function guardedTimelineMutation(...args) {
      await flushDirtyShots();
      return original.apply(this, args);
    };
  }

  globalThis.flushDirtyShots = flushDirtyShots;
  globalThis.markShotDirty = markShotDirty;

  bindInspectorAutosaveGuard();
  bindProjectSaveGuard();
  bindUploadGuards();
  bindActionGuards();
})();
