// 3D scene modal: Blender import, camera sync, capture-to-board.
//
// Loaded AFTER annotations.js and BEFORE app.js (see APP_SCRIPTS in main.js).
// Dynamically imports scene3d.js; relies on app.js globals at call time for
// setProject, saveShot, openProjectInBlender, etc.

export function isScene3dOpen() {
  return Boolean(el.canvasArea?.classList.contains("scene3d-active"));
}

function getShotCameraForScene3d() {
  const shot = selectedShot();
  if (!shot) return null;
  const data = { ...(shot.camera_data || {}) };
  if (!data.position && data.location) {
    data.position = parseCameraVec(data.location);
  }
  if (!data.rotation && data.rotation_text) {
    data.rotation = parseCameraVec(data.rotation_text);
  } else if (!Array.isArray(data.rotation) && typeof data.rotation === "string") {
    data.rotation = parseCameraVec(data.rotation);
  }
  if (!data.fov && data.focal_length) {
    const focal = Number(data.focal_length);
    if (!Number.isNaN(focal) && focal > 0) {
      const sensor = 36;
      data.fov = (2 * Math.atan(sensor / (2 * focal)) * 180) / Math.PI;
    }
  }
  return data.position ? data : null;
}

function applyShotCameraFromScene3d(cameraState) {
  const shot = selectedShot();
  if (!shot || !cameraState) return;
  const positionText = formatCameraVec(cameraState.position);
  const targetText = formatCameraVec(cameraState.target);
  const rotationText = formatCameraVec(cameraState.rotation, true);
  shot.camera_data = {
    ...(shot.camera_data || {}),
    position: cameraState.position,
    target: cameraState.target,
    rotation: cameraState.rotation,
    rotation_text: rotationText,
    fov: cameraState.fov,
    focal_length: String(cameraState.focal_length ?? ""),
    location: positionText,
    angle: targetText,
  };
  saveShot(shot).then(() => {
    renderInspector(shot);
    showToast("已保存镜头相机到当前分镜");
  });
}

async function loadScene3DEditorClass() {
  if (loadScene3DEditorClass.cached) return loadScene3DEditorClass.cached;
  try {
    const bust = loadScene3DEditorClass._v ?? (loadScene3DEditorClass._v = String(Date.now()));
    const module = await import(`/static/scene3d.js?v=${encodeURIComponent(bust)}`);
    loadScene3DEditorClass.cached = module.Scene3DEditor;
    return loadScene3DEditorClass.cached;
  } catch (error) {
    console.error("Failed to load 3D scene module:", error);
    const detail = error?.message || String(error);
    showToast(`3D 模块加载失败：${detail}`);
    throw error;
  }
}

function getBoardPreviewUrl() {
  const shot = selectedShot();
  if (!shot || (!shot.preview_image_path && !shot.image_path)) return "";
  return `/api/shots/${shot.shot_id}/image?t=${Date.now()}`;
}

function getBoardLabel() {
  const shot = selectedShot();
  if (!shot) return "—";
  const shots = state.project?.shots || [];
  const index = shots.findIndex((item) => item.shot_id === shot.shot_id);
  return `${formatShotId(shot.shot_id)} · Board ${index >= 0 ? index + 1 : "?"}`;
}

function getShotScene3dTime() {
  const shot = selectedShot();
  if (!shot?.camera_data) return null;
  const value = shot.camera_data.scene3d_time;
  return value != null && value !== "" ? Number(value) : null;
}

export async function captureScene3dToBoard() {
  const shot = selectedShot();
  if (!shot || !state.scene3dEditor) {
    showToast("请先打开 3D 场景并选择分镜");
    return;
  }
  try {
    const dataUrl = state.scene3dEditor.captureFrameDataUrl();
    const blob = await (await fetch(dataUrl)).blob();
    const form = new FormData();
    form.append("file", blob, `${shot.shot_id}_3d_frame.png`);
    await api(`/api/shots/${shot.shot_id}/image`, { method: "POST", body: form, headers: {} }).then(setProject);
    const anim = state.scene3dEditor.getAnimationState();
    shot.camera_data = {
      ...(shot.camera_data || {}),
      scene3d_time: anim.time,
      scene3d_camera: anim.camera_name,
    };
    await saveShot(shot);
    render();
    state.scene3dEditor?.refreshBoardPreview();
    showToast(`已印到分镜 ${formatShotId(shot.shot_id)} (${anim.time.toFixed(2)}s)`);
  } catch (error) {
    showToast(error?.message || String(error));
  }
}

let scene3dSettingsSaveTimer = null;

function scene3dSceneKey(project) {
  const scene3d = project?.settings?.scene3d;
  if (!scene3d) return `empty:${project?.project_json_path || ""}`;
  return `${scene3d.source || "builtin"}:${scene3d.file_path || ""}:${project?.project_json_path || ""}`;
}

function schedulePersistScene3dSettings(scene3d) {
  window.clearTimeout(scene3dSettingsSaveTimer);
  scene3dSettingsSaveTimer = window.setTimeout(async () => {
    if (!state.project) return;
    try {
      const project = await api("/api/project/settings", {
        method: "PATCH",
        body: JSON.stringify({ scene3d }),
      });
      setProject(project, false);
    } catch (error) {
      console.warn("Failed to autosave 3D settings:", error);
    }
  }, 120);
}

export async function openScene3dModal() {
  if (!state.project) return;
  if (typeof abandonPendingRefSegmentAssign === "function") {
    await abandonPendingRefSegmentAssign();
  }
  el.canvasArea?.classList.add("scene3d-active");
  if (!state.scene3dEditor) {
    let Scene3DEditor;
    try {
      Scene3DEditor = await loadScene3DEditorClass();
      state.scene3dEditor = new Scene3DEditor(el.scene3dRoot, {
        getShotCamera: () => getShotCameraForScene3d(),
        getShotScene3dTime: () => getShotScene3dTime(),
        getBoardPreviewUrl: () => getBoardPreviewUrl(),
        getBoardLabel: () => getBoardLabel(),
        onApplyShotCamera: (cameraState) => applyShotCameraFromScene3d(cameraState),
        onImportBlender: () => el.scene3dFile.click(),
        onOpenBlender: () => openProjectInBlender(),
        onCaptureToBoard: () => captureScene3dToBoard(),
        onMessage: (message) => showToast(message),
        onSceneSettingsChange: (scene3d) => schedulePersistScene3dSettings(scene3d),
      });
    } catch (error) {
      el.canvasArea?.classList.remove("scene3d-active");
      state.scene3dEditor = null;
      if (!String(error?.message || "").includes("3D 模块加载失败")) {
        showToast(`3D 启动失败：${error?.message || error}`);
      }
      return;
    }
  }
  try {
    const scene3dSettings = state.project.settings?.scene3d || null;
    const nextSceneKey = scene3dSceneKey(state.project);
    if (!state.scene3dLoadedKey || state.scene3dLoadedKey !== nextSceneKey) {
      await state.scene3dEditor.loadSceneData(scene3dSettings);
      state.scene3dLoadedKey = nextSceneKey;
    } else {
      state.scene3dEditor.applyDisplaySettings(scene3dSettings);
    }
    state.scene3dEditor.setBlendFilePath(state.project.settings?.scene3d?.blend_file_path);
    const shotTime = getShotScene3dTime();
    if (shotTime != null && !Number.isNaN(shotTime)) {
      state.scene3dEditor.setAnimationTime(shotTime);
    }
    state.scene3dEditor.refreshBoardPreview();
    requestAnimationFrame(() => state.scene3dEditor?._resize?.());
  } catch (error) {
    showToast(`3D 场景加载失败：${error?.message || error}`);
  }
}

export async function refreshScene3dFile() {
  if (!state.scene3dEditor) {
    showToast("请先打开 3D Scene");
    return;
  }
  await state.scene3dEditor.reloadBlenderScene();
}

export async function importBlenderScene(file) {
  if (!file || !state.project) return;
  const formData = new FormData();
  formData.append("file", file);
  try {
    let result;
    if (preferHttpApi()) {
      const response = await fetch("/api/project/scene3d/import", { method: "POST", body: formData });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload.detail || response.statusText);
      }
      result = await response.json();
    } else {
      const bridge = await whenDesktopBridgeReady();
      if (bridge) {
        result = await bridgeUpload(bridge, "/api/project/scene3d/import", formData);
      } else {
        const response = await fetch("/api/project/scene3d/import", { method: "POST", body: formData });
        if (!response.ok) {
          const payload = await response.json().catch(() => ({}));
          throw new Error(payload.detail || response.statusText);
        }
        result = await response.json();
      }
    }
    setProject(result, false);
    if (state.scene3dEditor) {
      await state.scene3dEditor.loadSceneData(result.scene3d || result.settings?.scene3d || null);
      state.scene3dLoadedKey = scene3dSceneKey(state.project);
    }
    showToast(`已导入 Blender 场景：${file.name}`);
  } catch (error) {
    showToast(error?.message || String(error));
  } finally {
    el.scene3dFile.value = "";
  }
}

export function closeScene3dModal() {
  state.scene3dEditor?.pauseAnimation();
  el.canvasArea?.classList.remove("scene3d-active");
}

export async function saveScene3dData() {
  if (!state.project || !state.scene3dEditor) return;
  const scene3d = state.scene3dEditor.exportSceneData();
  await api("/api/project/settings", {
    method: "PATCH",
    body: JSON.stringify({ scene3d }),
  }).then((project) => {
    setProject(project, false);
    showToast("3D 场景已保存");
  });
}

el.openScene3d.addEventListener("click", () => {
  if (isScene3dOpen()) {
    closeScene3dModal();
    return;
  }
  openScene3dModal();
});
el.saveScene3d.addEventListener("click", () => saveScene3dData());
el.captureScene3d?.addEventListener("click", () => captureScene3dToBoard());
el.importScene3d.addEventListener("click", () => el.scene3dFile.click());
el.reloadScene3d?.addEventListener("click", () => refreshScene3dFile());
el.scene3dFile.addEventListener("change", () => importBlenderScene(el.scene3dFile.files?.[0]));
el.closeScene3d?.addEventListener("click", () => closeScene3dModal());
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && isScene3dOpen()) {
    closeScene3dModal();
  }
});
