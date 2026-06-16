const CANVAS_SIZE_PRESETS = [
  { id: "hd", label: "HD 16:9", width: 1920, height: 1080 },
  { id: "2k", label: "2K Film", width: 2048, height: 1080 },
  { id: "4k", label: "4K UHD", width: 3840, height: 2160 },
  { id: "portrait", label: "Portrait HD", width: 1080, height: 1920 },
  { id: "square", label: "Square", width: 1080, height: 1080 },
  { id: "story", label: "Storyboard", width: 1600, height: 900 },
  { id: "custom", label: "Custom", width: 1920, height: 1080 },
];

const CANVAS_SIZE_LIMITS = { minWidth: 320, maxWidth: 8192, minHeight: 180, maxHeight: 8192 };
const canvasSizeUiState = { dialog: null, settings: null };

function normalizeCanvasSize(width, height) {
  const w = Math.min(
    CANVAS_SIZE_LIMITS.maxWidth,
    Math.max(CANVAS_SIZE_LIMITS.minWidth, Math.round(Number(width) || 1920))
  );
  const h = Math.min(
    CANVAS_SIZE_LIMITS.maxHeight,
    Math.max(CANVAS_SIZE_LIMITS.minHeight, Math.round(Number(height) || 1080))
  );
  return { width: w, height: h };
}

function getProjectCanvasSize(project = state.project) {
  const settings = project?.settings || {};
  return normalizeCanvasSize(settings.canvas_width ?? 1920, settings.canvas_height ?? 1080);
}

function applyCanvasAspectRatio(size = getProjectCanvasSize()) {
  const root = document.documentElement;
  root.style.setProperty("--canvas-aspect-w", String(size.width));
  root.style.setProperty("--canvas-aspect-h", String(size.height));
  if (typeof timelineBoardWidth === "function") {
    root.style.setProperty("--timeline-board-width", `${timelineBoardWidth(size)}px`);
  }
  if (typeof invalidateTimelineLayout === "function") invalidateTimelineLayout();
}

function canvasSizeLabel(size = getProjectCanvasSize()) {
  return `${size.width} × ${size.height}`;
}

function findCanvasPreset(width, height) {
  const normalized = normalizeCanvasSize(width, height);
  return (
    CANVAS_SIZE_PRESETS.find(
      (preset) =>
        preset.id !== "custom" &&
        preset.width === normalized.width &&
        preset.height === normalized.height
    ) || CANVAS_SIZE_PRESETS.find((preset) => preset.id === "custom")
  );
}

function renderCanvasSizePresets(container, { width, height, onChange }) {
  if (!container) return;
  const active = findCanvasPreset(width, height);
  container.replaceChildren();
  for (const preset of CANVAS_SIZE_PRESETS) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `canvas-size-preset${preset.id === active.id ? " active" : ""}`;
    button.dataset.presetId = preset.id;
    button.innerHTML = `<strong>${escapeHtml(preset.label)}</strong><span>${preset.width} × ${preset.height}</span>`;
    button.addEventListener("click", () => onChange(preset));
    container.appendChild(button);
  }
}

function readCanvasSizeFields(widthInput, heightInput) {
  return normalizeCanvasSize(widthInput?.value, heightInput?.value);
}

function syncCanvasSizeFields(widthInput, heightInput, presetContainer, size) {
  const normalized = normalizeCanvasSize(size.width, size.height);
  if (widthInput) widthInput.value = String(normalized.width);
  if (heightInput) heightInput.value = String(normalized.height);
  renderCanvasSizePresets(presetContainer, {
    width: normalized.width,
    height: normalized.height,
    onChange: (preset) => {
      if (preset.id === "custom") {
        presetContainer.querySelector('[data-preset-id="custom"]')?.classList.add("active");
        widthInput?.focus();
        return;
      }
      syncCanvasSizeFields(widthInput, heightInput, presetContainer, preset);
    },
  });
}

function bindCanvasSizeInputs(widthInput, heightInput, presetContainer, key) {
  if (canvasSizeUiState[key]) return;
  const syncFromInputs = () => {
    const size = readCanvasSizeFields(widthInput, heightInput);
    syncCanvasSizeFields(widthInput, heightInput, presetContainer, size);
  };
  const onWidthInput = () => {
    renderCanvasSizePresets(presetContainer, {
      width: widthInput.value,
      height: heightInput.value,
      onChange: (preset) => syncCanvasSizeFields(widthInput, heightInput, presetContainer, preset),
    });
  };
  const onHeightInput = () => {
    renderCanvasSizePresets(presetContainer, {
      width: widthInput.value,
      height: heightInput.value,
      onChange: (preset) => syncCanvasSizeFields(widthInput, heightInput, presetContainer, preset),
    });
  };
  widthInput?.addEventListener("change", syncFromInputs);
  heightInput?.addEventListener("change", syncFromInputs);
  widthInput?.addEventListener("input", onWidthInput);
  heightInput?.addEventListener("input", onHeightInput);
  canvasSizeUiState[key] = { syncFromInputs, onWidthInput, onHeightInput };
}

function teardownCanvasSizeInputs(key) {
  const wired = canvasSizeUiState[key];
  if (!wired) return;
  const widthInput = key === "dialog" ? el.dialogCanvasWidth : el.settingsCanvasWidth;
  const heightInput = key === "dialog" ? el.dialogCanvasHeight : el.settingsCanvasHeight;
  widthInput?.removeEventListener("change", wired.syncFromInputs);
  heightInput?.removeEventListener("change", wired.syncFromInputs);
  widthInput?.removeEventListener("input", wired.onWidthInput);
  heightInput?.removeEventListener("input", wired.onHeightInput);
  canvasSizeUiState[key] = null;
}

function setupDialogCanvasSizeControls(initialSize = getProjectCanvasSize()) {
  teardownCanvasSizeInputs("dialog");
  syncCanvasSizeFields(el.dialogCanvasWidth, el.dialogCanvasHeight, el.dialogCanvasPresets, initialSize);
  bindCanvasSizeInputs(el.dialogCanvasWidth, el.dialogCanvasHeight, el.dialogCanvasPresets, "dialog");
}

function setupSettingsCanvasSizeControls(initialSize = getProjectCanvasSize()) {
  teardownCanvasSizeInputs("settings");
  syncCanvasSizeFields(el.settingsCanvasWidth, el.settingsCanvasHeight, el.settingsCanvasPresets, initialSize);
  bindCanvasSizeInputs(el.settingsCanvasWidth, el.settingsCanvasHeight, el.settingsCanvasPresets, "settings");
}

function validateCanvasSizeFields(widthInput, heightInput) {
  const size = readCanvasSizeFields(widthInput, heightInput);
  if (!Number.isFinite(Number(widthInput?.value)) || !Number.isFinite(Number(heightInput?.value))) {
    return "Enter valid canvas width and height.";
  }
  if (size.width < CANVAS_SIZE_LIMITS.minWidth || size.height < CANVAS_SIZE_LIMITS.minHeight) {
    return `Canvas must be at least ${CANVAS_SIZE_LIMITS.minWidth}×${CANVAS_SIZE_LIMITS.minHeight}.`;
  }
  return null;
}

async function showNewProjectSetupDialog() {
  return new Promise((resolve) => {
    dialogState.resolve = resolve;
    dialogState.browse = "folder";
    dialogState.validate = null;
    dialogState.hasInput = true;
    dialogState.listItems = [];

    el.dialogTitle.textContent = "New project";
    el.dialogHint.textContent =
      "Choose a parent folder and canvas size. A Storyboard_Project folder will be created inside it.";
    el.dialogHint.hidden = false;
    setDialogSections({ input: true, canvasSize: true });

    el.dialogInputLabel.textContent = "Parent folder";
    el.dialogInput.value = localStorage.getItem("last_project_parent") || "";
    el.dialogInput.placeholder = "Empty = ./Storyboard_Project";
    el.dialogBrowseBtn.hidden = false;
    setupDialogCanvasSizeControls({ width: 1920, height: 1080 });

    el.dialogFooter.innerHTML = "";
    const spacer = document.createElement("span");
    spacer.className = "modal-spacer";
    el.dialogFooter.appendChild(spacer);

    const cancelButton = document.createElement("button");
    cancelButton.type = "button";
    cancelButton.textContent = "Cancel";
    cancelButton.addEventListener("click", () => closeDialog(null));
    el.dialogFooter.appendChild(cancelButton);

    const createButton = document.createElement("button");
    createButton.type = "button";
    createButton.textContent = "Create";
    createButton.classList.add("btn-primary");
    createButton.addEventListener("click", () => {
      const sizeError = validateCanvasSizeFields(el.dialogCanvasWidth, el.dialogCanvasHeight);
      if (sizeError) {
        setDialogError(sizeError);
        return;
      }
      const size = readCanvasSizeFields(el.dialogCanvasWidth, el.dialogCanvasHeight);
      closeDialog({
        path: el.dialogInput.value.trim(),
        canvas_width: size.width,
        canvas_height: size.height,
      });
    });
    el.dialogFooter.appendChild(createButton);

    setDialogError("");
    el.dialogModal.hidden = false;
    el.dialogInput.focus();
    el.dialogInput.oninput = () => setDialogError("");
  });
}

applyCanvasAspectRatio();


// --- module global bridge (auto) ---
Object.assign(globalThis, {
  CANVAS_SIZE_PRESETS,
  CANVAS_SIZE_LIMITS,
  canvasSizeUiState,
  normalizeCanvasSize,
  getProjectCanvasSize,
  applyCanvasAspectRatio,
  canvasSizeLabel,
  findCanvasPreset,
  renderCanvasSizePresets,
  readCanvasSizeFields,
  syncCanvasSizeFields,
  bindCanvasSizeInputs,
  teardownCanvasSizeInputs,
  setupDialogCanvasSizeControls,
  setupSettingsCanvasSizeControls,
  validateCanvasSizeFields,
  showNewProjectSetupDialog,
});
