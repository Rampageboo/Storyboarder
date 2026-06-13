function isScene3dOpen() {
  return Boolean(el.canvasArea?.classList.contains("scene3d-active"));
}

function totalDuration(shots) {
  return shots.reduce((total, shot) => total + Number(shot.duration_seconds || 3), 0);
}

function currentAnimaticSeconds() {
  if (!state.animaticTimer) return state.timelineCursor || 0;
  return state.animaticOffset + (performance.now() - state.animaticStartedAt) / 1000;
}

function playAnimatic() {
  const shots = state.project?.shots || [];
  if (!shots.length) return;
  state.animaticStartedAt = performance.now();
  state.animaticOffset = Number(el.progressSlider.value || state.timelineCursor || 0);
  window.clearInterval(state.animaticTimer);
  state.animaticTimer = window.setInterval(tickAnimatic, 120);
  setAppStatus(`Playing animatic · ${totalDuration(shots).toFixed(1)}s total`);
  tickAnimatic();
}

function stopAnimatic(resetProgress = true, { refreshTimeline = true } = {}) {
  const wasPlaying = Boolean(state.animaticTimer);
  window.clearInterval(state.animaticTimer);
  state.animaticTimer = null;
  if (!wasPlaying) return;

  if (resetProgress) {
    state.timelineCursor = 0;
    state.animaticOffset = 0;
    el.progressSlider.value = "0";
  } else {
    state.timelineCursor = Number(el.progressSlider.value || state.timelineCursor || 0);
  }

  const refresh = () => {
    if (refreshTimeline) renderTimeline();
    else updateTimelineMeta(state.project?.shots || [], state.selectedShotId);
    refreshAppStatus();
  };
  requestAnimationFrame(refresh);
}

function tickAnimatic() {
  const shots = state.project?.shots || [];
  const elapsed = currentAnimaticSeconds();
  const total = totalDuration(shots);
  if (elapsed >= total) {
    state.timelineCursor = 0;
    stopAnimatic();
    setAppStatus("Animatic finished", { temporary: true });
    return;
  }
  state.timelineCursor = elapsed;
  if (isScene3dOpen()) {
    renderTimeline(state.selectedShotId);
    return;
  }
  let cursor = 0;
  for (const shot of shots) {
    cursor += Number(shot.duration_seconds || 3);
    if (elapsed < cursor) {
      if (state.selectedShotId !== shot.shot_id) {
        state.selectedShotId = shot.shot_id;
        if (typeof patchTimelineActiveState === "function") patchTimelineActiveState(shot.shot_id);
        render();
        loadAnnotations(shot.shot_id);
      } else {
        renderTimeline(shot.shot_id);
      }
      return;
    }
  }
}

function selectShotAtTime(seconds) {
  if (isScene3dOpen()) {
    state.timelineCursor = seconds;
    renderTimeline(state.selectedShotId);
    return;
  }
  const shots = state.project?.shots || [];
  let cursor = 0;
  for (const shot of shots) {
    cursor += Number(shot.duration_seconds || 3);
    if (seconds <= cursor) {
      state.selectedShotId = shot.shot_id;
      if (typeof patchTimelineActiveState === "function") patchTimelineActiveState(shot.shot_id);
      render();
      loadAnnotations(shot.shot_id);
      return;
    }
  }
  if (shots.length) {
    state.selectedShotId = shots[shots.length - 1].shot_id;
    if (typeof patchTimelineActiveState === "function") patchTimelineActiveState(state.selectedShotId);
    render();
    loadAnnotations(state.selectedShotId);
  }
}

function bindAnimaticEvents() {
  el.playAnimatic?.addEventListener("click", playAnimatic);
  el.stopAnimatic?.addEventListener("click", stopAnimatic);
  el.progressSlider?.addEventListener("input", () => {
    state.timelineCursor = Number(el.progressSlider.value || 0);
    stopAnimatic(false);
    if (isScene3dOpen()) {
      renderTimeline(state.selectedShotId);
      return;
    }
    selectShotAtTime(state.timelineCursor);
    renderTimeline();
  });
}
