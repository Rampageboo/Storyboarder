const APP_SCRIPTS = [
  "core/state.js",
  "core/dom.js",
  "core/bootstrap.js",
  "core/utils.js",
  "core/canvas_size.js",
  "core/theme.js",
  "core/toolbar_menus.js",
  "core/dispatch.js",
  "core/api.js",
  "core/status.js",
  "core/undo.js",
  "ref_segment.js",
  "reference_media.js",
  "reference_preview.js",
  "references.js",
  "timeline.js",
  "virtual_timeline.js",
  "animatic.js",
  "sync_polling.js",
  "annotations.js",
  "app.js",
  "core/settings.js",
  "core/hints.js",
  "core/drop.js",
];

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

function setStartupProgress(value, stage, detail) {
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

function finishStartupOverlay(detail = "Ready") {
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

function failStartupOverlay(detail = "Startup failed") {
  if (startupUi.hidden) return;
  startupUi.failed = true;
  setStartupProgress(Math.max(startupUi.value || 0, 55), "Startup issue", detail);
  if (startupUi.overlay) {
    startupUi.overlay.classList.add("has-error");
    startupUi.overlay.style.pointerEvents = "auto";
  }
}

window.setStartupProgress = setStartupProgress;
window.finishStartupOverlay = finishStartupOverlay;
window.failStartupOverlay = failStartupOverlay;

setStartupProgress(8, "Storyboard Tool", "Booting interface");

const APP_BUILD = String(Date.now());

const MODULE_GATE_SCRIPTS = new Set(["core/canvas_size.js", "app.js"]);

function loadAppScripts(index = 0) {
  if (index >= APP_SCRIPTS.length) {
    window.setStartupProgress(55, "Storyboard Tool", "Modules loaded");
    window.setTimeout(() => {
      if (!startupUi.hidden && !startupUi.failed) {
        failStartupOverlay("Initialization timed out");
      }
    }, 35000);
    return;
  }
  if (MODULE_GATE_SCRIPTS.has(APP_SCRIPTS[index]) && !window.__bootstrapModuleReady) {
    window.setTimeout(() => loadAppScripts(index), 10);
    return;
  }
  const script = document.createElement("script");
  script.src = `/static/${APP_SCRIPTS[index]}?v=${APP_BUILD}`;
  script.onload = () => {
    const progress = 10 + Math.round(((index + 1) / APP_SCRIPTS.length) * 42);
    setStartupProgress(progress, "Loading modules", APP_SCRIPTS[index]);
    loadAppScripts(index + 1);
  };
  script.onerror = () => {
    console.error(`Failed to load ${APP_SCRIPTS[index]}`);
    failStartupOverlay(`Could not load ${APP_SCRIPTS[index]}`);
  };
  document.body.appendChild(script);
}

loadAppScripts();
