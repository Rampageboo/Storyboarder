// Startup overlay: progress bar, completion, failure, and the init watchdog.
// Imported first by main_module so these are available before any feature module.

const startupUi = {
  overlay: document.getElementById("startupOverlay"),
  progress: document.getElementById("startupProgress"),
  stage: document.getElementById("startupStage"),
  detail: document.getElementById("startupDetail"),
  percent: document.getElementById("startupPercent"),
  value: 0,
  hidden: false,
  failed: false,
};

export function setStartupProgress(value, stage, detail) {
  const requested = Math.max(0, Math.min(100, Math.round(value)));
  const current = startupUi.value || 0;
  if (requested < current) return;
  const percent = Math.max(current, requested);
  startupUi.value = percent;
  if (startupUi.progress) startupUi.progress.value = percent;
  if (startupUi.percent) startupUi.percent.textContent = `${percent}%`;
  if (stage && startupUi.stage) startupUi.stage.textContent = stage;
  if (detail && startupUi.detail) startupUi.detail.textContent = detail;
}

export function finishStartupOverlay(detail = "Ready") {
  if (startupUi.hidden) return;
  startupUi.hidden = true;
  setStartupProgress(100, "Ready", detail);
  if (startupUi.overlay) {
    startupUi.overlay.classList.add("is-done");
    startupUi.overlay.style.pointerEvents = "none";
  }
  window.setTimeout(() => {
    if (startupUi.overlay) startupUi.overlay.hidden = true;
  }, 320);
}

export function failStartupOverlay(detail = "Startup failed") {
  if (startupUi.hidden) return;
  startupUi.failed = true;
  setStartupProgress(Math.max(startupUi.value || 0, 55), "Startup issue", detail);
  if (startupUi.overlay) {
    startupUi.overlay.classList.add("has-error");
    startupUi.overlay.style.pointerEvents = "auto";
  }
}

export function armStartupWatchdog(ms = 35000) {
  window.setTimeout(() => {
    if (!startupUi.hidden && !startupUi.failed) {
      failStartupOverlay("Initialization timed out");
    }
  }, ms);
}

// Bridge to globalThis so classic-era callers (app.js) keep working.
Object.assign(globalThis, { setStartupProgress, finishStartupOverlay, failStartupOverlay });

setStartupProgress(8, "Storyboard Tool", "Booting interface");
