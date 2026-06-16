const IMAGE_DROP_EXTENSIONS = new Set([
  ".png",
  ".jpg",
  ".jpeg",
  ".tif",
  ".tiff",
  ".webp",
  ".bmp",
]);

let dropDepth = 0;

function fileExtension(name) {
  const match = String(name || "").match(/(\.[^./\\]+)$/i);
  return match ? match[1].toLowerCase() : "";
}

function isImageDropFile(file) {
  if (!file) return false;
  if (file.type && file.type.startsWith("image/")) return true;
  return IMAGE_DROP_EXTENSIONS.has(fileExtension(file.name));
}

function decodeFileUri(uri) {
  const raw = String(uri || "").trim();
  if (!raw || raw.startsWith("#")) return "";
  const line = raw.split(/\r?\n/).find((item) => item && !item.startsWith("#")) || "";
  if (!line.startsWith("file://")) return "";
  try {
    const url = new URL(line);
    let path = decodeURIComponent(url.pathname || "");
    if (/^\/[A-Za-z]:/.test(path)) path = path.slice(1);
    return path.replace(/\//g, "\\");
  } catch {
    return "";
  }
}

function pathsFromDataTransfer(dataTransfer) {
  const paths = [];
  const uriPath = decodeFileUri(dataTransfer.getData("text/uri-list"));
  if (uriPath) paths.push(uriPath);
  const plain = String(dataTransfer.getData("text/plain") || "").trim();
  if (plain && /^[A-Za-z]:\\/.test(plain)) paths.push(plain);
  return paths;
}

function showDropOverlay() {
  if (el.dropOverlay) el.dropOverlay.hidden = false;
}

function hideDropOverlay() {
  dropDepth = 0;
  if (el.dropOverlay) el.dropOverlay.hidden = true;
}

function hasDropFiles(event) {
  const types = event.dataTransfer?.types;
  if (!types) return false;
  return Array.from(types).includes("Files");
}

async function importDroppedImageFile(file) {
  const shot = selectedShot();
  if (!state.project || !shot) {
    showToast("Open a project and select a board before importing images.");
    return;
  }
  const form = new FormData();
  form.append("file", file);
  await api(`/api/shots/${shot.shot_id}/image`, { method: "POST", body: form, headers: {} }).then(setProject);
  await selectShot(shot.shot_id);
  showToast(`Imported preview for ${shot.shot_id}`);
}

async function importDroppedImagePath(sourcePath) {
  const shot = selectedShot();
  if (!state.project || !shot) {
    showToast("Open a project and select a board before importing images.");
    return;
  }
  await api(`/api/shots/${shot.shot_id}/import-image-path`, {
    method: "POST",
    body: JSON.stringify({ source_path: sourcePath }),
  }).then(setProject);
  await selectShot(shot.shot_id);
  showToast(`Imported preview for ${shot.shot_id}`);
}

async function openDroppedProjectPath(projectPath) {
  const project = await api("/api/project/open", {
    method: "POST",
    body: JSON.stringify({ project_json_path: projectPath }),
  });
  setProject(project);
  clearUndoStack();
  const firstShot = project.shots?.[0]?.shot_id;
  if (firstShot) await selectShot(firstShot);
  else render();
  showToast(`Opened ${project.name}`);
}

async function handleDroppedFiles(dataTransfer) {
  const paths = pathsFromDataTransfer(dataTransfer);
  for (const path of paths) {
    const lower = path.toLowerCase();
    if (lower.endsWith("project.json")) {
      await openDroppedProjectPath(path);
      return;
    }
    if (IMAGE_DROP_EXTENSIONS.has(fileExtension(path))) {
      await importDroppedImagePath(path);
      return;
    }
  }

  const files = [...(dataTransfer.files || [])];
  if (!files.length) return;

  const projectFile = files.find((file) => file.name.toLowerCase() === "project.json");
  if (projectFile) {
    showToast("Drop project.json from Explorer to preserve folder paths.");
    return;
  }

  const imageFile = files.find((file) => isImageDropFile(file));
  if (imageFile) {
    await importDroppedImageFile(imageFile);
    return;
  }

  showToast("Unsupported drop. Use images or project.json.");
}

function bindFileDrop() {
  if (!el.dropOverlay) return;

  document.addEventListener("dragenter", (event) => {
    if (!hasDropFiles(event)) return;
    event.preventDefault();
    dropDepth += 1;
    showDropOverlay();
  });

  document.addEventListener("dragover", (event) => {
    if (!hasDropFiles(event)) return;
    event.preventDefault();
    if (event.dataTransfer) event.dataTransfer.dropEffect = "copy";
  });

  document.addEventListener("dragleave", (event) => {
    if (!hasDropFiles(event)) return;
    dropDepth = Math.max(0, dropDepth - 1);
    if (dropDepth === 0) hideDropOverlay();
  });

  document.addEventListener("drop", async (event) => {
    if (!hasDropFiles(event)) return;
    event.preventDefault();
    hideDropOverlay();
    try {
      await handleDroppedFiles(event.dataTransfer);
    } catch (error) {
      showToast(error.message || "Drop failed");
    }
  });
}

bindFileDrop();


// --- module global bridge (auto) ---
Object.assign(globalThis, {
  IMAGE_DROP_EXTENSIONS,
  dropDepth,
  fileExtension,
  isImageDropFile,
  decodeFileUri,
  pathsFromDataTransfer,
  showDropOverlay,
  hideDropOverlay,
  hasDropFiles,
  importDroppedImageFile,
  importDroppedImagePath,
  openDroppedProjectPath,
  handleDroppedFiles,
  bindFileDrop,
});
