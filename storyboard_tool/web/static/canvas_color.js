// Canvas background color: normalization, dialog, and per-shot canvas creation.
//
// Loaded AFTER core/canvas_size.js and BEFORE core/theme.js (see APP_SCRIPTS in main.js).
// Relies on dialogs.js (setDialogSections, closeDialog, setDialogError) and canvas_size.js
// (getProjectCanvasSize, canvasSizeLabel, applyCanvasAspectRatio).

const CANVAS_COLOR_STORAGE_KEY = "storyboard_canvas_color";

function canvasColor() {
  const fromProject = state.project?.settings?.canvas_background_color;
  if (fromProject) return normalizeHexColor(fromProject);
  const stored = localStorage.getItem(CANVAS_COLOR_STORAGE_KEY);
  return normalizeHexColor(stored || "#E8E8E8");
}

function applyCanvasColor(hex = canvasColor()) {
  const color = normalizeHexColor(hex);
  document.documentElement.style.setProperty("--canvas-color", color);
  if (el.canvasBoard) {
    el.canvasBoard.style.setProperty("background-color", color, "important");
  }
}

function isValidHexColor(value) {
  return /^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/.test(String(value || "").trim());
}

function normalizeHexColor(value, fallback = "#E8E8E8") {
  const candidate = String(value || "").trim();
  if (!isValidHexColor(candidate)) return fallback;
  if (candidate.length === 4) {
    const chars = candidate.slice(1);
    return `#${chars.split("").map((char) => char + char).join("").toUpperCase()}`;
  }
  return candidate.toUpperCase();
}

function hexToRgb(hex) {
  const normalized = normalizeHexColor(hex).slice(1);
  return {
    r: parseInt(normalized.slice(0, 2), 16),
    g: parseInt(normalized.slice(2, 4), 16),
    b: parseInt(normalized.slice(4, 6), 16),
  };
}

function rgbToHex(r, g, b) {
  const toHex = (value) => Math.max(0, Math.min(255, Math.round(value))).toString(16).padStart(2, "0");
  return `#${toHex(r)}${toHex(g)}${toHex(b)}`.toUpperCase();
}

function hexToGrayLevel(hex) {
  const { r, g, b } = hexToRgb(hex);
  return Math.round((r + g + b) / 3);
}

function grayLevelToHex(level) {
  const gray = Math.max(0, Math.min(255, Math.round(level)));
  return rgbToHex(gray, gray, gray);
}

function currentCanvasColorHex() {
  return grayLevelToHex(canvasColorState.gray);
}

function syncCanvasColorUi() {
  const hex = currentCanvasColorHex();
  if (el.dialogColorGray) el.dialogColorGray.value = String(canvasColorState.gray);
  if (el.dialogColorHex) el.dialogColorHex.value = hex;
  if (el.dialogColorPreview) el.dialogColorPreview.style.background = hex;
  if (el.settingsCanvasGray) el.settingsCanvasGray.value = String(canvasColorState.gray);
  if (el.settingsCanvasHex) el.settingsCanvasHex.value = hex;
  if (el.settingsCanvasPreview) el.settingsCanvasPreview.style.background = hex;
  if (canvasColorState.previewing) applyCanvasColor(hex);
}

function setCanvasColorFromHex(hex) {
  canvasColorState.gray = hexToGrayLevel(normalizeHexColor(hex));
  syncCanvasColorUi();
}

function onCanvasGrayInput() {
  canvasColorState.gray = Number(el.dialogColorGray.value || 0);
  setDialogError("");
  syncCanvasColorUi();
}

function onCanvasHexInput() {
  const value = el.dialogColorHex.value.trim();
  if (!isValidHexColor(value)) {
    setDialogError("Enter a valid hex color like #E8E8E8.");
    return;
  }
  setDialogError("");
  setCanvasColorFromHex(value);
}

function setupCanvasColorControls(initialHex) {
  teardownCanvasColorControls();
  setCanvasColorFromHex(initialHex);
  el.dialogColorGray.addEventListener("input", onCanvasGrayInput);
  el.dialogColorHex.addEventListener("input", onCanvasHexInput);
  canvasColorState.wired = true;
}

function teardownCanvasColorControls() {
  if (!canvasColorState.wired) return;
  el.dialogColorGray.removeEventListener("input", onCanvasGrayInput);
  el.dialogColorHex.removeEventListener("input", onCanvasHexInput);
  canvasColorState.wired = false;
}

async function createCanvasForShot(shotId) {
  const backgroundColor = canvasColor();
  const size = getProjectCanvasSize();
  const project = await api(`/api/shots/${shotId}/canvas`, {
    method: "POST",
    body: JSON.stringify({
      width: size.width,
      height: size.height,
      background_color: backgroundColor,
    }),
  });
  rememberCanvasColor(project?.settings?.canvas_background_color || backgroundColor);
  setProject(project, false);
  state.selectedShotId = shotId;
  applyCanvasColor();
  applyCanvasAspectRatio();
  render();
  showToast(`Canvas created (${canvasSizeLabel(size)}, ${backgroundColor}). Click preview to open in Photoshop.`);
}

function finishCanvasColorPreview(savedColor) {
  canvasColorState.previewing = false;
  applyCanvasColor(savedColor);
}

function openCanvasColorDialog() {
  return new Promise((resolve) => {
    const initialColor = canvasColor();
    canvasColorState.savedColor = initialColor;
    canvasColorState.previewing = true;

    dialogState.resolve = (result) => {
      finishCanvasColorPreview(result ? normalizeHexColor(result) : initialColor);
      resolve(result);
    };
    dialogState.browse = null;
    dialogState.validate = null;
    dialogState.hasInput = false;

    el.dialogTitle.textContent = "Canvas color";
    el.dialogHint.textContent =
      "Sets the drawing canvas color for new boards, the in-app canvas, and Photoshop via Storyboard Bridge.";
    el.dialogHint.hidden = false;
    setDialogSections({ color: true });
    setupCanvasColorControls(initialColor);

    el.dialogFooter.innerHTML = "";
    const spacer = document.createElement("span");
    spacer.className = "modal-spacer";
    el.dialogFooter.appendChild(spacer);

    const cancelButton = document.createElement("button");
    cancelButton.type = "button";
    cancelButton.textContent = "Cancel";
    cancelButton.addEventListener("click", () => closeDialog(null));
    el.dialogFooter.appendChild(cancelButton);

    const saveButton = document.createElement("button");
    saveButton.type = "button";
    saveButton.textContent = "Save";
    saveButton.classList.add("btn-primary");
    saveButton.addEventListener("click", () => {
      const hex = currentCanvasColorHex();
      if (!isValidHexColor(hex)) {
        setDialogError("Enter a valid hex color like #E8E8E8.");
        return;
      }
      closeDialog(hex);
    });
    el.dialogFooter.appendChild(saveButton);

    setDialogError("");
    el.dialogModal.hidden = false;
    el.dialogColorGray.focus();
  });
}

function rememberCanvasColor(hex) {
  const normalized = normalizeHexColor(hex);
  localStorage.setItem(CANVAS_COLOR_STORAGE_KEY, normalized);
  if (state.project) {
    state.project.settings = state.project.settings || {};
    state.project.settings.canvas_background_color = normalized;
  }
  return normalized;
}

async function saveCanvasColorToServer(normalized) {
  return api("/api/project/canvas-color", {
    method: "POST",
    body: JSON.stringify({ color: normalized }),
  });
}

async function openCanvasSettingsDialog() {
  if (!state.project) return;
  const selectedColor = await openCanvasColorDialog();
  if (selectedColor === null) return;
  const normalized = rememberCanvasColor(selectedColor);
  applyCanvasColor(normalized);
  renderPreview(selectedShot());
  try {
    const result = await saveCanvasColorToServer(normalized);
    const saved = rememberCanvasColor(result.color || result.settings?.canvas_background_color || normalized);
    if (result.settings) {
      state.project.settings = { ...state.project.settings, ...result.settings };
    } else {
      state.project.settings = { ...state.project.settings, canvas_background_color: saved };
    }
    if (Array.isArray(result.shots)) {
      state.project.shots = result.shots;
    }
    applyCanvasColor(saved);
    render();
    publishLiveBridge().catch(() => {});
    showToast(`Canvas color saved: ${saved}`);
  } catch (error) {
    applyCanvasColor();
    showToast(error.message || "Could not save canvas color. Restart the app and try again.");
  }
}
