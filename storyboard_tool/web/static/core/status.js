let statusOverride = "";
let statusOverrideTimer = null;

function buildDefaultAppStatus() {
  if (state.isSyncing) return "Syncing preview from linked files…";
  const project = state.project;
  if (!project) return "Open or create a project to begin.";
  const shots = project.shots || [];
  const revisionCount = shots.filter((shot) =>
    (shot.comments || []).some((comment) => !comment.resolved)
  ).length;
  const scenes = new Set(shots.map((shot) => shot.scene).filter(Boolean));
  const parts = [`${shots.length} boards`];
  if (scenes.size) parts.push(`${scenes.size} scenes`);
  if (revisionCount) parts.push(`${revisionCount} need revision`);
  if (project.dirty) parts.push("unsaved changes");
  const shot = typeof selectedShot === "function" ? selectedShot() : null;
  if (shot) {
    const index = shots.findIndex((item) => item.shot_id === state.selectedShotId);
    if (index >= 0) parts.push(`viewing #${index + 1}`);
  }
  return parts.join(" · ");
}

function setAppStatus(message, { temporary = false, ms = 4500 } = {}) {
  if (!el.appStatus) return;
  if (temporary) {
    statusOverride = message;
    window.clearTimeout(statusOverrideTimer);
    statusOverrideTimer = window.setTimeout(() => {
      statusOverride = "";
      refreshAppStatus();
    }, ms);
  }
  el.appStatus.textContent = message || statusOverride || buildDefaultAppStatus();
}

function refreshAppStatus() {
  if (!el.appStatus) return;
  el.appStatus.textContent = statusOverride || buildDefaultAppStatus();
}

function showTopbarProgress({ indeterminate = true, percent = 0 } = {}) {
  if (!el.topbarProgress) return;
  el.topbarProgress.hidden = false;
  el.topbarProgress.classList.toggle("is-indeterminate", indeterminate);
  if (el.topbarProgressFill) {
    el.topbarProgressFill.style.width = indeterminate ? "" : `${Math.max(0, Math.min(100, percent))}%`;
  }
}

function hideTopbarProgress() {
  if (!el.topbarProgress) return;
  el.topbarProgress.hidden = true;
  el.topbarProgress.classList.remove("is-indeterminate");
  if (el.topbarProgressFill) el.topbarProgressFill.style.width = "0";
}

async function runWithProgress(label, task, { successMessage, temporary = true } = {}) {
  showTopbarProgress({ indeterminate: true });
  setAppStatus(label);
  try {
    const result = await task();
    if (successMessage) setAppStatus(successMessage, { temporary });
    else refreshAppStatus();
    return result;
  } catch (error) {
    refreshAppStatus();
    throw error;
  } finally {
    hideTopbarProgress();
  }
}
