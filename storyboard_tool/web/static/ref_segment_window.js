import { Scene3DEditor } from "./scene3d.js";

const s = {
  project: null,
  mode: "video",
  segmentId: "",
  boardRange: null,
  boardDuration: 0,
  mediaDuration: 0,
  segmentStart: 0,
  segmentDrag: null,
  saveTimer: 0,
  fitMode: "fit",
  editor: null,
  editorReady: null,
  sceneLoadedPath: "",
  bootstrapReady: false,
};

let switchSegmentChain = Promise.resolve();
let pendingParentMessage = null;
let saveGeneration = 0;

function handleParentMessage(data) {
  if (!data || data.source !== "storyboard-ref-parent") return;
  if (data.type === "overlay-hidden") {
    saveGeneration += 1;
    window.clearTimeout(s.saveTimer);
    s.saveTimer = 0;
    if (el.video && !el.video.paused) el.video.pause();
    return;
  }
  if (data.type === "switch-segment") {
    switchToSegment(data.segmentId, data.mode).catch(() => {});
    return;
  }
  if (data.type === "switch-view") {
    switchToSegment(s.segmentId, data.mode).catch(() => {});
  }
}

const el = {
  app: document.querySelector(".rsg-app"),
  referencesPanel: document.getElementById("rsgReferencesPanel"),
  referenceFile: document.getElementById("rsgReferenceFile"),
  panelTitle: document.getElementById("rsgPanelTitle"),
  meta: document.getElementById("rsgMeta"),
  boardMeta: document.getElementById("rsgBoardMeta"),
  video: document.getElementById("rsgVideo"),
  videoEmpty: document.getElementById("rsgVideoEmpty"),
  image: document.getElementById("rsgImage"),
  imageEmpty: document.getElementById("rsgImageEmpty"),
  sceneRoot: document.getElementById("rsgSceneRoot"),
  sceneEmpty: document.getElementById("rsgSceneEmpty"),
  scrubber: document.getElementById("rsgMediaScrubber"),
  segmentTimeline: document.getElementById("rsgSegmentTimeline"),
  segmentLayer: document.getElementById("rsgSegmentLayer"),
  playhead: document.getElementById("rsgPlayhead"),
  segmentSummary: document.getElementById("rsgSegmentSummary"),
  apply: document.getElementById("rsgApply"),
  fitBoards: document.getElementById("rsgFitBoards"),
  resetStart: document.getElementById("rsgResetStart"),
  fitModeGroup: document.querySelector(".rsg-fit-mode"),
  toast: document.getElementById("rsgToast"),
};

function showToast(message) {
  el.toast.textContent = message;
  el.toast.hidden = false;
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => {
    el.toast.hidden = true;
  }, 3200);
}

async function api(url, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (!(options.body instanceof FormData)) headers["Content-Type"] = "application/json";
  const response = await fetch(url, {
    headers,
    ...options,
    body:
      options.body instanceof FormData || typeof options.body === "string" || options.body == null
        ? options.body
        : JSON.stringify(options.body),
  });
  if (!response.ok) {
    let message = response.statusText;
    try {
      const payload = await response.json();
      message = payload.detail || payload.error || message;
    } catch {
      // keep
    }
    throw new Error(message);
  }
  return response.json();
}

function clampSeconds(value, min, max) {
  return Math.min(max, Math.max(min, Number(value) || 0));
}

function formatClock(seconds) {
  const totalMs = Math.max(0, Math.round((Number(seconds) || 0) * 1000));
  const mins = Math.floor(totalMs / 60000);
  const secs = Math.floor((totalMs % 60000) / 1000);
  const ms = totalMs % 1000;
  return `${String(mins).padStart(2, "0")}:${String(secs).padStart(2, "0")}.${String(ms).padStart(3, "0")}`;
}

function round3(value) {
  return Math.round((Number(value) || 0) * 1000) / 1000;
}

const REFERENCE_FIT_MODES = ["fit", "fill", "stretch"];

function normalizeReferenceFitMode(value) {
  const mode = String(value || "fit").trim().toLowerCase();
  return REFERENCE_FIT_MODES.includes(mode) ? mode : "fit";
}

function referenceFitModeToObjectFit(mode) {
  const normalized = normalizeReferenceFitMode(mode);
  if (normalized === "fill") return "cover";
  if (normalized === "stretch") return "fill";
  return "contain";
}

function applyReferenceFitPreview(fitMode = s.fitMode) {
  s.fitMode = normalizeReferenceFitMode(fitMode);
  const cssFit = referenceFitModeToObjectFit(s.fitMode);
  if (el.video) el.video.style.objectFit = cssFit;
  if (el.image) el.image.style.objectFit = cssFit;
  if (el.app) el.app.dataset.refFit = s.fitMode;
  el.fitModeGroup?.querySelectorAll("[data-fit-mode]").forEach((btn) => {
    btn.classList.toggle("is-active", btn.dataset.fitMode === s.fitMode);
  });
}

function loadSegmentFitMode() {
  const saved = currentSavedSegment();
  s.fitMode = normalizeReferenceFitMode(saved?.fit_mode);
  applyReferenceFitPreview(s.fitMode);
}

async function setSegmentFitMode(mode) {
  const next = normalizeReferenceFitMode(mode);
  if (s.fitMode === next) return;
  s.fitMode = next;
  applyReferenceFitPreview(next);
  await saveSegmentNow();
}

function activeReferenceImagePath(project, segment = null) {
  const path = String(segment?.reference_path || "").trim();
  if (path) return path;
  return String(project?.settings?.reference_image_path || "").trim();
}

function activeReferenceModelPath(project, segment = null) {
  const path = String(segment?.reference_path || "").trim();
  if (path) return path;
  return String(project?.settings?.reference_model_path || "").trim();
}

function activeReferenceVideoPathForSegment(project, segment = null) {
  const path = String(segment?.reference_path || "").trim();
  if (path) return path;
  return activeReferenceVideoPath(project);
}

function currentSavedSegment(project = s.project) {
  const segments = Array.isArray(project?.settings?.ref_segments) ? project.settings.ref_segments : [];
  const preferredId =
    String(s.segmentId || "").trim() ||
    new URLSearchParams(window.location.search).get("segment") ||
    String(project?.settings?.active_ref_segment_id || "").trim();
  let saved = preferredId ? segments.find((segment) => segment.id === preferredId) : null;
  if (!saved) saved = segments[0];
  return saved || null;
}

function fixedSegmentLength() {
  return Math.max(0.001, s.boardDuration || 0);
}

function maxSegmentStart() {
  if (s.mode === "image") return 0;
  if (!s.mediaDuration) return 0;
  if (fixedSegmentLength() >= s.mediaDuration) return 0;
  return Math.max(0, s.mediaDuration - fixedSegmentLength());
}

function clampSegmentStart(start) {
  if (s.mode === "image") return 0;
  return clampSeconds(start, 0, maxSegmentStart());
}

function segmentVisualEnd(start = s.segmentStart) {
  if (s.mode === "image") return fixedSegmentLength();
  if (!s.mediaDuration) return start + fixedSegmentLength();
  return Math.min(start + fixedSegmentLength(), s.mediaDuration);
}

function timelineInnerWidth() {
  const rect = el.segmentTimeline.getBoundingClientRect();
  return Math.max(1, rect.width - 24);
}

function timelineDeltaSeconds(deltaPx) {
  const duration = s.mode === "image" ? fixedSegmentLength() : s.mediaDuration;
  if (!duration) return 0;
  return (deltaPx / timelineInnerWidth()) * duration;
}

function timelineXForTime(time) {
  const rect = el.segmentTimeline.getBoundingClientRect();
  const innerLeft = rect.left + 12;
  const duration = s.mode === "image" ? fixedSegmentLength() : s.mediaDuration;
  const ratio = duration > 0 ? clampSeconds(time, 0, duration) / duration : 0;
  return innerLeft + ratio * timelineInnerWidth();
}

function notifyOpener(payload) {
  const target = window.opener && !window.opener.closed ? window.opener : null;
  const parent = window.parent && window.parent !== window ? window.parent : null;
  const receiver = target || parent;
  if (!receiver) return false;
  receiver.postMessage({ source: "storyboard-ref-scene3d", ...payload }, window.location.origin);
  receiver.postMessage({ source: "storyboard-ref-video", ...payload }, window.location.origin);
  return true;
}

function notifyParentSegmentUpdate({ segmentId, patch, setActive = false } = {}) {
  const id = String(segmentId || "").trim();
  if (!id || !patch || typeof patch !== "object") return Promise.resolve(false);

  const generation = saveGeneration;
  const requestId = `segupd_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`;
  const hasParent = notifyOpener({ type: "ref-segment-update", requestId, segmentId: id, patch, setActive });
  if (!hasParent) return Promise.resolve(false);

  return new Promise((resolve) => {
    const timeout = window.setTimeout(() => {
      window.removeEventListener("message", onAck);
      resolve(false);
    }, 5000);

    function onAck(event) {
      if (event.origin !== window.location.origin) return;
      if (event.data?.source !== "storyboard-ref-parent") return;
      if (event.data?.type !== "ref-segment-update-ack") return;
      if (event.data?.requestId !== requestId) return;
      window.clearTimeout(timeout);
      window.removeEventListener("message", onAck);
      resolve(Boolean(event.data.ok !== false));
    }

    window.addEventListener("message", onAck);
  }).then((ok) => ok && generation === saveGeneration);
}

function resolveBoardRange(project) {
  const shots = project?.shots || [];
  if (!shots.length) return null;
  const saved = currentSavedSegment(project);
  if (!saved) {
    const legacy = project?.settings?.ref_segment;
    if (legacy?.anchor_shot_id && legacy?.end_shot_id) {
      const min = shots.findIndex((shot) => shot.shot_id === legacy.anchor_shot_id);
      const max = shots.findIndex((shot) => shot.shot_id === legacy.end_shot_id);
      if (min >= 0 && max >= 0) {
        s.segmentId = "";
        return { min: Math.min(min, max), max: Math.max(min, max), anchor: min, end: max };
      }
    }
    return null;
  }
  const min = shots.findIndex((shot) => shot.shot_id === saved.anchor_shot_id);
  const max = shots.findIndex((shot) => shot.shot_id === saved.end_shot_id);
  if (min < 0 || max < 0) return null;
  s.segmentId = saved.id || "";
  return { min: Math.min(min, max), max: Math.max(min, max), anchor: min, end: max };
}

function boardDurationSeconds(project, range) {
  let total = 0;
  for (let index = range.min; index <= range.max; index += 1) {
    total += Number(project.shots[index]?.duration_seconds || 3);
  }
  return total;
}

function panelTitles() {
  return { video: "Video Segment", model: "3D Segment", image: "Image Segment" };
}

async function ensureSceneEditor() {
  if (s.editor) return s.editor;
  if (!s.editorReady) {
    s.editorReady = Promise.resolve().then(() => {
      s.editor = new Scene3DEditor(el.sceneRoot, { onMessage: (msg) => showToast(msg) });
      return s.editor;
    });
  }
  return s.editorReady;
}

function updateMeta() {
  const titles = panelTitles();
  const saved = currentSavedSegment();
  if (el.panelTitle) el.panelTitle.textContent = titles[s.mode] || "Segment";
  if (s.mode === "video") {
    const path = activeReferenceVideoPathForSegment(s.project, saved);
    const name = path ? path.split(/[/\\]/).pop() : "—";
    const w = el.video.videoWidth || 0;
    const h = el.video.videoHeight || 0;
    const size = w && h ? `${w}×${h}` : "—";
    el.meta.textContent = `${name} | ${size} | ${formatClock(s.mediaDuration || 0)}`;
    return;
  }
  if (s.mode === "image") {
    const path = activeReferenceImagePath(s.project, saved);
    el.meta.textContent = path ? path.split(/[/\\]/).pop() : "No image selected";
    return;
  }
  const path = activeReferenceModelPath(s.project, saved);
  const name = path ? path.split(/[/\\]/).pop() : "—";
  const camera = s.editor?.getAnimationState?.().camera_name || "—";
  el.meta.textContent = `${name} | ${formatClock(s.mediaDuration || 0)} | ${camera}`;
}

async function loadVideoView() {
  const saved = currentSavedSegment();
  const url = referenceMediaUrl(activeReferenceVideoPathForSegment(s.project, saved));
  if (!url) {
    s.mediaDuration = 0;
    el.video.removeAttribute("src");
    el.video.load();
    el.videoEmpty.hidden = false;
    el.video.hidden = true;
    el.scrubber.disabled = true;
    updateMeta();
    renderSegment();
    return;
  }
  el.videoEmpty.hidden = true;
  el.video.hidden = false;
  el.scrubber.disabled = false;
  if (el.video.src !== url) {
    el.video.src = url;
    el.video.load();
  }
}

async function loadImageView() {
  const saved = currentSavedSegment();
  const path = activeReferenceImagePath(s.project, saved);
  const url = referenceMediaUrl(path);
  if (!url) {
    s.mediaDuration = fixedSegmentLength() || 1;
    el.image.removeAttribute("src");
    el.imageEmpty.hidden = false;
    el.image.hidden = true;
    updateMeta();
    renderSegment();
    return;
  }
  el.imageEmpty.hidden = true;
  el.image.hidden = false;
  el.image.src = url;
  s.mediaDuration = fixedSegmentLength() || 1;
  s.segmentStart = 0;
  updateMeta();
  renderSegment();
}

async function loadModelView() {
  const saved = currentSavedSegment();
  const path = activeReferenceModelPath(s.project, saved);
  if (!path) {
    s.mediaDuration = 0;
    el.sceneEmpty.hidden = false;
    el.scrubber.disabled = true;
    updateMeta();
    renderSegment();
    return;
  }
  el.sceneEmpty.hidden = true;
  el.scrubber.disabled = false;
  const editor = await ensureSceneEditor();
  const sceneSettings = s.project?.settings?.scene3d || {};
  if (!sceneSettings.file_path) {
    el.sceneEmpty.hidden = false;
    return;
  }
  const scenePath = String(sceneSettings.file_path || "");
  if (s.sceneLoadedPath !== scenePath || !editor.blenderRoot) {
    await editor.loadSceneData(sceneSettings);
    s.sceneLoadedPath = scenePath;
  }
  s.mediaDuration = Number(editor.animationDuration) || 0;
  loadSegmentFromSettings();
  updateMeta();
  renderSegment();
  updateScrubber();
}

function updateSegmentUrl(segmentId, mode) {
  try {
    const url = new URL(window.location.href);
    if (segmentId) url.searchParams.set("segment", segmentId);
    else url.searchParams.delete("segment");
    if (mode) url.hash = `#${mode}`;
    window.history.replaceState(null, "", `${url.pathname}${url.search}${url.hash}`);
  } catch {
    // keep current URL
  }
}

async function switchToSegment(segmentId, mode) {
  const targetId = String(segmentId || "").trim();
  const nextMode = mode === "model" || mode === "image" ? mode : "video";
  if (!targetId) return;

  switchSegmentChain = switchSegmentChain.then(async () => {
    window.clearTimeout(s.saveTimer);
    s.saveTimer = 0;
    try {
      await saveSegmentNow();
    } catch {
      // keep switching even if save fails
    }

    const sameSegment = s.segmentId === targetId;
    s.segmentId = targetId;
    updateSegmentUrl(targetId, nextMode);

    try {
      s.project = await api("/api/project");
    } catch (error) {
      showToast(error.message || "Failed to refresh project.");
      return;
    }

    s.boardRange = resolveBoardRange(s.project);
    if (!s.boardRange) {
      showToast("Segment boards not found.");
      return;
    }
    s.boardDuration = boardDurationSeconds(s.project, s.boardRange);
    el.boardMeta.textContent = `Reference segment ${s.boardDuration.toFixed(1)}s · boards #${s.boardRange.min + 1}–#${s.boardRange.max + 1}`;

    s.sceneLoadedPath = "";
    loadSegmentFitMode();
    if (sameSegment && s.mode === nextMode) {
      await switchView(nextMode, { notify: false });
      loadSegmentFromSettings();
      renderSegment();
      renderReferencesPanel();
      return;
    }
    const prevMode = s.mode;
    s.mode = prevMode === nextMode ? "" : prevMode;
    await switchView(nextMode, { notify: false });
    loadSegmentFromSettings();
    renderSegment();
    renderReferencesPanel();
  });

  return switchSegmentChain.catch(() => {});
}

async function switchView(mode, { notify = true } = {}) {
  const next = mode === "model" || mode === "image" ? mode : "video";
  if (s.mode === next && s.project) {
    if (next === "video") await loadVideoView();
    else if (next === "image") await loadImageView();
    else await loadModelView();
    applyReferenceFitPreview(s.fitMode);
    return;
  }
  s.mode = next;
  if (el.app) el.app.dataset.mode = next;
  el.fitBoards.hidden = next === "image";
  el.resetStart.hidden = next === "image";
  if (next === "video") await loadVideoView();
  else if (next === "image") {
    s.segmentStart = 0;
    await loadImageView();
  } else await loadModelView();
  applyReferenceFitPreview(s.fitMode);
  renderReferencesPanel();
}

window.switchRefSegmentView = (mode) => switchView(mode);

async function patchReferenceMode(type, path, referenceId = "") {
  const body = { reference_segment_mode: type };
  if (type === "video") body.reference_video_path = path;
  else if (type === "model") body.reference_model_path = path;
  else body.reference_image_path = path;
  s.project = await api("/api/project/settings", { method: "PATCH", body });
  await notifyParentSegmentUpdate({
    segmentId: s.segmentId,
    patch: {
      source_type: type,
      reference_path: path,
      reference_id: referenceId || "",
    },
    setActive: true,
  });
  try {
    s.project = await api("/api/project");
  } catch {
    // keep current project snapshot
  }
}

async function selectReference(ref) {
  const type = resolveReferenceType(ref, s.project);
  const path = ref.path;
  if (!path) return;
  await patchReferenceMode(type, path, ref.id || "");
  await switchView(type, { notify: false });
  renderReferencesPanel();
  notifyOpener({ type: "ref-segment-saved" });
  showToast("Reference 已绑定，可调整起始点与 Fit，然后点击 Apply to boards");
}

function renderReferencesPanel() {
  const saved = currentSavedSegment();
  renderReferenceMediaPanel(el.referencesPanel, {
    project: s.project,
    activeVideoPath: activeReferenceVideoPath(s.project),
    activeModelPath: activeReferenceModelPath(s.project),
    activeImagePath: activeReferenceImagePath(s.project),
    activeMode: s.mode,
    boundReferenceId: String(saved?.reference_id || "").trim(),
    boundReferencePath: String(saved?.reference_path || "").trim(),
    boundReferenceType: String(saved?.source_type || s.mode || "").trim(),
    compact: true,
    hint: "单击绑定到当前 Segment · 调整参数后点 Apply to boards",
    onImportClick: () => el.referenceFile?.click(),
    onSelect: (ref) => selectReference(ref),
    onPreview: (ref) => selectReference(ref),
    onDelete: async (ref) => {
      if (!ref?.id || !window.confirm(`Remove “${referenceDisplayTitle(ref)}”?`)) return;
      try {
        s.project = await api(`/api/project/references/${encodeURIComponent(ref.id)}`, { method: "DELETE" });
        renderReferencesPanel();
        await switchView(s.mode, { notify: false });
        notifyOpener({ type: "ref-segment-saved" });
        showToast("Reference removed.");
      } catch (error) {
        showToast(error.message || "Could not remove reference.");
      }
    },
  });
}

async function importReferenceFile(file) {
  if (!file || !s.project) return;
  const form = new FormData();
  form.append("file", file);
  s.project = await api("/api/project/references", { method: "POST", body: form, headers: {} });
  const ref = s.project.reference || {};
  const type = resolveReferenceType(ref, s.project);
  if (ref.path) await patchReferenceMode(type, ref.path);
  await switchView(type);
  showToast("Reference imported.");
}

function loadSegmentFromSettings() {
  const segments = s.project?.settings?.ref_segments;
  let start = 0;
  if (Array.isArray(segments) && s.segmentId) {
    const saved = segments.find((segment) => segment.id === s.segmentId);
    if (saved) start = Number(saved.video_start);
  }
  if (!Number.isFinite(start)) {
    const legacy = s.project?.settings?.ref_segment_video;
    start = legacy && typeof legacy === "object" ? Number(legacy.start) : 0;
  }
  s.segmentStart = clampSegmentStart(Number.isFinite(start) ? start : 0);
  if (s.mode === "model" && s.editor) s.editor.setAnimationTime(s.segmentStart);
  if (s.mode === "video" && el.video) el.video.currentTime = s.segmentStart;
}

function saveSegmentSoon() {
  window.clearTimeout(s.saveTimer);
  s.saveTimer = window.setTimeout(() => saveSegmentNow().catch(() => {}), 350);
}

async function saveSegmentNow() {
  if (!s.segmentId) return;
  const saved = currentSavedSegment();
  const patch = {
    video_start: round3(s.segmentStart),
    source_type: s.mode,
    fit_mode: s.fitMode,
  };
  if (saved?.reference_path) {
    patch.reference_path = saved.reference_path;
    patch.reference_id = saved.reference_id || "";
  }
  await notifyParentSegmentUpdate({
    segmentId: s.segmentId,
    patch,
    setActive: true,
  });
}

function renderSegment() {
  const duration = s.mode === "image" ? fixedSegmentLength() || 1 : s.mediaDuration;
  el.segmentLayer.innerHTML = "";
  if (!duration || !s.boardRange) {
    el.segmentSummary.textContent = "Segments: none";
    updatePlayhead();
    return;
  }
  s.segmentStart = clampSegmentStart(s.segmentStart);
  const start = s.segmentStart;
  const segLen = fixedSegmentLength();
  const startPct = (100 * start) / duration;
  const widthPct = s.mode === "image" ? 100 : Math.min((100 * segLen) / duration, 100 - startPct);
  const item = document.createElement("div");
  item.className = "rsg-segment-item active";
  item.style.left = s.mode === "image" ? "0%" : `${startPct}%`;
  item.style.width = `${Math.max(s.mode === "image" ? 100 : 0.25, widthPct)}%`;
  if (s.mode !== "image") {
    item.addEventListener("pointerdown", (event) => {
      event.stopPropagation();
      onSegmentPointerDown(event);
    });
  }
  el.segmentLayer.appendChild(item);
  const visualEnd = segmentVisualEnd(start);
  const range = s.boardRange;
  if (s.mode === "image") {
    el.segmentSummary.textContent = `Image segment: ${segLen.toFixed(1)}s · boards #${range.min + 1}-#${range.max + 1}`;
  } else if (s.mode === "model") {
    el.segmentSummary.textContent = `3D segment: ${formatClock(segLen)} · anim ${formatClock(start)} -> ${formatClock(visualEnd)} · boards #${range.min + 1}-#${range.max + 1}`;
  } else {
    el.segmentSummary.textContent = `Video segment: ${formatClock(segLen)} · ${formatClock(start)} -> ${formatClock(visualEnd)} · boards #${range.min + 1}-#${range.max + 1}`;
  }
  updatePlayhead();
}

function updatePlayhead() {
  let current = 0;
  if (s.mode === "video") current = el.video.currentTime || 0;
  else if (s.mode === "model") current = s.editor?.animationTime || Number(el.scrubber.value) || 0;
  const x = timelineXForTime(current);
  const rect = el.segmentTimeline.getBoundingClientRect();
  el.playhead.style.left = `${x - rect.left}px`;
}

function updateScrubber() {
  if (s.mode === "image") return;
  let current = 0;
  let total = s.mediaDuration || 0;
  if (s.mode === "video") current = el.video.currentTime || 0;
  else if (s.mode === "model") current = s.editor?.animationTime || 0;
  el.scrubber.max = String(total || 0);
  el.scrubber.value = String(current);
  updatePlayhead();
}

function seekMedia(time) {
  if (s.mode === "image") return;
  const next = clampSeconds(time, 0, s.mediaDuration || 0);
  if (s.mode === "video") {
    el.video.currentTime = next;
  } else if (s.editor) {
    s.editor.setAnimationTime(next);
  }
  updateScrubber();
}

function onSegmentPointerDown(event) {
  if (event.button !== 0 || s.mode === "image") return;
  const duration = s.mediaDuration;
  if (!duration) return;
  if (!event.target.closest(".rsg-segment-item")) return;
  event.preventDefault();
  s.segmentDrag = { startX: event.clientX, segmentStart: s.segmentStart };
  el.segmentTimeline.setPointerCapture(event.pointerId);
}

function onSegmentPointerMove(event) {
  if (!s.segmentDrag || s.mode === "image") return;
  const delta = timelineDeltaSeconds(event.clientX - s.segmentDrag.startX);
  s.segmentStart = clampSegmentStart(s.segmentDrag.segmentStart + delta);
  renderSegment();
}

function onSegmentPointerUp(event) {
  if (!s.segmentDrag) return;
  s.segmentDrag = null;
  try {
    el.segmentTimeline.releasePointerCapture(event.pointerId);
  } catch {
    // ignore
  }
  saveSegmentSoon();
}

async function applyToBoards() {
  const range = s.boardRange;
  const shots = s.project?.shots || [];
  const saved = currentSavedSegment();
  if (!range || !shots.length) {
    showToast("Select boards on the filmstrip first.");
    return null;
  }
  el.apply.disabled = true;
  try {
    await saveSegmentNow();
    if (s.mode === "image") {
      if (!activeReferenceImagePath(s.project, saved)) throw new Error("Bind a reference image to this segment first.");
      const result = await api("/api/project/ref-segment/apply-image", {
        method: "POST",
        body: {
          anchor_shot_id: shots[range.anchor].shot_id,
          end_shot_id: shots[range.end].shot_id,
          segment_id: s.segmentId || "",
        },
      });
      notifyOpener({ type: "ref-segment-applied", result });
      showToast(`Applied to ${result.board_count || 0} boards.`);
      return result;
    }
    if (s.mode === "video") {
      if (!activeReferenceVideoPathForSegment(s.project, saved)) throw new Error("Bind a reference video to this segment first.");
      const result = await api("/api/project/ref-segment/apply", {
        method: "POST",
        body: {
          anchor_shot_id: shots[range.anchor].shot_id,
          end_shot_id: shots[range.end].shot_id,
          segment_id: s.segmentId || "",
        },
      });
      notifyOpener({ type: "ref-segment-applied", result });
      showToast(`Applied to ${result.board_count || 0} boards.`);
      return result;
    }
    if (!activeReferenceModelPath(s.project, saved)) throw new Error("Bind a reference GLB to this segment first.");
    const editor = await ensureSceneEditor();
    if (!editor || s.mediaDuration <= 0) throw new Error("Load a GLB with animation first.");
    const storyboardDuration = boardDurationSeconds(s.project, range);
    const animStart = s.segmentStart;
    const animSpan = Math.max(0.001, storyboardDuration);
    let segmentOffset = 0;
    for (let index = range.min; index <= range.max; index += 1) {
      const shot = shots[index];
      const ratio = storyboardDuration > 0 ? segmentOffset / storyboardDuration : 0;
      const animTime = animStart + ratio * animSpan;
      editor.setAnimationTime(animTime);
      updateScrubber();
      const dataUrl = editor.captureFrameDataUrl();
      const blob = await (await fetch(dataUrl)).blob();
      const form = new FormData();
      form.append("file", blob, `${shot.shot_id}_3d_frame.png`);
      s.project = await api(`/api/shots/${shot.shot_id}/image`, { method: "POST", body: form, headers: {} });
      segmentOffset += Number(shot.duration_seconds || 3);
    }
    const anim = editor.getAnimationState();
    const result = await api("/api/project/ref-segment/apply-3d", {
      method: "POST",
      body: {
        anchor_shot_id: shots[range.anchor].shot_id,
        end_shot_id: shots[range.end].shot_id,
        segment_id: s.segmentId || "",
        camera_name: anim.camera_name || "",
      },
    });
    notifyOpener({ type: "ref-segment-applied", result });
    showToast(`Applied to ${result.board_count || 0} boards.`);
    return result;
  } catch (error) {
    showToast(error.message || "Apply failed.");
    throw error;
  } finally {
    el.apply.disabled = false;
  }
}

function initialMode(project) {
  const hash = String(window.location.hash || "").replace("#", "").toLowerCase();
  if (hash === "video" || hash === "model" || hash === "image") return hash;
  const saved = currentSavedSegment(project);
  const savedType = String(saved?.source_type || "").toLowerCase();
  if (savedType === "video" || savedType === "model" || savedType === "image") return savedType;
  const mode = String(project?.settings?.reference_segment_mode || "video").toLowerCase();
  if (mode === "model" || mode === "image") return mode;
  return "video";
}

async function bootstrap() {
  initReferencePreviewModal();
  if (typeof window.hydrateReferenceModelPreviews !== "function") {
    await new Promise((resolve) => {
      window.addEventListener("reference-model-preview-ready", resolve, { once: true });
      window.setTimeout(resolve, 2000);
    });
  }
  try {
    s.project = await api("/api/project");
  } catch (error) {
    showToast(error.message || "Open a project first.");
    return;
  }
  if (!s.project?.shots?.length) {
    showToast("Project has no boards.");
    return;
  }
  s.boardRange = resolveBoardRange(s.project);
  if (!s.boardRange) {
    showToast("Select a board range on the filmstrip first.");
    return;
  }
  s.boardDuration = boardDurationSeconds(s.project, s.boardRange);
  el.boardMeta.textContent = `Reference segment ${s.boardDuration.toFixed(1)}s · boards #${s.boardRange.min + 1}–#${s.boardRange.max + 1}`;

  el.video.addEventListener("loadedmetadata", () => {
    s.mediaDuration = Number.isFinite(el.video.duration) ? el.video.duration : 0;
    loadSegmentFromSettings();
    updateMeta();
    renderSegment();
    updateScrubber();
  });
  el.video.addEventListener("timeupdate", updateScrubber);
  el.scrubber.addEventListener("input", () => seekMedia(el.scrubber.value));
  el.segmentTimeline.addEventListener("pointerdown", onSegmentPointerDown);
  el.segmentTimeline.addEventListener("pointermove", onSegmentPointerMove);
  el.segmentTimeline.addEventListener("pointerup", onSegmentPointerUp);
  el.segmentTimeline.addEventListener("pointercancel", onSegmentPointerUp);
  el.fitBoards.addEventListener("click", () => {
    s.segmentStart = 0;
    renderSegment();
    saveSegmentSoon();
  });
  el.resetStart.addEventListener("click", () => {
    s.segmentStart = 0;
    renderSegment();
    seekMedia(0);
    saveSegmentSoon();
  });
  el.fitModeGroup?.querySelectorAll("[data-fit-mode]").forEach((btn) => {
    btn.addEventListener("click", () => {
      setSegmentFitMode(btn.dataset.fitMode).catch(() => {});
    });
  });
  el.apply.addEventListener("click", () => {
    applyToBoards().catch(() => {});
  });
  el.referenceFile?.addEventListener("change", async () => {
    const file = el.referenceFile.files?.[0];
    if (!file) return;
    try {
      await importReferenceFile(file);
    } catch (error) {
      showToast(error.message || "Import failed.");
    }
    el.referenceFile.value = "";
  });
  window.addEventListener("resize", () => {
    renderSegment();
    updateScrubber();
  });
  window.setInterval(() => {
    if (s.mode === "model" && s.editor?.isPlaying) updateScrubber();
  }, 100);

  window.addEventListener("message", (event) => {
    if (event.origin !== window.location.origin) return;
    if (event.data?.source !== "storyboard-ref-parent") return;
    if (!s.bootstrapReady) {
      pendingParentMessage = event.data;
      return;
    }
    handleParentMessage(event.data);
  });

  const mode = initialMode(s.project);
  loadSegmentFitMode();
  await switchView(mode, { notify: false });
  applyReferenceFitPreview(s.fitMode);
  renderReferencesPanel();
  s.bootstrapReady = true;
  if (pendingParentMessage) {
    const queued = pendingParentMessage;
    pendingParentMessage = null;
    handleParentMessage(queued);
  }
}

bootstrap();
