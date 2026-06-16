function resolveReferenceType(ref, project = null) {
  const path = String(ref?.path || "").trim();
  const pathLower = path.toLowerCase();
  const titleLower = String(ref?.title || "").toLowerCase();
  if (/\.(glb|gltf)$/i.test(pathLower) || /\.(glb|gltf)$/i.test(titleLower)) return "model";
  const modelPath = String(project?.settings?.reference_model_path || "").trim();
  if (modelPath && path === modelPath) return "model";
  const scenePath = String(project?.settings?.scene3d?.file_path || "").trim();
  if (scenePath && path === scenePath) return "model";
  const imagePath = String(project?.settings?.reference_image_path || "").trim();
  if (imagePath && path === imagePath) return "image";
  const type = String(ref?.type || "").trim().toLowerCase();
  if (type === "video" || type === "model" || type === "image") return type;
  if (/\.(mp4|mov|webm|mkv|avi|m4v)$/i.test(pathLower)) return "video";
  return "image";
}

function referenceModelPreviewUrl(path, project = null) {
  const normalized = String(path || "").trim();
  if (!normalized) return "";
  const scenePath = String(project?.settings?.scene3d?.file_path || "").trim();
  if (scenePath && normalized === scenePath) {
    return `/api/project/scene3d/file?t=${Date.now()}`;
  }
  return referenceMediaUrl(normalized);
}

function scheduleReferenceModelPreviews(container, attempt = 0) {
  if (!container) return;
  if (typeof window.hydrateReferenceModelPreviews === "function") {
    window.hydrateReferenceModelPreviews(container);
    return;
  }
  if (attempt < 60) {
    window.setTimeout(() => scheduleReferenceModelPreviews(container, attempt + 1), 50);
  }
}

if (!window.__referenceModelPreviewListener) {
  window.__referenceModelPreviewListener = true;
  window.addEventListener("reference-model-preview-ready", () => {
    document.querySelectorAll(".reference-media-panel").forEach((panel) => {
      scheduleReferenceModelPreviews(panel);
    });
  });
}

window.resolveReferenceType = resolveReferenceType;

function referenceSegmentEditorPath(mode) {
  return "/ref-segment";
}

function navigateToReferenceSegmentEditor(mode) {
  if (typeof window.switchRefSegmentView === "function") {
    window.switchRefSegmentView(mode);
    return true;
  }
  const query = window.location.search || "";
  if (!window.location.pathname.endsWith("/ref-segment")) {
    window.location.assign(`/ref-segment${query}#${mode}`);
    return true;
  }
  return false;
}

function referenceLinksFromProject(project) {
  const links = project?.settings?.reference_links;
  return Array.isArray(links) ? links : [];
}

function activeReferenceVideoPath(project) {
  return String(project?.settings?.reference_video_path || "").trim();
}

function referenceMediaUrl(path) {
  const value = String(path || "").trim();
  if (!value) return "";
  return `/api/files?path=${encodeURIComponent(value)}`;
}

function referenceDisplayTitle(ref) {
  return String(ref?.title || "").trim() || String(ref?.path || "").split(/[/\\]/).pop() || "Reference";
}

function renderReferenceEmptyState(message) {
  const empty = document.createElement("div");
  empty.className = "reference-media-empty";
  const icon = document.createElement("div");
  icon.className = "reference-media-empty-icon";
  icon.setAttribute("aria-hidden", "true");
  icon.textContent = "◎";
  const text = document.createElement("p");
  text.className = "reference-media-empty-text";
  text.textContent = message;
  empty.appendChild(icon);
  empty.appendChild(text);
  return empty;
}

function renderReferenceMediaPanel(container, options = {}) {
  if (!container) return;
  const project = options.project || null;
  const links = referenceLinksFromProject(project);
  const activeVideoPath = options.activeVideoPath ?? activeReferenceVideoPath(project);
  const activeModelPath = options.activeModelPath ?? String(project?.settings?.reference_model_path || "").trim();
  const activeImagePath = options.activeImagePath ?? String(project?.settings?.reference_image_path || "").trim();
  const activeMode = String(
    options.activeMode ?? project?.settings?.reference_segment_mode ?? "video"
  ).toLowerCase();
  const boundReferenceId = String(options.boundReferenceId || "").trim();
  const boundReferencePath = String(options.boundReferencePath || "").trim();
  const boundReferenceType = String(options.boundReferenceType || "").trim().toLowerCase();
  const disabled = Boolean(options.disabled);
  const showImport = options.showImport !== false;
  const compact = Boolean(options.compact);

  container.classList.toggle("reference-media-panel", true);
  container.classList.toggle("is-compact", compact);
  if (typeof window.disposeReferenceModelPreviews === "function") {
    window.disposeReferenceModelPreviews(container);
  }
  container.innerHTML = "";

  const header = document.createElement("div");
  header.className = "reference-media-header";

  const heading = document.createElement("div");
  heading.className = "reference-media-heading";
  const title = document.createElement("span");
  title.className = "reference-media-title";
  title.textContent = options.title || "References";
  heading.appendChild(title);
  if (project && links.length) {
    const count = document.createElement("span");
    count.className = "reference-media-count";
    count.textContent = String(links.length);
    count.title = `${links.length} reference${links.length === 1 ? "" : "s"}`;
    heading.appendChild(count);
  }
  header.appendChild(heading);

  const hint = document.createElement("p");
  hint.className = "reference-media-hint";
  hint.textContent = options.hint || "单击绑定到当前 Segment · 双击打开工作台";
  header.appendChild(hint);

  if (showImport) {
    const importButton = document.createElement("button");
    importButton.type = "button";
    importButton.className = "reference-media-import";
    importButton.textContent = "Import";
    importButton.disabled = disabled;
    importButton.title = "Import image or video";
    importButton.addEventListener("click", () => options.onImportClick?.());
    header.appendChild(importButton);
  }
  container.appendChild(header);

  const grid = document.createElement("div");
  grid.className = "reference-media-grid";

  if (!project) {
    grid.appendChild(renderReferenceEmptyState("Open a project to manage references."));
    container.appendChild(grid);
    return;
  }

  if (!links.length) {
    grid.appendChild(renderReferenceEmptyState("No references yet. Import an image, video, or GLB."));
    container.appendChild(grid);
    return;
  }

  links.forEach((rawRef) => {
    const ref = { ...rawRef, type: resolveReferenceType(rawRef, project) };
    const card = document.createElement("div");
    card.className = "reference-media-card";
    const isBound =
      (boundReferenceId && ref.id === boundReferenceId) ||
      (boundReferencePath && ref.path === boundReferencePath);
    if (isBound) {
      card.classList.add("is-bound-segment");
      if (ref.type === "video") card.classList.add("is-active-video");
      else if (ref.type === "model") card.classList.add("is-active-model");
      else if (ref.type === "image") card.classList.add("is-active-image");
    } else if (ref.type === "video" && ref.path === activeVideoPath && activeMode === "video") {
      card.classList.add("is-active-video");
    } else if (ref.type === "model" && ref.path === activeModelPath && activeMode === "model") {
      card.classList.add("is-active-model");
    } else if (ref.type === "image" && ref.path === activeImagePath && activeMode === "image") {
      card.classList.add("is-active-image");
    }

    const preview = document.createElement("button");
    preview.type = "button";
    preview.className = "reference-media-preview";
    preview.title =
      ref.type === "video"
        ? "单击绑定到当前 Segment · 双击打开工作台"
        : ref.type === "model"
          ? "单击绑定到当前 Segment · 双击打开工作台"
          : ref.type === "image"
            ? "单击绑定到当前 Segment · 双击打开工作台"
            : "双击打开工作台";
    const mediaUrl = referenceMediaUrl(ref.path);
    if (ref.type === "video") {
      const video = document.createElement("video");
      video.src = mediaUrl;
      video.muted = true;
      video.playsInline = true;
      video.preload = "metadata";
      preview.appendChild(video);
    } else if (ref.type === "model") {
      const canvas = document.createElement("canvas");
      canvas.className = "reference-media-model-canvas";
      canvas.dataset.refModelPreview = referenceModelPreviewUrl(ref.path, project);
      preview.appendChild(canvas);
    } else {
      const image = document.createElement("img");
      image.src = mediaUrl;
      image.alt = referenceDisplayTitle(ref);
      image.loading = "lazy";
      preview.appendChild(image);
    }

    const typeBadge = document.createElement("span");
    typeBadge.className = `reference-media-type-badge${ref.type === "video" ? " is-video" : ref.type === "model" ? " is-model" : ref.type === "image" ? " is-image" : ""}`;
    typeBadge.textContent = ref.type === "video" ? "VIDEO" : ref.type === "model" ? "GLB" : "IMAGE";
    preview.appendChild(typeBadge);

    if (isBound) {
      const activeChip = document.createElement("span");
      activeChip.className = `reference-media-active-chip${ref.type === "video" ? " is-video" : ref.type === "model" ? " is-model" : " is-image"}`;
      activeChip.textContent = "已绑定";
      preview.appendChild(activeChip);
    } else if (ref.type === "video" && ref.path === activeVideoPath && activeMode === "video") {
      const activeChip = document.createElement("span");
      activeChip.className = "reference-media-active-chip is-video";
      activeChip.textContent = "SEGMENT";
      preview.appendChild(activeChip);
    }
    if (ref.type === "model" && ref.path === activeModelPath && activeMode === "model") {
      const activeChip = document.createElement("span");
      activeChip.className = "reference-media-active-chip is-model";
      activeChip.textContent = "3D SEG";
      preview.appendChild(activeChip);
    }
    if (ref.type === "image" && ref.path === activeImagePath && activeMode === "image") {
      const activeChip = document.createElement("span");
      activeChip.className = "reference-media-active-chip is-image";
      activeChip.textContent = "IMG SEG";
      preview.appendChild(activeChip);
    }

    const deleteButton = document.createElement("button");
    deleteButton.type = "button";
    deleteButton.textContent = "×";
    deleteButton.className = "reference-media-delete";
    deleteButton.title = "Remove";
    deleteButton.disabled = disabled;
    deleteButton.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      options.onDelete?.(ref);
    });
    preview.appendChild(deleteButton);
    bindReferencePreviewInteractions(preview, ref, {
      onSelect: (item) => options.onSelect?.(item),
      onPreview: (item) => options.onPreview?.(item),
    });

    const name = document.createElement("div");
    name.className = "reference-media-name";
    name.textContent = referenceDisplayTitle(ref);
    name.title = referenceDisplayTitle(ref);

    card.appendChild(preview);
    card.appendChild(name);
    grid.appendChild(card);
  });

  container.appendChild(grid);
  scheduleReferenceModelPreviews(container);
}


// --- module global bridge (auto) ---
Object.assign(globalThis, {
  resolveReferenceType,
  referenceModelPreviewUrl,
  scheduleReferenceModelPreviews,
  referenceSegmentEditorPath,
  navigateToReferenceSegmentEditor,
  referenceLinksFromProject,
  activeReferenceVideoPath,
  referenceMediaUrl,
  referenceDisplayTitle,
  renderReferenceEmptyState,
  renderReferenceMediaPanel,
});
