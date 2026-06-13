let refSegmentDrag = null;
let refSegmentPreviewTimer = null;
let refSegmentPopup = null;

function newRefSegmentId() {
  return `seg_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 7)}`;
}

function refSegmentList() {
  return state.refSegment.segments || [];
}

function refSegmentById(id) {
  if (!id) return null;
  return refSegmentList().find((segment) => segment.id === id) || null;
}

function refSegmentActive() {
  return refSegmentById(state.refSegment.activeId) || refSegmentList()[0] || null;
}

function segmentIndices(segment) {
  if (!segment) return null;
  const anchor = segment.anchorIndex;
  const end = segment.endIndex;
  if (anchor < 0 || end < 0) return null;
  return {
    min: Math.min(anchor, end),
    max: Math.max(anchor, end),
    anchor,
    end,
    id: segment.id,
  };
}

function refSegmentRange(segment = refSegmentActive()) {
  return segmentIndices(segment);
}

function refSegmentDurationSeconds(segment = refSegmentActive(), shots = state.project?.shots || []) {
  const range = segmentIndices(segment);
  if (!range) return 0;
  let total = 0;
  for (let index = range.min; index <= range.max; index += 1) {
    total += Number(shots[index]?.duration_seconds || 3);
  }
  return total;
}

function findSegmentAtIndex(index) {
  return refSegmentList().find((segment) => {
    const range = segmentIndices(segment);
    return range && index >= range.min && index <= range.max;
  });
}

function shotIndexFromId(shotId) {
  return (state.project?.shots || []).findIndex((shot) => shot.shot_id === shotId);
}

function segmentFromSavedEntry(entry) {
  const anchor = shotIndexFromId(entry.anchor_shot_id);
  const end = shotIndexFromId(entry.end_shot_id);
  if (anchor < 0 || end < 0) return null;
  const raw = String(entry.source_type || "").toLowerCase();
  const sourceType =
    raw === "model" || raw === "image" || raw === "video" || raw === "none" ? raw : "none";
  let referenceId = String(entry.reference_id || "").trim();
  let referencePath = String(entry.reference_path || "").trim();
  if (!referencePath && sourceType !== "none") {
    const settings = state.project?.settings;
    if (sourceType === "video") referencePath = String(settings?.reference_video_path || "").trim();
    else if (sourceType === "model") referencePath = String(settings?.reference_model_path || "").trim();
    else if (sourceType === "image") referencePath = String(settings?.reference_image_path || "").trim();
    if (referencePath && !referenceId) {
      const links = Array.isArray(settings?.reference_links) ? settings.reference_links : [];
      const match = links.find((item) => item.path === referencePath);
      if (match?.id) referenceId = match.id;
    }
  }
  return {
    id: entry.id || newRefSegmentId(),
    anchorIndex: anchor,
    endIndex: end,
    videoStart: Number(entry.video_start) || 0,
    sourceType,
    referenceId,
    referencePath,
  };
}

function restoreRefSegmentFromProject() {
  const settings = state.project?.settings;
  if (!settings) {
    state.refSegment.segments = [];
    state.refSegment.activeId = null;
    return;
  }

  let segments = [];
  if (Array.isArray(settings.ref_segments) && settings.ref_segments.length) {
    segments = settings.ref_segments.map(segmentFromSavedEntry).filter(Boolean);
  } else if (settings.ref_segment && typeof settings.ref_segment === "object") {
    const legacy = segmentFromSavedEntry({
      id: settings.ref_segment.id || "seg_default",
      anchor_shot_id: settings.ref_segment.anchor_shot_id,
      end_shot_id: settings.ref_segment.end_shot_id,
      video_start: settings.ref_segment_video?.start ?? 0,
    });
    if (legacy) segments = [legacy];
  }

  if (!segments.length && refSegmentList().length) return;

  state.refSegment.segments = segments;
  const activeId = String(settings.active_ref_segment_id || "").trim();
  state.refSegment.activeId =
    activeId && segments.some((segment) => segment.id === activeId) ? activeId : segments[0]?.id || null;
}

function saveRefSegmentSoon() {
  window.clearTimeout(saveRefSegmentSoon.timer);
  saveRefSegmentSoon.timer = window.setTimeout(() => {
    saveRefSegmentToProject().catch(() => {});
  }, 400);
}

async function saveRefSegmentToProject() {
  if (!state.project) return;
  const shots = state.project.shots || [];
  const segments = refSegmentList().map((segment) => ({
    id: segment.id,
    anchor_shot_id: shots[segment.anchorIndex]?.shot_id || "",
    end_shot_id: shots[segment.endIndex]?.shot_id || "",
    video_start: roundRefSegmentTime(segment.videoStart ?? 0),
    source_type: segmentSourceType(segment),
    reference_id: segment.referenceId || "",
    reference_path: segment.referencePath || "",
  }));
  const active = refSegmentActive();
  const payload = {
    ref_segments: segments,
    active_ref_segment_id: state.refSegment.activeId || "",
    ref_segment: active
      ? {
          anchor_shot_id: shots[active.anchorIndex]?.shot_id || "",
          end_shot_id: shots[active.endIndex]?.shot_id || "",
        }
      : {},
  };
  await api("/api/project/settings", {
    method: "PATCH",
    body: JSON.stringify(payload),
    silent: true,
  });
}

function findProjectReferenceById(id) {
  if (!id) return null;
  return (typeof projectReferences === "function" ? projectReferences() : []).find((ref) => ref.id === id) || null;
}

function findProjectReferenceByPath(path) {
  const normalized = String(path || "").trim();
  if (!normalized) return null;
  return (
    (typeof projectReferences === "function" ? projectReferences() : []).find((ref) => ref.path === normalized) ||
    null
  );
}

function segmentReferenceEntry(segment = refSegmentActive()) {
  if (!segment) return null;
  if (segment.referenceId) {
    const byId = findProjectReferenceById(segment.referenceId);
    if (byId) return byId;
  }
  if (segment.referencePath) {
    return findProjectReferenceByPath(segment.referencePath);
  }
  return null;
}

function segmentReferencePath(segment = refSegmentActive()) {
  if (!segment) return "";
  if (segment.referencePath) return String(segment.referencePath).trim();
  const ref = segmentReferenceEntry(segment);
  return ref?.path ? String(ref.path).trim() : "";
}

function segmentReferenceTitle(segment = refSegmentActive()) {
  const ref = segmentReferenceEntry(segment);
  if (ref && typeof referenceDisplayTitle === "function") {
    return referenceDisplayTitle(ref);
  }
  const path = segmentReferencePath(segment);
  return path ? path.split(/[/\\]/).pop() : "";
}

function referenceVideoPath(segment = refSegmentActive()) {
  const type = segmentSourceType(segment);
  if (type === "video") {
    const path = segmentReferencePath(segment);
    if (path) return path;
  }
  if (typeof activeReferenceVideoPath === "function") {
    return activeReferenceVideoPath(state.project);
  }
  return String(state.project?.settings?.reference_video_path || "").trim();
}

function referenceModelPathForSegment(segment = refSegmentActive()) {
  const type = segmentSourceType(segment);
  if (type === "model") {
    const path = segmentReferencePath(segment);
    if (path) return path;
  }
  if (typeof referenceModelPath === "function") {
    return referenceModelPath(state.project);
  }
  return String(state.project?.settings?.reference_model_path || "").trim();
}

function referenceImagePathForSegment(segment = refSegmentActive()) {
  const type = segmentSourceType(segment);
  if (type === "image") {
    const path = segmentReferencePath(segment);
    if (path) return path;
  }
  if (typeof referenceImagePath === "function") {
    return referenceImagePath(state.project);
  }
  return String(state.project?.settings?.reference_image_path || "").trim();
}

function segmentSourceType(segment = refSegmentActive()) {
  if (
    segment?.sourceType === "none" ||
    segment?.sourceType === "model" ||
    segment?.sourceType === "video" ||
    segment?.sourceType === "image"
  ) {
    return segment.sourceType;
  }
  return "none";
}

function segmentHasReference(segment = refSegmentActive()) {
  const type = segmentSourceType(segment);
  if (type === "none") return false;
  return Boolean(segmentReferencePath(segment));
}

function segmentDisplayType(segment = refSegmentActive()) {
  return segmentHasReference(segment) ? segmentSourceType(segment) : "none";
}

function isModelSegment(segment = refSegmentActive()) {
  return segmentDisplayType(segment) === "model";
}

function isImageSegment(segment = refSegmentActive()) {
  return segmentDisplayType(segment) === "image";
}

function isEmptySegment(segment = refSegmentActive()) {
  return segmentDisplayType(segment) === "none";
}

function referenceImageUrl() {
  const path = referenceImagePathForSegment();
  if (!path) return "";
  if (typeof referenceMediaUrl === "function") {
    return referenceMediaUrl(path);
  }
  return `/api/files?path=${encodeURIComponent(path)}`;
}

function referenceVideoUrl() {
  const path = referenceVideoPath();
  if (!path) return "";
  if (typeof referenceMediaUrl === "function") {
    return referenceMediaUrl(path);
  }
  return `/api/files?path=${encodeURIComponent(path)}`;
}

function ensureSegmentLayer() {
  const track = typeof ensureTimelineTrack === "function" ? ensureTimelineTrack() : null;
  if (!track) return null;
  let layer = track.querySelector(":scope > .timeline-segment-layer");
  if (!layer) {
    layer = document.createElement("div");
    layer.className = "timeline-segment-layer";
    track.appendChild(layer);
  }
  return layer;
}

function segmentsOverlap(min, max, excludeId = null) {
  return refSegmentList().some((segment) => {
    if (excludeId && segment.id === excludeId) return false;
    const range = segmentIndices(segment);
    return range && min <= range.max && max >= range.min;
  });
}

function normalizeSegmentEndpoints(anchorIndex, endIndex) {
  const min = Math.min(anchorIndex, endIndex);
  const max = Math.max(anchorIndex, endIndex);
  return { anchorIndex: min, endIndex: max, min, max };
}

function refSegmentLayoutShot(index) {
  return timelineVirtual?.layout?.items?.find((item) => item.type === "shot" && item.index === index) || null;
}

function refSegmentIndexFromPointerX(clientX) {
  const track = typeof ensureTimelineTrack === "function" ? ensureTimelineTrack() : null;
  const layout = timelineVirtual?.layout;
  if (!track || !layout?.items?.length) return -1;

  const trackRect = track.getBoundingClientRect();
  // Track rect already accounts for horizontal scroll; do not add scrollLeft again.
  const x = clientX - trackRect.left;
  const shotItems = layout.items.filter((item) => item.type === "shot");
  if (!shotItems.length) return -1;

  for (let i = 0; i < shotItems.length; i += 1) {
    const item = shotItems[i];
    const right = item.left + item.width;
    const next = shotItems[i + 1];
    if (x >= item.left && x <= right) return item.index;
    if (next && x > right && x < next.left) {
      const mid = (right + next.left) / 2;
      return x < mid ? item.index : next.index;
    }
  }

  if (x < shotItems[0].left) return shotItems[0].index;
  return shotItems[shotItems.length - 1].index;
}

function refSegmentIndexFromEvent(event) {
  return refSegmentIndexFromPointerX(event.clientX);
}

function syncSegmentBarGeometry(bar, segment, { preview = false } = {}) {
  const range = segmentIndices(segment);
  if (!range || !timelineVirtual?.layout) return false;
  const startItem = refSegmentLayoutShot(range.min);
  const endItem = refSegmentLayoutShot(range.max);
  if (!startItem || !endItem) return false;

  const pad = 12;
  const barLeft = startItem.left + pad;
  const barWidth =
    range.min === range.max
      ? Math.max(36, startItem.width - pad * 2)
      : Math.max(36, endItem.left + endItem.width - startItem.left - pad * 2);
  bar.style.left = `${barLeft}px`;
  bar.style.width = `${barWidth}px`;
  const displayType = preview ? "none" : segmentDisplayType(segment);
  const duration = refSegmentDurationSeconds(segment).toFixed(1);
  const refTitle = segmentReferenceTitle(segment);
  const refShort = refTitle.length > 14 ? `${refTitle.slice(0, 12)}…` : refTitle;
  const boardLabel =
    range.min === range.max ? `#${range.min + 1}` : `#${range.min + 1}–#${range.max + 1}`;
  bar.textContent =
    displayType === "none"
      ? `No ref · ${boardLabel}`
      : `${refShort || displayType} · ${duration}s · ${boardLabel}`;
  bar.classList.toggle("is-preview", preview);
  bar.classList.toggle("is-active", !preview && segment.id === state.refSegment.activeId);
  bar.classList.toggle("is-empty", displayType === "none");
  bar.classList.toggle("is-model", displayType === "model");
  bar.classList.toggle("is-video", displayType === "video");
  bar.classList.toggle("is-image", displayType === "image");
  bar.title =
    displayType === "none"
      ? "未绑定 Reference · 单击选择 Reference"
      : `${refTitle || displayType} · 单击切换 · 双击编辑 · 拖拽边缘调整范围 · Delete 删除`;
  return true;
}

function upsertSegmentBar(layer, segment, { preview = false } = {}) {
  const range = segmentIndices(segment);
  if (!range) return;

  const barId = preview ? "__preview__" : segment.id;
  let bar = layer.querySelector(`.timeline-segment-bar[data-segment-id="${barId}"]`);
  if (!bar) {
    bar = document.createElement("span");
    bar.className = "timeline-segment-bar";
    bar.dataset.segmentId = barId;
    bar.setAttribute("role", "button");
    bar.tabIndex = -1;
    if (!preview) bindSegmentBarEvents(bar);
    layer.appendChild(bar);
  }
  syncSegmentBarGeometry(bar, segment, { preview });
}

function patchRefSegmentDotClasses(coveredIndices) {
  el.timelineStrip?.querySelectorAll(".timeline-segment-dot").forEach((dot) => {
    dot.classList.remove("is-active", "is-anchor", "is-end", "in-range");
    const index = Number(dot.dataset.index);
    if (coveredIndices.has(index)) dot.classList.add("in-range");
    const active = refSegmentActive();
    const activeRange = segmentIndices(active);
    if (activeRange && index === activeRange.anchor) dot.classList.add("is-anchor", "is-active");
    if (activeRange && index === activeRange.end && activeRange.end !== activeRange.anchor) {
      dot.classList.add("is-end", "is-active");
    }
  });
}

function collectCoveredIndices(extraPreview = null) {
  const coveredIndices = new Set();
  refSegmentList().forEach((segment) => {
    const range = segmentIndices(segment);
    if (!range) return;
    for (let index = range.min; index <= range.max; index += 1) coveredIndices.add(index);
  });
  if (extraPreview) {
    for (let index = extraPreview.min; index <= extraPreview.max; index += 1) coveredIndices.add(index);
  }
  return coveredIndices;
}

function attachRefSegmentDragListeners() {
  detachRefSegmentDragListeners();
  window.addEventListener("pointermove", onRefSegmentPointerMove);
  window.addEventListener("pointerup", onRefSegmentPointerUp);
  window.addEventListener("pointercancel", onRefSegmentPointerUp);
}

function detachRefSegmentDragListeners() {
  window.removeEventListener("pointermove", onRefSegmentPointerMove);
  window.removeEventListener("pointerup", onRefSegmentPointerUp);
  window.removeEventListener("pointercancel", onRefSegmentPointerUp);
}

function restoreSegmentDragSnapshot(drag) {
  const segment = refSegmentById(drag.segmentId);
  if (!segment || !drag.snapshot) return;
  segment.anchorIndex = drag.snapshot.anchorIndex;
  segment.endIndex = drag.snapshot.endIndex;
}

function beginRefSegmentDrag() {
  const drag = refSegmentDrag;
  if (!drag || drag.dragging) return;
  drag.dragging = true;
  if (drag.captureTarget && !drag.captureStarted) {
    try {
      drag.captureTarget.setPointerCapture(drag.pointerId);
      drag.captureStarted = true;
    } catch {
      // ignore
    }
  }
  if (drag.isNew) {
    drag.previewEnd = drag.anchor;
  }
  patchRefSegmentUi();
}

function applyRefSegmentDragIndex(index) {
  const drag = refSegmentDrag;
  if (!drag) return;

  if (drag.isNew) {
    drag.previewEnd = index;
    patchRefSegmentUi();
    return;
  }

  const segment = refSegmentById(drag.segmentId);
  if (!segment || !drag.snapshot) return;

  let nextMin = drag.snapshot.min;
  let nextMax = drag.snapshot.max;

  if (drag.mode === "resize-start") {
    nextMin = Math.min(index, drag.snapshot.max);
    nextMax = drag.snapshot.max;
  } else if (drag.mode === "resize-end") {
    nextMin = drag.snapshot.min;
    nextMax = Math.max(index, drag.snapshot.min);
  } else {
    return;
  }

  const shots = state.project?.shots || [];
  nextMin = Math.max(0, nextMin);
  nextMax = Math.min(shots.length - 1, nextMax);
  if (nextMax < nextMin) return;
  if (segmentsOverlap(nextMin, nextMax, segment.id)) return;

  segment.anchorIndex = nextMin;
  segment.endIndex = nextMax;
  setActiveRefSegment(segment.id, { syncProject: false });
  patchRefSegmentUi();
}

function startRefSegmentDrag(event, anchorIndex, options = {}) {
  const { segmentId = null, isNew = false, mode = "", snapshot = null } = options;
  event.stopPropagation();
  if (Number.isNaN(anchorIndex) || anchorIndex < 0) return;

  if (segmentId) setActiveRefSegment(segmentId);

  refSegmentDrag = {
    anchor: anchorIndex,
    segmentId,
    isNew: Boolean(isNew),
    mode,
    snapshot,
    pointerId: event.pointerId,
    startX: event.clientX,
    startY: event.clientY,
    dragging: false,
    previewEnd: anchorIndex,
    captureTarget: ensureTimelineTrack() || event.currentTarget,
    captureStarted: false,
  };
  attachRefSegmentDragListeners();
}

function onRefSegmentDotPointerDown(event) {
  if (event.button !== 0) return;
  const index = Number(event.currentTarget.dataset.index);
  if (Number.isNaN(index) || index < 0) return;
  if (findSegmentAtIndex(index)) return;
  startRefSegmentDrag(event, index, { isNew: true });
}

function onRefSegmentBarPointerDown(event) {
  if (event.button !== 0) return;
  event.stopPropagation();
  const bar = event.currentTarget;
  const segmentId = bar.dataset.segmentId;
  const segment = refSegmentById(segmentId);
  if (!segment) return;
  const range = segmentIndices(segment);
  if (!range) return;

  setActiveRefSegment(segmentId);
  const rect = bar.getBoundingClientRect();
  const ratio = rect.width > 0 ? (event.clientX - rect.left) / rect.width : 0.5;
  const mode = ratio <= 0.5 ? "resize-start" : "resize-end";
  const anchorIndex = ratio <= 0.5 ? range.min : range.max;
  const pending = {
    segmentId,
    mode,
    anchorIndex,
    snapshot: {
      anchorIndex: segment.anchorIndex,
      endIndex: segment.endIndex,
      min: range.min,
      max: range.max,
    },
    pointerId: event.pointerId,
    startX: event.clientX,
    startY: event.clientY,
  };

  const cleanup = () => {
    bar.removeEventListener("pointermove", onBarMove);
    bar.removeEventListener("pointerup", onBarUp);
    bar.removeEventListener("pointercancel", onBarUp);
  };

  const onBarMove = (moveEvent) => {
    if (moveEvent.pointerId !== pending.pointerId) return;
    const moved = Math.hypot(moveEvent.clientX - pending.startX, moveEvent.clientY - pending.startY);
    if (moved < 5) return;
    cleanup();
    startRefSegmentDrag(moveEvent, pending.anchorIndex, {
      segmentId: pending.segmentId,
      mode: pending.mode,
      snapshot: pending.snapshot,
    });
    beginRefSegmentDrag();
    const index = refSegmentIndexFromEvent(moveEvent);
    if (index >= 0) applyRefSegmentDragIndex(index);
  };

  const onBarUp = (upEvent) => {
    if (upEvent.pointerId !== pending.pointerId) return;
    cleanup();
  };

  bar.addEventListener("pointermove", onBarMove);
  bar.addEventListener("pointerup", onBarUp);
  bar.addEventListener("pointercancel", onBarUp);
}

function onRefSegmentPointerMove(event) {
  if (!refSegmentDrag || event.pointerId !== refSegmentDrag.pointerId) return;
  if (!refSegmentDrag.dragging) {
    const moved = Math.hypot(event.clientX - refSegmentDrag.startX, event.clientY - refSegmentDrag.startY);
    if (moved < 5) return;
    event.preventDefault();
    beginRefSegmentDrag();
  }
  const index = refSegmentIndexFromEvent(event);
  if (index < 0) return;
  applyRefSegmentDragIndex(index);
}

function onRefSegmentPointerUp(event) {
  if (!refSegmentDrag || event.pointerId !== refSegmentDrag.pointerId) return;
  const drag = refSegmentDrag;
  refSegmentDrag = null;
  detachRefSegmentDragListeners();
  try {
    if (drag.captureStarted) {
      drag.captureTarget?.releasePointerCapture(event.pointerId);
    }
  } catch {
    // ignore
  }

  if (drag.dragging && drag.isNew) {
    const endIndex = drag.previewEnd ?? drag.anchor;
    const { min, max } = normalizeSegmentEndpoints(drag.anchor, endIndex);
    if (segmentsOverlap(min, max)) {
      showToast("Segment overlaps an existing range.");
      patchRefSegmentUi();
      return;
    }
    addRefSegment(drag.anchor, endIndex);
    return;
  }

  if (!drag.dragging && drag.isNew) {
    if (!segmentsOverlap(drag.anchor, drag.anchor)) {
      addRefSegment(drag.anchor, drag.anchor);
    }
    patchRefSegmentUi();
    return;
  }

  if (drag.dragging && !drag.isNew) {
    const segment = refSegmentById(drag.segmentId);
    const range = segmentIndices(segment);
    if (!segment || !range || segmentsOverlap(range.min, range.max, segment.id)) {
      restoreSegmentDragSnapshot(drag);
    }
    saveRefSegmentSoon();
  }

  patchRefSegmentUi();
}

function bindSegmentBarEvents(bar) {
  let pendingClickTimer = null;

  bar.addEventListener("pointerdown", onRefSegmentBarPointerDown);
  bar.addEventListener("dblclick", (event) => {
    event.preventDefault();
    event.stopPropagation();
    window.clearTimeout(pendingClickTimer);
    pendingClickTimer = null;
    if (refSegmentDrag?.dragging) return;
    const id = bar.dataset.segmentId;
    if (!id || id === "__preview__") return;
    setActiveRefSegment(id);
    patchRefSegmentUi();
    openRefSegmentWindow();
  });
  bar.addEventListener("click", (event) => {
    if (refSegmentDrag) return;
    const id = bar.dataset.segmentId;
    if (!id) return;

    if (pendingClickTimer) {
      window.clearTimeout(pendingClickTimer);
      pendingClickTimer = null;
      setActiveRefSegment(id);
      patchRefSegmentUi();
      openRefSegmentWindow();
      return;
    }

    pendingClickTimer = window.setTimeout(() => {
      pendingClickTimer = null;
      if (refSegmentDrag) return;
      setActiveRefSegment(id);
      patchRefSegmentUi();
      const segment = refSegmentById(id);
      if (segment && !segmentHasReference(segment)) {
        openRefSegmentWorkbench();
      }
    }, 260);
  });
}

function refSegmentApplyMeta() {
  return state.project?.settings?.ref_segment_apply || null;
}

function isRefSegmentApplyStale(segment = refSegmentActive()) {
  const meta = refSegmentApplyMeta();
  const range = segmentIndices(segment);
  if (!meta || !range) return Boolean(range && (referenceVideoPath() || referenceModelPathForSegment()));
  const shots = state.project?.shots || [];
  const storyboardDuration = refSegmentDurationSeconds(segment);
  const durationStale =
    meta.storyboard_duration != null &&
    roundRefSegmentTime(meta.storyboard_duration) !== roundRefSegmentTime(storyboardDuration);
  const segmentMatch =
    !meta.segment_id || !segment?.id ? true : meta.segment_id === segment.id;
  const modelSegment = isModelSegment(segment);
  const imageSegment = isImageSegment(segment);
  const segmentRefPath = segmentReferencePath(segment);
  const sourceMatch = modelSegment
    ? String(meta.reference_model_path || "") === segmentRefPath
    : imageSegment
      ? String(meta.reference_image_path || "") === segmentRefPath
      : String(meta.reference_video_path || "") === segmentRefPath;
  return (
    !segmentMatch ||
    meta.anchor_shot_id !== shots[range.min]?.shot_id ||
    meta.end_shot_id !== shots[range.max]?.shot_id ||
    !sourceMatch ||
    roundRefSegmentTime(meta.video_start) !== roundRefSegmentTime(segment?.videoStart ?? 0) ||
    durationStale
  );
}

function roundRefSegmentTime(value) {
  return Math.round((Number(value) || 0) * 1000) / 1000;
}

function refSegmentSummaryLabel() {
  const segments = refSegmentList();
  const active = refSegmentActive();
  const range = segmentIndices(active);
  if (!segments.length) return "";
  if (segments.length === 1 && range) {
    const duration = refSegmentDurationSeconds(active);
    const count = range.max - range.min + 1;
    const meta = refSegmentApplyMeta();
    if (meta && !isRefSegmentApplyStale(active)) {
      return `Applied · ${duration.toFixed(1)}s · ${count} boards`;
    }
    if (meta && isRefSegmentApplyStale(active)) {
      return `Re-apply needed · ${duration.toFixed(1)}s · ${count} boards`;
    }
    return `Segment ${duration.toFixed(1)}s · ${count} boards`;
  }
  const totalDuration = segments.reduce((sum, segment) => sum + refSegmentDurationSeconds(segment), 0);
  return `${segments.length} segments · ${totalDuration.toFixed(1)}s total`;
}

function renderSegmentBar(layer, segment, { preview = false } = {}) {
  upsertSegmentBar(layer, segment, { preview });
}

function patchRefSegmentUi() {
  const layer = ensureSegmentLayer();
  if (!layer) return;

  let previewRange = null;
  if (refSegmentDrag?.dragging && refSegmentDrag.isNew) {
    const previewEnd = refSegmentDrag.previewEnd ?? refSegmentDrag.anchor;
    const preview = normalizeSegmentEndpoints(refSegmentDrag.anchor, previewEnd);
    if (preview.max >= preview.min && !segmentsOverlap(preview.min, preview.max)) {
      previewRange = preview;
    }
  }

  if (refSegmentDrag?.dragging) {
    refSegmentList().forEach((segment) => upsertSegmentBar(layer, segment));
    layer.querySelector(".timeline-segment-bar[data-segment-id='__preview__']")?.remove();
    if (previewRange) {
      upsertSegmentBar(
        layer,
        {
          id: "__preview__",
          anchorIndex: previewRange.anchorIndex,
          endIndex: previewRange.endIndex,
          sourceType: "none",
        },
        { preview: true }
      );
    }
    patchRefSegmentDotClasses(collectCoveredIndices(previewRange));
  } else {
    layer.innerHTML = "";
    refSegmentList().forEach((segment) => renderSegmentBar(layer, segment));
    if (previewRange) {
      renderSegmentBar(
        layer,
        {
          id: "__preview__",
          anchorIndex: previewRange.anchorIndex,
          endIndex: previewRange.endIndex,
          sourceType: "none",
        },
        { preview: true }
      );
    }
    patchRefSegmentDotClasses(collectCoveredIndices(previewRange));
  }

  const hasSegmentBar = refSegmentList().some((segment) => Boolean(segmentIndices(segment)));
  layer.closest(".timeline-track")?.classList.toggle("has-segment-bar", hasSegmentBar);

  if (el.refSegmentSummary) {
    el.refSegmentSummary.textContent = refSegmentSummaryLabel();
    const active = refSegmentActive();
    el.refSegmentSummary.classList.toggle(
      "is-stale",
      Boolean(active && refSegmentApplyMeta() && isRefSegmentApplyStale(active))
    );
  }
  const segMode = segmentDisplayType(refSegmentActive());
  el.refSegmentApply?.classList.toggle("is-model-apply", segMode === "model");
  el.refSegmentApply?.classList.toggle("is-image-apply", segMode === "image");
  patchRefSegmentPlayerMode();
}

function updateRefSegment(segmentId, anchorIndex, endIndex) {
  const segment = refSegmentById(segmentId);
  if (!segment) return;
  segment.anchorIndex = anchorIndex;
  segment.endIndex = endIndex;
  state.refSegment.activeId = segmentId;
  patchRefSegmentUi();
  saveRefSegmentSoon();
}

function refSegmentOverlayUrl(segment = refSegmentActive()) {
  const query = segment?.id ? `?segment=${encodeURIComponent(segment.id)}` : "";
  const mode = segmentHasReference(segment) ? segmentDisplayType(segment) : "video";
  const hash = mode && mode !== "none" ? `#${mode}` : "#video";
  return `/ref-segment${query}${hash}`;
}

function isRefSegmentOverlayOpen() {
  return Boolean(el.refVideoOverlay && !el.refVideoOverlay.hidden && el.refVideoFrame);
}

function openRefSegmentWorkbench() {
  const segment = refSegmentActive();
  const range = segmentIndices(segment);
  if (!range) {
    showToast("Click a dot under a board, then drag to another board.");
    return false;
  }
  const mode = segmentHasReference(segment) ? segmentDisplayType(segment) : "video";
  if (isRefSegmentOverlayOpen()) {
    try {
      const current = new URL(el.refVideoFrame.src, window.location.origin);
      if (current.pathname.endsWith("/ref-segment")) {
        el.refVideoFrame.contentWindow?.postMessage(
          { source: "storyboard-ref-parent", type: "switch-view", mode },
          window.location.origin
        );
        el.refVideoFrame.title = refSegmentOverlayTitle(mode);
        if (!segmentHasReference(segment)) {
          showToast("从左侧选择 Reference 绑定到此 Segment");
        }
        return true;
      }
    } catch {
      // fall through to (re)load
    }
  }
  openRefSegmentOverlay(refSegmentOverlayUrl(segment));
  if (el.refVideoFrame) {
    el.refVideoFrame.title = refSegmentOverlayTitle(mode);
  }
  if (!segmentHasReference(segment)) {
    showToast("从左侧选择 Reference 绑定到此 Segment");
  }
  return true;
}

function clearRefSegmentBindingMode() {
  el.refSegmentModal?.classList.remove("is-binding-reference");
  el.refSegmentRefsPanel?.classList.remove("is-segment-pick");
  document.getElementById("referencePanel")?.classList.remove("is-segment-pick");
}

function openRefSegmentReferenceFlow() {
  return openRefSegmentWorkbench();
}

function jumpToReferencePicker() {
  openRefSegmentWorkbench();
}

function addRefSegment(anchorIndex, endIndex) {
  const { anchorIndex: minAnchor, endIndex: maxEnd } = normalizeSegmentEndpoints(anchorIndex, endIndex);
  const id = newRefSegmentId();
  state.refSegment.segments.push({
    id,
    anchorIndex: minAnchor,
    endIndex: maxEnd,
    videoStart: 0,
    sourceType: "none",
    referenceId: "",
    referencePath: "",
  });
  state.refSegment.activeId = id;
  patchRefSegmentUi();
  saveRefSegmentSoon();
  window.requestAnimationFrame(() => openRefSegmentWorkbench());
  return id;
}

async function applyRefSegmentToBoards() {
  const segment = refSegmentActive();
  const range = segmentIndices(segment);
  const shots = state.project?.shots || [];
  if (!range || !shots.length) {
    showToast("Select a board range on the segment dots.");
    return;
  }
  if (!segmentHasReference(segment)) {
    openRefSegmentWorkbench();
    return;
  }
  if (isModelSegment(segment)) {
    if (!referenceModelPathForSegment()) {
      showToast("Import or select a reference GLB first.");
      return;
    }
    await applyRefSegment3dToBoards(segment, range, shots);
    return;
  }
  if (isImageSegment(segment)) {
    if (!referenceImagePathForSegment()) {
      showToast("Import or select a reference image first.");
      return;
    }
    const count = range.max - range.min + 1;
    const confirmed = await showDialog({
      title: "Apply image segment",
      hint: `Apply the reference image to boards #${range.min + 1}–#${range.max + 1} (${count} boards)?`,
      actions: [
        { label: "Cancel", value: null },
        { label: "Apply", value: "apply", primary: true },
      ],
    });
    if (confirmed !== "apply") return;
    try {
      const result = await runWithProgress(
        "Applying image…",
        () =>
          api("/api/project/ref-segment/apply-image", {
            method: "POST",
            body: JSON.stringify({
              anchor_shot_id: shots[range.anchor].shot_id,
              end_shot_id: shots[range.end].shot_id,
              segment_id: segment?.id || "",
            }),
          }),
        { successMessage: `Applied to ${count} boards`, temporary: true }
      );
      setProject(result);
      restoreRefSegmentFromProject();
      await selectShot(shots[range.min].shot_id);
      patchRefSegmentUi();
    } catch {
      // api() already toasts
    }
    return;
  }
  if (!referenceVideoPath()) {
    showToast("Add a reference video first.");
    return;
  }
  const count = range.max - range.min + 1;
  const duration = refSegmentDurationSeconds(segment, shots);
  const confirmed = await showDialog({
    title: "Apply to boards",
    hint: `Save preview frames for boards #${range.min + 1}–#${range.max + 1} (${count} boards, ${duration.toFixed(1)}s)? Frames are cached on disk; re-apply after changing segment or video.`,
    actions: [
      { label: "Cancel", value: null },
      { label: "Apply", value: "apply", primary: true },
    ],
  });
  if (confirmed !== "apply") return;
  try {
    const result = await runWithProgress(
      "Extracting frames…",
      () =>
        api("/api/project/ref-segment/apply", {
          method: "POST",
          body: JSON.stringify({
            anchor_shot_id: shots[range.anchor].shot_id,
            end_shot_id: shots[range.end].shot_id,
            segment_id: segment?.id || "",
          }),
        }),
      { successMessage: `Applied to ${count} boards`, temporary: true }
    );
    setProject(result);
    restoreRefSegmentFromProject();
    await selectShot(shots[range.min].shot_id);
    patchRefSegmentUi();
  } catch {
    // api() already toasts
  }
}

function bindRefSegmentDot(dot) {
  dot.addEventListener("pointerdown", onRefSegmentDotPointerDown);
  dot.addEventListener("dblclick", (event) => {
    event.preventDefault();
    event.stopPropagation();
    const index = Number(event.currentTarget.dataset.index);
    const existing = findSegmentAtIndex(index);
    if (!existing) {
      showToast("先单击下方圆点创建 Segment");
      return;
    }
    state.refSegment.activeId = existing.id;
    syncActiveSegmentToProjectSettings().catch(() => {});
    patchRefSegmentUi();
    openRefSegmentWindow();
  });
}

const refSegmentSceneState = {
  editor: null,
  loading: null,
  loadedPath: "",
};

function refSegmentUsesModelView() {
  return isModelSegment();
}

function refSegmentUsesImageView() {
  return isImageSegment();
}

function setActiveRefSegment(id, { syncProject = true } = {}) {
  if (!id || state.refSegment.activeId === id) return;
  state.refSegment.activeId = id;
  if (syncProject) syncActiveSegmentToProjectSettings().catch(() => {});
}

async function syncActiveSegmentToProjectSettings() {
  const segment = refSegmentActive();
  if (!segment || !state.project) return;
  const path = segmentReferencePath(segment);
  const type = segmentSourceType(segment);
  if (!path || type === "none") return;
  const body = { reference_segment_mode: type, active_ref_segment_id: segment.id };
  if (type === "video") body.reference_video_path = path;
  else if (type === "model") body.reference_model_path = path;
  else body.reference_image_path = path;
  const project = await api("/api/project/settings", {
    method: "PATCH",
    body: JSON.stringify(body),
    silent: true,
  });
  setProject(project, false);
  if (typeof refreshAllReferencePanels === "function") refreshAllReferencePanels();
}

async function bindReferenceToActiveSegment(ref) {
  const segment = refSegmentActive();
  if (!segment) {
    showToast("先在时间轴创建 Segment");
    return null;
  }
  const type =
    typeof resolveReferenceType === "function" ? resolveReferenceType(ref, state.project) : ref?.type;
  const path = String(ref?.path || "").trim();
  if (!path || !type || type === "none") return null;

  segment.referenceId = String(ref?.id || "").trim();
  segment.referencePath = path;
  segment.sourceType = type;
  refSegmentSceneState.loadedPath = "";

  const body = { reference_segment_mode: type, active_ref_segment_id: segment.id };
  if (type === "video") body.reference_video_path = path;
  else if (type === "model") body.reference_model_path = path;
  else body.reference_image_path = path;

  const project = await api("/api/project/settings", {
    method: "PATCH",
    body: JSON.stringify(body),
    silent: true,
  });
  setProject(project, false);
  await saveRefSegmentToProject();
  patchRefSegmentUi();
  if (typeof refreshAllReferencePanels === "function") refreshAllReferencePanels();
  return segment;
}

function activeSegmentReferenceBinding() {
  const segment = refSegmentActive();
  return {
    id: segment?.referenceId || "",
    path: segmentReferencePath(segment),
    type: segmentSourceType(segment),
  };
}

function syncActiveSegmentSourceType(sourceType) {
  const segment = refSegmentActive();
  if (!segment) return;
  const nextType = sourceType === "model" ? "model" : sourceType === "image" ? "image" : "video";
  if (segment.sourceType === nextType && segment.referencePath) return;
  segment.sourceType = nextType;
  refSegmentSceneState.loadedPath = "";
  saveRefSegmentSoon();
}

async function ensureRefSegmentScene3d() {
  if (!el.refSegmentSceneRoot) return null;
  if (refSegmentSceneState.editor) return refSegmentSceneState.editor;
  if (!refSegmentSceneState.loading) {
    refSegmentSceneState.loading = import(`/static/scene3d.js?v=${Date.now()}`)
      .then((module) => {
        const editor = new module.Scene3DEditor(el.refSegmentSceneRoot, {});
        refSegmentSceneState.editor = editor;
        return editor;
      })
      .catch((error) => {
        refSegmentSceneState.loading = null;
        throw error;
      });
  }
  return refSegmentSceneState.loading;
}

async function loadRefSegmentScene3d() {
  if (!refSegmentUsesModelView() || !state.project) return;
  const editor = await ensureRefSegmentScene3d();
  if (!editor) return;
  const sceneSettings = state.project.settings?.scene3d || {};
  if (!sceneSettings.file_path) return;
  const scenePath = String(sceneSettings.file_path || "");
  if (refSegmentSceneState.loadedPath === scenePath && editor.blenderRoot) {
    const segment = refSegmentActive();
    const start = Number(segment?.videoStart);
    if (Number.isFinite(start) && start >= 0) editor.setAnimationTime(start);
    return;
  }
  await editor.loadSceneData(sceneSettings);
  refSegmentSceneState.loadedPath = scenePath;
  const segment = refSegmentActive();
  const start = Number(segment?.videoStart);
  if (Number.isFinite(start) && start >= 0) {
    editor.setAnimationTime(start);
  }
}

function patchRefSegmentPlayerMode() {
  const modelMode = refSegmentUsesModelView();
  const imageMode = refSegmentUsesImageView();
  const videoMode = !modelMode && !imageMode;
  el.refSegmentVideo?.toggleAttribute("hidden", !videoMode);
  if (el.refSegmentFreeze) el.refSegmentFreeze.hidden = true;
  if (el.refSegmentSceneRoot) el.refSegmentSceneRoot.hidden = !modelMode;
  if (el.refSegmentImage) el.refSegmentImage.hidden = !imageMode;
  const player = el.refSegmentVideo?.closest(".ref-segment-player");
  player?.classList.toggle("is-model-player", modelMode);
  player?.classList.toggle("is-image-player", imageMode);
  if (modelMode) {
    stopRefSegmentVideoPreview();
    loadRefSegmentScene3d().catch(() => {});
  } else if (imageMode) {
    stopRefSegmentPreview();
    loadRefSegmentImagePreview();
  }
}

function loadRefSegmentImagePreview() {
  if (!el.refSegmentImage) return;
  const url = referenceImageUrl();
  if (!url) {
    el.refSegmentImage.removeAttribute("src");
    return;
  }
  if (el.refSegmentImage.src !== url) el.refSegmentImage.src = url;
}

function stopRefSegmentPreview() {
  stopRefSegmentVideoPreview();
  const editor = refSegmentSceneState.editor;
  if (editor) {
    editor.pauseAnimation?.();
    editor.isPlaying = false;
  }
}

function stopRefSegmentVideoPreview() {
  window.clearInterval(refSegmentPreviewTimer);
  refSegmentPreviewTimer = null;
  if (el.refSegmentVideo) {
    el.refSegmentVideo.pause();
    el.refSegmentVideo.removeAttribute("src");
  }
  if (el.refSegmentFreeze) el.refSegmentFreeze.hidden = true;
}

function syncRefSegmentFreezeFrame() {
  if (!el.refSegmentVideo || !el.refSegmentFreeze) return;
  const video = el.refSegmentVideo;
  if (!video.videoWidth) return;
  const canvas = el.refSegmentFreeze;
  canvas.width = video.videoWidth;
  canvas.height = video.videoHeight;
  const ctx = canvas.getContext("2d");
  ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
  canvas.hidden = false;
}

function playRefSegmentPreview() {
  if (refSegmentUsesModelView()) {
    playRefSegmentModelPreview();
    return;
  }
  if (refSegmentUsesImageView()) {
    stopRefSegmentPreview();
    patchRefSegmentPlayerMode();
    const duration = refSegmentDurationSeconds();
    if (!referenceImagePathForSegment()) {
      showToast("Import or select a reference image.");
      return;
    }
    if (!duration) {
      showToast("Select a board range on the segment dots.");
      return;
    }
    if (el.refSegmentTime) {
      el.refSegmentTime.textContent = `Image · ${duration.toFixed(1)}s`;
    }
    return;
  }
  stopRefSegmentPreview();
  const url = referenceVideoUrl();
  const duration = refSegmentDurationSeconds();
  if (!url) {
    showToast("Import or select a reference video.");
    return;
  }
  if (!duration) {
    showToast("Select a board range on the segment dots.");
    return;
  }
  const video = el.refSegmentVideo;
  video.src = url;
  video.load();
  video.onloadedmetadata = () => {
    const videoDuration = Number.isFinite(video.duration) ? video.duration : 0;
    let elapsed = 0;
    video.currentTime = 0;
    if (el.refSegmentFreeze) el.refSegmentFreeze.hidden = true;
    video.play().catch(() => {});
    refSegmentPreviewTimer = window.setInterval(() => {
      elapsed += 0.05;
      if (elapsed >= duration) {
        stopRefSegmentPreview();
        return;
      }
      if (videoDuration > 0 && elapsed < videoDuration) {
        if (video.paused) video.play().catch(() => {});
        if (el.refSegmentFreeze) el.refSegmentFreeze.hidden = true;
      } else {
        video.pause();
        if (videoDuration > 0) video.currentTime = Math.max(0, videoDuration - 0.05);
        syncRefSegmentFreezeFrame();
      }
      if (el.refSegmentTime) {
        el.refSegmentTime.textContent = `${elapsed.toFixed(1)}s / ${duration.toFixed(1)}s`;
      }
    }, 50);
  };
}

async function playRefSegmentModelPreview() {
  stopRefSegmentPreview();
  const duration = refSegmentDurationSeconds();
  if (!referenceModelPathForSegment()) {
    showToast("Import or select a reference GLB.");
    return;
  }
  if (!duration) {
    showToast("Select a board range on the segment dots.");
    return;
  }
  patchRefSegmentPlayerMode();
  const editor = await ensureRefSegmentScene3d();
  if (!editor) return;
  await loadRefSegmentScene3d();
  const segment = refSegmentActive();
  const start = Number(segment?.videoStart) || 0;
  editor.setAnimationTime(start);
  if (!editor.isPlaying) editor.toggleAnimationPlayback?.();
  let elapsed = 0;
  refSegmentPreviewTimer = window.setInterval(() => {
    elapsed += 0.05;
    if (elapsed >= duration) {
      stopRefSegmentPreview();
      return;
    }
    if (el.refSegmentTime) {
      const animTime = editor.animationTime || 0;
      el.refSegmentTime.textContent = `${animTime.toFixed(1)}s anim · ${elapsed.toFixed(1)}s / ${duration.toFixed(1)}s`;
    }
  }, 50);
}

function ensureRefVideoOverlay() {
  if (el.refVideoOverlay && el.refVideoFrame) return;

  const overlay = document.createElement("div");
  overlay.id = "refVideoOverlay";
  overlay.className = "ref-video-overlay";
  overlay.hidden = true;
  overlay.innerHTML = `
    <div class="ref-video-overlay-backdrop" data-ref-video-close></div>
    <div class="ref-video-overlay-frame">
      <button type="button" id="refVideoOverlayClose" class="ref-video-overlay-close" data-ref-video-close title="Close">×</button>
      <iframe id="refVideoFrame" class="ref-video-overlay-iframe" title="Reference video segment"></iframe>
    </div>
  `;
  document.body.appendChild(overlay);
  el.refVideoOverlay = overlay;
  el.refVideoFrame = overlay.querySelector("#refVideoFrame");
  el.refVideoOverlayClose = overlay.querySelector("#refVideoOverlayClose");
  overlay.querySelectorAll("[data-ref-video-close]").forEach((node) => {
    node.addEventListener("click", () => closeRefVideoOverlay());
  });
}

function closeRefVideoOverlay() {
  if (el.refVideoFrame) el.refVideoFrame.src = "about:blank";
  if (el.refVideoOverlay) el.refVideoOverlay.hidden = true;
}

function refSegmentOverlayTitle(mode) {
  if (mode === "model") return "Reference 3D segment";
  if (mode === "image") return "Reference image segment";
  return "Reference video segment";
}

function openRefSegmentOverlay(url) {
  ensureRefVideoOverlay();
  if (!el.refVideoFrame || !el.refVideoOverlay) {
    window.open(url, "storyboardRefSegment", "popup=yes,width=1180,height=820");
    return;
  }
  el.refVideoFrame.src = url;
  el.refVideoOverlay.hidden = false;
  el.refVideoOverlayClose?.focus?.();
}

function openRefVideoOverlay(url) {
  openRefSegmentOverlay(url);
}

function openRefScene3dOverlay(url) {
  const query = url.includes("?") ? url.slice(url.indexOf("?")) : "";
  openRefSegmentOverlay(`/ref-segment${query}#model`);
}

function navigateOpenRefSegmentOverlay(mode) {
  if (!el.refVideoOverlay || el.refVideoOverlay.hidden || !el.refVideoFrame) return;
  const normalized = mode === "model" || mode === "image" ? mode : "video";
  let query = "";
  try {
    const current = new URL(el.refVideoFrame.src, window.location.origin);
    if (
      current.pathname.endsWith("/ref-segment") ||
      current.pathname.endsWith("/ref-video") ||
      current.pathname.endsWith("/ref-scene3d")
    ) {
      query = current.search || "";
    }
  } catch {
    query = "";
  }
  if (!query) {
    const segment = typeof refSegmentActive === "function" ? refSegmentActive() : null;
    if (segment?.id) query = `?segment=${encodeURIComponent(segment.id)}`;
  }
  try {
    const current = new URL(el.refVideoFrame.src, window.location.origin);
    if (current.pathname.endsWith("/ref-segment")) {
      el.refVideoFrame.contentWindow?.postMessage(
        { source: "storyboard-ref-parent", type: "switch-view", mode: normalized },
        window.location.origin
      );
      el.refVideoFrame.title = refSegmentOverlayTitle(normalized);
      return;
    }
  } catch {
    // fall through to load unified page
  }
  const next = `/ref-segment${query}#${normalized}`;
  if (!el.refVideoFrame.src.includes("/ref-segment")) {
    el.refVideoFrame.src = next;
  }
  el.refVideoFrame.title = refSegmentOverlayTitle(normalized);
}

function openRefSegmentWindow() {
  openRefSegmentWorkbench();
}

async function applyRefSegment3dToBoards(segment, range, shots) {
  const count = range.max - range.min + 1;
  const confirmed = await showDialog({
    title: "Apply 3D segment",
    hint: `Capture ${count} boards from the 3D scene editor?`,
    actions: [
      { label: "Cancel", value: null },
      { label: "Open editor", value: "open", primary: true },
    ],
  });
  if (confirmed !== "open") return;
  const query = segment?.id ? `?segment=${encodeURIComponent(segment.id)}` : "";
  openRefSegmentOverlay(`/ref-segment${query}#model`);
}

function shouldIgnoreRefSegmentShortcut(event) {
  const target = event.target;
  if (!target || target.closest(".context-menu")) return true;
  const tag = target.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return true;
  if (target.isContentEditable) return true;
  if (el.dialogModal && !el.dialogModal.hidden) return true;
  if (el.settingsModal && !el.settingsModal.hidden) return true;
  if (el.refVideoOverlay && !el.refVideoOverlay.hidden) return true;
  return false;
}

async function deleteActiveRefSegment() {
  const segment = refSegmentActive();
  if (!segment?.id || !state.project) return;
  const range = segmentIndices(segment);
  const count = range ? range.max - range.min + 1 : 0;
  try {
    const result = await api(`/api/project/ref-segments/${encodeURIComponent(segment.id)}`, {
      method: "DELETE",
    });
    setProject(result);
    restoreRefSegmentFromProject();
    patchRefSegmentUi();
    render();
    showToast(count > 1 ? `Segment removed · ${count} boards cleared` : "Segment removed · board cleared");
  } catch {
    // api() already toasts
  }
}

function openRefSegmentModal() {
  openRefSegmentWorkbench();
}

function closeRefSegmentModal() {
  stopRefSegmentPreview();
  clearRefSegmentBindingMode();
  if (el.refSegmentModal) el.refSegmentModal.hidden = true;
}

async function uploadReferenceVideo(file) {
  if (!file || !state.project) return;
  if (typeof importProjectReference === "function") {
    await importProjectReference(file, { setActiveVideo: true });
    restoreRefSegmentFromProject();
    patchRefSegmentUi();
    showToast("Reference video imported.");
    return;
  }
  const form = new FormData();
  form.append("file", file);
  await api("/api/project/reference-video", { method: "POST", body: form, headers: {} }).then(setProject);
  restoreRefSegmentFromProject();
  patchRefSegmentUi();
  showToast("Reference video added.");
}

function bindRefSegmentUi() {
  ensureRefVideoOverlay();
  el.setRefVideo?.addEventListener("click", () => el.projectReferenceFile?.click());
  el.refSegmentPlay?.addEventListener("click", () => playRefSegmentPreview());
  el.refSegmentStop?.addEventListener("click", () => stopRefSegmentPreview());
  el.refSegmentApply?.addEventListener("click", () => applyRefSegmentToBoards());
  document.querySelectorAll("[data-ref-video-close]").forEach((node) => {
    node.addEventListener("click", () => closeRefVideoOverlay());
  });
  document.querySelectorAll("[data-ref-segment-close]").forEach((node) => {
    node.addEventListener("click", () => closeRefSegmentModal());
  });
  el.refSegmentModal?.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeRefSegmentModal();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && el.refVideoOverlay && !el.refVideoOverlay.hidden) {
      closeRefVideoOverlay();
      return;
    }
    if (event.key !== "Delete") return;
    if (shouldIgnoreRefSegmentShortcut(event)) return;
    if (!refSegmentActive()) return;
    event.preventDefault();
    deleteActiveRefSegment();
  });
  window.addEventListener("message", (event) => {
    if (event.origin !== window.location.origin) return;
    const source = event.data?.source;
    if (source !== "storyboard-ref-video" && source !== "storyboard-ref-scene3d") return;
    if (event.data.type === "ref-segment-applied" && event.data.result) {
      setProject(event.data.result);
      restoreRefSegmentFromProject();
      patchRefSegmentUi();
      render();
      closeRefVideoOverlay();
      return;
    }
    if (event.data.type === "ref-segment-saved") {
      api("/api/project", { silent: true }).then((project) => {
        if (project) {
          state.project = project;
          restoreRefSegmentFromProject();
          patchRefSegmentUi();
          if (typeof refreshAllReferencePanels === "function") refreshAllReferencePanels();
        }
      });
    }
  });
}

bindRefSegmentUi();
