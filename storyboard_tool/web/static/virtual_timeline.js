const TIMELINE_LAYOUT = {
  gap: 6,
  insertWidth: 22,
  minShotWidth: 132,
  widthPerSec: 58,
  bufferPx: 360,
};

const timelineVirtual = {
  layoutKey: "",
  layout: null,
  rangeKey: "",
  viewportRaf: 0,
  activeShotId: null,
  activeShotIndex: -1,
};

function timelineShotWidth(duration) {
  return Math.max(TIMELINE_LAYOUT.minShotWidth, Number(duration || 3) * TIMELINE_LAYOUT.widthPerSec);
}

function timelineLayoutKey(shots) {
  return (shots || []).map((shot) => `${shot.shot_id}:${shot.duration_seconds}`).join("|");
}

function buildTimelineLayout(shots) {
  const items = [];
  let left = 0;
  let cursor = 0;
  for (let index = 0; index < shots.length; index += 1) {
    const shot = shots[index];
    const duration = Number(shot.duration_seconds || 3);
    const start = cursor;
    const end = cursor + duration;
    cursor = end;
    const width = timelineShotWidth(duration);
    items.push({ type: "shot", shot, index, left, width, start, end, duration });
    left += width + TIMELINE_LAYOUT.gap;
    items.push({ type: "insert", afterShotId: shot.shot_id, left, width: TIMELINE_LAYOUT.insertWidth });
    left += TIMELINE_LAYOUT.insertWidth + TIMELINE_LAYOUT.gap;
  }
  return {
    items,
    totalWidth: Math.max(0, left - TIMELINE_LAYOUT.gap),
  };
}

function computeVisibleTimelineItems(layout, scrollLeft, viewportWidth) {
  const buffer = TIMELINE_LAYOUT.bufferPx;
  const viewStart = Math.max(0, scrollLeft - buffer);
  const viewEnd = scrollLeft + Math.max(viewportWidth, 320) + buffer;
  return layout.items.filter((item) => item.left + item.width >= viewStart && item.left <= viewEnd);
}

function ensureTimelineTrack() {
  let track = el.timelineStrip?.querySelector(":scope > .timeline-track");
  if (!track && el.timelineStrip) {
    el.timelineStrip.replaceChildren();
    track = document.createElement("div");
    track.className = "timeline-track";
    el.timelineStrip.appendChild(track);
  }
  return track;
}

function timelineShotNode(shotId) {
  if (!shotId || !el.timelineStrip) return null;
  return el.timelineStrip.querySelector(`.timeline-shot[data-shot-id="${CSS.escape(shotId)}"]`);
}

function timelineSelectedBoardIndex(shotId = state.selectedShotId) {
  return (state.project?.shots || []).findIndex((shot) => shot.shot_id === shotId);
}

function patchTimelineSelectedDot(prevIndex, nextIndex) {
  if (prevIndex >= 0) {
    el.timelineStrip
      ?.querySelector(`.timeline-segment-dot[data-index="${prevIndex}"]`)
      ?.classList.remove("is-selected-board");
  }
  if (nextIndex >= 0 && nextIndex !== prevIndex) {
    el.timelineStrip
      ?.querySelector(`.timeline-segment-dot[data-index="${nextIndex}"]`)
      ?.classList.add("is-selected-board");
  }
}

function patchTimelineActiveState(activeShotId = state.selectedShotId, { force = false } = {}) {
  if (!el.timelineStrip) return;
  const prevId = timelineVirtual.activeShotId;
  const nextId = activeShotId || null;
  const prevIndex = timelineVirtual.activeShotIndex ?? -1;
  const nextIndex = timelineSelectedBoardIndex(nextId);

  if (!force && prevId === nextId) {
    const current = nextId ? timelineShotNode(nextId) : null;
    if (current?.classList.contains("active")) return;
  }

  if (prevId && prevId !== nextId) {
    timelineShotNode(prevId)?.classList.remove("active");
    timelineShotNode(prevId)?.closest(".timeline-shot-wrap")?.classList.remove("is-active");
  }
  if (nextId) {
    timelineShotNode(nextId)?.classList.add("active");
    timelineShotNode(nextId)?.closest(".timeline-shot-wrap")?.classList.add("is-active");
  }

  patchTimelineSelectedDot(prevIndex, nextIndex);

  timelineVirtual.activeShotId = nextId;
  timelineVirtual.activeShotIndex = nextIndex;
}

function timelineShotDisplayName(shot) {
  const title = String(shot.title || "").trim();
  if (title) return title;
  return formatShotId(shot.shot_id);
}

function mountTimelineShotElement(entry, activeShotId) {
  const { shot, index, left, width, start, end, duration } = entry;
  const filteredOut =
    (state.statusFilter && shot.status !== state.statusFilter) ||
    (state.revisionOnly && !(shot.comments || []).some((comment) => !comment.resolved));

  const wrap = document.createElement("div");
  wrap.className = "timeline-shot-wrap";
  wrap.style.left = `${left}px`;
  wrap.style.width = `${width}px`;
  wrap.dataset.index = String(index);

  const item = document.createElement("button");
  item.type = "button";
  item.className = `timeline-shot ${shot.shot_id === activeShotId ? "active" : ""}${
    filteredOut ? " timeline-shot-filtered" : ""
  }`;
  item.draggable = true;
  item.dataset.shotId = shot.shot_id;
  item.dataset.index = String(index);
  const thumbMeta = timelineThumbStyle(shot);
  const thumbnailStyle = thumbMeta.style ? `style="${thumbMeta.style}"` : "";
  const thumbClass = thumbMeta.className ? ` ${thumbMeta.className}` : "";
  const dialoguePreview = shot.dialogue
    ? `<span class="timeline-dialogue">${escapeHtml(shot.dialogue.slice(0, 40))}</span>`
    : "";
  const displayName = timelineShotDisplayName(shot);
  item.innerHTML = `
    <div class="timeline-thumb${thumbClass}" ${thumbnailStyle}>
      <span class="timeline-order" aria-hidden="true">${index + 1}</span>
    </div>
    <div class="timeline-meta">
      <span class="timeline-shot-name" title="${escapeHtml(displayName)}">${escapeHtml(displayName)}</span>
      ${dialoguePreview}
      <div class="timeline-duration-row">
        <input class="timeline-duration" type="number" min="0.1" step="0.1" value="${duration.toFixed(1)}" aria-label="Duration seconds" />
        <span>s</span>
      </div>
      <span class="timeline-range">${start.toFixed(1)}s - ${end.toFixed(1)}s</span>
    </div>
  `;
  item.setAttribute("aria-label", `Board ${index + 1}${displayName ? `: ${displayName}` : ""}`);

  const dot = document.createElement("span");
  dot.className = "timeline-segment-dot";
  dot.dataset.index = String(index);
  dot.dataset.shotId = shot.shot_id;
  dot.setAttribute("role", "button");
  dot.setAttribute("aria-label", `Segment board ${index + 1}`);
  dot.tabIndex = -1;
  if (index === timelineSelectedBoardIndex(activeShotId)) {
    dot.classList.add("is-selected-board");
  }

  bindTimelineShotEvents(item, shot, activeShotId);
  if (typeof bindRefSegmentDot === "function") bindRefSegmentDot(dot);

  wrap.appendChild(item);
  wrap.appendChild(dot);
  return wrap;
}

function mountTimelineInsertElement(entry) {
  const button = createTimelineInsertButton(entry.afterShotId);
  button.style.left = `${entry.left}px`;
  button.style.width = `${entry.width}px`;
  return button;
}

function bindTimelineShotEvents(item, shot, activeShotId) {
  item.addEventListener("pointerdown", (event) => {
    if (event.button !== 0) return;
    if (event.target.closest(".timeline-duration")) return;
    window.getSelection()?.removeAllRanges();
    patchTimelineActiveState(shot.shot_id, { force: true });
    stopAnimatic(true, { refreshTimeline: false });
    if (state.selectedShotId !== shot.shot_id) {
      selectShot(shot.shot_id);
    }
  });
  item.addEventListener("click", (event) => {
    event.preventDefault();
  });
  item.addEventListener("contextmenu", (event) => {
    event.preventDefault();
    stopAnimatic();
    selectShot(shot.shot_id);
    showShotContextMenu(shot.shot_id, event.clientX, event.clientY);
  });
  item.addEventListener("dragstart", (event) => {
    event.dataTransfer.setData("text/plain", shot.shot_id);
    event.dataTransfer.effectAllowed = "move";
  });
  item.addEventListener("dragover", (event) => {
    event.preventDefault();
    item.classList.add("drag-over");
  });
  item.addEventListener("dragleave", () => {
    item.classList.remove("drag-over");
  });
  item.addEventListener("drop", async (event) => {
    event.preventDefault();
    item.classList.remove("drag-over");
    const draggedShotId = event.dataTransfer.getData("text/plain");
    if (draggedShotId && draggedShotId !== shot.shot_id) {
      await reorderShot(draggedShotId, shot.shot_id);
    }
  });
  const durationInput = item.querySelector(".timeline-duration");
  durationInput.addEventListener("click", (event) => event.stopPropagation());
  durationInput.addEventListener("change", async (event) => {
    event.stopPropagation();
    const value = Math.max(0.1, Number(durationInput.value || 3));
    shot.duration_seconds = value;
    if (shot.shot_id === state.selectedShotId) {
      el.durationSeconds.value = value;
    }
    state.project.dirty = true;
    await saveShot(shot);
    renderTimeline(activeShotId);
  });
}

function updateTimelineMeta(shots, activeShotId = state.selectedShotId) {
  const total = totalDuration(shots);
  const current = Math.min(currentAnimaticSeconds(), total);
  el.timeCurrent.textContent = `${current.toFixed(1)}s`;
  el.timeTotal.textContent = `${total.toFixed(1)}s`;
  el.progressSlider.max = total.toFixed(1);
  el.progressSlider.value = current.toFixed(1);
}

function renderTimelineViewport(activeShotId = state.selectedShotId) {
  const layout = timelineVirtual.layout;
  const track = ensureTimelineTrack();
  if (!layout || !track) return;

  track.style.width = `${layout.totalWidth}px`;
  const scrollLeft = el.timelineStrip?.scrollLeft || 0;
  const viewportWidth = el.timelineStrip?.clientWidth || 640;
  const visible = computeVisibleTimelineItems(layout, scrollLeft, viewportWidth);
  const rangeKey = `${layout.totalWidth}:${scrollLeft}:${viewportWidth}:${visible
    .map((item) => `${item.type}:${item.left}`)
    .join(",")}`;

  if (timelineVirtual.rangeKey === rangeKey && track.childElementCount > 0) {
    patchTimelineActiveState(activeShotId);
    if (typeof patchRefSegmentUi === "function") patchRefSegmentUi();
    return;
  }
  timelineVirtual.rangeKey = rangeKey;
  track.replaceChildren();
  for (const entry of visible) {
    track.appendChild(
      entry.type === "shot" ? mountTimelineShotElement(entry, activeShotId) : mountTimelineInsertElement(entry)
    );
  }
  timelineVirtual.activeShotId = activeShotId || null;
  timelineVirtual.activeShotIndex = timelineSelectedBoardIndex(activeShotId);
  if (typeof patchRefSegmentUi === "function") patchRefSegmentUi();
}

function scheduleTimelineViewportRender(activeShotId = state.selectedShotId) {
  if (timelineVirtual.viewportRaf) return;
  timelineVirtual.viewportRaf = requestAnimationFrame(() => {
    timelineVirtual.viewportRaf = 0;
    renderTimelineViewport(activeShotId);
  });
}

function invalidateTimelineLayout() {
  timelineVirtual.layoutKey = "";
  timelineVirtual.layout = null;
  timelineVirtual.rangeKey = "";
  timelineVirtual.activeShotId = null;
  timelineVirtual.activeShotIndex = -1;
}

function scrollTimelineToShot(shotId, behavior = "smooth") {
  if (!shotId || !el.timelineStrip) return;
  const layout = timelineVirtual.layout;
  const entry = layout?.items.find((item) => item.type === "shot" && item.shot.shot_id === shotId);
  if (entry) {
    const targetLeft = Math.max(0, entry.left - 48);
    el.timelineStrip.scrollTo({ left: targetLeft, behavior });
    requestAnimationFrame(() => {
      captureTimelineScroll();
      scheduleTimelineViewportRender(state.selectedShotId);
    });
    return;
  }
  requestAnimationFrame(() => {
    const item = el.timelineStrip.querySelector(`[data-shot-id="${shotId}"]`);
    if (!item) return;
    item.scrollIntoView({ behavior, block: "nearest", inline: "nearest" });
    requestAnimationFrame(() => captureTimelineScroll());
  });
}
