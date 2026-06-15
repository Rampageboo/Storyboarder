// Sole frontend entry: init globals, sequential classic script chain, startup overlay.

import "./init_globals.js";

const APP_SCRIPTS = [
  "core/canvas_size.js",
  "core/theme.js",
  "core/toolbar_menus.js",
  "exports_ui.js",
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
  "external_tools_ui.js",
  "annotations.js",
  "app.js",
  "core/settings.js",
  "core/hints.js",
  "core/drop.js",
];

const APP_BUILD = String(Date.now());

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

Object.assign(globalThis, { setStartupProgress, finishStartupOverlay, failStartupOverlay });

function loadClassicScript(src) {
  return new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = `/static/${src}?v=${APP_BUILD}`;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error(`Could not load ${src}`));
    document.body.appendChild(script);
  });
}

setStartupProgress(8, "Storyboard Tool", "Booting interface");

try {
  for (let index = 0; index < APP_SCRIPTS.length; index += 1) {
    const src = APP_SCRIPTS[index];
    await loadClassicScript(src);
    const progress = 10 + Math.round(((index + 1) / APP_SCRIPTS.length) * 42);
    setStartupProgress(progress, "Loading modules", src);
  }
  setStartupProgress(55, "Storyboard Tool", "Modules loaded");
  window.setTimeout(() => {
    if (!startupUi.hidden && !startupUi.failed) {
      failStartupOverlay("Initialization timed out");
    }
  }, 35000);
} catch (error) {
  console.error(error);
  failStartupOverlay(error.message || "Startup failed");
}
