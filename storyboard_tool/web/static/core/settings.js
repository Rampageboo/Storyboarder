// Settings modal (ES module). Prior APP_SCRIPTS must be loaded before this imports.

import { state, canvasColorState, el, $ } from "../app/feature_runtime.js";

const settingsState = {
  canvasWired: false,
  canvasSizeWired: false,
  canvasSizeSnapshot: { width: 1920, height: 1080 },
  themeSnapshot: "studio",
  timelineNameSnapshot: true,
};
const TIMELINE_SHOW_SELECTED_NAME_KEY = "storyboard_timeline_show_selected_name";

function getTimelineShowSelectedName() {
  try {
    return localStorage.getItem(TIMELINE_SHOW_SELECTED_NAME_KEY) !== "0";
  } catch {
    return true;
  }
}

function applyTimelineUiPrefs(showSelectedName = getTimelineShowSelectedName()) {
  document.documentElement.setAttribute(
    "data-timeline-selected-name",
    showSelectedName ? "1" : "0"
  );
}

function persistTimelineShowSelectedName(showSelectedName) {
  try {
    localStorage.setItem(TIMELINE_SHOW_SELECTED_NAME_KEY, showSelectedName ? "1" : "0");
  } catch {
    // ignore storage failures
  }
  applyTimelineUiPrefs(showSelectedName);
}

function closeSettingsModal({ revertTheme = true, revertTimeline = true } = {}) {
  if (!el.settingsModal) return;
  if (revertTheme) $.applyUiTheme(settingsState.themeSnapshot);
  if (revertTimeline) applyTimelineUiPrefs(settingsState.timelineNameSnapshot);
  el.settingsModal.hidden = true;
  teardownSettingsCanvasControls();
}

function populateSettingsFields() {
  if (!el.settingsModal) return;
  const photoshopPath =
    state.project?.settings?.photoshop_path || localStorage.getItem("photoshop_path_default") || "";
  const blenderPath =
    state.project?.settings?.blender_path || localStorage.getItem("blender_path_default") || "";
  if (el.settingsPhotoshopPath) el.settingsPhotoshopPath.value = photoshopPath;
  if (el.settingsBlenderPath) el.settingsBlenderPath.value = blenderPath;
  if (el.settingsTimelineShowSelectedName) {
    el.settingsTimelineShowSelectedName.checked = getTimelineShowSelectedName();
  }
  const canvasSize = $.getProjectCanvasSize();
  settingsState.canvasSizeSnapshot = { ...canvasSize };
  $.setupSettingsCanvasSizeControls(canvasSize);
  if (el.settingsApplyCanvasSize) el.settingsApplyCanvasSize.checked = false;
  const hasProject = Boolean(state.project);
  [el.settingsCanvasWidth, el.settingsCanvasHeight, el.settingsApplyCanvasSize].forEach((node) => {
    if (node) node.disabled = !hasProject;
  });
  el.settingsCanvasPresets?.querySelectorAll("button").forEach((button) => {
    button.disabled = !hasProject;
  });
  setupSettingsCanvasControls($.canvasColor());
  $.renderThemePicker(el.settingsThemePicker);
}

function openSettingsModal() {
  const modal = el.settingsModal ?? document.getElementById("settingsModal");
  if (!modal) {
    console.error("Settings modal element is missing");
    $.showToast?.("Settings UI failed to load. Restart the app.");
    return;
  }
  try {
    settingsState.themeSnapshot = $.getStoredUiTheme();
    settingsState.timelineNameSnapshot = getTimelineShowSelectedName();
    modal.hidden = false;
    populateSettingsFields();
    loadSettingsCandidates().catch(() => {});
    el.settingsPhotoshopPath?.focus();
  } catch (error) {
    console.error("Failed to open settings:", error);
    $.showToast?.("Could not open settings.");
  }
}

async function loadSettingsCandidates() {
  const [psResult, blResult] = await Promise.allSettled([
    $.api("/api/system/photoshop-candidates", { silent: true }),
    $.api("/api/system/blender-candidates", { silent: true }),
  ]);
  if (psResult.status === "fulfilled") {
    renderSettingsCandidateList(el.settingsPhotoshopList, psResult.value.candidates || [], (path) => {
      if (el.settingsPhotoshopPath) el.settingsPhotoshopPath.value = path;
    });
  }
  if (blResult.status === "fulfilled") {
    renderSettingsCandidateList(el.settingsBlenderList, blResult.value.candidates || [], (path) => {
      if (el.settingsBlenderPath) el.settingsBlenderPath.value = path;
    });
  }
}

function renderSettingsCandidateList(container, paths, onPick) {
  if (!container) return;
  container.replaceChildren();
  if (!paths.length) {
    const empty = document.createElement("p");
    empty.className = "settings-candidate-empty";
    empty.textContent = "No installations detected.";
    container.appendChild(empty);
    return;
  }
  for (const path of paths) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "settings-candidate-item";
    button.innerHTML = `<strong>${$.escapeHtml($.pathBasename(path))}</strong><span>${$.escapeHtml($.pathDirname(path))}</span>`;
    button.addEventListener("click", () => onPick(path));
    container.appendChild(button);
  }
}

function syncSettingsCanvasUi() {
  const hex = $.currentCanvasColorHex();
  if (el.settingsCanvasGray) el.settingsCanvasGray.value = String(canvasColorState.gray);
  if (el.settingsCanvasHex) el.settingsCanvasHex.value = hex;
  if (el.settingsCanvasPreview) el.settingsCanvasPreview.style.background = hex;
}

function onSettingsCanvasGrayInput() {
  canvasColorState.gray = Number(el.settingsCanvasGray?.value || 0);
  syncSettingsCanvasUi();
}

function onSettingsCanvasHexInput() {
  const value = el.settingsCanvasHex?.value.trim() || "";
  if (!$.isValidHexColor(value)) return;
  $.setCanvasColorFromHex(value);
  syncSettingsCanvasUi();
}

function setupSettingsCanvasControls(initialHex) {
  teardownSettingsCanvasControls();
  $.setCanvasColorFromHex(initialHex);
  el.settingsCanvasGray?.addEventListener("input", onSettingsCanvasGrayInput);
  el.settingsCanvasHex?.addEventListener("input", onSettingsCanvasHexInput);
  syncSettingsCanvasUi();
  settingsState.canvasWired = true;
}

function teardownSettingsCanvasControls() {
  if (!settingsState.canvasWired) return;
  el.settingsCanvasGray?.removeEventListener("input", onSettingsCanvasGrayInput);
  el.settingsCanvasHex?.removeEventListener("input", onSettingsCanvasHexInput);
  settingsState.canvasWired = false;
}

async function browseSettingsPath(kind) {
  const endpoint = kind === "blender" ? "/api/system/browse-blender" : "/api/system/browse-photoshop";
  const result = await $.api(endpoint, { method: "POST" });
  if (result.cancelled || !result.path) return;
  if (kind === "blender" && el.settingsBlenderPath) el.settingsBlenderPath.value = result.path;
  if (kind === "photoshop" && el.settingsPhotoshopPath) el.settingsPhotoshopPath.value = result.path;
}

async function saveSettingsFromModal() {
  const photoshopPath = el.settingsPhotoshopPath?.value.trim() || "";
  const blenderPath = el.settingsBlenderPath?.value.trim() || "";
  const canvasHex = $.normalizeHexColor(el.settingsCanvasHex?.value.trim() || $.canvasColor());
  const canvasSize = $.readCanvasSizeFields(el.settingsCanvasWidth, el.settingsCanvasHeight);
  const sizeError = $.validateCanvasSizeFields(el.settingsCanvasWidth, el.settingsCanvasHeight);
  if (sizeError) {
    $.showToast(sizeError);
    return;
  }
  const sizeChanged =
    canvasSize.width !== settingsState.canvasSizeSnapshot.width ||
    canvasSize.height !== settingsState.canvasSizeSnapshot.height;
  const applyCanvasSize = Boolean(el.settingsApplyCanvasSize?.checked);
  const themeId =
    el.settingsThemePicker?.querySelector(".theme-option.active")?.dataset.themeId || $.getStoredUiTheme();
  const showSelectedName = Boolean(el.settingsTimelineShowSelectedName?.checked);

  try {
    if (state.project) {
      const settingsBody = {
        photoshop_path: photoshopPath,
        blender_path: blenderPath,
        canvas_width: canvasSize.width,
        canvas_height: canvasSize.height,
      };
      if (sizeChanged) {
        settingsBody.apply_canvas_size_to_blank_shots = applyCanvasSize;
      }
      const projectResult = await $.api("/api/project/settings", {
        method: "PATCH",
        body: JSON.stringify(settingsBody),
      });
      $.setProject(projectResult, false);
      const savedCanvas = $.rememberCanvasColor(canvasHex);
      $.applyCanvasColor(savedCanvas);
      const colorResult = await $.saveCanvasColorToServer(savedCanvas);
      if (colorResult.settings) {
        state.project.settings = { ...state.project.settings, ...colorResult.settings };
      }
      if (Array.isArray(colorResult.shots)) state.project.shots = colorResult.shots;
      $.applyCanvasColor(savedCanvas);
      $.applyCanvasAspectRatio($.getProjectCanvasSize());
      $.renderPreview($.selectedShot());
    } else {
      $.rememberCanvasColor(canvasHex);
      $.applyCanvasColor(canvasHex);
    }

    if (photoshopPath) localStorage.setItem("photoshop_path_default", photoshopPath);
    else localStorage.removeItem("photoshop_path_default");
    if (blenderPath) localStorage.setItem("blender_path_default", blenderPath);
    else localStorage.removeItem("blender_path_default");

    $.applyUiTheme(themeId);
    settingsState.themeSnapshot = themeId;
    settingsState.canvasSizeSnapshot = { ...$.getProjectCanvasSize() };
    persistTimelineShowSelectedName(showSelectedName);
    settingsState.timelineNameSnapshot = showSelectedName;
    await $.persistUiThemePreference(themeId);
    $.renderBlenderMenuStatus();
    $.render();
    $.publishLiveBridge().catch(() => {});
    closeSettingsModal({ revertTheme: false });
    const toastParts = ["Settings saved"];
    if (sizeChanged) toastParts.push(`canvas ${$.canvasSizeLabel(canvasSize)}`);
    if (sizeChanged && applyCanvasSize) toastParts.push("blank boards updated");
    $.showToast(`${toastParts.join(" · ")}.`);
  } catch {
    // api() already toasts
  }
}

function bindSettingsUi() {
  const openBtn = el.openSettings ?? document.getElementById("openSettings");
  if (!openBtn) {
    console.warn("[settings] #openSettings not found");
    return false;
  }
  if (openBtn.dataset.settingsUiBound !== "1") {
    openBtn.dataset.settingsUiBound = "1";
    openBtn.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      openSettingsModal();
    });
  }

  const modal = el.settingsModal ?? document.getElementById("settingsModal");
  if (!modal) {
    console.warn("[settings] #settingsModal not found");
    return false;
  }

  if (modal.dataset.settingsUiBound !== "1") {
    modal.dataset.settingsUiBound = "1";
    el.settingsSave?.addEventListener("click", () => saveSettingsFromModal());
    el.settingsCancel?.addEventListener("click", () => closeSettingsModal({ revertTheme: true }));
    el.settingsBrowsePhotoshop?.addEventListener("click", () => browseSettingsPath("photoshop"));
    el.settingsBrowseBlender?.addEventListener("click", () => browseSettingsPath("blender"));
    el.settingsClearPhotoshop?.addEventListener("click", () => {
      if (el.settingsPhotoshopPath) el.settingsPhotoshopPath.value = "";
    });
    el.settingsClearBlender?.addEventListener("click", () => {
      if (el.settingsBlenderPath) el.settingsBlenderPath.value = "";
    });
    el.settingsTimelineShowSelectedName?.addEventListener("change", () => {
      if (modal.hidden) return;
      applyTimelineUiPrefs(Boolean(el.settingsTimelineShowSelectedName.checked));
    });
    document.querySelectorAll("[data-settings-close]").forEach((node) => {
      node.addEventListener("click", () => closeSettingsModal({ revertTheme: true }));
    });
    modal.addEventListener("keydown", (event) => {
      if (event.key === "Escape") closeSettingsModal({ revertTheme: true });
    });
  }

  applyTimelineUiPrefs();
  return true;
}

Object.assign(globalThis, {
  settingsState,
  TIMELINE_SHOW_SELECTED_NAME_KEY,
  getTimelineShowSelectedName,
  applyTimelineUiPrefs,
  persistTimelineShowSelectedName,
  closeSettingsModal,
  populateSettingsFields,
  openSettingsModal,
  loadSettingsCandidates,
  renderSettingsCandidateList,
  syncSettingsCanvasUi,
  onSettingsCanvasGrayInput,
  onSettingsCanvasHexInput,
  setupSettingsCanvasControls,
  teardownSettingsCanvasControls,
  browseSettingsPath,
  saveSettingsFromModal,
  bindSettingsUi,
});
