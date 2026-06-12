const photoshop = require("photoshop");
const fs = require("uxp").storage.localFileSystem;

const app = photoshop.app;
const DEFAULT_CANVAS_COLOR = "#E8E8E8";
const CANVAS_WIDTH = 1920;
const CANVAS_HEIGHT = 1080;
const SHARED_BRIDGE_PATH = "C:/Users/Public/StoryboardTool/storyboard_live_bridge.json";
const SHARED_HEARTBEAT_PATH = "C:/Users/Public/StoryboardTool/storyboard_plugin_heartbeat.json";
const SB_POLL_MS = 1500;
const BRIDGE_CACHE_FILE = "storyboard_bridge_cache.json";
const BRIDGE_STALE_MS = 8000;
const OVERLAY_LAYER_PREFIX = "SB ref:";
const OVERLAY_OPACITY = 45;
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
let linkedFromStoryboard = false;
let lastBridgeSignature = "";
let linkedProjectRootPath = "";
let bridgePollTimer = null;

function $(id) {
  return document.getElementById(id);
}

function init() {
  $("chooseProject").addEventListener("click", () => runPanelAction(chooseProjectFolder));
  $("chooseFolder").addEventListener("click", () => runPanelAction(chooseShotFolder));
  $("shotSelect").addEventListener("change", () => runPanelAction(switchToSelectedShot));
  $("openShot").addEventListener("click", () => runPanelAction(switchToSelectedShot));
  $("overlayPrevious").addEventListener("click", () => runPanelAction(overlayPreviousShots));
  $("clearOverlay").addEventListener("click", () => runPanelAction(clearOverlayLayers));
  $("overlayCount")?.addEventListener("change", () => clampOverlayCountInput());
  $("overlayCount")?.addEventListener("input", () => clampOverlayCountInput());
  $("applyBackground").addEventListener("click", () => runPanelAction(applyCanvasBackground));
  $("saveAndStay").addEventListener("click", () => runPanelAction(saveCurrentShot));
  $("saveAndNext").addEventListener("click", () => runPanelAction(saveAndGoNext));
  $("relinkNow").addEventListener("click", () => runPanelAction(reconnectStoryboardBridge));
  setLinkedUi(false);
  setLinkStatus("Connecting…", true);
  startStoryboardBridgePolling();
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
    await applyCanvasBackground();
  }
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
  const payload = JSON.stringify({
    at: new Date().toISOString(),
    plugin: "storyboard-bridge",
    project_root: live?.project_root || "",
    selected_shot_id: live?.selected_shot_id || "",
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
    urls.push(`http://127.0.0.1:${port}/api/bridge/plugin-heartbeat`);
    urls.push(`http://localhost:${port}/api/bridge/plugin-heartbeat`);
  }
  for (const url of urls) {
    try {
      await fetch(url, { method: "POST", cache: "no-store" });
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

  await sendPluginHeartbeat(live);
  await applyLiveBridge(live);
}

async function applyLiveBridge(live) {
  const signature = [
    live.updated_at,
    live.project_root,
    live.selected_shot_id,
    live.canvas_background_color,
    live.shot_count,
  ].join("|");
  const isSame = signature === lastBridgeSignature;
  lastBridgeSignature = signature;
  linkedFromStoryboard = true;

  const root = await resolveFolderEntry(live.project_root);
  if (!root) {
    setLinkedUi(false);
    setLinkStatus("Folder access failed — use Advanced", true);
    canvasColor = normalizeHexColor(live.canvas_background_color);
    updateColorSwatch();
    return;
  }

  setLinkedUi(true);

  if (!isSame || linkedProjectRootPath !== live.project_root) {
    linkedProjectRootPath = live.project_root;
    projectRoot = root;
    projectData = await loadProjectJson();
    populateShotSelect();
  }

  const shotId = live.selected_shot_id || detectShotFromDocument();
  if (shotId) {
    setSelectedShotId(shotId);
    if (live.shot_folder) {
      shotFolder = await resolveFolderEntry(live.shot_folder);
    } else {
      shotFolder = await getShotFolderEntry(shotId);
    }
  }

  const nextColor = normalizeHexColor(live.canvas_background_color);
  const colorChanged = nextColor !== canvasColor;
  canvasColor = nextColor;
  updateColorSwatch();

  if (colorChanged && app.activeDocument && isAutoApplyColorEnabled()) {
    await applyCanvasBackground();
  }

  const label = shotId || live.project_name || "project";
  setLinkStatus(`Linked · ${label}`);
  if (!isSame && shotId) {
    setStatus(`Synced: ${shotId}`);
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

function populateShotSelect() {
  const select = $("shotSelect");
  select.innerHTML = "";
  for (const shot of projectData?.shots || []) {
    const option = document.createElement("option");
    option.value = shot.shot_id;
    option.textContent = formatShotIdLabel(shot.shot_id);
    select.appendChild(option);
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
  const previousAvailable = Math.max(0, currentShotIndex());
  const maxSelectable = Math.max(1, previousAvailable);
  input.setAttribute("data-max", String(maxSelectable));
  input.disabled = previousAvailable === 0;
  $("overlayPrevious").disabled = previousAvailable === 0;
  clampOverlayCountInput();
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

function getPreviousShotsForOverlay(count) {
  const shots = projectData?.shots || [];
  const index = currentShotIndex();
  if (index <= 0) {
    return [];
  }
  const start = Math.max(0, index - count);
  return shots.slice(start, index);
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

function detectShotFromDocument() {
  const doc = app.activeDocument;
  if (!doc?.name) {
    return "";
  }
  const base = String(doc.name).replace(/\.[^.]+$/, "");
  const legacy = base.match(/^(shot_\d{3,})/i);
  if (legacy) {
    return legacy[1].toLowerCase();
  }
  const uuid = base.match(/^([a-f0-9]{32})$/i);
  return uuid ? uuid[1].toLowerCase() : "";
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

function collectOverlayLayers(layers, output = []) {
  for (const layer of layers || []) {
    if (String(layer.name || "").startsWith(OVERLAY_LAYER_PREFIX)) {
      output.push(layer);
    }
    if (layer.layers?.length) {
      collectOverlayLayers(layer.layers, output);
    }
  }
  return output;
}

async function deleteLayersInModal(layers) {
  for (const layer of layers) {
    try {
      await layer.delete();
    } catch {
      try {
        await photoshop.action.batchPlay(
          [
            {
              _obj: "delete",
              _target: [{ _ref: "layer", _id: layer.id }],
            },
          ],
          { synchronousExecution: true },
        );
      } catch {
        // Skip layers that Photoshop refuses to delete.
      }
    }
  }
}

async function clearOverlayLayersInModal(doc) {
  const overlayLayers = collectOverlayLayers(doc.layers);
  if (overlayLayers.length) {
    await deleteLayersInModal(overlayLayers);
  }
}

async function renameActiveLayer(name) {
  await photoshop.action.batchPlay(
    [
      {
        _obj: "set",
        _target: [{ _ref: "layer", _enum: "ordinal", _value: "targetEnum" }],
        to: { _obj: "layer", name },
      },
    ],
    { synchronousExecution: true },
  );
}

async function setActiveLayerOpacity(percent) {
  await photoshop.action.batchPlay(
    [
      {
        _obj: "set",
        _target: [{ _ref: "layer", _enum: "ordinal", _value: "targetEnum" }],
        to: {
          _obj: "layer",
          opacity: { _unit: "percentUnit", _value: percent },
        },
      },
    ],
    { synchronousExecution: true },
  );
}

async function placeFileEntryAsLayer(entry) {
  const token = await fs.createSessionToken(entry);
  await photoshop.action.batchPlay(
    [
      {
        _obj: "placeEvent",
        null: { _path: token, _kind: "local" },
        linked: false,
        freeTransformCenterState: { _enum: "quadCenterState", _value: "QCSAverage" },
      },
    ],
    { synchronousExecution: true },
  );
  return app.activeDocument.activeLayers[0];
}

async function moveLayerBelowReference(layer, referenceLayer) {
  const constants = photoshop.constants;
  if (referenceLayer) {
    await layer.move(referenceLayer, constants.ElementPlacement.PLACEAFTER);
    return;
  }
  await layer.move(app.activeDocument, constants.ElementPlacement.PLACEATEND);
}

async function overlayPreviousShotsInModal(doc, previousShots) {
  await clearOverlayLayersInModal(doc);
  const backgroundLayer = findBackgroundLayer(doc);
  let anchor = backgroundLayer;
  let placed = 0;

  for (const shot of previousShots) {
    const entry = await resolveShotImageEntry(shot);
    if (!entry) {
      continue;
    }
    const placedLayer = await placeFileEntryAsLayer(entry);
    if (!placedLayer) {
      continue;
    }
    await renameActiveLayer(`${OVERLAY_LAYER_PREFIX} ${formatShotIdLabel(shot.shot_id)}`);
    await setActiveLayerOpacity(OVERLAY_OPACITY);
    const layer = app.activeDocument.activeLayers[0] || placedLayer;
    await moveLayerBelowReference(layer, anchor);
    anchor = layer;
    placed += 1;
  }
  return placed;
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

  const targetLayer = findBackgroundLayer(doc);
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
}

async function savePsdInModal(folder, shotId) {
  const file = await folder.createFile(`${shotId}.psd`, { overwrite: true });
  await app.activeDocument.saveAs.psd(file, {}, false);
  return file;
}

async function exportPreviewInModal(folder, shotId) {
  const file = await folder.createFile(`${shotId}_preview.png`, { overwrite: true });
  await app.activeDocument.saveAs.png(file, {}, true);
  return file;
}

async function createCanvasDocumentInModal(shotId) {
  await photoshop.action.batchPlay(
    [
      {
        _obj: "make",
        _target: [{ _ref: "document" }],
        using: {
          _obj: "document",
          name: shotId,
          width: { _unit: "pixelsUnit", _value: CANVAS_WIDTH },
          height: { _unit: "pixelsUnit", _value: CANVAS_HEIGHT },
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
  const psdFile = await savePsdInModal(folder, shotId);
  const previewFile = await exportPreviewInModal(folder, shotId);
  return { psdFile, previewFile };
}

async function openOrActivateShotDocument(shotId, psdEntry) {
  const existing = findOpenDocumentForShot(shotId);
  if (existing) {
    return existing;
  }
  if (psdEntry) {
    const opened = await openPsdEntry(psdEntry);
    return opened || app.activeDocument;
  }
  await createCanvasDocumentInModal(shotId);
  return app.activeDocument;
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

async function finishShotSwitch(previousDoc, nextDoc) {
  const activeNext = activateDocument(nextDoc || app.activeDocument);
  if (!activeNext) {
    throw new Error("Could not activate the target shot document.");
  }
  if (previousDoc && previousDoc.id !== activeNext.id) {
    await closeDocumentInModal(previousDoc, activeNext);
  }
  return activeNext;
}

async function saveCurrentShot() {
  await exportBoth();
  await updateProjectAfterSave();
  setStatus(`Saved ${currentShotId()}. Stay in Photoshop — Storyboard Tool will sync in the background.`);
}

async function saveAndGoNext() {
  const shotId = currentShotId();
  const currentFolder = await requireWorkingFolder();
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
    await applyCanvasBackgroundInModal();
    await savePsdInModal(currentFolder, shotId);
    await exportPreviewInModal(currentFolder, shotId);

    if (!nextShot) {
      return;
    }

    const nextShotId = nextShot.shot_id;
    const nextDoc = await openOrActivateShotDocument(nextShotId, nextPsdEntry);
    if (!nextDoc) {
      throw new Error(`Could not open ${nextShotId}.`);
    }

    if (!nextPsdEntry) {
      canvasColor = nextColor;
      await applyCanvasBackgroundInModal();
      await saveActiveDocumentToFolder(nextFolder, nextShotId);
      createdNewNext = true;
    }

    await finishShotSwitch(previousDoc, app.activeDocument || nextDoc);
  });

  await updateProjectAfterSave(shotId, currentFolder);

  if (!nextShot) {
    setStatus(`Saved ${shotId}. No more shots in the project.`);
    return;
  }

  setSelectedShotId(nextShot.shot_id);
  shotFolder = nextFolder;
  canvasColor = nextColor;
  updateColorSwatch();

  if (createdNewNext) {
    const psdFile = await nextFolder.getEntry(`${nextShot.shot_id}.psd`);
    await writeBridgeFiles(nextShot.shot_id, `shots/${nextShot.shot_id}/${nextShot.shot_id}.psd`, nextFolder);
    if (projectData) {
      const shot = projectData.shots.find((item) => item.shot_id === nextShot.shot_id);
      if (shot) {
        applySavedPaths(shot, nextShot.shot_id, await fileUnixMtime(psdFile));
        await saveProjectJson();
      }
    }
  }

  setStatus(`Saved ${shotId}. Now working on ${nextShot.shot_id}.`);
}

async function switchToSelectedShot() {
  const shotId = currentShotId();
  await switchToShot(shotId);
}

async function switchToShot(shotId) {
  if (detectShotFromDocument() === shotId && app.activeDocument) {
    setSelectedShotId(shotId);
    shotFolder = await ensureShotStructure(shotId);
    setStatus(`Already working on ${shotId}.`);
    return;
  }

  const folder = await ensureShotStructure(shotId);
  const nextColor = await readProjectCanvasColor(folder);
  const psdName = `${shotId}.psd`;
  let psdEntry = null;
  let createdNew = false;

  try {
    psdEntry = await folder.getEntry(psdName);
  } catch {
    psdEntry = null;
  }

  await runModal(`Open ${shotId}`, async () => {
    const previousDoc = app.activeDocument;
    const nextDoc = await openOrActivateShotDocument(shotId, psdEntry);
    if (!nextDoc) {
      throw new Error(`Could not open ${shotId}.`);
    }
    if (!psdEntry) {
      canvasColor = nextColor;
      await applyCanvasBackgroundInModal();
      await saveActiveDocumentToFolder(folder, shotId);
      createdNew = true;
    }
    await finishShotSwitch(previousDoc, app.activeDocument || nextDoc);
  });

  setSelectedShotId(shotId);
  shotFolder = folder;
  $("folderLabel").textContent = `Folder: ${shotFolder.nativePath || shotFolder.name}`;
  canvasColor = nextColor;
  updateColorSwatch();

  if (createdNew) {
    const psdFile = await folder.getEntry(psdName);
    await writeBridgeFiles(shotId, `shots/${shotId}/${shotId}.psd`);
    if (projectData) {
      const shot = projectData.shots.find((item) => item.shot_id === shotId);
      if (shot) {
        applySavedPaths(shot, shotId, await fileUnixMtime(psdFile));
        await saveProjectJson();
      }
    }
    setStatus(`Created canvas for ${shotId}.`);
    return;
  }

  setStatus(psdEntry ? `Opened ${shotId}.` : `Opened ${shotId}.`);
}

async function createCanvasForShot(shotId) {
  const folder = await ensureShotStructure(shotId);
  let createdNew = false;
  await runModal(`Create ${shotId}`, async () => {
    await createCanvasDocumentInModal(shotId);
    await applyCanvasBackgroundInModal();
    await saveActiveDocumentToFolder(folder, shotId);
    createdNew = true;
  });
  if (!createdNew) {
    return;
  }
  const psdFile = await folder.getEntry(`${shotId}.psd`);
  await writeBridgeFiles(shotId, `shots/${shotId}/${shotId}.psd`);
  if (projectData) {
    const shot = projectData.shots.find((item) => item.shot_id === shotId);
    if (shot) {
      applySavedPaths(shot, shotId, await fileUnixMtime(psdFile));
      await saveProjectJson();
    }
  }
}

async function exportBoth() {
  const folder = await requireWorkingFolder();
  const shotId = currentShotId();
  await runModal("Save shot", async () => {
    await applyCanvasBackgroundInModal();
    await savePsdInModal(folder, shotId);
    await exportPreviewInModal(folder, shotId);
  });
}

async function updateProjectAfterSave(shotId = currentShotId(), folder = null) {
  const resolvedFolder = folder || (await ensureShotStructure(shotId));
  const psdFile = await resolvedFolder.getEntry(`${shotId}.psd`);
  const mtime = await fileUnixMtime(psdFile);
  await writeBridgeFiles(shotId, `shots/${shotId}/${shotId}.psd`, resolvedFolder);
  if (!projectData) {
    return;
  }
  const shot = (projectData.shots || []).find((item) => item.shot_id === shotId);
  if (!shot) {
    return;
  }
  applySavedPaths(shot, shotId, mtime);
  await saveProjectJson();
}

function applySavedPaths(shot, shotId, mtime) {
  shot.source_file_path = `shots/${shotId}/${shotId}.psd`;
  shot.preview_image_path = `shots/${shotId}/${shotId}_preview.png`;
  shot.image_path = shot.preview_image_path;
  shot.thumbnail_path = `shots/${shotId}/${shotId}_thumb.png`;
  shot.source_sync_mtime = mtime;
}

async function writeBridgeFiles(shotId, sourcePath, folder = null) {
  const resolvedFolder = folder || (await ensureShotStructure(shotId));
  const payload = {
    canvas_background_color: canvasColor,
    shot_id: shotId,
    source_file_path: sourcePath,
    last_saved_at: new Date().toISOString(),
  };
  await writeEntryText(
    await resolvedFolder.createFile("storyboard_bridge.json", { overwrite: true }),
    JSON.stringify(payload, null, 2),
  );
  await writeEntryText(await resolvedFolder.createFile("canvas_color.txt", { overwrite: true }), `${canvasColor}\n`);
  if (projectRoot) {
    await writeEntryText(
      await projectRoot.createFile("storyboard_bridge.json", { overwrite: true }),
      JSON.stringify(payload, null, 2),
    );
    await writeEntryText(
      await projectRoot.createFile("canvas_color.txt", { overwrite: true }),
      `${canvasColor}\n`,
    );
  }
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
}

function isDocumentOpen(doc) {
  if (!doc?.id) {
    return false;
  }
  return app.documents.some((item) => item.id === doc.id);
}

async function requireWorkingFolder() {
  if (!app.activeDocument) {
    throw new Error("No active Photoshop document.");
  }
  return ensureShotStructure(currentShotId());
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

function findBackgroundLayer(doc) {
  try {
    if (doc.backgroundLayer) {
      return doc.backgroundLayer;
    }
  } catch {
    // Some documents do not expose backgroundLayer.
  }

  for (const layer of doc.layers) {
    if (layer.isBackgroundLayer || layer.name === "Background") {
      return layer;
    }
  }

  const layers = doc.layers;
  return layers.length ? layers[layers.length - 1] : null;
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
  try {
    const root = projectRoot || (await findProjectRoot(folder));
    if (root) {
      const rootTxt = await readCanvasColorTxt(root);
      if (rootTxt) {
        return rootTxt;
      }
      for (const fileName of ["storyboard_live_bridge.json", "storyboard_bridge.json", "settings.json"]) {
        const value = await readJsonField(root, fileName, "canvas_background_color");
        if (value) {
          return normalizeHexColor(value);
        }
      }
    }

    const localTxt = await readCanvasColorTxt(folder);
    if (localTxt) {
      return localTxt;
    }

    const localBridge = await readJsonField(folder, "storyboard_bridge.json", "canvas_background_color");
    if (localBridge) {
      return normalizeHexColor(localBridge);
    }
  } catch (error) {
    setStatus(`Color read failed: ${error.message || error}`);
  }
  return DEFAULT_CANVAS_COLOR;
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
