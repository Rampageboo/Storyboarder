import { Scene3DEditor } from "./scene3d.js";

const rs = {
  project: null,
  editor: null,
  segmentId: "",
  boardRange: null,
  boardDuration: 0,
  animDuration: 0,
  segmentStart: 0,
  segmentDrag: null,
  saveTimer: 0,
};

const el = {
  referencesPanel: document.getElementById("rsReferencesPanel"),
  referenceFile: document.getElementById("rsReferenceFile"),
  sceneMeta: document.getElementById("rsSceneMeta"),
  boardMeta: document.getElementById("rsBoardMeta"),
  sceneRoot: document.getElementById("rsSceneRoot"),
  sceneEmpty: document.getElementById("rsSceneEmpty"),
  scrubber: document.getElementById("rsAnimScrubber"),
  segmentTimeline: document.getElementById("rsSegmentTimeline"),
  segmentLayer: document.getElementById("rsSegmentLayer"),
  playhead: document.getElementById("rsPlayhead"),
  segmentSummary: document.getElementById("rsSegmentSummary"),
  apply: document.getElementById("rsApply"),
  fitBoards: document.getElementById("rsFitBoards"),
  resetStart: document.getElementById("rsResetStart"),
  toast: document.getElementById("rsToast"),
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
  if (!(options.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
  }
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
      // keep status text
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

function activeReferenceModelPath(project) {
  return String(project?.settings?.reference_model_path || "").trim();
}

function fixedSegmentLength() {
  return Math.max(0.001, rs.boardDuration || 0);
}

function maxSegmentStart() {
  if (!rs.animDuration) return 0;
  if (fixedSegmentLength() >= rs.animDuration) return 0;
  return Math.max(0, rs.animDuration - fixedSegmentLength());
}

function clampSegmentStart(start) {
  return clampSeconds(start, 0, maxSegmentStart());
}

function segmentVisualEnd(start = rs.segmentStart) {
  if (!rs.animDuration) return start + fixedSegmentLength();
  return Math.min(start + fixedSegmentLength(), rs.animDuration);
}

function timelineInnerWidth() {
  const rect = el.segmentTimeline.getBoundingClientRect();
  return Math.max(1, rect.width - 24);
}

function timelineDeltaSeconds(deltaPx) {
  if (!rs.animDuration) return 0;
  return (deltaPx / timelineInnerWidth()) * rs.animDuration;
}

function timelineXForTime(time) {
  const rect = el.segmentTimeline.getBoundingClientRect();
  const innerLeft = rect.left + 12;
  const ratio = rs.animDuration > 0 ? clampSeconds(time, 0, rs.animDuration) / rs.animDuration : 0;
  return innerLeft + ratio * timelineInnerWidth();
}

function shotIndexFromId(shots, shotId) {
  return shots.findIndex((shot) => shot.shot_id === shotId);
}

function resolveBoardRange(project) {
  const shots = project?.shots || [];
  if (!shots.length) return null;

  const queryId = new URLSearchParams(window.location.search).get("segment") || "";
  const segments = Array.isArray(project?.settings?.ref_segments) ? project.settings.ref_segments : [];
  let saved = null;
  if (queryId) {
    saved = segments.find((segment) => segment.id === queryId);
  }
  if (!saved) {
    const activeId = String(project?.settings?.active_ref_segment_id || "").trim();
    saved = segments.find((segment) => segment.id === activeId) || segments[0];
  }
  if (!saved) {
    const legacy = project?.settings?.ref_segment;
    if (legacy?.anchor_shot_id && legacy?.end_shot_id) saved = legacy;
  }
  if (!saved) return null;

  const min = shotIndexFromId(shots, saved.anchor_shot_id);
  const max = shotIndexFromId(shots, saved.end_shot_id);
  if (min < 0 || max < 0) return null;
  rs.segmentId = saved.id || queryId || "";
  return {
    min: Math.min(min, max),
    max: Math.max(min, max),
    anchor: min,
    end: max,
  };
}

function boardDurationSeconds(project, range) {
  let total = 0;
  for (let index = range.min; index <= range.max; index += 1) {
    total += Number(project.shots[index]?.duration_seconds || 3);
  }
  return total;
}

function referenceModelName(project) {
  const path = activeReferenceModelPath(project);
  if (!path) return "reference";
  const parts = path.split(/[/\\]/);
  return parts[parts.length - 1] || "reference";
}

function notifyOpener(payload) {
  const target = window.opener && !window.opener.closed ? window.opener : null;
  const parent = window.parent && window.parent !== window ? window.parent : null;
  const receiver = target || parent;
  if (!receiver) return;
  receiver.postMessage({ source: "storyboard-ref-scene3d", ...payload }, window.location.origin);
}

function updateSceneMeta() {
  const name = referenceModelName(rs.project);
  const duration = formatClock(rs.animDuration || 0);
  const anim = rs.editor?.getAnimationState?.() || {};
  const camera = anim.camera_name || "—";
  el.sceneMeta.textContent = `${name} | ${duration} | ${camera}`;
}

function setSceneEmptyState(empty) {
  if (el.sceneEmpty) el.sceneEmpty.hidden = !empty;
  if (el.scrubber) el.scrubber.disabled = empty;
  if (el.apply) el.apply.disabled = empty;
  if (el.fitBoards) el.fitBoards.disabled = empty;
  if (el.resetStart) el.resetStart.disabled = empty;
}

function renderReferencesPanel() {
  renderReferenceMediaPanel(el.referencesPanel, {
    project: rs.project,
    activeVideoPath: activeReferenceVideoPath(rs.project),
    activeModelPath: activeReferenceModelPath(rs.project),
    activeMode: String(rs.project?.settings?.reference_segment_mode || "model").toLowerCase(),
    compact: true,
    hint: "单击切换 Segment 参考 · 双击预览",
    onImportClick: () => el.referenceFile?.click(),
    onSelect: async (ref) => {
      const type = typeof resolveReferenceType === "function" ? resolveReferenceType(ref, rs.project) : ref.type;
      if (type === "model") {
        await selectReferenceModel(ref.path, { silent: true });
        return;
      }
      if (type === "video") {
        await selectReferenceVideo(ref.path, { silent: true });
        navigateToReferenceSegmentEditor("video");
      }
    },
    onPreview: async (ref) => {
      const type = typeof resolveReferenceType === "function" ? resolveReferenceType(ref, rs.project) : ref.type;
      if (type === "model") {
        await selectReferenceModel(ref.path, { silent: true });
        return;
      }
      if (type === "video") {
        await selectReferenceVideo(ref.path, { silent: true });
        navigateToReferenceSegmentEditor("video");
        return;
      }
      openReferencePreview(ref);
    },
    onDelete: async (ref) => {
      if (!ref?.id) return;
      if (!window.confirm(`Remove “${referenceDisplayTitle(ref)}”?`)) return;
      try {
        rs.project = await api(`/api/project/references/${encodeURIComponent(ref.id)}`, {
          method: "DELETE",
        });
        renderReferencesPanel();
        await loadActiveReferenceModel({ notify: true });
        showToast("Reference removed.");
      } catch (error) {
        showToast(error.message || "Could not remove reference.");
      }
    },
  });
}

async function importReferenceFile(file) {
  if (!file || !rs.project) return;
  const form = new FormData();
  form.append("file", file);
  const result = await api("/api/project/references", {
    method: "POST",
    body: form,
    headers: {},
  });
  rs.project = result;
  renderReferencesPanel();
  const importedType =
    typeof resolveReferenceType === "function" ? resolveReferenceType(result.reference || {}, result) : result.reference?.type;
  if (importedType === "model" && result.reference?.path) {
    await selectReferenceModel(result.reference.path, { silent: true });
  } else if (importedType === "video" && result.reference?.path) {
    await selectReferenceVideo(result.reference.path, { silent: true });
    navigateToReferenceSegmentEditor("video");
  }
  showToast("Reference imported.");
}

async function selectReferenceModel(path, { silent = false } = {}) {
  const relativePath = String(path || "").trim();
  if (!relativePath) return;
  rs.project = await api("/api/project/settings", {
    method: "PATCH",
    body: {
      reference_model_path: relativePath,
      reference_segment_mode: "model",
    },
  });
  renderReferencesPanel();
  await loadActiveReferenceModel({ notify: true });
  if (!silent) showToast("3D reference selected.");
}

async function selectReferenceVideo(path, { silent = false } = {}) {
  const relativePath = String(path || "").trim();
  if (!relativePath) return;
  rs.project = await api("/api/project/settings", {
    method: "PATCH",
    body: {
      reference_video_path: relativePath,
      reference_segment_mode: "video",
    },
  });
  renderReferencesPanel();
  notifyOpener({ type: "ref-segment-saved" });
  if (!silent) showToast("Video reference selected.");
}

async function loadActiveReferenceModel({ notify = false } = {}) {
  const modelPath = activeReferenceModelPath(rs.project);
  if (!modelPath) {
    rs.animDuration = 0;
    setSceneEmptyState(true);
    el.sceneMeta.textContent = "No reference GLB selected";
    renderSegment();
    updateScrubber();
    return;
  }

  setSceneEmptyState(false);
  const sceneSettings = rs.project?.settings?.scene3d || {};
  if (!sceneSettings.file_path) {
    setSceneEmptyState(true);
    el.sceneMeta.textContent = "GLB path missing in project settings";
    return;
  }

  try {
    await rs.editor.loadSceneData(sceneSettings);
    rs.animDuration = Number(rs.editor.animationDuration) || 0;
    loadSegmentFromSettings();
    updateSceneMeta();
    renderSegment();
    updateScrubber();
    if (notify) notifyOpener({ type: "ref-segment-saved" });
  } catch (error) {
    setSceneEmptyState(true);
    el.sceneMeta.textContent = error.message || "Could not load GLB";
    showToast(error.message || "Could not load GLB");
  }
}

function loadSegmentFromSettings() {
  const segments = rs.project?.settings?.ref_segments;
  let start = 0;
  if (Array.isArray(segments) && rs.segmentId) {
    const saved = segments.find((segment) => segment.id === rs.segmentId);
    if (saved) start = Number(saved.video_start);
  }
  if (!Number.isFinite(start)) {
    const legacy = rs.project?.settings?.ref_segment_video;
    start = legacy && typeof legacy === "object" ? Number(legacy.start) : 0;
  }
  rs.segmentStart = clampSegmentStart(Number.isFinite(start) ? start : 0);
  if (rs.editor) {
    rs.editor.setAnimationTime(rs.segmentStart);
  }
}

function saveSegmentSoon() {
  window.clearTimeout(rs.saveTimer);
  rs.saveTimer = window.setTimeout(async () => {
    try {
      await saveSegmentNow({ notify: true });
    } catch (error) {
      showToast(error.message || "Could not save segment.");
    }
  }, 350);
}

async function saveSegmentNow({ notify = false } = {}) {
  const segments = Array.isArray(rs.project?.settings?.ref_segments)
    ? rs.project.settings.ref_segments.map((segment) => ({ ...segment }))
    : [];
  const index = segments.findIndex((segment) => segment.id === rs.segmentId);
  if (index >= 0) {
    segments[index].video_start = round3(rs.segmentStart);
    segments[index].source_type = "model";
  }
  rs.project = await api("/api/project/settings", {
    method: "PATCH",
    body: {
      ref_segments: segments,
      active_ref_segment_id: rs.segmentId || rs.project?.settings?.active_ref_segment_id || "",
      reference_segment_mode: "model",
      ref_segment_video: {
        start: round3(rs.segmentStart),
        board_duration: round3(fixedSegmentLength()),
        segment_id: rs.segmentId,
      },
    },
  });
  if (notify) notifyOpener({ type: "ref-segment-saved" });
}

function renderSegment() {
  const duration = rs.animDuration;
  el.segmentLayer.innerHTML = "";
  if (!duration) {
    el.segmentSummary.textContent = "Segments: none";
    updatePlayhead();
    return;
  }

  rs.segmentStart = clampSegmentStart(rs.segmentStart);
  const start = rs.segmentStart;
  const segLen = fixedSegmentLength();
  const startPct = (100 * start) / duration;
  const widthPct = Math.min((100 * segLen) / duration, 100 - startPct);
  const visualEnd = segmentVisualEnd(start);

  const item = document.createElement("div");
  item.className = "rs-segment-item active";
  item.style.left = `${startPct}%`;
  item.style.width = `${Math.max(0.25, widthPct)}%`;
  item.innerHTML = '<div class="rs-segment-handle start" data-edge="move"></div>';
  item.addEventListener("pointerdown", (event) => {
    event.stopPropagation();
    onSegmentPointerDown(event);
  });
  el.segmentLayer.appendChild(item);

  el.segmentSummary.textContent = `3D segment: ${formatClock(segLen)} · anim ${formatClock(start)} -> ${formatClock(visualEnd)} · boards #${rs.boardRange.min + 1}-#${rs.boardRange.max + 1}`;
  updatePlayhead();
}

function updatePlayhead() {
  const current = rs.editor?.animationTime || Number(el.scrubber.value) || 0;
  const x = timelineXForTime(current);
  const rect = el.segmentTimeline.getBoundingClientRect();
  el.playhead.style.left = `${x - rect.left}px`;
}

function updateScrubber() {
  const current = rs.editor?.animationTime || 0;
  const total = rs.animDuration || 0;
  el.scrubber.max = String(total || 0);
  el.scrubber.value = String(current);
  updatePlayhead();
}

function seekAnimation(time) {
  const next = clampSeconds(time, 0, rs.animDuration || 0);
  rs.editor?.setAnimationTime(next);
  updateScrubber();
}

function onSegmentPointerDown(event) {
  if (event.button !== 0) return;
  if (!rs.animDuration) return;
  const item = event.target.closest(".rs-segment-item");
  if (!item) return;
  event.preventDefault();
  rs.segmentDrag = {
    startX: event.clientX,
    segmentStart: rs.segmentStart,
  };
  el.segmentTimeline.setPointerCapture(event.pointerId);
}

function onSegmentPointerMove(event) {
  if (!rs.segmentDrag) return;
  const delta = timelineDeltaSeconds(event.clientX - rs.segmentDrag.startX);
  rs.segmentStart = clampSegmentStart(rs.segmentDrag.segmentStart + delta);
  renderSegment();
}

function onSegmentPointerUp(event) {
  if (!rs.segmentDrag) return;
  rs.segmentDrag = null;
  try {
    el.segmentTimeline.releasePointerCapture(event.pointerId);
  } catch {
    // ignore
  }
  saveSegmentSoon();
}

function fitSegmentToBoardDuration() {
  rs.segmentStart = 0;
  renderSegment();
  saveSegmentSoon();
}

function resetSegmentStart() {
  rs.segmentStart = 0;
  renderSegment();
  seekAnimation(0);
  saveSegmentSoon();
}

async function applyToBoards() {
  const range = rs.boardRange;
  const shots = rs.project?.shots || [];
  if (!range || !shots.length) {
    showToast("Select boards on the filmstrip first.");
    return;
  }
  if (!activeReferenceModelPath(rs.project)) {
    showToast("Import or select a reference GLB first.");
    return;
  }
  if (!rs.editor || rs.animDuration <= 0) {
    showToast("Load a GLB with animation first.");
    return;
  }

  el.apply.disabled = true;
  try {
    await saveSegmentNow();
    const storyboardDuration = boardDurationSeconds(rs.project, range);
    const animStart = rs.segmentStart;
    const animSpan = Math.max(0.001, storyboardDuration);
    let segmentOffset = 0;

    for (let index = range.min; index <= range.max; index += 1) {
      const shot = shots[index];
      const ratio = storyboardDuration > 0 ? segmentOffset / storyboardDuration : 0;
      const animTime = animStart + ratio * animSpan;
      rs.editor.setAnimationTime(animTime);
      updateScrubber();
      const dataUrl = rs.editor.captureFrameDataUrl();
      const blob = await (await fetch(dataUrl)).blob();
      const form = new FormData();
      form.append("file", blob, `${shot.shot_id}_3d_frame.png`);
      rs.project = await api(`/api/shots/${shot.shot_id}/image`, {
        method: "POST",
        body: form,
        headers: {},
      });
      segmentOffset += Number(shot.duration_seconds || 3);
    }

    const anim = rs.editor.getAnimationState();
    const result = await api("/api/project/ref-segment/apply-3d", {
      method: "POST",
      body: {
        anchor_shot_id: shots[range.anchor].shot_id,
        end_shot_id: shots[range.end].shot_id,
        segment_id: rs.segmentId || "",
        camera_name: anim.camera_name || "",
      },
    });
    notifyOpener({ type: "ref-segment-applied", result });
    showToast(`Applied to ${result.board_count || 0} boards.`);
  } catch (error) {
    showToast(error.message || "Apply failed.");
  } finally {
    el.apply.disabled = false;
  }
}

async function waitForReferenceModelPreviewReady() {
  if (typeof window.hydrateReferenceModelPreviews === "function") return;
  await new Promise((resolve) => {
    const done = () => resolve();
    window.addEventListener("reference-model-preview-ready", done, { once: true });
    window.setTimeout(done, 3000);
  });
}

async function bootstrap() {
  initReferencePreviewModal();
  await waitForReferenceModelPreviewReady();
  try {
    rs.project = await api("/api/project");
  } catch (error) {
    showToast(error.message || "Open a project in Storyboard Tool first.");
    return;
  }
  if (!rs.project?.shots?.length) {
    showToast("Project has no boards.");
    return;
  }
  rs.boardRange = resolveBoardRange(rs.project);
  if (!rs.boardRange) {
    showToast("Select a board range on the filmstrip dots first.");
    return;
  }
  rs.boardDuration = boardDurationSeconds(rs.project, rs.boardRange);
  el.boardMeta.textContent = `3D segment ${rs.boardDuration.toFixed(1)}s · boards #${rs.boardRange.min + 1}–#${rs.boardRange.max + 1}`;

  rs.editor = new Scene3DEditor(el.sceneRoot, {
    onMessage: (message) => showToast(message),
  });

  renderReferencesPanel();

  el.scrubber.addEventListener("input", () => seekAnimation(el.scrubber.value));
  el.segmentTimeline.addEventListener("pointerdown", onSegmentPointerDown);
  el.segmentTimeline.addEventListener("pointermove", onSegmentPointerMove);
  el.segmentTimeline.addEventListener("pointerup", onSegmentPointerUp);
  el.segmentTimeline.addEventListener("pointercancel", onSegmentPointerUp);
  el.fitBoards.addEventListener("click", fitSegmentToBoardDuration);
  el.resetStart?.addEventListener("click", resetSegmentStart);
  el.apply.addEventListener("click", applyToBoards);
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
    if (!rs.editor?.isPlaying) return;
    updateScrubber();
  }, 100);

  await loadActiveReferenceModel();
}

bootstrap();
