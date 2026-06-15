// Modal dialog subsystem: showDialog, project new/open, browse helpers.
//
// Loaded as a classic script AFTER core/utils.js and BEFORE core/canvas_size.js
// (see APP_SCRIPTS in main.js). Exports globals used by canvas_size.js,
// canvas_color.js, annotations.js, and app.js.

function rememberProjectPath(projectJsonPath) {
  const recent = [projectJsonPath, ...getRecentProjects().filter((item) => item !== projectJsonPath)].slice(0, 10);
  localStorage.setItem("recent_projects", JSON.stringify(recent));
}

function setDialogError(message) {
  if (!message) {
    el.dialogError.hidden = true;
    el.dialogError.textContent = "";
    return;
  }
  el.dialogError.hidden = false;
  el.dialogError.textContent = message;
}

function renderDialogList(items, activePath, onSelect) {
  el.dialogList.innerHTML = "";
  if (!items.length) {
    el.dialogList.innerHTML = '<div class="dialog-item-empty">No matches found. Use Browse to pick a path.</div>';
    return;
  }
  const normalized = (activePath || "").trim().toLowerCase();
  items.forEach((item) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `dialog-item ${item.path?.toLowerCase() === normalized ? "active" : ""}`;
    button.dataset.path = item.path || "";
    button.innerHTML = `<span class="dialog-item-name">${escapeHtml(item.name || pathBasename(item.path))}</span><span class="dialog-item-path">${escapeHtml(item.subtitle || pathDirname(item.path))}</span>`;
    button.addEventListener("click", () => onSelect(item.path));
    el.dialogList.appendChild(button);
  });
}

function highlightDialogList(path) {
  const normalized = (path || "").trim().toLowerCase();
  el.dialogList.querySelectorAll(".dialog-item").forEach((button) => {
    button.classList.toggle("active", button.dataset.path?.toLowerCase() === normalized);
  });
}

function setDialogSections({ input = false, list = false, color = false, canvasSize = false } = {}) {
  el.dialogInputSection.hidden = !input;
  el.dialogListSection.hidden = !list;
  el.dialogColorSection.hidden = !color;
  el.dialogCanvasSizeSection.hidden = !canvasSize;
  if (!color) teardownCanvasColorControls();
  if (!canvasSize) teardownCanvasSizeInputs("dialog");
}

function closeDialog(result) {
  el.dialogModal.hidden = true;
  setDialogSections();
  setDialogError("");
  const resolve = dialogState.resolve;
  dialogState.resolve = null;
  resolve?.(result);
  dialogState.browse = null;
  dialogState.validate = null;
  dialogState.hasInput = false;
  dialogState.listItems = [];
}

function showDialog(config) {
  return new Promise((resolve) => {
    dialogState.resolve = resolve;
    dialogState.browse = config.browse || null;
    dialogState.validate = config.validate || null;
    dialogState.listItems = config.list?.items || [];
    dialogState.hasInput = Boolean(config.input);

    el.dialogTitle.textContent = config.title || "";
    el.dialogHint.textContent = config.hint || "";
    el.dialogHint.hidden = !config.hint;
    setDialogSections({ input: Boolean(config.input), list: Boolean(config.list), color: false });

    if (config.input) {
      el.dialogInputLabel.textContent = config.input.label || "Path";
      el.dialogInput.value = config.input.value || "";
      el.dialogInput.placeholder = config.input.placeholder || "";
      el.dialogBrowseBtn.hidden = !config.browse;
    } else {
      el.dialogBrowseBtn.hidden = true;
    }

    if (config.list) {
      el.dialogListTitle.textContent = config.list.title || "";
      renderDialogList(config.list.items || [], config.input?.value || "", (path) => {
        if (config.input) el.dialogInput.value = path;
        setDialogError("");
        highlightDialogList(path);
      });
    } else {
      el.dialogList.innerHTML = "";
    }

    el.dialogFooter.innerHTML = "";
    if (config.input?.clearLabel) {
      const clearButton = document.createElement("button");
      clearButton.type = "button";
      clearButton.textContent = config.input.clearLabel;
      clearButton.addEventListener("click", () => {
        el.dialogInput.value = "";
        setDialogError("");
        highlightDialogList("");
      });
      el.dialogFooter.appendChild(clearButton);
    }

    const spacer = document.createElement("span");
    spacer.className = "modal-spacer";
    el.dialogFooter.appendChild(spacer);

    (config.actions || []).forEach((action) => {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = action.label;
      if (action.primary) button.classList.add("btn-primary");
      if (action.danger) button.classList.add("btn-danger");
      button.addEventListener("click", async () => {
        if (action.value === null || action.value === "cancel") {
          closeDialog(null);
          return;
        }
        if (config.input) {
          const value = el.dialogInput.value.trim();
          if (dialogState.validate) {
            const error = dialogState.validate(value);
            if (error) {
              setDialogError(error);
              return;
            }
          }
          if (action.submitValue !== undefined) {
            closeDialog(action.submitValue);
            return;
          }
          closeDialog(value);
          return;
        }
        closeDialog(action.value);
      });
      el.dialogFooter.appendChild(button);
    });

    setDialogError("");
    el.dialogModal.hidden = false;
    if (config.input) {
      el.dialogInput.focus();
      el.dialogInput.oninput = () => {
        setDialogError("");
        highlightDialogList(el.dialogInput.value.trim());
      };
    }
  });
}

async function browseFromDialog() {
  const browseMap = {
    folder: "/api/system/browse-folder",
    "project-json": "/api/system/browse-project-json",
    photoshop: "/api/system/browse-photoshop",
    blender: "/api/system/browse-blender",
  };
  const endpoint = browseMap[dialogState.browse];
  if (!endpoint) return;
  el.dialogBrowseBtn.disabled = true;
  setDialogError("Opening file picker…");
  try {
    const result = await api(endpoint, { method: "POST", silent: true });
    setDialogError("");
    if (result.cancelled) return;
    el.dialogInput.value = result.path || "";
    highlightDialogList(result.path || "");
  } catch (error) {
    const message =
      error.message === "Not Found"
        ? "Browse API unavailable. Restart the app (python main.py) and try again."
        : error.message;
    setDialogError(message);
  } finally {
    el.dialogBrowseBtn.disabled = false;
  }
}

async function confirmUnsaved() {
  if (!state.project?.dirty) return true;
  const choice = await showDialog({
    title: "Unsaved changes",
    hint: "This project has unsaved changes. Save before continuing?",
    actions: [
      { label: "Cancel", value: null },
      { label: "Don't save", value: "discard" },
      { label: "Save and continue", value: "save", primary: true },
    ],
  });
  if (!choice) return false;
  if (choice === "save") {
    await flushSelectedShot();
    await api("/api/project/save", { method: "POST" }).then(setProject);
  }
  return true;
}

async function openNewProjectDialog() {
  if (!(await confirmUnsaved())) return;
  const result = await showNewProjectSetupDialog();
  if (result === null) return;
  try {
    await api("/api/project/new", {
      method: "POST",
      body: JSON.stringify({
        path: result.path || null,
        canvas_width: result.canvas_width,
        canvas_height: result.canvas_height,
      }),
    }).then(setProject);
    clearUndoStack();
    if (result.path) localStorage.setItem("last_project_parent", result.path);
    showToast(`Project created · ${canvasSizeLabel(result)}`);
  } catch {
    // api() already toasts
  }
}

async function openOpenProjectDialog() {
  if (!(await confirmUnsaved())) return;
  const recent = getRecentProjects();
  const projectJsonPath = await showDialog({
    title: "Open project",
    hint: "Choose a project.json file or pick from recent projects.",
    input: {
      label: "project.json path",
      value: recent[0] || "",
      placeholder: "e.g. D:\\MyProject\\Storyboard_Project\\project.json",
    },
    browse: "project-json",
    list: recent.length
      ? {
          title: "Recent projects",
          items: recent.map((path) => ({
            name: pathBasename(pathDirname(path)) || pathBasename(path),
            path,
            subtitle: pathDirname(path),
          })),
        }
      : undefined,
    validate: (value) => (value ? null : "Choose a project.json file."),
    actions: [
      { label: "Cancel", value: null },
      { label: "Open", value: "open", primary: true },
    ],
  });
  if (!projectJsonPath) return;
  try {
    await api("/api/project/open", {
      method: "POST",
      body: JSON.stringify({ project_json_path: projectJsonPath }),
    }).then(setProject);
    clearUndoStack();
    rememberProjectPath(projectJsonPath);
    showToast("Project opened.");
  } catch {
    // api() already toasts
  }
}

document.querySelectorAll("[data-dialog-cancel]").forEach((node) => {
  node.addEventListener("click", () => closeDialog(null));
});
el.dialogModal.addEventListener("keydown", (event) => {
  if (event.key === "Escape") closeDialog(null);
  if (event.key === "Enter" && dialogState.hasInput && !event.shiftKey) {
    const primary = el.dialogFooter.querySelector(".btn-primary");
    if (primary && document.activeElement === el.dialogInput) {
      event.preventDefault();
      primary.click();
    }
  }
});
el.dialogBrowseBtn.addEventListener("click", () => browseFromDialog());
el.newProject.addEventListener("click", () => openNewProjectDialog());
el.openProject.addEventListener("click", () => openOpenProjectDialog());
