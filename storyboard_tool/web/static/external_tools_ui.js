// Blender / Photoshop external-tool UI: bridge relink, open in Blender, settings dialogs.
//
// Loaded as a classic script AFTER sync_polling.js and BEFORE annotations.js
// (see APP_SCRIPTS in main.js). renderBlenderMenuStatus is called from app.js
// render() and core/settings.js at runtime.

async function relinkPhotoshopBridge() {
  if (!state.project) {
    showToast("Open a project first.");
    return;
  }
  try {
    await publishLiveBridge();
    const status = await api("/api/bridge/relink", { method: "POST" });
    updateBridgeLinkStatus(status);
    showToast("Photoshop link published.");
  } catch (error) {
    renderPsBridgeState("error", error.message || "Link failed");
    showToast(error.message || "Could not publish Photoshop link.");
  }
}

async function openBlenderSettingsDialog() {
  const current =
    state.project?.settings?.blender_path || localStorage.getItem("blender_path_default") || "";
  let candidates = [];
  let templateExists = false;
  try {
    const result = await api("/api/system/blender-candidates");
    candidates = result.candidates || [];
    templateExists = Boolean(result.template_exists);
  } catch {
    candidates = [];
  }
  const blenderPath = await showDialog({
    title: "Blender path",
    hint: templateExists
      ? "Choose blender.exe, or the Blender install folder (Steam / Blender Foundation)."
      : "Choose blender.exe or install folder. Also place scene_template.blend in storyboard_tool/assets/.",
    input: {
      label: "Path",
      value: current,
      placeholder: "e.g. ...\\Steam\\steamapps\\common\\Blender\\blender.exe",
      clearLabel: "Clear (auto-detect)",
    },
    browse: "blender",
    list: {
      title: "Detected installations",
      items: candidates.map((path) => ({
        name: pathBasename(path),
        path,
        subtitle: pathDirname(path),
      })),
    },
    actions: [
      { label: "Cancel", value: null },
      { label: "Save", value: "save", primary: true },
    ],
  });
  if (blenderPath === null) return;
  try {
    if (state.project) {
      await api("/api/project/settings", {
        method: "PATCH",
        body: JSON.stringify({ blender_path: blenderPath }),
      }).then(setProject);
    }
    if (blenderPath) {
      localStorage.setItem("blender_path_default", blenderPath);
    } else {
      localStorage.removeItem("blender_path_default");
    }
    renderBlenderMenuStatus();
    showToast(
      blenderPath
        ? `Blender path saved: ${blenderPath}`
        : "Path cleared. Blender will be auto-detected when possible.",
    );
  } catch {
    // api() already shows the error toast.
  }
}

async function openProjectInBlender() {
  if (!state.project) return;
  try {
    const result = await api("/api/project/scene3d/open-blender", { method: "POST" });
    setProject(result, false);
    renderBlenderMenuStatus();
    if (state.scene3dEditor) {
      state.scene3dEditor.setBlendFilePath(result.settings?.scene3d?.blend_file_path);
    }
    const label = result.relative_path || result.path || "scene.blend";
    showToast(`Opened in Blender: ${label}`);
  } catch {
    // api() already shows the error toast.
  }
}

function renderBlenderMenuStatus() {
  if (!el.blMenuSummary) return;
  el.blMenuSummary.classList.remove("bl-ok", "bl-warn");
  if (!state.project) {
    if (el.blMenuStatus) el.blMenuStatus.textContent = "No project open";
    el.blMenuSummary.title = "Blender";
    return;
  }
  const blendPath = state.project.settings?.scene3d?.blend_file_path || "scene3d/scene.blend";
  const hasBlender =
    state.project.settings?.blender_path || localStorage.getItem("blender_path_default");
  if (blendPath) {
    el.blMenuSummary.classList.add("bl-ok");
    if (el.blMenuStatus) {
      el.blMenuStatus.textContent = hasBlender ? blendPath : `${blendPath} · set Blender path`;
    }
    el.blMenuSummary.title = hasBlender ? `Scene: ${blendPath}` : "Set Blender path in Settings";
  } else {
    el.blMenuSummary.classList.add("bl-warn");
    if (el.blMenuStatus) el.blMenuStatus.textContent = "Add scene_template.blend to assets/";
    el.blMenuSummary.title = "Missing scene template";
  }
}

async function openPhotoshopSettingsDialog() {
  const current =
    state.project?.settings?.photoshop_path || localStorage.getItem("photoshop_path_default") || "";
  let candidates = [];
  try {
    const result = await api("/api/system/photoshop-candidates");
    candidates = result.candidates || [];
  } catch {
    candidates = [];
  }
  const photoshopPath = await showDialog({
    title: "Photoshop path",
    hint: "Choose the local Photoshop executable. Leave empty to use the system default app for PSD files.",
    input: {
      label: "Path",
      value: current,
      placeholder: "e.g. C:\\Program Files\\Adobe\\Adobe Photoshop 2024\\Photoshop.exe",
      clearLabel: "Clear (use system default)",
    },
    browse: "photoshop",
    list: {
      title: "Detected installations",
      items: candidates.map((path) => ({
        name: pathBasename(path),
        path,
        subtitle: pathDirname(path),
      })),
    },
    actions: [
      { label: "Cancel", value: null },
      { label: "Save", value: "save", primary: true },
    ],
  });
  if (photoshopPath === null) return;
  try {
    if (state.project) {
      await api("/api/project/settings", {
        method: "PATCH",
        body: JSON.stringify({ photoshop_path: photoshopPath }),
      }).then(setProject);
    }
    if (photoshopPath) {
      localStorage.setItem("photoshop_path_default", photoshopPath);
    } else {
      localStorage.removeItem("photoshop_path_default");
    }
    showToast(
      photoshopPath
        ? `Photoshop path saved: ${photoshopPath}`
        : "Path cleared. PSD files will open with the system default app.",
    );
  } catch {
    // api() already shows the error toast.
  }
}

el.linkPhotoshop?.addEventListener("click", () => relinkPhotoshopBridge());
el.openBlender?.addEventListener("click", () => openProjectInBlender());
el.openBlenderScene?.addEventListener("click", () => openProjectInBlender());


// --- module global bridge (auto) ---
Object.assign(globalThis, {
  relinkPhotoshopBridge,
  openBlenderSettingsDialog,
  openProjectInBlender,
  renderBlenderMenuStatus,
  openPhotoshopSettingsDialog,
});
