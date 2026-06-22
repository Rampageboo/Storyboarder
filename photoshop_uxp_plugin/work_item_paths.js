(function attachWorkItemPathHelpers(global) {
  function normalizeNativePath(value) {
    let path = String(value || "").trim();
    if (!path) return "";
    if (/^file:\/\//i.test(path)) {
      try {
        path = decodeURIComponent(new URL(path).pathname || "");
        if (/^\/[A-Za-z]:\//.test(path)) path = path.slice(1);
      } catch {
        path = path.replace(/^file:\/+/i, "");
      }
    }
    path = path.replace(/\\/g, "/").replace(/\/+/g, "/");
    path = path.replace(/\/$/, "");
    if (/^[A-Za-z]:\//.test(path)) {
      path = `${path[0].toLowerCase()}${path.slice(1)}`;
    }
    return path;
  }

  function sameNativePath(left, right) {
    const a = normalizeNativePath(left);
    const b = normalizeNativePath(right);
    return Boolean(a && b && a === b);
  }

  function nativePathFromEntryLike(value) {
    if (!value) return "";
    if (typeof value === "string") return value;
    return String(value.nativePath || value.fsName || value.path || "");
  }

  function projectRelativeNativePath(context, relPath, fallbackRoot = "") {
    const root = String(context?.project_root || fallbackRoot || "").trim();
    const rel = String(relPath || "").trim();
    if (!root || !rel) return "";
    return `${root.replace(/[\\/]+$/, "")}/${rel.replace(/^[\\/]+/, "")}`;
  }

  function workContextFromItem(item) {
    if (!item) return null;
    return {
      kind: item.kind,
      key: item.key || (item.kind === "shot" ? `shot:${item.shot_id}` : `scene2d:${item.scene_id}:${item.perspective_id}`),
      shot_id: item.shot_id || "",
      scene_id: item.scene_id || "",
      perspective_id: item.perspective_id || "",
      scene_title: item.scene_title || "",
      perspective_title: item.perspective_title || "",
      perspective_type: item.perspective_type || "psd",
      label: item.label || "",
      source_file_path: item.source_file_path || "",
      source_native_path: item.source_native_path || "",
      preview_image_path: item.preview_image_path || "",
      index: item.index,
      count: item.count,
      previous_key: item.previous_key || "",
      next_key: item.next_key || "",
    };
  }

  function findWorkItemByNativePath(nativePath, context, fallbackRoot = "") {
    if (!nativePath) return null;
    const items = Array.isArray(context?.work_items) ? context.work_items : [];
    for (const item of items) {
      if (sameNativePath(nativePath, item.source_native_path)) return item;
      if (sameNativePath(nativePath, projectRelativeNativePath(context, item.source_file_path, fallbackRoot))) return item;
    }
    return null;
  }

  function deriveActiveWorkKey(workContext) {
    return String(workContext?.key || "");
  }

  function filterKnownOpenWorkKeys(keys, knownKeys) {
    const known = new Set(knownKeys || []);
    const seen = new Set();
    const accepted = [];
    for (const raw of Array.isArray(keys) ? keys : []) {
      const key = String(raw || "").trim();
      if (known.has(key) && !seen.has(key)) {
        accepted.push(key);
        seen.add(key);
      }
    }
    return accepted;
  }

  function displayPerspectiveIndex(index, count) {
    return `${index ?? "?"} / ${count ?? "?"}`;
  }

  function scene2DPerspectiveOptions(workItems, activeSceneId) {
    const sceneId = String(activeSceneId || "");
    return (Array.isArray(workItems) ? workItems : [])
      .filter((item) => item?.kind === "scene2d" && String(item.scene_id || "") === sceneId)
      .map((item) => ({
        key: item.key || `scene2d:${item.scene_id}:${item.perspective_id}`,
        scene_id: item.scene_id || "",
        perspective_id: item.perspective_id || "",
        scene_title: item.scene_title || "",
        perspective_title: item.perspective_title || item.perspective_id || "Perspective",
        perspective_type: item.perspective_type || "psd",
      }));
  }

  function shouldPreserveManualMode(mode) {
    return mode === "manual-project" || mode === "manual-folder";
  }

  // ── Work-item list cache & shot label formatting (Part 2) ────────────────────

  let _workItems = [];

  function getWorkItems() {
    return _workItems;
  }

  function setWorkItems(items) {
    _workItems = Array.isArray(items) ? items : [];
  }

  /**
   * Format a shot work item into a compact human-readable label. Never exposes a UUID.
   * Requires index > 0 to use the numeric prefix; otherwise falls back to title or "Shot".
   * Examples: { index: 1,  shot_title: "Copy" } → "1. Copy"
   *           { index: 16, shot_title: "" }     → "16. Untitled shot"
   *           { index: 0,  shot_title: "Title"} → "Title"
   *           { index: 0,  shot_title: "" }     → "Shot"
   */
  function formatShotDisplayLabel(item) {
    const index = Number(item?.index);
    const title = String(item?.shot_title || "").trim();
    if (Number.isInteger(index) && index > 0) {
      return title ? `${index}. ${title}` : `${index}. Untitled shot`;
    }
    return title || "Shot";
  }

  /** Return the shot work item for a given shot_id, or null. */
  function shotWorkItemById(shotId) {
    const id = String(shotId || "").toLowerCase();
    return _workItems.find((item) => item.kind === "shot" && item.shot_id === id) || null;
  }

  /**
   * Compact display label for a shot, using work items when available.
   * arrayIndexFallback must be >= 0 to produce a numbered label; -1 or null yields title-only.
   */
  function shotDisplayLabel(shotId, arrayIndexFallback, titleFallback) {
    const item = shotWorkItemById(shotId);
    if (item) return formatShotDisplayLabel(item);
    const rawIndex = Number(arrayIndexFallback);
    const displayIndex = Number.isInteger(rawIndex) && rawIndex >= 0 ? rawIndex + 1 : null;
    const title = String(titleFallback || "").trim();
    if (displayIndex !== null) {
      return title ? `${displayIndex}. ${title}` : `${displayIndex}. Untitled shot`;
    }
    return title || "Shot";
  }

  /**
   * Verbose human-readable label for user-facing error and status messages.
   * Priority: 1) backend work-item data  2) projectShots array  3) generic "Shot".
   * Never exposes a raw UUID.
   * Examples: (work item with index=4, title="Look at the moon") → "Shot 4 · Look at the moon"
   *           (work item with index=16, no title)                → "Shot 16"
   *           (no work item or project entry)                    → "Shot"
   */
  function humanReadableShotLabel(shotId, projectShots) {
    const item = shotWorkItemById(shotId);
    if (item) {
      const index = Number(item.index);
      const title = String(item.shot_title || "").trim();
      if (Number.isInteger(index) && index > 0) {
        return title ? `Shot ${index} · ${title}` : `Shot ${index}`;
      }
      return title ? `Shot · ${title}` : "Shot";
    }
    const shots = Array.isArray(projectShots) ? projectShots : [];
    const idx = shots.findIndex(
      (s) => String(s?.shot_id || "").toLowerCase() === String(shotId || "").toLowerCase()
    );
    if (idx >= 0) {
      const displayIndex = idx + 1;
      const title = String(shots[idx]?.title || "").trim();
      return title ? `Shot ${displayIndex} · ${title}` : `Shot ${displayIndex}`;
    }
    return "Shot";
  }

  Object.assign(global, {
    normalizeNativePath,
    sameNativePath,
    nativePathFromEntryLike,
    projectRelativeNativePath,
    workContextFromItem,
    findWorkItemByNativePath,
    deriveActiveWorkKey,
    filterKnownOpenWorkKeys,
    displayPerspectiveIndex,
    scene2DPerspectiveOptions,
    shouldPreserveManualMode,
    getWorkItems,
    setWorkItems,
    formatShotDisplayLabel,
    shotWorkItemById,
    shotDisplayLabel,
    humanReadableShotLabel,
  });
})(typeof globalThis !== "undefined" ? globalThis : this);
