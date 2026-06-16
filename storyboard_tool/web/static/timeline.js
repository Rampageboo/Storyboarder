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

function captureTimelineScroll() {
  if (!el.timelineStrip) return;
  const max = maxTimelineScrollLeft();
  const left = Math.min(max, Math.max(0, Math.round(el.timelineStrip.scrollLeft)));
  if (left !== el.timelineStrip.scrollLeft) {
    el.timelineStrip.scrollLeft = left;
  }
  state.timelineScrollLeft = left;
}

function maxTimelineScrollLeft() {
  if (!el.timelineStrip) return 0;
  const total = timelineVirtual.layout?.totalWidth || el.timelineStrip.scrollWidth || 0;
  return Math.max(0, total - el.timelineStrip.clientWidth);
}

function restoreTimelineScroll(scrollLeft = state.timelineScrollLeft) {
  if (!el.timelineStrip) return;
  const max = maxTimelineScrollLeft();
  const left = Math.min(max, Math.max(0, Math.round(scrollLeft || 0)));
  el.timelineStrip.scrollLeft = left;
  state.timelineScrollLeft = left;
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

async function addShot(afterShotId = null) {
  await flushSelectedShot();
  const body = afterShotId ? { after_shot_id: afterShotId } : {};
  const result = await api("/api/shots", { method: "POST", body: JSON.stringify(body) });
  setProject(result);
  await selectShot(result.shot.shot_id);
  scrollTimelineToShot(result.shot.shot_id);
  showToast(boardAddedToast(result.shot.shot_id));
}

function navigateShot(delta, { scrollTimeline = false } = {}) {
  const shots = state.project?.shots || [];
  if (!shots.length) return;
  const currentIndex = shots.findIndex((shot) => shot.shot_id === state.selectedShotId);
  const nextIndex = Math.min(Math.max((currentIndex < 0 ? 0 : currentIndex) + delta, 0), shots.length - 1);
  const shotId = shots[nextIndex].shot_id;
  selectShot(shotId).then(() => {
    if (scrollTimeline) scrollTimelineToShot(shotId, "auto");
  });
}

function shouldIgnoreShotNavigation(event) {
  const target = event.target;
  if (!target || target.closest(".context-menu")) return true;
  const tag = target.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return true;
  if (target.isContentEditable) return true;
  if (el.dialogModal && !el.dialogModal.hidden) return true;
  if (el.settingsModal && !el.settingsModal.hidden) return true;
  return false;
}

function filteredShots() {
  const shots = state.project?.shots || [];
  return shots.filter((shot) => {
    if (state.statusFilter && shot.status !== state.statusFilter) return false;
    if (state.revisionOnly && !(shot.comments || []).some((comment) => !comment.resolved)) return false;
    return true;
  });
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

async function duplicateShotById(shotId) {
  if (!state.project) return;
  await flushSelectedShot();
  const result = await api(`/api/shots/${shotId}/duplicate`, { method: "POST" });
  setProject(result);
  await selectShot(result.shot.shot_id);
  scrollTimelineToShot(result.shot.shot_id);
}

async function recoverShotById(shotId) {
  const shots = state.project?.shots || [];
  const shot = shots.find((item) => item.shot_id === shotId);
  if (!shot) return;
  if (!shot.source_file_path) {
    showToast("No PSD linked for this board — nothing to recover.");
    return;
  }
  const choice = await showDialog({
    title: "Recover broken PSD",
    hint:
      `Rebuild ${shot.shot_id}'s PSD from its layers. The current file is backed up to ` +
      `_history/ first. Close it in Photoshop before recovering. "Keep layers" preserves ` +
      `blend modes/opacity; use "Flatten" only if that still won't open in Photoshop.`,
    actions: [
      { label: "Cancel", value: null },
      { label: "Flatten", value: "flatten" },
      { label: "Keep layers", value: "layers", primary: true },
    ],
  });
  if (choice !== "layers" && choice !== "flatten") return;
  await flushSelectedShot();
  const query = choice === "flatten" ? "?preserve_layers=false" : "";
  const response = await api(`/api/shots/${shotId}/recover-source${query}`, { method: "POST" });
  setProject(response);
  await selectShot(shotId);
  const result = response.result || {};
  const how = result.method === "flatten" ? "flattened" : "layers preserved";
  showToast(`Recovered ${shot.shot_id} (${how}): ${result.layers_recovered ?? "?"} layer(s). Backup in _history/.`);
}

async function deleteShotById(shotId) {
  const shots = state.project?.shots || [];
  const index = shots.findIndex((item) => item.shot_id === shotId);
  const shot = index >= 0 ? shots[index] : null;
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
  const undoEntry = {
    type: "delete_shot",
    shot: snapshotShot(shot),
    index,
    selectedShotId: state.selectedShotId,
  };
  await api(`/api/shots/${shot.shot_id}`, { method: "DELETE" }).then(setProject);
  pushUndo(undoEntry);
  const remaining = state.project?.shots || [];
  const nextIndex = Math.min(index, Math.max(remaining.length - 1, 0));
  const nextId = remaining[nextIndex]?.shot_id || null;
  await selectShot(nextId);
  showToast(`Deleted ${shot.shot_id}.`);
}

function renderTimeline(activeShotId = state.selectedShotId) {
  const scrollBefore = el.timelineStrip ? el.timelineStrip.scrollLeft : 0;
  const scrollToRestore = state.timelineScrollPendingRestore ? state.timelineScrollLeft : scrollBefore;
  const shots = state.project?.shots || [];

  updateTimelineMeta(shots, activeShotId);

  if (!el.timelineStrip) return;
  if (!shots.length) {
    el.timelineStrip.innerHTML = "";
    invalidateTimelineLayout();
    return;
  }

  const nextLayoutKey = timelineLayoutKey(shots);
  if (timelineVirtual.layoutKey !== nextLayoutKey) {
    timelineVirtual.layoutKey = nextLayoutKey;
    timelineVirtual.layout = buildTimelineLayout(shots);
    timelineVirtual.rangeKey = "";
    state.timelineScrollLeft = Math.min(state.timelineScrollLeft, maxTimelineScrollLeft());
  }

  restoreTimelineScroll(scrollToRestore);
  renderTimelineViewport(activeShotId);

  requestAnimationFrame(() => {
    if (state.timelineScrollPendingRestore) {
      state.timelineScrollPendingRestore = false;
    }
    scheduleTimelineViewportRender(activeShotId);
    if (activeShotId) ensureTimelineShowsShot(activeShotId, { behavior: "auto" });
  });
}

async function reorderShot(draggedShotId, targetShotId) {
  const shots = state.project?.shots || [];
  const from = shots.findIndex((shot) => shot.shot_id === draggedShotId);
  const to = shots.findIndex((shot) => shot.shot_id === targetShotId);
  if (from < 0 || to < 0 || from === to) return;
  const previousIds = shots.map((item) => item.shot_id);
  const nextIds = [...previousIds];
  const [moved] = nextIds.splice(from, 1);
  nextIds.splice(to, 0, moved);
  stopAnimatic();
  await api("/api/shots/reorder", {
    method: "POST",
    body: JSON.stringify({ shot_ids: nextIds }),
  }).then(setProject);
  pushUndo({
    type: "reorder",
    shotIds: previousIds,
    selectedShotId: state.selectedShotId,
  });
  selectShot(draggedShotId);
}

function bindTimelineEvents() {
  el.addShot?.addEventListener("click", () => addShot());
  el.prevShot?.addEventListener("click", () => {
    stopAnimatic();
    navigateShot(-1, { scrollTimeline: true });
  });
  el.nextShot?.addEventListener("click", () => {
    stopAnimatic();
    navigateShot(1, { scrollTimeline: true });
  });

  el.timelineStrip?.addEventListener(
    "scroll",
    () => {
      captureTimelineScroll();
      saveAppSessionSoon();
      scheduleTimelineViewportRender(state.selectedShotId);
    },
    { passive: true }
  );

  if (el.timelineStrip && typeof ResizeObserver !== "undefined") {
    new ResizeObserver(() => {
      timelineVirtual.rangeKey = "";
      scheduleTimelineViewportRender(state.selectedShotId);
    }).observe(el.timelineStrip);
  }

  el.statusFilter?.addEventListener("change", () => {
    state.statusFilter = el.statusFilter.value;
    timelineVirtual.rangeKey = "";
    renderTimeline();
    refreshAppStatus();
    saveAppSessionSoon();
  });

  el.revisionFilter?.addEventListener("change", () => {
    state.revisionOnly = el.revisionFilter.checked;
    timelineVirtual.rangeKey = "";
    renderTimeline();
    refreshAppStatus();
    saveAppSessionSoon();
  });

  el.shotContextMenu?.querySelectorAll("[data-shot-action]").forEach((button) => {
    button.addEventListener("click", async () => {
      const shotId = contextMenuState.shotId;
      hideShotContextMenu();
      if (!shotId) return;
      if (button.dataset.shotAction === "duplicate") {
        await duplicateShotById(shotId);
        return;
      }
      if (button.dataset.shotAction === "recover") {
        await recoverShotById(shotId);
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

  document.addEventListener("keydown", (event) => {
    if (shouldIgnoreShotNavigation(event)) return;
    if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
      event.preventDefault();
      stopAnimatic();
      navigateShot(-1, { scrollTimeline: true });
      return;
    }
    if (event.key === "ArrowRight" || event.key === "ArrowDown") {
      event.preventDefault();
      stopAnimatic();
      navigateShot(1, { scrollTimeline: true });
    }
  });
}


// --- module global bridge (auto) ---
Object.assign(globalThis, {
  boardAddedToast,
  captureTimelineScroll,
  maxTimelineScrollLeft,
  restoreTimelineScroll,
  createTimelineInsertButton,
  addShot,
  navigateShot,
  shouldIgnoreShotNavigation,
  filteredShots,
  hideShotContextMenu,
  showShotContextMenu,
  duplicateShotById,
  deleteShotById,
  renderTimeline,
  reorderShot,
  bindTimelineEvents,
});
