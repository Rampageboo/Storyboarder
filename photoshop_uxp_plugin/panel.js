const photoshop = require("photoshop");
const fs = require("uxp").storage.localFileSystem;

const app = photoshop.app;
const DEFAULT_CANVAS_COLOR = "#E8E8E8";
const DEFAULT_CANVAS_WIDTH = 1920;
const DEFAULT_CANVAS_HEIGHT = 1080;
const SHARED_BRIDGE_PATH = "C:/Users/Public/StoryboardTool/storyboard_live_bridge.json";
const SHARED_HEARTBEAT_PATH = "C:/Users/Public/StoryboardTool/storyboard_plugin_heartbeat.json";
const SB_POLL_MS = 1500;
const BRIDGE_CACHE_FILE = "storyboard_bridge_cache.json";
const PLUGIN_SETTINGS_FILE = "storyboard_plugin_settings.json";
const BRIDGE_STALE_MS = 8000;
const QUICK_STATUS_OPTIONS = ["Draft", "In Progress", "Review", "Approved"];
const SHOT_CSV_COLUMNS = [
  "order",
  "shot_id",
  "title",
  "scene",
  "sequence",
  "description",
  "action_note",
  "camera_note",
  "character_note",
  "dialogue",
  "lighting_note",
  "transition_note",
  "duration_seconds",
  "status",
  "image_path",
  "preview_image_path",
  "thumbnail_path",
  "source_file_path",
  "source_sync_mtime",
  "annotation_path",
  "camera_data",
  "tags",
  "comments",
  "reference_image_paths",
];
const JSON_CSV_COLUMNS = new Set(["camera_data", "tags", "comments", "reference_image_paths"]);

let projectRoot = null;
let projectData = null;
let shotFolder = null;
let canvasColor = DEFAULT_CANVAS_COLOR;
let canvasWidth = DEFAULT_CANVAS_WIDTH;
let canvasHeight = DEFAULT_CANVAS_HEIGHT;
let linkedFromStoryboard = false;
let lastBridgeSignature = "";
let linkedProjectRootPath = "";
let bridgePollTimer = null;
let backgroundSyncTimer = null;
let backgroundSyncInFlight = false;
let activeDocWatchTimer = null;
let lastActiveDocKey = "";
let lastFocusToken = 0;
let focusBaselineSet = false;
let focusSwitchInFlight = false;
let focusStoryboardAfterPreviewExport = false;
const boardBackgroundSigByShot = new Map();

function $(id) {
  return document.getElementById(id);
}

function init() {
  $("chooseProject").addEventListener("click", () => runPanelAction(chooseProjectFolder));
  $("chooseFolder").addEventListener("click", () => runPanelAction(chooseShotFolder));
  $("shotSelect").addEventListener("change", () => runPanelAction(switchToSelectedShot));
  $("openShot").addEventListener("click", () => runPanelAction(switchToSelectedShot));
  $("focusCurrentTab")?.addEventListener("click", () => runPanelAction(focusCurrentShotTab));
  $("ensureTemplateLayers")?.addEventListener("click", () => runPanelAction(ensureTemplateLayersForActiveDocument));
  $("quickStatusButtons")?.addEventListener("click", (event) => {
    const button = event.target?.closest?.("[data-status]");
    if (button) {
      runPanelAction(() => updateShotStatusViaBackend(button.getAttribute("data-status"))).catch(() => {});
    }
  });
  $("addQuickNote")?.addEventListener("click", () => runPanelAction(addQuickNoteViaBackend));
  $("previousShot")?.addEventListener("click", () => runPanelAction(goToPreviousShot));
  $("nextShot")?.addEventListener("click", () => runPanelAction(goToNextShot));
  $("overlayPrevious").addEventListener("click", () => runPanelAction(overlayPreviousShots));
  $("overlayNext")?.addEventListener("click", () => runPanelAction(overlayNextShots));
  $("clearOverlay").addEventListener("click", () => runPanelAction(clearOverlayLayers));
  $("overlayCount")?.addEventListener("change", () => clampOverlayCountInput());
  $("overlayCount")?.addEventListener("input", () => clampOverlayCountInput());
  $("overlayOpacity")?.addEventListener("change", () => clampOverlayOpacityInput());
  $("overlayOpacity")?.addEventListener("input", () => clampOverlayOpacityInput());
  $("applyBackground").addEventListener("click", () => runPanelAction(applyCanvasBackground));
  $("saveAndStay").addEventListener("click", () => runPanelAction(saveCurrentShot));
  $("saveAndNext").addEventListener("click", () => runPanelAction(saveAndGoNext));
  $("focusStoryboardAfterExport")?.addEventListener("change", () => runPanelAction(updateFocusStoryboardAfterExportSetting));
  $("recoverPsd")?.addEventListener("click", () => runPanelAction(recoverCurrentShotPsd));
  $("relinkNow").addEventListener("click", () => runPanelAction(reconnectStoryboardBridge));
  setLinkedUi(false);
  setLinkStatus("Connecting…", true);
  startStoryboardBridgePolling();
  registerDocumentBackgroundListeners();
  startActiveDocumentWatch();
  scheduleBackgroundSyncForActiveDocument();
  updateCurrentShotIndicator();
  renderCurrentShotCard();
  loadPluginSettings().catch(() => {});
}

function setLinkedUi(linked) {
  const linkedPanel = $("linkedPanel");
  const unlinkedPanel = $("unlinkedPanel");
  const colorSection = $("colorSection");
  if (linkedPanel) linkedPanel.hidden = !linked;
  if (unlinkedPanel) unlinkedPanel.hidden = linked;
  if (colorSection) colorSection.hidden = linked;
}

async function runPanelAction(action) {
  try {
    await action();
  } catch (error) {
    setStatus(error.message || String(error));
  }
}

async function chooseProjectFolder() {
  const folder = await fs.getFolder();
  try {
    await folder.getEntry("project.json");
  } catch {
    throw new Error("Choose the Storyboard_Project folder that contains project.json.");
  }
  projectRoot = folder;
  projectData = await loadProjectJson();
  $("projectLabel").textContent = `Project: ${folder.nativePath || folder.name}`;
  canvasColor = await readProjectCanvasColor(folder);
  updateColorSwatch();
  populateShotSelect();
  const detected = detectShotFromDocument();
  if (detected) {
    setSelectedShotId(detected);
  } else if (projectData.shots.length) {
    setSelectedShotId(projectData.shots[0].shot_id);
  }
  linkedFromStoryboard = false;
  setLinkedUi(false);
  setLinkStatus("Manual project", true);
  setStatus(`Project loaded (${projectData.shots.length} shots).`);
  if (app.activeDocument) {
    scheduleBackgroundSyncForActiveDocument();
  }
  updateCurrentShotIndicator();
}

async function chooseShotFolder() {
  shotFolder = await fs.getFolder();
  $("folderLabel").textContent = `Folder: ${shotFolder.nativePath || shotFolder.name}`;
  const folderName = shotFolder.name || "";
  if (isValidShotId(folderName)) {
    setSelectedShotId(folderName);
  }
  const root = await findProjectRoot(shotFolder);
  if (root) {
    projectRoot = root;
    projectData = await loadProjectJson();
    $("projectLabel").textContent = `Project: ${root.nativePath || root.name}`;
    populateShotSelect();
  }
  canvasColor = await readProjectCanvasColor(shotFolder);
  updateColorSwatch();
  linkedFromStoryboard = false;
  setLinkedUi(false);
  setLinkStatus("Manual folder", true);
  setStatus(`Shot folder selected.`);
  if (app.activeDocument) {
    scheduleBackgroundSyncForActiveDocument();
  }
  updateCurrentShotIndicator();
}

function startStoryboardBridgePolling() {
  stopStoryboardBridgePolling();
  pollStoryboardBridge().catch(() => {});
  bridgePollTimer = setInterval(() => {
    pollStoryboardBridge().catch(() => {});
  }, SB_POLL_MS);
}

function stopStoryboardBridgePolling() {
  if (bridgePollTimer) {
    clearInterval(bridgePollTimer);
    bridgePollTimer = null;
  }
}

function setLinkStatus(message, waiting = false) {
  const node = $("linkStatus");
  if (!node) return;
  node.textContent = message;
  node.classList.toggle("waiting", waiting);
}

function pathToFileUrl(nativePath) {
  const path = String(nativePath || "").trim().replace(/\\/g, "/");
  if (!path) return "";
  if (path.startsWith("file:")) return path;
  if (/^[A-Za-z]:\//.test(path)) return `file:///${path}`;
  return `file://${path.startsWith("/") ? "" : "/"}${path}`;
}

async function resolveFolderEntry(nativePath) {
  const path = String(nativePath || "").trim();
  if (!path) return null;
  try {
    return await fs.getEntryWithUrl(pathToFileUrl(path));
  } catch {
    return null;
  }
}

function bridgeUrlsFromLive(live) {
  const urls = [];
  if (live?.bridge_url) urls.push(live.bridge_url);
  const port = Number(live?.port || 0);
  if (port > 0) {
    urls.push(`http://127.0.0.1:${port}/api/bridge/live`);
    urls.push(`http://localhost:${port}/api/bridge/live`);
  }
  for (const port of [8000, 8001, 8002, 8003, 8004]) {
    urls.push(`http://127.0.0.1:${port}/api/bridge/live`);
  }
  return [...new Set(urls)];
}

function isLiveBridgeFresh(live) {
  if (!live?.updated_at) return false;
  const updated = Date.parse(live.updated_at);
  if (Number.isNaN(updated)) return true;
  return Date.now() - updated <= BRIDGE_STALE_MS;
}

async function fetchLiveBridgeHttp(seedLive) {
  const cache = await loadBridgeCache();
  const urls = [
    ...bridgeUrlsFromLive(seedLive),
    ...bridgeUrlsFromLive(cache),
  ];
  let lastError = null;
  for (const url of [...new Set(urls)]) {
    try {
      const response = await fetch(url, { cache: "no-store" });
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      const live = await response.json();
      await cacheBridgeEndpoints(live, url);
      return live;
    } catch (error) {
      lastError = error;
    }
  }
  throw lastError || new Error("Storyboard HTTP bridge unavailable");
}

async function fetchLiveBridgeFiles() {
  const cache = await loadBridgeCache();
  const candidates = [
    SHARED_BRIDGE_PATH,
    cache?.shared_bridge_path,
    cache?.global_bridge_path,
    cache?.project_bridge_path,
  ].filter(Boolean);
  for (const nativePath of candidates) {
    const live = await readLiveBridgeFile(nativePath);
    if (live && isLiveBridgeFresh(live)) {
      return live;
    }
  }
  return null;
}

async function readLiveBridgeFile(nativePath) {
  try {
    const entry = await fs.getEntryWithUrl(pathToFileUrl(nativePath));
    const text = await readEntryText(entry);
    const live = JSON.parse(text);
    return live && typeof live === "object" ? live : null;
  } catch {
    return null;
  }
}

async function loadBridgeCache() {
  try {
    const dataFolder = await fs.getDataFolder();
    const entry = await dataFolder.getEntry(BRIDGE_CACHE_FILE);
    return JSON.parse(await readEntryText(entry));
  } catch {
    return null;
  }
}

async function loadPluginSettings() {
  try {
    const dataFolder = await fs.getDataFolder();
    const entry = await dataFolder.getEntry(PLUGIN_SETTINGS_FILE);
    const settings = JSON.parse(await readEntryText(entry));
    focusStoryboardAfterPreviewExport = Boolean(settings?.focus_storyboard_after_preview_export);
  } catch {
    focusStoryboardAfterPreviewExport = false;
  }
  const checkbox = $("focusStoryboardAfterExport");
  if (checkbox) checkbox.checked = focusStoryboardAfterPreviewExport;
}

async function savePluginSettings() {
  const dataFolder = await fs.getDataFolder();
  const file = await dataFolder.createFile(PLUGIN_SETTINGS_FILE, { overwrite: true });
  await writeEntryText(
    file,
    JSON.stringify(
      {
        focus_storyboard_after_preview_export: focusStoryboardAfterPreviewExport,
      },
      null,
      2,
    ),
  );
}

async function updateFocusStoryboardAfterExportSetting() {
  const checkbox = $("focusStoryboardAfterExport");
  focusStoryboardAfterPreviewExport = Boolean(checkbox?.checked);
  await savePluginSettings();
}

async function maybeFocusStoryboardAfterPreviewExport() {
  if (!focusStoryboardAfterPreviewExport) return;
  try {
    if (typeof requestStoryboardAppFocus === "function") {
      await requestStoryboardAppFocus();
    }
  } catch {
    // Focusing Storyboarder is best-effort; export success must not depend on it.
  }
}

async function focusStoryboardAfterPreviewExportIfEnabled() {
  maybeFocusStoryboardAfterPreviewExport().catch(() => {});
}

async function cacheBridgeEndpoints(live, sourceUrl) {
  try {
    const dataFolder = await fs.getDataFolder();
    const file = await dataFolder.createFile(BRIDGE_CACHE_FILE, { overwrite: true });
    const payload = {
      bridge_url: live.bridge_url || sourceUrl,
      port: live.port || 0,
      shared_bridge_path: live.shared_bridge_path || SHARED_BRIDGE_PATH,
      global_bridge_path: live.global_bridge_path || "",
      project_bridge_path: live.project_root
        ? `${String(live.project_root).replace(/\\/g, "/")}/storyboard_live_bridge.json`
        : "",
      cached_at: new Date().toISOString(),
    };
    await writeEntryText(file, JSON.stringify(payload, null, 2));
  } catch {
    // Cache is optional.
  }
}

async function ensureSharedBridgeDir() {
  try {
    return await fs.getEntryWithUrl(pathToFileUrl("C:/Users/Public/StoryboardTool"));
  } catch {
    const publicRoot = await fs.getEntryWithUrl(pathToFileUrl("C:/Users/Public"));
    return publicRoot.createFolder("StoryboardTool");
  }
}

async function sendPluginHeartbeat(live) {
  const openShotIds = getOpenShotIds();
  const selectedShotId = detectShotFromDocument() || live?.selected_shot_id || "";
  const payload = JSON.stringify({
    at: new Date().toISOString(),
    plugin: "storyboard-bridge",
    project_root: live?.project_root || "",
    selected_shot_id: selectedShotId,
    open_shot_ids: openShotIds,
  });
  try {
    const dir = await ensureSharedBridgeDir();
    const file = await dir.createFile("storyboard_plugin_heartbeat.json", { overwrite: true });
    await writeEntryText(file, payload);
    return;
  } catch {
    // Fall back to HTTP heartbeat when available.
  }
  const port = Number(live?.port || 0);
  const urls = [];
  if (port > 0) {
    urls.push(`http://127.0.0.1:${port}/api/plugin/heartbeat`);
    urls.push(`http://localhost:${port}/api/plugin/heartbeat`);
    urls.push(`http://127.0.0.1:${port}/api/bridge/plugin-heartbeat`);
    urls.push(`http://localhost:${port}/api/bridge/plugin-heartbeat`);
  }
  const body = JSON.stringify({ open_shot_ids: openShotIds, selected_shot_id: selectedShotId });
  for (const url of urls) {
    try {
      await fetch(url, {
        method: "POST",
        cache: "no-store",
        headers: { "Content-Type": "application/json" },
        body,
      });
      return;
    } catch {
      // Try the next endpoint.
    }
  }
}

async function reconnectStoryboardBridge() {
  lastBridgeSignature = "";
  await pollStoryboardBridge();
  if (linkedFromStoryboard) {
    setStatus("Reconnected to Storyboard Tool.");
    return;
  }
  throw new Error("Still not linked. Start Storyboard Tool, open a project, then click Ps Link.");
}

async function pollStoryboardBridge() {
  let live = await fetchLiveBridgeFiles();
  if (!live) {
    try {
      live = await fetchLiveBridgeHttp();
    } catch {
      live = null;
    }
  }

  if (!live) {
    linkedFromStoryboard = false;
    setLinkedUi(false);
    setLinkStatus("Not connected", true);
    return;
  }

  if (!live.app_running) {
    setLinkedUi(false);
    setLinkStatus("Storyboard not running", true);
    return;
  }
  if (!live.connected) {
    linkedFromStoryboard = false;
    setLinkedUi(false);
    setLinkStatus("Open a project in Storyboard", true);
    return;
  }

  await cacheBridgeEndpoints(live, live.bridge_url || "");
  await sendPluginHeartbeat(live);
  await applyLiveBridge(live);
}

async function applyLiveBridge(live) {
  const context = await requestPluginContext();
  const signature = [
    live.updated_at,
    live.project_root,
    live.selected_shot_id,
    live.canvas_background_color,
    live.canvas_width,
    live.canvas_height,
    live.shot_count,
  ].join("|");
  const isSame = signature === lastBridgeSignature;
  lastBridgeSignature = signature;
  linkedFromStoryboard = true;

  const root = await resolveFolderEntry(live.project_root);
  if (!root) {
    setLinkedUi(false);
    setLinkStatus("Folder access failed — use Advanced", true);
    if (context) {
      applyPluginContext(context);
      return;
    }
    canvasColor = normalizeHexColor(live.canvas_background_color);
    const fallbackSize = normalizeCanvasSize(live.canvas_width, live.canvas_height);
    canvasWidth = fallbackSize.width;
    canvasHeight = fallbackSize.height;
    updateColorSwatch();
    return;
  }

  setLinkedUi(true);

  if (!isSame || linkedProjectRootPath !== live.project_root) {
    linkedProjectRootPath = live.project_root;
    projectRoot = root;
    if (context) {
      applyPluginContext(context);
    } else {
      projectData = await loadProjectJson();
      populateShotSelect();
    }
  } else if (context) {
    applyPluginContext(context);
  }

  // Prefer the shot the artist is actually editing (the active Photoshop tab) so
  // picking a shot in the panel — which opens it — sticks, instead of being reset
  // to Storyboard Tool's selection on the next poll. Fall back to ST's selection
  // only when no shot document is open.
  const shotId = detectShotFromDocument() || live.selected_shot_id;
  if (shotId) {
    setSelectedShotId(shotId);
    shotFolder = await getShotFolderEntry(shotId);
  }

  const nextColor = normalizeHexColor(context?.canvas?.background_color || live.canvas_background_color);
  const colorChanged = nextColor !== canvasColor;
  canvasColor = nextColor;
  const nextSize = normalizeCanvasSize(
    context?.canvas?.width || live.canvas_width || canvasWidth,
    context?.canvas?.height || live.canvas_height || canvasHeight,
  );
  canvasWidth = nextSize.width;
  canvasHeight = nextSize.height;
  updateColorSwatch();

  if (colorChanged && app.activeDocument && isAutoApplyColorEnabled()) {
    await applyCanvasBackground();
  }

  const label = shotId || live.project_name || "project";
  setLinkStatus(`Linked · ${label}`);
  if (!isSame && shotId) {
    setStatus(`Synced: ${shotId}`);
  }

  if (shotId && app.activeDocument && detectShotFromDocument() === shotId) {
    scheduleBackgroundSyncForActiveDocument();
  }

  await maybeHandleFocusRequest(live);

  // Project data may have just loaded; refresh the label so it can show titles.
  updateCurrentShotIndicator();
}

// Storyboard Tool sets a focus request (shot_id + monotonic token) when the user
// asks to open a shot that is already a tab in Photoshop. Acting only on a new
// token — and adopting the current token as a baseline on first sight — means
// passive polls never yank tabs and stale requests are not replayed on reload.
async function maybeHandleFocusRequest(live) {
  const request = live?.focus_request;
  const token = Number(request?.token || 0);
  if (!focusBaselineSet) {
    focusBaselineSet = true;
    lastFocusToken = token;
    return;
  }
  if (token === lastFocusToken || focusSwitchInFlight) {
    return;
  }
  lastFocusToken = token;
  const shotId = String(request?.shot_id || "").trim().toLowerCase();
  if (!shotId) {
    return;
  }
  focusSwitchInFlight = true;
  try {
    await switchToShot(shotId);
    setStatus(`Switched to ${shotId} (already open).`);
  } catch (error) {
    setStatus(error.message || String(error));
  } finally {
    focusSwitchInFlight = false;
  }
}

function isAutoApplyColorEnabled() {
  const checkbox = $("autoApplyColor");
  return !checkbox || checkbox.checked !== false;
}

async function loadProjectJson() {
  requireProjectRoot();
  const entry = await projectRoot.getEntry("project.json");
  const text = await readEntryText(entry);
  const data = JSON.parse(text);
  const csvShots = await loadShotsCsv();
  if (csvShots) {
    data.shots = csvShots;
    data.version = data.version || 3;
    return data;
  }
  if (!Array.isArray(data.shots)) {
    throw new Error("Invalid project: missing shots.csv and shots list in project.json.");
  }
  return data;
}

async function loadShotsCsv() {
  requireProjectRoot();
  try {
    const entry = await projectRoot.getEntry("shots.csv");
    const text = await readEntryText(entry);
    return parseShotsCsv(text);
  } catch {
    return null;
  }
}

async function saveProjectJson() {
  requireProjectRoot();
  const entry = await projectRoot.getEntry("project.json");
  const payload = {
    version: projectData.version || 3,
  };
  await writeEntryText(entry, JSON.stringify(payload, null, 2));
  await saveShotsCsv(projectData.shots || []);
}

async function saveShotsCsv(shots) {
  requireProjectRoot();
  let entry;
  try {
    entry = await projectRoot.getEntry("shots.csv");
  } catch {
    entry = await projectRoot.createFile("shots.csv", { overwrite: true });
  }
  await writeEntryText(entry, shotsToCsv(shots));
}

function parseShotsCsv(text) {
  const lines = String(text || "")
    .replace(/\r\n/g, "\n")
    .split("\n")
    .filter((line) => line.trim());
  if (!lines.length) {
    return [];
  }
  const headers = parseCsvRow(lines[0]);
  const shots = [];
  for (let lineIndex = 1; lineIndex < lines.length; lineIndex += 1) {
    const values = parseCsvRow(lines[lineIndex]);
    const row = {};
    headers.forEach((header, index) => {
      row[header] = values[index] || "";
    });
    const shot = shotFromCsvRow(row, lineIndex);
    if (shot.shot_id) {
      const { _order, _row, ...record } = shot;
      shots.push(record);
    }
  }
  return shots;
}

function shotsToCsv(shots) {
  const lines = [SHOT_CSV_COLUMNS.join(",")];
  shots.forEach((shot, index) => {
    const row = shotToCsvRow(shot, index + 1);
    lines.push(SHOT_CSV_COLUMNS.map((column) => escapeCsvCell(row[column] ?? "")).join(","));
  });
  return `${lines.join("\n")}\n`;
}

function shotFromCsvRow(row, rowIndex) {
  const order = Number.parseInt(String(row.order || ""), 10);
  return {
    _order: Number.isFinite(order) && order > 0 ? order : rowIndex,
    _row: rowIndex,
    shot_id: String(row.shot_id || "").trim(),
    title: row.title || "",
    scene: row.scene || "",
    sequence: row.sequence || "",
    description: row.description || "",
    action_note: row.action_note || "",
    camera_note: row.camera_note || "",
    character_note: row.character_note || "",
    dialogue: row.dialogue || "",
    lighting_note: row.lighting_note || "",
    transition_note: row.transition_note || "",
    duration_seconds: Number.parseFloat(row.duration_seconds || "3") || 3,
    camera_data: readJsonCsvCell(row.camera_data, {}),
    tags: readJsonCsvCell(row.tags, []),
    comments: readJsonCsvCell(row.comments, []),
    status: row.status || "Draft",
    image_path: row.image_path || "",
    preview_image_path: row.preview_image_path || "",
    thumbnail_path: row.thumbnail_path || "",
    source_file_path: row.source_file_path || "",
    source_sync_mtime: Number.parseFloat(row.source_sync_mtime || "0") || 0,
    annotation_path: row.annotation_path || "",
    reference_image_paths: readJsonCsvCell(row.reference_image_paths, []),
  };
}

function shotToCsvRow(shot, order) {
  const row = { order: String(order) };
  for (const column of SHOT_CSV_COLUMNS) {
    if (column === "order") {
      continue;
    }
    const value = shot[column];
    if (JSON_CSV_COLUMNS.has(column)) {
      row[column] = JSON.stringify(value ?? (column === "camera_data" ? {} : []));
    } else {
      row[column] = value == null ? "" : String(value);
    }
  }
  return row;
}

function readJsonCsvCell(raw, fallback) {
  const text = String(raw || "").trim();
  if (!text) {
    return fallback;
  }
  try {
    return JSON.parse(text);
  } catch {
    if (Array.isArray(fallback) && text) {
      return text.split(",").map((item) => item.trim()).filter(Boolean);
    }
    return fallback;
  }
}

function parseCsvRow(line) {
  const values = [];
  let current = "";
  let inQuotes = false;
  for (let index = 0; index < line.length; index += 1) {
    const char = line[index];
    if (inQuotes) {
      if (char === '"') {
        if (line[index + 1] === '"') {
          current += '"';
          index += 1;
        } else {
          inQuotes = false;
        }
      } else {
        current += char;
      }
    } else if (char === '"') {
      inQuotes = true;
    } else if (char === ",") {
      values.push(current);
      current = "";
    } else {
      current += char;
    }
  }
  values.push(current);
  return values;
}

function escapeCsvCell(value) {
  const text = value == null ? "" : String(value);
  if (/[",\n\r]/.test(text)) {
    return `"${text.replace(/"/g, '""')}"`;
  }
  return text;
}

function shotOptionLabel(shot, index) {
  const order = index + 1;
  const title = String(shot?.title || "").trim();
  return title ? `${order}. ${title}` : `${order}. ${formatShotIdLabel(shot.shot_id)}`;
}

function populateShotSelect() {
  const select = $("shotSelect");
  if (!select) {
    return;
  }
  const shots = projectData?.shots || [];
  const signature = shots.map((shot) => shot.shot_id).join("|");
  if (select.getAttribute("data-shots-sig") === signature && select.options.length === shots.length) {
    // Same shot list — refresh labels (titles/order may have changed) without
    // rebuilding, so the user's current selection is never reset out from under
    // them on the next bridge poll.
    shots.forEach((shot, index) => {
      if (select.options[index]) {
        select.options[index].textContent = shotOptionLabel(shot, index);
      }
    });
  } else {
    const previous = select.value;
    select.innerHTML = "";
    shots.forEach((shot, index) => {
      const option = document.createElement("option");
      option.value = shot.shot_id;
      option.textContent = shotOptionLabel(shot, index);
      select.appendChild(option);
    });
    select.setAttribute("data-shots-sig", signature);
    if (previous && shots.some((shot) => shot.shot_id === previous)) {
      select.value = previous;
    }
  }
  updateOverlayCountLimits();
}

function setSelectedShotId(shotId) {
  $("shotId").value = shotId;
  const select = $("shotSelect");
  if (select) {
    select.value = shotId;
  }
  updateOverlayCountLimits();
  renderCurrentShotCard();
}

function currentShotIndex() {
  const shotId = String($("shotId").value || $("shotSelect").value || "").trim().toLowerCase();
  return (projectData?.shots || []).findIndex((shot) => shot.shot_id === shotId);
}

function updateOverlayCountLimits() {
  const input = $("overlayCount");
  if (!input) {
    return;
  }
  const shots = projectData?.shots || [];
  const index = currentShotIndex();
  const previousAvailable = Math.max(0, index);
  const nextCount = index >= 0 ? Math.max(0, shots.length - index - 1) : 0;
  const nextAvailable = nextCount > 0;
  const maxSelectable = Math.max(1, previousAvailable, nextCount);
  input.setAttribute("data-max", String(maxSelectable));
  input.disabled = previousAvailable === 0 && nextCount === 0;
  $("overlayPrevious").disabled = previousAvailable === 0;
  if ($("overlayNext")) {
    $("overlayNext").disabled = !nextAvailable;
  }
  if ($("previousShot")) {
    $("previousShot").disabled = previousAvailable === 0;
  }
  if ($("nextShot")) {
    $("nextShot").disabled = !nextAvailable && !isAutoAddShotEnabled();
  }
  clampOverlayCountInput();
  clampOverlayOpacityInput();
}

function clampOverlayCountInput() {
  const input = $("overlayCount");
  if (!input) {
    return 1;
  }
  const maxSelectable = Math.max(1, parseInt(input.getAttribute("data-max") || "1", 10) || 1);
  const parsed = Math.max(1, parseInt(input.value || "1", 10) || 1);
  const clamped = Math.min(parsed, maxSelectable);
  input.value = String(clamped);
  return clamped;
}

function clampOverlayOpacityInput() {
  const input = $("overlayOpacity");
  if (!input) {
    return DEFAULT_OVERLAY_OPACITY;
  }
  const parsed = Math.max(1, Math.min(100, parseInt(input.value || `${DEFAULT_OVERLAY_OPACITY}`, 10) || DEFAULT_OVERLAY_OPACITY));
  input.value = String(parsed);
  return parsed;
}

function getPreviousShotsForOverlay(count) {
  const shots = projectData?.shots || [];
  const index = currentShotIndex();
  if (index <= 0) {
    return [];
  }
  const start = Math.max(0, index - count);
  return shots.slice(start, index);
}

function getNextShotsForOverlay(count) {
  const shots = projectData?.shots || [];
  const index = currentShotIndex();
  if (index < 0 || index >= shots.length - 1) {
    return [];
  }
  return shots.slice(index + 1, Math.min(shots.length, index + 1 + count));
}

async function goToPreviousShot() {
  const shots = projectData?.shots || [];
  const index = currentShotIndex();
  if (index <= 0) {
    throw new Error("No previous shot.");
  }
  await switchToShot(shots[index - 1].shot_id);
}

async function goToNextShot() {
  const shot = await resolveNextShot(currentShotId());
  if (!shot) {
    throw new Error("No next shot.");
  }
  await switchToShot(shot.shot_id);
}

async function focusCurrentShotTab() {
  const shotId = selectedShotIdValue();
  if (!isValidShotId(shotId)) {
    throw new Error("Pick a shot first.");
  }
  const doc = findOpenDocumentForShot(shotId);
  if (!doc) {
    throw new Error(`No open Photoshop tab for ${shotId}.`);
  }
  activateDocument(doc);
  setSelectedShotId(shotId);
  await notifyBackendShotFocus(shotId);
  setStatus(`Focused open tab for ${shotId}.`);
}

function isValidShotId(value) {
  return /^shot_\d{3,}$/i.test(value) || /^[a-f0-9]{32}$/i.test(value);
}

function formatShotIdLabel(shotId) {
  const value = String(shotId || "");
  if (value.length <= 12) {
    return value;
  }
  return `${value.slice(0, 8)}…`;
}

function currentShotId() {
  const value = String($("shotId").value || $("shotSelect").value || "").trim();
  if (!isValidShotId(value)) {
    throw new Error("Shot ID must be a legacy shot_001 id or a 32-character UUID.");
  }
  return value.toLowerCase();
}

function currentShotRecord() {
  const shotId = currentShotId();
  const shot = (projectData?.shots || []).find((item) => item.shot_id === shotId);
  if (!shot) {
    throw new Error(`Shot not found in project: ${shotId}`);
  }
  return shot;
}

function selectedShotIdValue() {
  return String($("shotId")?.value || $("shotSelect")?.value || detectShotFromDocument() || "").trim().toLowerCase();
}

function currentShotFromProjectData() {
  const shotId = selectedShotIdValue();
  if (!shotId) {
    return null;
  }
  return (projectData?.shots || []).find((shot) => shot.shot_id === shotId) || null;
}

function currentShotIndexLabel(shot) {
  const shots = projectData?.shots || [];
  const index = shots.findIndex((item) => item.shot_id === shot?.shot_id);
  if (index < 0) {
    return shot?.shot_id || selectedShotIdValue() || "No shot";
  }
  return `${shot.shot_id} / ${String(index + 1).padStart(3, "0")} of ${String(shots.length).padStart(3, "0")}`;
}

function compactText(value, fallback = "") {
  return String(value || "").trim() || fallback;
}

function latestCommentSummary(shot) {
  const comments = Array.isArray(shot?.comments) ? shot.comments : [];
  const latest = [...comments].reverse().find((comment) => String(comment?.text || "").trim());
  return latest ? String(latest.text || "").trim() : "";
}

function setCardSection(id, label, value) {
  const node = $(id);
  if (!node) {
    return;
  }
  const text = compactText(value);
  node.hidden = !text;
  node.innerHTML = "";
  if (!text) {
    return;
  }
  const strong = document.createElement("strong");
  strong.textContent = label;
  const body = document.createElement("span");
  body.textContent = text;
  node.append(strong, body);
}

function renderQuickStatusButtons(shot, enabled) {
  const container = $("quickStatusButtons");
  if (!container) {
    return;
  }
  container.innerHTML = "";
  const currentStatus = String(shot?.status || "Draft");
  for (const status of QUICK_STATUS_OPTIONS) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = status;
    button.setAttribute("data-status", status);
    button.disabled = !enabled;
    button.classList.toggle("is-active", status === currentStatus);
    container.appendChild(button);
  }
}

function renderCurrentShotCard() {
  const card = $("currentShotCard");
  if (!card) {
    return;
  }
  const shot = currentShotFromProjectData();
  const selectedId = selectedShotIdValue();
  const hasStandaloneSelection = !linkedFromStoryboard && selectedId;
  if (!shot && !hasStandaloneSelection) {
    card.hidden = true;
    return;
  }

  card.hidden = false;
  $("shotCardMode").textContent = linkedFromStoryboard ? "Linked to Storyboard Tool" : "Standalone folder mode";
  $("shotCardIndex").textContent = shot ? currentShotIndexLabel(shot) : selectedId;
  $("shotCardTitle").textContent = compactText(shot?.title, "Untitled shot");
  $("shotCardStatus").textContent = compactText(shot?.status, linkedFromStoryboard ? "Draft" : "Standalone");
  const meta = [];
  if (shot?.duration_seconds) meta.push(`${Number(shot.duration_seconds).toFixed(1)}s`);
  if (compactText(shot?.scene)) meta.push(`Scene: ${shot.scene}`);
  if (compactText(shot?.sequence)) meta.push(`Seq: ${shot.sequence}`);
  $("shotCardMeta").textContent = meta.join(" | ");
  setCardSection("shotCardAction", "Action", shot?.action_note || shot?.description);
  setCardSection("shotCardCamera", "Camera", shot?.camera_note);
  setCardSection("shotCardNotes", "Notes", latestCommentSummary(shot));
  renderQuickStatusButtons(shot, Boolean(linkedFromStoryboard && shot));
  const note = $("quickNoteText");
  if (note) note.disabled = !linkedFromStoryboard || !shot;
  const add = $("addQuickNote");
  if (add) add.disabled = !linkedFromStoryboard || !shot;
  const hint = $("shotCardHint");
  if (hint) {
    hint.textContent = linkedFromStoryboard
      ? "Status and notes are saved through Storyboard Tool."
      : "Status and quick notes need Storyboard Tool linked.";
  }
}

function shotUpdatePayload(shot, status) {
  return {
    title: shot.title || "",
    scene: shot.scene || "",
    sequence: shot.sequence || "",
    description: shot.description || "",
    action_note: shot.action_note || "",
    camera_note: shot.camera_note || "",
    character_note: shot.character_note || "",
    dialogue: shot.dialogue || "",
    lighting_note: shot.lighting_note || "",
    transition_note: shot.transition_note || "",
    duration_seconds: Number.parseFloat(shot.duration_seconds || "3") || 3,
    camera_data: shot.camera_data && typeof shot.camera_data === "object" ? shot.camera_data : {},
    tags: Array.isArray(shot.tags) ? shot.tags : [],
    status,
  };
}

async function updateShotStatusViaBackend(status) {
  if (!linkedFromStoryboard) {
    throw new Error("Status changes require Storyboard Tool linked.");
  }
  const shot = currentShotFromProjectData();
  if (!shot) {
    throw new Error("Pick a shot first.");
  }
  const payload = await requestStoryboardApi(`/api/shots/${encodeURIComponent(shot.shot_id)}`, {
    method: "PATCH",
    body: JSON.stringify(shotUpdatePayload(shot, status || "Draft")),
  });
  if (!payload) {
    throw new Error("Could not update shot status. Is Storyboard Tool running?");
  }
  await refreshProjectDataFromBackend();
  setStatus(`Marked ${shot.shot_id} as ${status}.`);
}

async function addQuickNoteViaBackend() {
  if (!linkedFromStoryboard) {
    throw new Error("Quick notes require Storyboard Tool linked.");
  }
  const shot = currentShotFromProjectData();
  if (!shot) {
    throw new Error("Pick a shot first.");
  }
  const input = $("quickNoteText");
  const text = String(input?.value || "").trim();
  if (!text) {
    throw new Error("Type a note first.");
  }
  const payload = await requestStoryboardApi(`/api/shots/${encodeURIComponent(shot.shot_id)}/comments`, {
    method: "POST",
    body: JSON.stringify({ text }),
  });
  if (!payload) {
    throw new Error("Could not add note. Is Storyboard Tool running?");
  }
  if (input) input.value = "";
  await refreshProjectDataFromBackend();
  setStatus(`Added note to ${shot.shot_id}.`);
}

function shotIdFromDocumentName(name) {
  const base = String(name || "").replace(/\.[^.]+$/, "");
  const legacy = base.match(/^(shot_\d{3,})/i);
  if (legacy) {
    return legacy[1].toLowerCase();
  }
  const uuid = base.match(/^([a-f0-9]{32})$/i);
  return uuid ? uuid[1].toLowerCase() : "";
}

function detectShotFromDocument() {
  return shotIdFromDocumentName(app.activeDocument?.name);
}

function getOpenShotIds() {
  const ids = new Set();
  try {
    for (const doc of app.documents) {
      const shotId = shotIdFromDocumentName(doc.name);
      if (shotId) {
        ids.add(shotId);
      }
    }
  } catch {
    // Document enumeration is best-effort.
  }
  return [...ids];
}

async function getShotFolderEntry(shotId) {
  if (projectRoot) {
    const shotsDir = await projectRoot.getEntry("shots");
    try {
      return await shotsDir.getEntry(shotId);
    } catch {
      return await shotsDir.createFolder(shotId);
    }
  }
  if (shotFolder && (shotFolder.name || "") === shotId) {
    return shotFolder;
  }
  throw new Error("Choose a project or shot folder first.");
}

async function ensureShotStructure(shotId) {
  const folder = await getShotFolderEntry(shotId);
  try {
    await folder.getEntry("references");
  } catch {
    await folder.createFolder("references");
  }
  const annotationName = `${shotId}_annotations.json`;
  try {
    await folder.getEntry(annotationName);
  } catch {
    const entry = await folder.createFile(annotationName, { overwrite: false });
    await writeEntryText(entry, "[]");
  }
  const notesName = `${shotId}_notes.json`;
  try {
    await folder.getEntry(notesName);
  } catch {
    const shot = (projectData?.shots || []).find((item) => item.shot_id === shotId);
    const entry = await folder.createFile(notesName, { overwrite: false });
    await writeEntryText(entry, JSON.stringify(shot || createEmptyShot(shotId), null, 2));
  }
  return folder;
}

function createEmptyShot(shotId) {
  return {
    shot_id: shotId,
    title: "",
    scene: "",
    sequence: "",
    description: "",
    action_note: "",
    camera_note: "",
    character_note: "",
    dialogue: "",
    lighting_note: "",
    transition_note: "",
    duration_seconds: 3.0,
    camera_data: {},
    tags: [],
    comments: [],
    status: "Draft",
    image_path: "",
    preview_image_path: "",
    thumbnail_path: "",
    source_file_path: "",
    source_sync_mtime: 0.0,
    annotation_path: `shots/${shotId}/${shotId}_annotations.json`,
    reference_image_paths: [],
  };
}

function nextShotId() {
  if (typeof crypto !== "undefined" && crypto.randomUUID) {
    return crypto.randomUUID().replace(/-/g, "");
  }
  const bytes = new Uint8Array(16);
  for (let index = 0; index < bytes.length; index += 1) {
    bytes[index] = Math.floor(Math.random() * 256);
  }
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
}

async function addShotToProject() {
  requireProjectRoot();
  const shot = createEmptyShot(nextShotId());
  projectData.shots.push(shot);
  await ensureShotStructure(shot.shot_id);
  await saveProjectJson();
  populateShotSelect();
  return shot;
}

async function resolveNextShot(shotId) {
  if (linkedFromStoryboard) {
    const payload = await requestStoryboardApi("/api/plugin/shots/next", {
      method: "POST",
      body: JSON.stringify({
        current_shot_id: shotId,
        auto_add: isAutoAddShotEnabled(),
      }),
    });
    if (payload?.context) {
      applyPluginContext(payload.context);
    } else {
      await refreshProjectDataFromBackend();
    }
    if (payload?.shot?.shot_id) {
      try {
        await ensureShotStructure(payload.shot.shot_id);
      } catch {
        // Backend-created shot folders are the source of truth in linked mode.
      }
      return normalizeShotFromBackend(payload.shot);
    }
    return null;
  }
  const shots = projectData?.shots || [];
  const index = shots.findIndex((shot) => shot.shot_id === shotId);
  if (index >= 0 && index < shots.length - 1) {
    return shots[index + 1];
  }
  if (isAutoAddShotEnabled()) {
    return addShotToProject();
  }
  return null;
}

function isAutoAddShotEnabled() {
  const checkbox = $("autoAddShot");
  return !checkbox || checkbox.checked !== false;
}

function findOpenDocumentForShot(shotId) {
  const normalized = String(shotId || "").toLowerCase();
  if (!normalized) {
    return null;
  }
  for (const doc of app.documents) {
    const name = String(doc.name || "").toLowerCase();
    if (name === `${normalized}.psd` || name === normalized || name.startsWith(`${normalized}.`)) {
      return doc;
    }
  }
  return null;
}

function activateDocument(doc) {
  if (!doc || !isDocumentOpen(doc)) {
    return null;
  }
  app.activeDocument = doc;
  return doc;
}

async function resolveShotImageEntry(shot) {
  const folder = await getShotFolderEntry(shot.shot_id);
  const candidates = [`${shot.shot_id}_preview.png`, `${shot.shot_id}.psd`];
  for (const name of candidates) {
    try {
      return await folder.getEntry(name);
    } catch {
      // Try the next file name.
    }
  }
  return null;
}







function registerDocumentBackgroundListeners() {
  const events = ["open", "select", "close"];
  try {
    photoshop.action.addNotificationListener(events, (eventName) => {
      updateCurrentShotIndicator();
      if (eventName === "open" || eventName === "select") {
        scheduleBackgroundSyncForActiveDocument();
      }
    });
  } catch {
    // Notification listeners are optional.
  }
}

function activeDocumentKey() {
  try {
    const doc = app.activeDocument;
    if (!doc) {
      return "";
    }
    return `${doc.id}:${doc.name}`;
  } catch {
    return "";
  }
}

// Switching tabs in Photoshop does not always fire a notification we can hook,
// so poll the active document and refresh the "Now editing" label when it
// changes. This only reads document/layer-free properties — no modal needed.
function startActiveDocumentWatch() {
  if (activeDocWatchTimer) {
    clearInterval(activeDocWatchTimer);
  }
  activeDocWatchTimer = setInterval(() => {
    const key = activeDocumentKey();
    if (key !== lastActiveDocKey) {
      lastActiveDocKey = key;
      updateCurrentShotIndicator();
    }
  }, 700);
}

function updateCurrentShotIndicator() {
  const node = $("currentShot");
  if (!node) {
    return;
  }
  let doc = null;
  try {
    doc = app.activeDocument;
  } catch {
    doc = null;
  }
  if (!doc) {
    node.hidden = true;
    return;
  }

  const shotId = detectShotFromDocument();
  if (!shotId) {
    node.textContent = `Editing: ${doc.name} (not a storyboard shot)`;
    node.classList.add("muted");
    node.hidden = false;
    return;
  }

  node.classList.remove("muted");
  const shots = projectData?.shots || [];
  const index = shots.findIndex((shot) => shot.shot_id === shotId);
  if (index >= 0 && String($("shotId")?.value || "").trim().toLowerCase() !== shotId) {
    setSelectedShotId(shotId);
  }
  const idLabel = formatShotIdLabel(shotId);
  let text;
  if (index >= 0) {
    const shot = shots[index];
    const title = String(shot.title || "").trim();
    text = `Editing shot ${index + 1}/${shots.length}`;
    text += title ? ` · ${title} (${idLabel})` : ` · ${idLabel}`;
  } else {
    text = `Editing · ${idLabel}`;
  }
  if (index >= 0) {
    const shot = shots[index];
    const status = String(shot.status || "").trim();
    const duration = Number.parseFloat(shot.duration_seconds || "0") || 0;
    const warnings = [];
    if (shot.broken_or_zero_byte_psd) warnings.push("PSD broken");
    else if (shot.source_path_missing || shot.psd_exists === false) warnings.push("PSD missing");
    if (shot.preview_out_of_date) warnings.push("preview stale");
    else if (shot.preview_exists === false) warnings.push("preview missing");
    if (status || duration) {
      text += ` Â· ${status || "No status"}${duration ? ` Â· ${duration}s` : ""}`;
    }
    if (warnings.length) {
      text += ` Â· ${warnings.join(", ")}`;
    }
  }
  node.textContent = text;
  node.hidden = false;
  renderCurrentShotCard();
}

function scheduleBackgroundSyncForActiveDocument() {
  if (backgroundSyncTimer) {
    clearTimeout(backgroundSyncTimer);
  }
  backgroundSyncTimer = setTimeout(() => {
    backgroundSyncTimer = null;
    syncActiveDocumentBackground().catch(() => {});
  }, 400);
}

async function syncActiveDocumentBackground() {
  const shotId = detectShotFromDocument();
  if (!shotId || !app.activeDocument) {
    return;
  }
  if (!projectRoot && !shotFolder) {
    return;
  }
  if (backgroundSyncInFlight) {
    return;
  }
  // Check whether anything actually changed before entering a modal, so passive
  // events (layer select, the 1.5s live-bridge poll) never flicker a modal or
  // rebuild the layer stack while the artist is working.
  if (!(await boardBackgroundRefreshNeeded(shotId, false))) {
    return;
  }
  backgroundSyncInFlight = true;
  let synced = false;
  try {
    await runModal("Sync board background", async () => {
      synced = await syncBoardBackgroundFromDisk(shotId, true);
    });
  } finally {
    backgroundSyncInFlight = false;
  }
  if (synced) {
    setStatus(`Background synced for ${shotId}.`);
  }
}


async function overlayShotsInModal(doc, shots, label) {
  await clearOverlayLayersInModal(doc);
  const backgroundLayer = findBackgroundLayer(doc);
  let anchor = backgroundLayer;
  let placed = 0;
  const opacity = clampOverlayOpacityInput();

  for (const shot of shots) {
    const entry = await resolveShotImageEntry(shot);
    if (!entry) {
      continue;
    }
    const placedLayer = await placeFileEntryAsLayer(entry);
    if (!placedLayer) {
      continue;
    }
    await renameActiveLayer(`${OVERLAY_LAYER_PREFIX} ${label} ${formatShotIdLabel(shot.shot_id)}`);
    await setActiveLayerOpacity(opacity);
    const layer = app.activeDocument.activeLayers[0] || placedLayer;
    await moveLayerBelowReference(layer, anchor);
    anchor = layer;
    placed += 1;
  }
  return placed;
}

async function overlayPreviousShotsInModal(doc, previousShots) {
  return overlayShotsInModal(doc, previousShots, "previous");
}

async function overlayPreviousShots() {
  if (!app.activeDocument) {
    throw new Error("Open a shot canvas first.");
  }
  const count = clampOverlayCountInput();
  const previousShots = getPreviousShotsForOverlay(count);
  if (!previousShots.length) {
    throw new Error("No previous shots available to overlay.");
  }

  let placed = 0;
  await runModal("Overlay previous shots", async () => {
    const doc = app.activeDocument;
    if (!doc) {
      throw new Error("No active Photoshop document.");
    }
    placed = await overlayPreviousShotsInModal(doc, previousShots);
  });
  if (!placed) {
    throw new Error("Previous shots have no preview or PSD files to overlay.");
  }
  setStatus(`Stacked ${placed} previous shot(s) under the canvas.`);
}

async function overlayNextShots() {
  if (!app.activeDocument) {
    throw new Error("Open a shot canvas first.");
  }
  const count = clampOverlayCountInput();
  const nextShots = getNextShotsForOverlay(count);
  if (!nextShots.length) {
    throw new Error("No next shots available to overlay.");
  }

  let placed = 0;
  await runModal("Overlay next shots", async () => {
    const doc = app.activeDocument;
    if (!doc) {
      throw new Error("No active Photoshop document.");
    }
    placed = await overlayShotsInModal(doc, nextShots, "next");
  });
  if (!placed) {
    throw new Error("Next shots have no preview or PSD files to overlay.");
  }
  setStatus(`Stacked ${placed} next shot(s) under the canvas.`);
}

async function clearOverlayLayers() {
  if (!app.activeDocument) {
    throw new Error("No active Photoshop document.");
  }
  let removed = 0;
  await runModal("Clear overlay refs", async () => {
    const doc = app.activeDocument;
    const overlayLayers = collectOverlayLayers(doc.layers);
    removed = overlayLayers.length;
    await clearOverlayLayersInModal(doc);
  });
  setStatus(removed ? `Removed ${removed} overlay layer(s).` : "No overlay layers to remove.");
}

async function applyCanvasBackgroundInModal() {
  const color = await resolveActiveCanvasColor();
  canvasColor = color;
  updateColorSwatch();
  const doc = app.activeDocument;
  if (!doc) {
    throw new Error("No active Photoshop document.");
  }

  // Filling the background must not steal the artist's active layer selection.
  const previousActiveIds = captureActiveLayerIds(doc);
  let targetLayer = findBackgroundLayer(doc);
  if (!targetLayer) {
    // No canvas-color base exists (e.g. a PSD opened with only `SB bg`). Create
    // one rather than painting over the reference or the drawing.
    targetLayer = await createCanvasBackgroundLayerInModal(doc);
  }
  if (!targetLayer) {
    throw new Error("No layer found to fill with the canvas color.");
  }

  doc.activeLayers = [targetLayer];
  const rgb = hexToRgb(color);
  await photoshop.action.batchPlay(
    [
      {
        _obj: "set",
        _target: [{ _ref: "color", _property: "foregroundColor" }],
        to: {
          _obj: "RGBColor",
          red: rgb.r,
          grain: rgb.g,
          blue: rgb.b,
        },
      },
      {
        _obj: "fill",
        using: { _enum: "fillContents", _value: "foregroundColor" },
        opacity: { _unit: "percentUnit", _value: 100 },
        mode: { _enum: "blendMode", _value: "normal" },
      },
    ],
    { synchronousExecution: true },
  );
  restoreActiveLayersByIds(doc, previousActiveIds);
}

const PSD_MIN_VALID_BYTES = 26; // A PSD header alone is 26 bytes; anything smaller is empty/truncated.
const SHOT_HISTORY_FOLDER = "_history";

async function psdFileSize(entry) {
  try {
    const metadata = await entry.getMetadata();
    const size = Number(metadata?.size);
    return Number.isFinite(size) ? size : -1;
  } catch {
    return -1; // Size unknown — callers must not treat this as broken.
  }
}

function psdSizeLooksBroken(size) {
  return size >= 0 && size < PSD_MIN_VALID_BYTES;
}

async function psdEntryLooksOpenable(entry) {
  return !psdSizeLooksBroken(await psdFileSize(entry));
}

async function shotHistoryFolder(folder) {
  try {
    return await folder.getEntry(SHOT_HISTORY_FOLDER);
  } catch {
    return await folder.createFolder(SHOT_HISTORY_FOLDER);
  }
}

// Best-effort native copy of a file aside into the shot's _history folder so a
// corrupt or about-to-be-overwritten PSD can be recovered manually.
async function copyPsdToHistory(folder, entry) {
  try {
    if (!entry || typeof entry.copyTo !== "function") {
      return;
    }
    const history = await shotHistoryFolder(folder);
    await entry.copyTo(history, { overwrite: true });
  } catch {
    // History copies are optional.
  }
}

async function backupExistingPsd(folder, shotId) {
  try {
    const existing = await folder.getEntry(`${shotId}.psd`);
    if (await psdEntryLooksOpenable(existing)) {
      await copyPsdToHistory(folder, existing);
    }
  } catch {
    // No prior PSD to back up.
  }
}

async function preserveBrokenPsd(folder, shotId) {
  try {
    const entry = await folder.getEntry(`${shotId}.psd`);
    await copyPsdToHistory(folder, entry);
  } catch {
    // Nothing to preserve.
  }
}

async function savePsdInModal(folder, shotId) {
  // Never overwrite an existing PSD via saveAs — that is the call that corrupts
  // files. The artist saves with native Ctrl+S; the plugin only ever creates the
  // PSD the first time it does not exist yet (so a brand-new canvas has a file).
  const existing = await getShotPsdEntry(folder, shotId);
  if (existing) {
    return existing;
  }
  const file = await folder.createFile(`${shotId}.psd`, { overwrite: true });
  await app.activeDocument.saveAs.psd(file, {}, false);
  if ((await psdFileSize(file)) === 0) {
    throw new Error(
      `Creating ${shotId}.psd produced an empty file. Your work is still open in Photoshop — try again.`,
    );
  }
  return file;
}

async function saveActiveDocumentNativeInModal() {
  // Photoshop's native Save (Ctrl+S) — does not use UXP saveAs overwrite, which can
  // corrupt PSDs when writing into the project folder.
  try {
    await photoshop.action.batchPlay([{ _obj: "save" }], { synchronousExecution: true });
    return true;
  } catch {
    return false;
  }
}


async function createCanvasDocumentInModal(shotId) {
  const size = currentCanvasSize();
  await photoshop.action.batchPlay(
    [
      {
        _obj: "make",
        _target: [{ _ref: "document" }],
        using: {
          _obj: "document",
          name: shotId,
          width: { _unit: "pixelsUnit", _value: size.width },
          height: { _unit: "pixelsUnit", _value: size.height },
          resolution: { _unit: "densityUnit", _value: 72 },
          depth: 8,
          mode: { _class: "RGBColorMode" },
          fill: { _enum: "fill", _value: "white" },
        },
      },
    ],
    { synchronousExecution: true },
  );
  return app.activeDocument;
}

async function saveActiveDocumentToFolder(folder, shotId) {
  const previewFile = await exportPreviewInModal(folder, shotId);
  const existingPsd = await getShotPsdEntry(folder, shotId);
  let psdFile = existingPsd;
  if (!existingPsd) {
    // First-time canvas only — establish the linked PSD path once.
    psdFile = await savePsdInModal(folder, shotId);
  }
  return { psdFile, previewFile };
}


async function getShotPsdEntry(folder, shotId) {
  try {
    return await folder.getEntry(`${shotId}.psd`);
  } catch {
    return null;
  }
}

// Rebuild a broken shot PSD and open it. Tries to preserve the original layers
// first; if Photoshop still cannot open that rebuild, escalates to a flattened
// rebuild. Returns { doc, rebuilt } on success, or null if it could not be opened.
async function recoverBrokenShotAndOpen(shotId, folder) {
  for (const preserveLayers of [true, false]) {
    const rebuilt = await requestPsdRecovery(shotId, preserveLayers);
    if (!rebuilt) {
      return null; // Storyboard Tool unreachable or the file is unreadable.
    }
    const entry = await getShotPsdEntry(folder, shotId);
    if (entry && (await psdEntryLooksOpenable(entry))) {
      const opened = await openPsdEntry(entry);
      if (opened && isDocumentOpen(opened) && shotIdFromDocumentName(opened.name) === shotId) {
        return { doc: opened, rebuilt };
      }
    }
    // The rebuilt file still will not open. Escalate to a flattened rebuild only
    // when we just tried (and got) a layer-preserving one; otherwise give up.
    if (!(preserveLayers && rebuilt.method === "layers")) {
      return null;
    }
  }
  return null;
}

// Activates the shot's existing tab, opens its PSD, or — when the file is
// missing or unreadable (corrupt) — asks Storyboard Tool to rebuild it from its
// layers and retries, falling back to a fresh canvas. Returns
// { doc, createdFresh, recoveredBroken, rebuilt } so callers can set up a freshly
// created canvas and report what happened.
async function openOrCreateShotDocInModal(shotId, folder, psdEntry) {
  const existing = findOpenDocumentForShot(shotId);
  if (existing) {
    return { doc: existing, createdFresh: false, recoveredBroken: false };
  }

  let recoveredBroken = false;
  if (psdEntry) {
    if (await psdEntryLooksOpenable(psdEntry)) {
      const opened = await openPsdEntry(psdEntry);
      if (opened && isDocumentOpen(opened) && shotIdFromDocumentName(opened.name) === shotId) {
        return { doc: opened, createdFresh: false, recoveredBroken: false };
      }
    }
    // Photoshop could not open the file. Ask Storyboard Tool to rebuild it from
    // its own layers (the broken original is backed up under _history/), then
    // retry opening the rebuilt PSD.
    const recovered = await recoverBrokenShotAndOpen(shotId, folder);
    if (recovered) {
      return { doc: recovered.doc, createdFresh: false, recoveredBroken: true, rebuilt: recovered.rebuilt };
    }
    // Recovery unavailable or still unreadable: preserve a copy and start fresh.
    await preserveBrokenPsd(folder, shotId);
    recoveredBroken = true;
  }

  await createCanvasDocumentInModal(shotId);
  return { doc: app.activeDocument, createdFresh: true, recoveredBroken };
}

async function closeDocumentInModal(doc, keepDoc) {
  if (!doc || !isDocumentOpen(doc)) {
    return;
  }
  if (keepDoc && doc.id === keepDoc.id) {
    return;
  }
  if (keepDoc && isDocumentOpen(keepDoc)) {
    app.activeDocument = keepDoc;
  }
  if (!isDocumentOpen(doc) || app.documents.length <= 1) {
    return;
  }
  try {
    await doc.closeWithoutSaving();
  } catch {
    await photoshop.action.batchPlay(
      [
        {
          _obj: "close",
          saving: { _enum: "yesNo", _value: "no" },
          _target: [{ _ref: "document", _id: doc.id }],
        },
      ],
      { synchronousExecution: true },
    );
  }
}

async function finishShotSwitch(previousDoc, nextDoc, { closePrevious = true } = {}) {
  const activeNext = activateDocument(nextDoc || app.activeDocument);
  if (!activeNext) {
    throw new Error("Could not activate the target shot document.");
  }
  // closePrevious=false keeps the previous shot's tab open (its PSD may have
  // unsaved strokes the artist still needs to Ctrl+S) instead of discarding it.
  if (closePrevious && previousDoc && previousDoc.id !== activeNext.id) {
    await closeDocumentInModal(previousDoc, activeNext);
  }
  return activeNext;
}


async function saveAndGoNext() {
  const shotId = activeShotId();
  setSelectedShotId(shotId);
  const currentFolder = await ensureShotStructure(shotId);
  const nextShot = await resolveNextShot(shotId);

  let nextFolder = null;
  let nextPsdEntry = null;
  let nextColor = canvasColor;
  let createdNewNext = false;

  if (nextShot) {
    nextFolder = await ensureShotStructure(nextShot.shot_id);
    nextColor = await readProjectCanvasColor(nextFolder);
    try {
      nextPsdEntry = await nextFolder.getEntry(`${nextShot.shot_id}.psd`);
    } catch {
      nextPsdEntry = null;
    }
  }

  await runModal("Save & next shot", async () => {
    const previousDoc = app.activeDocument;
    await exportPreviewInModal(currentFolder, shotId);
    // Do NOT save or close the current shot — its tab stays open so unsaved
    // strokes are never discarded. The artist saves the PSD with Ctrl+S.

    if (!nextShot) {
      return;
    }

    const nextShotId = nextShot.shot_id;
    const result = await openOrCreateShotDocInModal(nextShotId, nextFolder, nextPsdEntry);
    const nextDoc = result.doc;
    if (!nextDoc) {
      throw new Error(`Could not open ${nextShotId}.`);
    }

    if (result.createdFresh) {
      canvasColor = nextColor;
      await applyCanvasBackgroundInModal();
      await ensureDrawingLayerInModal(app.activeDocument);
      await saveActiveDocumentToFolder(nextFolder, nextShotId);
      await syncBoardBackgroundFromDisk(nextShotId, true);
      createdNewNext = true;
    } else {
      await syncBoardBackgroundFromDisk(nextShotId, true);
      await ensureDrawingLayerInModal(app.activeDocument);
    }

    await finishShotSwitch(previousDoc, app.activeDocument || nextDoc, { closePrevious: false });
  });

  await updateProjectAfterSave(shotId, currentFolder);

  if (!nextShot) {
    focusStoryboardAfterPreviewExportIfEnabled();
    setStatus(
      `Preview exported for ${shotId}. No more shots in the project. Press Ctrl+S to save the PSD.`,
    );
    return;
  }

  setSelectedShotId(nextShot.shot_id);
  shotFolder = nextFolder;
  canvasColor = nextColor;
  updateColorSwatch();
  await notifyBackendShotFocus(nextShot.shot_id);

  if (createdNewNext) {
    await updateProjectAfterSave(nextShot.shot_id, nextFolder);
  }

  setStatus(
    `Exported drawing for ${shotId}. Now on ${nextShot.shot_id}. ${shotId}'s tab stays open — switch to it and Ctrl+S to save its PSD.`,
  );
  focusStoryboardAfterPreviewExportIfEnabled();
}

async function switchToSelectedShot() {
  // Read the dropdown directly — currentShotId() prefers the hidden #shotId
  // field, which lags behind the dropdown and would switch back to the old shot.
  const shotId = String($("shotSelect")?.value || "").trim().toLowerCase();
  if (!isValidShotId(shotId)) {
    throw new Error("Pick a shot from the list first.");
  }
  await switchToShot(shotId);
}

// Report a Photoshop "could not open / program error" for the selected shot and
// ask Storyboard Tool to rebuild its PSD (keeping the original layers when it can),
// then re-open it.
async function recoverCurrentShotPsd() {
  const shotId = String($("shotSelect")?.value || "").trim().toLowerCase() || currentShotId();
  if (!isValidShotId(shotId)) {
    throw new Error("Pick a shot from the list first.");
  }
  const folder = await ensureShotStructure(shotId);
  setStatus(`Reporting PS error for ${shotId} — rebuilding…`);
  let recovered = null;
  await runModal(`Recover ${shotId}`, async () => {
    const previousDoc = app.activeDocument;
    recovered = await recoverBrokenShotAndOpen(shotId, folder);
    if (recovered) {
      await finalizeRecoveredShotInModal(shotId);
      await finishShotSwitch(previousDoc, app.activeDocument || recovered.doc);
    }
  });
  if (!recovered) {
    throw new Error(
      "Could not rebuild the PSD. Make sure Storyboard Tool is running with this project open.",
    );
  }
  setSelectedShotId(shotId);
  shotFolder = folder;
  const layers = recovered.rebuilt?.layers_recovered ?? "?";
  const how = recovered.rebuilt?.method === "flatten" ? "flattened" : "with layers preserved";
  setStatus(`Recovered ${shotId} ${how}: ${layers} layer(s). Broken original kept in ${SHOT_HISTORY_FOLDER}/.`);
}

async function switchToShot(shotId) {
    if (detectShotFromDocument() === shotId && app.activeDocument) {
    setSelectedShotId(shotId);
    shotFolder = await ensureShotStructure(shotId);
    let synced = false;
    await runModal("Sync board background", async () => {
      synced = await syncBoardBackgroundFromDisk(shotId);
      await ensureBoardBackgroundStackOrderInModal(app.activeDocument);
      await ensureDrawingLayerInModal(app.activeDocument);
    });
    setStatus(synced ? `Background synced for ${shotId}.` : `Already working on ${shotId}.`);
    await notifyBackendShotFocus(shotId);
    return;
  }

  const folder = await ensureShotStructure(shotId);
  const nextColor = await readProjectCanvasColor(folder);
  const psdName = `${shotId}.psd`;
  let psdEntry = null;
  let createdNew = false;
  let recoveredBroken = false;
  let rebuiltInfo = null;

  try {
    psdEntry = await folder.getEntry(psdName);
  } catch {
    psdEntry = null;
  }

  await runModal(`Open ${shotId}`, async () => {
    const previousDoc = app.activeDocument;
    const result = await openOrCreateShotDocInModal(shotId, folder, psdEntry);
    const nextDoc = result.doc;
    if (!nextDoc) {
      throw new Error(`Could not open ${shotId}.`);
    }
    recoveredBroken = result.recoveredBroken;
    rebuiltInfo = result.rebuilt || null;
    if (result.createdFresh) {
      canvasColor = nextColor;
      await applyCanvasBackgroundInModal();
      await ensureDrawingLayerInModal(app.activeDocument);
      await saveActiveDocumentToFolder(folder, shotId);
      await syncBoardBackgroundFromDisk(shotId, true);
      createdNew = true;
    } else {
      if (rebuiltInfo) {
        await finalizeRecoveredShotInModal(shotId);
      } else {
        await syncBoardBackgroundFromDisk(shotId, true);
        await ensureBoardBackgroundStackOrderInModal(app.activeDocument);
        await ensureDrawingLayerInModal(app.activeDocument);
      }
    }
    await finishShotSwitch(previousDoc, app.activeDocument || nextDoc, { closePrevious: false });
  });

  setSelectedShotId(shotId);
  shotFolder = folder;
  $("folderLabel").textContent = `Folder: ${shotFolder.nativePath || shotFolder.name}`;
  canvasColor = nextColor;
  updateColorSwatch();
  await notifyBackendShotFocus(shotId);

  if (createdNew) {
    await updateProjectAfterSave(shotId, folder);
    setStatus(
      recoveredBroken
        ? `${psdName} was unreadable — kept a copy in ${SHOT_HISTORY_FOLDER}/ and created a fresh canvas.`
        : `Created canvas for ${shotId}.`,
    );
    return;
  }

  if (rebuiltInfo) {
    const layers = rebuiltInfo.layers_recovered ?? "?";
    const how = rebuiltInfo.method === "flatten" ? "flattened" : "with layers preserved";
    setStatus(`Recovered ${shotId} ${how}: ${layers} layer(s). Broken original kept in ${SHOT_HISTORY_FOLDER}/.`);
    return;
  }

  setStatus(`Opened ${shotId}.`);
}

async function createCanvasForShot(shotId) {
  const folder = await ensureShotStructure(shotId);
  let createdNew = false;
  await runModal(`Create ${shotId}`, async () => {
    await createCanvasDocumentInModal(shotId);
    await applyCanvasBackgroundInModal();
    await ensureDrawingLayerInModal(app.activeDocument);
    await saveActiveDocumentToFolder(folder, shotId);
    await syncBoardBackgroundFromDisk(shotId, true);
    createdNew = true;
  });
  if (!createdNew) {
    return;
  }
  await updateProjectAfterSave(shotId, folder);
}


async function openPsdEntry(entry) {
  try {
    const opened = await app.open(entry);
    if (opened) {
      return opened;
    }
  } catch {
    // Fall back to batchPlay open with a session token.
  }

  try {
    const token = await fs.createSessionToken(entry);
    await photoshop.action.batchPlay(
      [
        {
          _obj: "open",
          null: { _path: token, _kind: "local" },
        },
      ],
      { synchronousExecution: true },
    );
    return app.activeDocument;
  } catch {
    // Both open paths failed — likely a corrupt PSD. Let the caller recover.
    return null;
  }
}

function isDocumentOpen(doc) {
  if (!doc?.id) {
    return false;
  }
  return app.documents.some((item) => item.id === doc.id);
}

function activeShotId() {
  if (!app.activeDocument) {
    throw new Error("No active Photoshop document.");
  }
  const shotId = detectShotFromDocument();
  if (!shotId) {
    throw new Error(
      "The active Photoshop tab is not a recognized shot. Open the shot from Storyboard Tool or the panel before saving.",
    );
  }
  return shotId;
}

function requireProjectRoot() {
  if (!projectRoot) {
    throw new Error("Open a project in Storyboard Tool, or use Manual folder below.");
  }
}

async function fileUnixMtime(entry) {
  try {
    const metadata = await entry.getMetadata();
    if (metadata?.modificationDate) {
      return metadata.modificationDate.getTime() / 1000;
    }
  } catch {
    // Fall back to the current time.
  }
  return Date.now() / 1000;
}

async function writeEntryText(entry, text) {
  await entry.write(text);
}

async function resolveActiveCanvasColor() {
  if (linkedFromStoryboard && canvasColor) {
    return normalizeHexColor(canvasColor);
  }
  if (projectRoot) {
    const fromRoot = await readCanvasColorTxt(projectRoot);
    if (fromRoot) return fromRoot;
    const fromSettings = await readJsonField(projectRoot, "settings.json", "canvas_background_color");
    if (fromSettings) return normalizeHexColor(fromSettings);
  }
  if (shotFolder) {
    return readProjectCanvasColor(shotFolder);
  }
  return normalizeHexColor(canvasColor);
}

async function applyCanvasBackground() {
  await runModal("Apply canvas color", async () => {
    await applyCanvasBackgroundInModal();
  });
}


async function createCanvasBackgroundLayerInModal(doc) {
  // Add a dedicated canvas-color base at the very bottom (below `SB bg` and the
  // drawing) for documents that were opened without a real Background layer.
  await photoshop.action.batchPlay(
    [{ _obj: "make", _target: [{ _ref: "layer" }] }],
    { synchronousExecution: true },
  );
  await renameActiveLayer(CANVAS_BG_LAYER_NAME);
  const layer = doc.activeLayers[0] || null;
  if (layer) {
    await layer.move(doc, photoshop.constants.ElementPlacement.PLACEATEND);
  }
  return layer;
}

async function readEntryText(entry) {
  const contents = await entry.read();
  if (typeof contents === "string") {
    return contents;
  }
  if (contents instanceof ArrayBuffer) {
    return new TextDecoder("utf-8").decode(contents);
  }
  if (contents && contents.buffer instanceof ArrayBuffer) {
    return new TextDecoder("utf-8").decode(contents);
  }
  return String(contents || "");
}

async function readCanvasColorTxt(folder) {
  try {
    const entry = await folder.getEntry("canvas_color.txt");
    const text = await readEntryText(entry);
    const candidate = text.trim().split(/\s+/)[0];
    if (/^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/.test(candidate)) {
      return normalizeHexColor(candidate);
    }
  } catch {
    // Try the next source.
  }
  return "";
}

async function findProjectRoot(folder) {
  let current = folder;
  for (let depth = 0; depth < 6 && current; depth += 1) {
    if (await hasProjectMarker(current)) {
      return current;
    }
    try {
      current = await current.getParent();
    } catch {
      break;
    }
  }
  return null;
}

async function hasProjectMarker(folder) {
  for (const fileName of ["settings.json", "project.json", "shots.csv", "storyboard_bridge.json", "canvas_color.txt"]) {
    try {
      await folder.getEntry(fileName);
      return true;
    } catch {
      // Try the next marker file.
    }
  }
  return false;
}

async function readProjectCanvasColor(folder) {
  const settings = await readProjectCanvasSettings(folder);
  canvasWidth = settings.width;
  canvasHeight = settings.height;
  return settings.color;
}

async function readProjectCanvasSettings(folder) {
  let color = DEFAULT_CANVAS_COLOR;
  let width = DEFAULT_CANVAS_WIDTH;
  let height = DEFAULT_CANVAS_HEIGHT;
  try {
    const root = projectRoot || (await findProjectRoot(folder));
    if (root) {
      const projectSettings = await readJsonObject(root, "settings.json");
      if (projectSettings) {
        if (projectSettings.canvas_background_color) {
          color = normalizeHexColor(projectSettings.canvas_background_color);
        }
        if (projectSettings.canvas_width) {
          width = Number(projectSettings.canvas_width);
        }
        if (projectSettings.canvas_height) {
          height = Number(projectSettings.canvas_height);
        }
      }

      const rootTxt = await readCanvasColorTxt(root);
      if (rootTxt) {
        color = rootTxt;
      }

      for (const fileName of ["storyboard_live_bridge.json", "storyboard_bridge.json"]) {
        const bridge = await readJsonObject(root, fileName);
        if (!bridge) {
          continue;
        }
        if (bridge.canvas_background_color) {
          color = normalizeHexColor(bridge.canvas_background_color);
        }
        if (bridge.canvas_width) {
          width = Number(bridge.canvas_width);
        }
        if (bridge.canvas_height) {
          height = Number(bridge.canvas_height);
        }
      }
    }

    const localTxt = await readCanvasColorTxt(folder);
    if (localTxt) {
      color = localTxt;
    }

    const localBridge = await readJsonObject(folder, "storyboard_bridge.json");
    if (localBridge) {
      if (localBridge.canvas_background_color) {
        color = normalizeHexColor(localBridge.canvas_background_color);
      }
      if (localBridge.canvas_width) {
        width = Number(localBridge.canvas_width);
      }
      if (localBridge.canvas_height) {
        height = Number(localBridge.canvas_height);
      }
    }
  } catch (error) {
    setStatus(`Canvas settings read failed: ${error.message || error}`);
  }
  const size = normalizeCanvasSize(width, height);
  return { color, width: size.width, height: size.height };
}

async function readJsonObject(folder, fileName) {
  try {
    const entry = await folder.getEntry(fileName);
    const text = await readEntryText(entry);
    const data = JSON.parse(text);
    return data && typeof data === "object" ? data : null;
  } catch {
    return null;
  }
}

function normalizeCanvasSize(width, height) {
  const w = Math.min(Math.max(parseInt(width, 10) || DEFAULT_CANVAS_WIDTH, 320), 8192);
  const h = Math.min(Math.max(parseInt(height, 10) || DEFAULT_CANVAS_HEIGHT, 180), 8192);
  return { width: w, height: h };
}

function currentCanvasSize() {
  return normalizeCanvasSize(canvasWidth, canvasHeight);
}

async function readJsonField(folder, fileName, fieldName) {
  try {
    const entry = await folder.getEntry(fileName);
    const text = await readEntryText(entry);
    const data = JSON.parse(text);
    return data[fieldName] || "";
  } catch {
    return "";
  }
}

function normalizeHexColor(value) {
  const candidate = String(value || "").trim();
  if (!/^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/.test(candidate)) {
    return DEFAULT_CANVAS_COLOR;
  }
  if (candidate.length === 4) {
    const chars = candidate.slice(1);
    return ("#" + chars.split("").map((char) => char + char).join("")).toUpperCase();
  }
  return candidate.toUpperCase();
}

function hexToRgb(hex) {
  const normalized = normalizeHexColor(hex).slice(1);
  return {
    r: parseInt(normalized.slice(0, 2), 16),
    g: parseInt(normalized.slice(2, 4), 16),
    b: parseInt(normalized.slice(4, 6), 16),
  };
}

function updateColorSwatch() {
  const swatch = $("colorSwatch");
  if (swatch) {
    swatch.textContent = canvasColor;
    swatch.style.backgroundColor = canvasColor;
  }
}

async function runModal(commandName, fn) {
  await photoshop.core.executeAsModal(fn, { commandName });
}

function setStatus(message) {
  $("status").textContent = message;
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}
