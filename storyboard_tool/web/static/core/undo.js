const UNDO_LIMIT = 24;
const undoStack = [];

function snapshotShot(shot) {
  return JSON.parse(JSON.stringify(shot));
}

function pushUndo(entry) {
  undoStack.push(entry);
  if (undoStack.length > UNDO_LIMIT) undoStack.shift();
  refreshUndoUi();
}

function clearUndoStack() {
  undoStack.length = 0;
  refreshUndoUi();
}

function canUndo() {
  return undoStack.length > 0;
}

function refreshUndoUi() {
  if (el.undoAction) {
    el.undoAction.disabled = !canUndo();
    el.undoAction.title = canUndo() ? "Undo last action (Ctrl+Z)" : "Nothing to undo";
  }
}

function undoEntryLabel(entry) {
  if (entry.type === "delete_shot") return `Restore ${entry.shot?.shot_id || "board"}`;
  if (entry.type === "reorder") return "Restore board order";
  if (entry.type === "remove_reference") return "Restore reference image";
  if (entry.type === "apply_reference") return "Undo reference apply";
  return "Undo";
}

async function performUndo() {
  const entry = undoStack.pop();
  if (!entry) {
    refreshUndoUi();
    return;
  }
  refreshUndoUi();
  try {
    if (entry.type === "delete_shot") {
      await api("/api/shots/restore", {
        method: "POST",
        body: JSON.stringify({ shot: entry.shot, index: entry.index }),
      }).then(setProject);
      const restoreId = entry.selectedShotId || entry.shot?.shot_id;
      if (restoreId) await selectShot(restoreId);
      else render();
      showToast(`Undid delete · ${entry.shot?.shot_id || "board"} restored`);
      return;
    }
    if (entry.type === "reorder") {
      await api("/api/shots/reorder", {
        method: "POST",
        body: JSON.stringify({ shot_ids: entry.shotIds }),
      }).then(setProject);
      if (entry.selectedShotId) await selectShot(entry.selectedShotId);
      else render();
      showToast("Undid reorder");
      return;
    }
    if (entry.type === "remove_reference") {
      await api(`/api/shots/${entry.shot_id}/references`, {
        method: "PUT",
        body: JSON.stringify({ paths: entry.paths }),
      }).then(setProject);
      if (entry.selectedShotId) await selectShot(entry.selectedShotId);
      else renderForShotChange();
      showToast("Restored reference image");
      return;
    }
    if (entry.type === "apply_reference") {
      await api("/api/project/ref-apply/undo", {
        method: "POST",
        body: JSON.stringify({ token: entry.token }),
      }).then(setProject);
      if (typeof restoreRefSegmentFromProject === "function") restoreRefSegmentFromProject();
      // Drop the per-board segments the assign created, then persist.
      const removeIds = new Set(entry.segmentIds || []);
      if (removeIds.size && state.refSegment) {
        state.refSegment.segments = (state.refSegment.segments || []).filter(
          (segment) => !removeIds.has(segment.id)
        );
        if (removeIds.has(state.refSegment.activeId)) {
          state.refSegment.activeId = state.refSegment.segments[0]?.id || null;
        }
        if (typeof saveRefSegmentToProject === "function") await saveRefSegmentToProject();
      }
      if (entry.selectedShotId) await selectShot(entry.selectedShotId);
      else render();
      if (typeof patchRefSegmentUi === "function") patchRefSegmentUi();
      const n = entry.boardCount || 0;
      showToast(n ? `Undid reference apply · ${n} boards restored` : "Undid reference apply");
    }
  } catch (error) {
    undoStack.push(entry);
    refreshUndoUi();
    showToast(error.message || "Undo failed");
  }
}

function shouldIgnoreUndo(event) {
  const target = event.target;
  if (!target) return false;
  const tag = target.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return true;
  if (target.isContentEditable) return true;
  return false;
}

function bindUndoUi() {
  el.undoAction?.addEventListener("click", () => performUndo());
  document.addEventListener("keydown", (event) => {
    if (!(event.ctrlKey || event.metaKey) || event.key.toLowerCase() !== "z" || event.shiftKey) return;
    if (shouldIgnoreUndo(event)) return;
    if (!canUndo()) return;
    event.preventDefault();
    performUndo();
  });
  refreshUndoUi();
}


// --- module global bridge (auto) ---
Object.assign(globalThis, {
  UNDO_LIMIT,
  undoStack,
  snapshotShot,
  pushUndo,
  clearUndoStack,
  canUndo,
  refreshUndoUi,
  undoEntryLabel,
  performUndo,
  shouldIgnoreUndo,
  bindUndoUi,
});
