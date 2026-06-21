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
  });
})(typeof globalThis !== "undefined" ? globalThis : this);
