// Backend API client for the Storyboard Tool HTTP service.
//
// All functions here communicate with the FastAPI backend over localhost.
// They read panel.js state globals at call time (projectData, canvasColor,
// canvasWidth, canvasHeight, linkedFromStoryboard) but declare no state of
// their own.
//
// Runtime deps on panel.js globals: loadBridgeCache, populateShotSelect,
//   setSelectedShotId, renderCurrentShotCard, normalizeHexColor,
//   normalizeCanvasSize, updateColorSwatch, detectWorkItemFromDocument,
//   linkedFromStoryboard, projectData, canvasColor, canvasWidth, canvasHeight,
//   currentWorkContext, setWorkContext.

// â”€â”€ Work context state (Part 6) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
// A single mutable slot holding the current active work context.
// Kind is "shot" | "scene2d". panel.js reads this for UI routing.
let _activeWorkContext = null;
const STORYBOARDER_PLUGIN_PROTOCOL = 2;
const STORYBOARDER_PLUGIN_CAPABILITY = "explicit_asset_paths_v2";
let _pluginProtocolContext = null;

function activeWorkContext() {
  return _activeWorkContext;
}

function activeScene2DContext() {
  if (_activeWorkContext?.kind === "scene2d") return _activeWorkContext;
  return null;
}

function activeIsShot() {
  return _activeWorkContext?.kind === "shot";
}

function activeIsScene2D() {
  return _activeWorkContext?.kind === "scene2d";
}

function activeIsUnmatched() {
  return _activeWorkContext?.kind === "unmatched";
}

function setWorkContext(ctx) {
  _activeWorkContext = ctx || null;
}

// Called by panel.js when a focus_request arrives from the live bridge.
// Also called from applyPluginContext() if the backend sends work_context.
function applyWorkContext(ctx) {
  setWorkContext(ctx);
  if (typeof renderWorkModeUI === "function") {
    renderWorkModeUI(ctx);
  }
}

// Per-launch API token published by the backend in the live-bridge JSON
// (see build_payload in live_bridge.py). Sent as X-Storyboarder-Token on
// state-changing API calls so the backend accepts them. Read from the same
// bridge cache the plugin already loads to discover the port.
async function storyboardApiToken() {
  try {
    const cache = await loadBridgeCache();
    return String(cache?.api_token || "");
  } catch {
    return "";
  }
}

function withStoryboardToken(headers, token) {
  const merged = { ...(headers || {}) };
  if (token) {
    merged["X-Storyboarder-Token"] = token;
  }
  return merged;
}

function rememberPluginProtocolContext(context) {
  _pluginProtocolContext = context && typeof context === "object" ? context : null;
}

function pluginProtocolHeaders(path, headers = {}) {
  const merged = { ...(headers || {}) };
  if (!String(path || "").startsWith("/api/plugin/")) {
    return merged;
  }
  merged["X-Storyboarder-Protocol"] = String(STORYBOARDER_PLUGIN_PROTOCOL);
  merged["X-Storyboarder-Capabilities"] = STORYBOARDER_PLUGIN_CAPABILITY;
  const session = String(_pluginProtocolContext?.project_session_id || "");
  const revision = _pluginProtocolContext?.context_revision;
  if (session) {
    merged["X-Storyboarder-Project-Session"] = session;
  }
  if (Number.isInteger(revision)) {
    merged["X-Storyboarder-Context-Revision"] = String(revision);
  }
  return merged;
}

function pluginWriteHeaders(workKey, assetRole, writeIntent) {
  const headers = {};
  if (workKey) headers["X-Storyboarder-Work-Key"] = String(workKey);
  if (assetRole) headers["X-Storyboarder-Asset-Role"] = String(assetRole);
  if (writeIntent) headers["X-Storyboarder-Write-Intent"] = String(writeIntent);
  return headers;
}

function pluginRequiresScopedWrites(context = _pluginProtocolContext) {
  return Boolean(
    isExplicitAssetContext(context) &&
    context?.offline_write_allowed === false,
  );
}

async function pluginHttpError(response) {
  let payload = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  const detail = String(payload?.detail || payload?.message || `HTTP ${response.status}`);
  const error = new Error(detail);
  error.status = response.status;
  error.code = payload?.code || "";
  return error;
}

async function storyboardApiOrigins() {
  const cache = await loadBridgeCache();
  const origins = [];
  if (cache?.bridge_url) {
    try {
      origins.push(new URL(cache.bridge_url).origin);
    } catch {
      // Ignore invalid cached URLs.
    }
  }
  const port = Number(cache?.port || 0);
  if (port > 0) {
    origins.push(`http://127.0.0.1:${port}`);
    origins.push(`http://localhost:${port}`);
  }
  for (const candidate of [8000, 8001, 8002, 8003, 8004]) {
    origins.push(`http://127.0.0.1:${candidate}`);
  }
  return [...new Set(origins)];
}

async function requestStoryboardApi(path, options = {}) {
  const token = await storyboardApiToken();
  let lastError = null;
  for (const origin of await storyboardApiOrigins()) {
    try {
      const response = await fetch(`${origin}${path}`, {
        cache: "no-store",
        ...options,
        headers: withStoryboardToken(
          pluginProtocolHeaders(path, {
            ...(options.body ? { "Content-Type": "application/json" } : {}),
            ...(options.headers || {}),
          }),
          token,
        ),
      });
      if (!response.ok) {
        const error = await pluginHttpError(response);
        lastError = error;
        if (
          String(path || "").startsWith("/api/plugin/") &&
          [400, 403, 409, 426].includes(response.status)
        ) {
          throw error;
        }
        continue;
      }
      return await response.json();
    } catch (error) {
      if (
        String(path || "").startsWith("/api/plugin/") &&
        [400, 403, 409, 426].includes(Number(error?.status || 0))
      ) {
        throw error;
      }
      lastError = error;
      // Try the next origin.
    }
  }
  if (
    String(path || "").startsWith("/api/plugin/") &&
    [400, 403, 409, 426].includes(Number(lastError?.status || 0))
  ) {
    throw lastError;
  }
  return null;
}

function normalizeShotFromBackend(raw = {}) {
  return {
    shot_id: String(raw.shot_id || "").trim().toLowerCase(),
    title: String(raw.title || ""),
    scene: String(raw.scene || ""),
    sequence: String(raw.sequence || ""),
    description: String(raw.description || ""),
    action_note: String(raw.action_note || ""),
    camera_note: String(raw.camera_note || ""),
    character_note: String(raw.character_note || ""),
    dialogue: String(raw.dialogue || ""),
    lighting_note: String(raw.lighting_note || ""),
    transition_note: String(raw.transition_note || ""),
    duration_seconds: Number.parseFloat(raw.duration_seconds || "3") || 3,
    camera_data: raw.camera_data && typeof raw.camera_data === "object" ? raw.camera_data : {},
    tags: Array.isArray(raw.tags) ? raw.tags : [],
    comments: Array.isArray(raw.comments) ? raw.comments : [],
    status: String(raw.status || "Draft"),
    image_path: String(raw.image_path || ""),
    preview_image_path: String(raw.preview_image_path || raw.image_path || ""),
    thumbnail_path: String(raw.thumbnail_path || ""),
    source_file_path: String(raw.source_file_path || ""),
    source_sync_mtime: Number.parseFloat(raw.source_sync_mtime || "0") || 0,
    annotation_path: String(raw.annotation_path || ""),
    reference_image_paths: Array.isArray(raw.reference_image_paths) ? raw.reference_image_paths : [],
    ref_video_path: String(raw.ref_video_path || ""),
    ref_video_time: Number.parseFloat(raw.ref_video_time || "0") || 0,
    ref_segment_time: Number.parseFloat(raw.ref_segment_time || "0") || 0,
    psd_exists: Boolean(raw.psd_exists),
    preview_exists: Boolean(raw.preview_exists),
    thumbnail_exists: Boolean(raw.thumbnail_exists),
    source_path_missing: Boolean(raw.source_path_missing),
    preview_out_of_date: Boolean(raw.preview_out_of_date),
    broken_or_zero_byte_psd: Boolean(raw.broken_or_zero_byte_psd),
    last_exported_preview_time: raw.last_exported_preview_time || null,
    paths: raw.paths && typeof raw.paths === "object" ? raw.paths : {},
    has_board_background: Boolean(raw.has_board_background),
    has_artwork_preview: Boolean(raw.has_artwork_preview),
  };
}

function projectDataFromPluginContext(context) {
  return {
    version: 4,
    name: String(context?.project_name || ""),
    settings: {},
    shots: Array.isArray(context?.shots)
      ? context.shots.map(normalizeShotFromBackend).filter((shot) => shot.shot_id)
      : [],
  };
}

async function requestPluginContext() {
  const payload = await requestStoryboardApi("/api/plugin/context");
  if (payload && Array.isArray(payload.shots)) {
    rememberPluginProtocolContext(payload);
    return payload;
  }
  return null;
}

function applyPluginContext(context) {
  if (!context) {
    return;
  }
  rememberPluginProtocolContext(context);
  if (typeof lastPluginContext !== "undefined") {
    lastPluginContext = context;
  }
  // Cache work_items for human-readable shot label formatting (Part 2).
  if (typeof setWorkItems === "function") {
    setWorkItems(context.work_items);
  }
  projectData = projectDataFromPluginContext(context);
  populateShotSelect();
  if (context.canvas) {
    canvasColor = normalizeHexColor(context.canvas.background_color);
    const size = normalizeCanvasSize(context.canvas.width, context.canvas.height);
    canvasWidth = size.width;
    canvasHeight = size.height;
    updateColorSwatch();
  }

  let hasActiveDocument = false;
  try {
    hasActiveDocument = Boolean(app.activeDocument);
  } catch {
    hasActiveDocument = false;
  }

  if (hasActiveDocument && typeof syncWorkContextFromActiveDocument === "function") {
    syncWorkContextFromActiveDocument(context).catch(() => {});
    renderCurrentShotCard();
    return;
  } else if (context.work_context?.kind) {
    applyWorkContext(context.work_context);
  } else {
    applyWorkContext({ kind: "shot", shot_id: context.selected_shot_id || "" });
  }

  const workCtx = activeWorkContext();
  if (workCtx?.kind === "scene2d") {
    // In scene2d mode the shot selector stays hidden; no shot preselect needed.
    renderCurrentShotCard();
    return;
  }

  const shotId = context.selected_shot_id || "";
  if (shotId) {
    setSelectedShotId(shotId);
  }
  renderCurrentShotCard();
}

async function requestPluginWriteIntent(workKey, assetRole) {
  if (!pluginRequiresScopedWrites()) {
    return null;
  }
  const payload = await requestStoryboardApi("/api/plugin/write-intents", {
    method: "POST",
    body: JSON.stringify({
      work_key: String(workKey || ""),
      asset_role: String(assetRole || ""),
    }),
  });
  if (!payload?.token || !payload?.write_path) {
    throw new Error("Storyboarder did not authorize the project write.");
  }
  return payload;
}

async function notifyPluginPsdSaved(workContext, intent) {
  const ctx = workContext || activeWorkContext();
  if (!ctx?.key) {
    throw new Error("No linked work item is active.");
  }
  const headers = pluginWriteHeaders(ctx.key, "source_psd", intent?.token || "");
  let path = "";
  if (ctx.kind === "shot") {
    path = `/api/plugin/shots/${encodeURIComponent(ctx.shot_id)}/psd-saved`;
  } else if (ctx.kind === "scene2d") {
    path = `/api/plugin/scenes2d/${encodeURIComponent(ctx.scene_id)}/perspectives/${encodeURIComponent(ctx.perspective_id)}/psd-saved`;
  } else {
    throw new Error("The active document is not a writable Storyboarder work item.");
  }
  const payload = await requestStoryboardApi(path, {
    method: "POST",
    headers,
    body: JSON.stringify({
      source_file_path: assetProjectRelativePathForRole(ctx, "source_psd"),
    }),
  });
  if (payload?.context) {
    applyPluginContext(payload.context);
  } else if (payload?.work_context) {
    applyWorkContext(payload.work_context);
  }
  return payload;
}

async function refreshProjectDataFromBackend() {
  const context = await requestPluginContext();
  if (context) {
    applyPluginContext(context);
    return true;
  }
  return false;
}

async function notifyBackendShotFocus(shotId) {
  if (!linkedFromStoryboard || !shotId) {
    return;
  }
  const context = await requestStoryboardApi(`/api/plugin/shots/${encodeURIComponent(shotId)}/focus`, {
    method: "POST",
  });
  if (context?.shots) {
    applyPluginContext(context);
  }
}

async function requestStoryboardAppFocus() {
  await requestStoryboardApi("/api/app/focus", { method: "POST" });
}

// Ask Storyboard Tool to rebuild a Photoshop-unopenable PSD. preserveLayers keeps
// the original layer data (blend modes, opacity, masks) via a psd_tools round-trip;
// false forces a flattened rebuild. Returns the recovery result (or null).
async function requestPsdRecovery(shotId, preserveLayers = true) {
  const query = preserveLayers ? "" : "?preserve_layers=false";
  const token = await storyboardApiToken();
  for (const origin of await storyboardApiOrigins()) {
    try {
      const response = await fetch(`${origin}/api/shots/${shotId}/recover-source${query}`, {
        method: "POST",
        cache: "no-store",
        headers: withStoryboardToken({}, token),
      });
      if (response.ok) {
        const payload = await response.json();
        return payload?.result || payload;
      }
    } catch {
      // Try the next candidate origin.
    }
  }
  return null;
}

async function requestShotSync(shotId, force = true) {
  const query = force ? "?force=true" : "";
  const token = await storyboardApiToken();
  for (const origin of await storyboardApiOrigins()) {
    try {
      const response = await fetch(`${origin}/api/shots/${encodeURIComponent(shotId)}/sync${query}`, {
        method: "POST",
        cache: "no-store",
        headers: withStoryboardToken({}, token),
      });
      if (response.ok) {
        return await response.json();
      }
    } catch {
      // Try the next candidate origin.
    }
  }
  return null;
}

// â”€â”€ Scene 2D API helpers (Part 9 / 10) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

async function requestScene2DPsdSaved(sceneId, perspectiveId, intent = null) {
  const key = `scene2d:${sceneId}:${perspectiveId}`;
  return requestStoryboardApi(
    `/api/plugin/scenes2d/${encodeURIComponent(sceneId)}/perspectives/${encodeURIComponent(perspectiveId)}/psd-saved`,
    {
      method: "POST",
      headers: pluginWriteHeaders(key, "source_psd", intent?.token || ""),
    }
  );
}

async function requestScene2DFocus(sceneId, perspectiveId) {
  return requestStoryboardApi(
    `/api/project/scenes2d/${encodeURIComponent(sceneId)}/perspectives/${encodeURIComponent(perspectiveId)}/open`,
    { method: "POST" }
  );
}

async function requestScene2DNextPerspective(sceneId, perspectiveId) {
  return requestStoryboardApi(
    `/api/plugin/scenes2d/${encodeURIComponent(sceneId)}/perspectives/${encodeURIComponent(perspectiveId)}/next-perspective`,
    { method: "POST" }
  );
}

// Populate the perspective <select> in the Work panel with all PSD perspectives
// from work_items (provided in the plugin context payload).
function populatePerspectiveSelect(workItems, activeSceneId) {
  const sel = document.getElementById("perspectiveSelect");
  if (!sel) return;
  sel.innerHTML = "";

  const sceneItems = typeof scene2DPerspectiveOptions === "function"
    ? scene2DPerspectiveOptions(workItems, activeSceneId)
    : (workItems || []).filter((item) => item.kind === "scene2d" && item.scene_id === activeSceneId);

  for (const item of sceneItems) {
    const opt = document.createElement("option");
    opt.value = item.key || `scene2d:${item.scene_id}:${item.perspective_id}`;
    opt.textContent = item.perspective_title || item.perspective_id || "Perspective";
    opt.dataset.perspectiveType = item.perspective_type || "psd";
    sel.appendChild(opt);
  }

  const ctx = activeScene2DContext();
  if (ctx) {
    const key = `scene2d:${ctx.scene_id}:${ctx.perspective_id}`;
    sel.value = key;
  }
}
