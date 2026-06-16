// Sole frontend entry: startup overlay, init globals, ordered feature load.
// Migrated features use import(); legacy scripts use classic injection.

import { setStartupProgress, failStartupOverlay, armStartupWatchdog } from "./startup_overlay.js";

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
  "app_render.js",
  "app.js",
  "core/settings.js",
  "core/hints.js",
  "core/drop.js",
];

const ES_MODULE_SCRIPTS = new Set(["core/settings.js"]);

const APP_BUILD = String(Date.now());

function loadClassicScript(src) {
  return new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = `/static/${src}?v=${APP_BUILD}`;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error(`Could not load ${src}`));
    document.body.appendChild(script);
  });
}

async function loadFeatureScript(src) {
  if (ES_MODULE_SCRIPTS.has(src)) {
    try {
      await import(`/static/${src}`);
    } catch (cause) {
      throw new Error(`Could not load ${src}`, { cause });
    }
    return;
  }
  await loadClassicScript(src);
}

function ensureSettingsClickFallback() {
  const openBtn = document.getElementById("openSettings");
  if (!openBtn || openBtn.dataset.settingsUiBound === "1") return;
  openBtn.dataset.settingsUiBound = "1";
  openBtn.addEventListener("click", (event) => {
    event.preventDefault();
    globalThis.openSettingsModal?.();
  });
}

try {
  await import("/static/app/init_globals.js");
  for (let index = 0; index < APP_SCRIPTS.length; index += 1) {
    const src = APP_SCRIPTS[index];
    await loadFeatureScript(src);
    const progress = 10 + Math.round(((index + 1) / APP_SCRIPTS.length) * 42);
    setStartupProgress(progress, "Loading modules", src);
  }
  setStartupProgress(55, "Storyboard Tool", "Modules loaded");
  if (!globalThis.bindSettingsUi?.()) {
    console.warn("[main] bindSettingsUi failed; using click fallback");
    ensureSettingsClickFallback();
  }
  armStartupWatchdog();
} catch (error) {
  console.error(error);
  failStartupOverlay(error.message || "Startup failed");
}
