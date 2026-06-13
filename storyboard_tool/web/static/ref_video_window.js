const rv = {
  project: null,
  segmentId: "",
  boardRange: null,
  boardDuration: 0,
  videoDuration: 0,
  segmentStart: 0,
  segmentDrag: null,
  saveTimer: 0,
};

const el = {
  referencesPanel: document.getElementById("rvReferencesPanel"),
  referenceFile: document.getElementById("rvReferenceFile"),
  videoMeta: document.getElementById("rvVideoMeta"),
  boardMeta: document.getElementById("rvBoardMeta"),
  video: document.getElementById("rvVideo"),
  videoEmpty: document.getElementById("rvVideoEmpty"),
  scrubber: document.getElementById("rvScrubber"),
  segmentTimeline: document.getElementById("rvSegmentTimeline"),
  segmentLayer: document.getElementById("rvSegmentLayer"),
  playhead: document.getElementById("rvPlayhead"),
  segmentSummary: document.getElementById("rvSegmentSummary"),
  apply: document.getElementById("rvApply"),
  fitBoards: document.getElementById("rvFitBoards"),
  resetStart: document.getElementById("rvResetStart"),
  toast: document.getElementById("rvToast"),
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

function fixedSegmentLength() {
  return Math.max(0.001, rv.boardDuration || 0);
}

function maxSegmentStart() {
  if (!rv.videoDuration) return 0;
  if (fixedSegmentLength() >= rv.videoDuration) return 0;
  return Math.max(0, rv.videoDuration - fixedSegmentLength());
}

function clampSegmentStart(start) {
  return clampSeconds(start, 0, maxSegmentStart());
}

function segmentVisualEnd(start = rv.segmentStart) {
  if (!rv.videoDuration) return start + fixedSegmentLength();
  return Math.min(start + fixedSegmentLength(), rv.videoDuration);
}

function timelineInnerWidth() {
  const rect = el.segmentTimeline.getBoundingClientRect();
  return Math.max(1, rect.width - 24);
}

function timelineDeltaSeconds(deltaPx) {
  if (!rv.videoDuration) return 0;
  return (deltaPx / timelineInnerWidth()) * rv.videoDuration;
}

function timelineXForTime(time) {
  const rect = el.segmentTimeline.getBoundingClientRect();
  const innerLeft = rect.left + 12;
  const ratio = rv.videoDuration > 0 ? clampSeconds(time, 0, rv.videoDuration) / rv.videoDuration : 0;
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
  rv.segmentId = saved.id || queryId || "";
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

function referenceVideoName(project) {
  const path = activeReferenceVideoPath(project);
  if (!path) return "reference";
  const parts = path.split(/[/\\]/);
  return parts[parts.length - 1] || "reference";
}

function updateVideoMeta() {
  const name = referenceVideoName(rv.project);
  const w = el.video.videoWidth || 0;
  const h = el.video.videoHeight || 0;
  const size = w && h ? `${w}x${h}` : "—";
  const duration = formatClock(rv.videoDuration || 0);
  el.videoMeta.textContent = `${name} | ${size} | ${duration}`;
}

function referenceVideoUrl(project) {
  const path = activeReferenceVideoPath(project);
  if (!path) return "";
  return referenceMediaUrl(path);
}

function notifyOpener(payload) {
  const target = window.opener && !window.opener.closed ? window.opener : null;
  const parent = window.parent && window.parent !== window ? window.parent : null;
  const receiver = target || parent;
  if (!receiver) return;
  receiver.postMessage({ source: "storyboard-ref-video", ...payload }, window.location.origin);
}

function renderReferencesPanel() {
  renderReferenceMediaPanel(el.referencesPanel, {
    project: rv.project,
    activeVideoPath: activeReferenceVideoPath(rv.project),
    activeModelPath: String(rv.project?.settings?.reference_model_path || "").trim(),
    activeMode: String(rv.project?.settings?.reference_segment_mode || "video").toLowerCase(),
    compact: true,
    hint: "单击视频/GLB 设为 Segment · 双击预览",
    onImportClick: () => el.referenceFile?.click(),
    onSelect: async (ref) => {
      const type = typeof resolveReferenceType === "function" ? resolveReferenceType(ref, rv.project) : ref.type;
      if (type === "video") {
        await selectReferenceVideo(ref.path, { silent: true });
        return;
      }
      if (type === "model") {
        await selectReferenceModel(ref.path, { silent: true });
        navigateToReferenceSegmentEditor("model");
      }
    },
    onPreview: (ref) => {
      const type = typeof resolveReferenceType === "function" ? resolveReferenceType(ref, rv.project) : ref.type;
      if (type === "model") {
        selectReferenceModel(ref.path, { silent: true }).then(() => navigateToReferenceSegmentEditor("model"));
        return;
      }
      openReferencePreview(ref);
    },
    onDelete: async (ref) => {
      if (!ref?.id) return;
      if (!window.confirm(`Remove “${referenceDisplayTitle(ref)}”?`)) return;
      try {
        rv.project = await api(`/api/project/references/${encodeURIComponent(ref.id)}`, {
          method: "DELETE",
        });
        renderReferencesPanel();
        await loadActiveReferenceVideo({ notify: true });
        showToast("Reference removed.");
      } catch (error) {
        showToast(error.message || "Could not remove reference.");
      }
    },
  });
}

async function importReferenceFile(file) {
  if (!file || !rv.project) return;
  const form = new FormData();
  form.append("file", file);
  const result = await api("/api/project/references", {
    method: "POST",
    body: form,
    headers: {},
  });
  rv.project = result;
  renderReferencesPanel();
  const importedType =
    typeof resolveReferenceType === "function" ? resolveReferenceType(result.reference || {}, result) : result.reference?.type;
  if (importedType === "video" && result.reference?.path) {
    await selectReferenceVideo(result.reference.path, { silent: true });
  } else if (importedType === "model" && result.reference?.path) {
    await selectReferenceModel(result.reference.path, { silent: true });
    navigateToReferenceSegmentEditor("model");
  }
  showToast("Reference imported.");
}

async function selectReferenceModel(path, { silent = false } = {}) {
  const relativePath = String(path || "").trim();
  if (!relativePath) return;
  rv.project = await api("/api/project/settings", {
    method: "PATCH",
    body: {
      reference_model_path: relativePath,
      reference_segment_mode: "model",
    },
  });
  renderReferencesPanel();
  notifyOpener({ type: "ref-segment-saved" });
  if (!silent) showToast("3D reference selected.");
}

async function selectReferenceVideo(path, { silent = false } = {}) {
  const relativePath = String(path || "").trim();
  if (!relativePath) return;
  rv.project = await api("/api/project/settings", {
    method: "PATCH",
    body: {
      reference_video_path: relativePath,
      reference_segment_mode: "video",
    },
  });
  renderReferencesPanel();
  await loadActiveReferenceVideo({ notify: true });
  if (!silent) showToast("Reference video selected.");
}

function setVideoEmptyState(empty) {
  if (el.videoEmpty) el.videoEmpty.hidden = !empty;
  if (el.video) el.video.hidden = empty;
  if (el.scrubber) el.scrubber.disabled = empty;
  if (el.apply) el.apply.disabled = empty;
  if (el.fitBoards) el.fitBoards.disabled = empty;
  if (el.resetStart) el.resetStart.disabled = empty;
}

async function loadActiveReferenceVideo({ notify = false } = {}) {
  const videoUrl = referenceVideoUrl(rv.project);
  if (!videoUrl) {
    rv.videoDuration = 0;
    el.video.removeAttribute("src");
    el.video.load();
    setVideoEmptyState(true);
    el.videoMeta.textContent = "No reference video selected";
    renderSegment();
    updateScrubber();
    return;
  }

  setVideoEmptyState(false);
  el.video.src = videoUrl;
  el.video.load();
  if (notify) notifyOpener({ type: "ref-segment-saved" });
}

function loadSegmentFromSettings() {
  const segments = rv.project?.settings?.ref_segments;
  let start = 0;
  if (Array.isArray(segments) && rv.segmentId) {
    const saved = segments.find((segment) => segment.id === rv.segmentId);
    if (saved) start = Number(saved.video_start);
  }
  if (!Number.isFinite(start)) {
    const legacy = rv.project?.settings?.ref_segment_video;
    start = legacy && typeof legacy === "object" ? Number(legacy.start) : 0;
  }
  rv.segmentStart = clampSegmentStart(Number.isFinite(start) ? start : 0);
}

function saveSegmentSoon() {
  window.clearTimeout(rv.saveTimer);
  rv.saveTimer = window.setTimeout(async () => {
    try {
      const segments = Array.isArray(rv.project?.settings?.ref_segments)
        ? rv.project.settings.ref_segments.map((segment) => ({ ...segment }))
        : [];
      const index = segments.findIndex((segment) => segment.id === rv.segmentId);
      if (index >= 0) {
        segments[index].video_start = round3(rv.segmentStart);
      }
      await api("/api/project/settings", {
        method: "PATCH",
        body: {
          ref_segments: segments,
          active_ref_segment_id: rv.segmentId || rv.project?.settings?.active_ref_segment_id || "",
          ref_segment_video: {
            start: round3(rv.segmentStart),
            board_duration: round3(fixedSegmentLength()),
            segment_id: rv.segmentId,
          },
        },
      });
      notifyOpener({ type: "ref-segment-saved" });
    } catch (error) {
      showToast(error.message || "Could not save segment.");
    }
  }, 350);
}

function round3(value) {
  return Math.round((Number(value) || 0) * 1000) / 1000;
}

function renderSegment() {
  const duration = rv.videoDuration;
  el.segmentLayer.innerHTML = "";
  if (!duration) {
    el.segmentSummary.textContent = "Segments: none";
    updatePlayhead();
    return;
  }

  rv.segmentStart = clampSegmentStart(rv.segmentStart);
  const start = rv.segmentStart;
  const segLen = fixedSegmentLength();
  const startPct = (100 * start) / duration;
  const widthPct = Math.min((100 * segLen) / duration, 100 - startPct);
  const visualEnd = segmentVisualEnd(start);

  const item = document.createElement("div");
  item.className = "rv-segment-item active";
  item.style.left = `${startPct}%`;
  item.style.width = `${Math.max(0.25, widthPct)}%`;
  item.innerHTML = '<div class="rv-segment-handle start" data-edge="move"></div>';
  item.addEventListener("pointerdown", (event) => {
    event.stopPropagation();
    onSegmentPointerDown(event);
  });
  el.segmentLayer.appendChild(item);

  el.segmentSummary.textContent = `Reference segment: ${formatClock(segLen)} · video ${formatClock(start)} -> ${formatClock(visualEnd)} · boards #${rv.boardRange.min + 1}-#${rv.boardRange.max + 1}`;
  updatePlayhead();
}

function updatePlayhead() {
  const x = timelineXForTime(el.video.currentTime || 0);
  const rect = el.segmentTimeline.getBoundingClientRect();
  el.playhead.style.left = `${x - rect.left}px`;
}

function updateScrubber() {
  const current = el.video.currentTime || 0;
  const total = rv.videoDuration || 0;
  el.scrubber.max = String(total || 0);
  el.scrubber.value = String(current);
  updatePlayhead();
}

function seekVideo(time) {
  const next = clampSeconds(time, 0, rv.videoDuration || 0);
  el.video.currentTime = next;
  updateScrubber();
}

function onSegmentPointerDown(event) {
  if (event.button !== 0) return;
  if (!rv.videoDuration) return;
  const item = event.target.closest(".rv-segment-item");
  if (!item) return;
  event.preventDefault();
  rv.segmentDrag = {
    startX: event.clientX,
    segmentStart: rv.segmentStart,
  };
  el.segmentTimeline.setPointerCapture(event.pointerId);
}

function onSegmentPointerMove(event) {
  if (!rv.segmentDrag) return;
  const delta = timelineDeltaSeconds(event.clientX - rv.segmentDrag.startX);
  rv.segmentStart = clampSegmentStart(rv.segmentDrag.segmentStart + delta);
  renderSegment();
}

function onSegmentPointerUp(event) {
  if (!rv.segmentDrag) return;
  rv.segmentDrag = null;
  try {
    el.segmentTimeline.releasePointerCapture(event.pointerId);
  } catch {
    // ignore
  }
  saveSegmentSoon();
}

function fitSegmentToBoardDuration() {
  rv.segmentStart = 0;
  renderSegment();
  saveSegmentSoon();
}

function resetSegmentStart() {
  rv.segmentStart = 0;
  renderSegment();
  saveSegmentSoon();
}

async function applyToBoards() {
  const range = rv.boardRange;
  const shots = rv.project?.shots || [];
  if (!range || !shots.length) {
    showToast("Select boards on the filmstrip first.");
    return;
  }
  if (!activeReferenceVideoPath(rv.project)) {
    showToast("Import or select a reference video first.");
    return;
  }
  el.apply.disabled = true;
  try {
    await saveSegmentNow();
    const result = await api("/api/project/ref-segment/apply", {
      method: "POST",
      body: {
        anchor_shot_id: shots[range.anchor].shot_id,
        end_shot_id: shots[range.end].shot_id,
        segment_id: rv.segmentId || "",
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

async function saveSegmentNow() {
  const segments = Array.isArray(rv.project?.settings?.ref_segments)
    ? rv.project.settings.ref_segments.map((segment) => ({ ...segment }))
    : [];
  const index = segments.findIndex((segment) => segment.id === rv.segmentId);
  if (index >= 0) {
    segments[index].video_start = round3(rv.segmentStart);
  }
  await api("/api/project/settings", {
    method: "PATCH",
    body: {
      ref_segments: segments,
      active_ref_segment_id: rv.segmentId || rv.project?.settings?.active_ref_segment_id || "",
      ref_segment_video: {
        start: round3(rv.segmentStart),
        board_duration: round3(fixedSegmentLength()),
        segment_id: rv.segmentId,
      },
    },
  });
}

async function bootstrap() {
  initReferencePreviewModal();
  try {
    rv.project = await api("/api/project");
  } catch (error) {
    showToast(error.message || "Open a project in Storyboard Tool first.");
    return;
  }
  if (!rv.project?.shots?.length) {
    showToast("Project has no boards.");
    return;
  }
  rv.boardRange = resolveBoardRange(rv.project);
  if (!rv.boardRange) {
    showToast("Select a board range on the filmstrip dots first.");
    return;
  }
  rv.boardDuration = boardDurationSeconds(rv.project, rv.boardRange);
  el.boardMeta.textContent = `Reference segment ${rv.boardDuration.toFixed(1)}s · boards #${rv.boardRange.min + 1}–#${rv.boardRange.max + 1}`;

  renderReferencesPanel();

  el.video.addEventListener("loadedmetadata", () => {
    rv.videoDuration = Number.isFinite(el.video.duration) ? el.video.duration : 0;
    if (!Number.isFinite(rv.videoDuration) || rv.videoDuration <= 0) {
      el.videoMeta.textContent = `${referenceVideoName(rv.project)} | duration unavailable`;
      return;
    }
    updateVideoMeta();
    loadSegmentFromSettings();
    renderSegment();
    updateScrubber();
  });

  el.video.addEventListener("timeupdate", updateScrubber);
  el.scrubber.addEventListener("input", () => seekVideo(el.scrubber.value));
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

  await loadActiveReferenceVideo();
}

bootstrap();
