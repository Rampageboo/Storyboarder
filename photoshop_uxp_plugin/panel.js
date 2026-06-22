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
let connectionMode = "disconnected";
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
let lastPluginContext = null;
let workContextSyncInFlight = false;
let workContextSyncPending = false;
let focusStoryboardAfterPreviewExport = false;
let autoAddAtEnd = true;
const boardBackgroundSigByShot = new Map();

function $(id) {
  return document.getElementById(id);
}

function init() {
  $("openSettingsView")?.addEventListener("click", () => setPluginView("settings"));
  $("openAdvancedView")?.addEventListener("click", () => setPluginView("advanced"));
  $("settingsBack")?.addEventListener("click", () => setPluginView("main"));
  $("advancedBack")?.addEventListener("click", () => setPluginView("main"));
  $("chooseProject")?.addEventListener("click", () => runPanelAction(chooseProjectFolder));
  $("chooseFolder")?.addEventListener("click", () => runPanelAction(chooseShotFolder));
  $("shotSelect")?.addEventListener("change", () => runPanelAction(switchToSelectedShot));
  $("openShot")?.addEventListener("click", () => runPanelAction(switchToSelectedShot));
  $("focusCurrentTab")?.addEventListener("click", () => runPanelAction(focusCurrentShotTab));
  $("ensureTemplateLayers")?.addEventListener("click", () => runPanelAction(ensureTemplateLayersForActiveDocument));
  $("quickStatusButtons")?.addEventListener("click", (event) => {
    const button = event.target?.closest?.("[data-status]");
    if (button) {
      runPanelAction(() => updateShotStatusViaBackend(button.getAttribute("data-status"))).catch(() => {});
    }
  });
  $("previousShot")?.addEventListener("click", () => runPanelAction(goToPreviousShot));
  $("nextShot")?.addEventListener("click", () => runPanelAction(goToNextShot));
  $("overlayPrevious")?.addEventListener("click", () => runPanelAction(overlayPreviousShots));
  $("overlayNext")?.addEventListener("click", () => runPanelAction(overlayNextShots));
  $("clearOverlay")?.addEventListener("click", () => runPanelAction(clearOverlayLayers));
  $("overlayCount")?.addEventListener("change", () => clampOverlayCountInput());
  $("overlayCount")?.addEventListener("input", () => clampOverlayCountInput());
  $("overlayOpacity")?.addEventListener("change", () => clampOverlayOpacityInput());
  $("overlayOpacity")?.addEventListener("input", () => clampOverlayOpacityInput());
  $("applyBackground")?.addEventListener("click", () => runPanelAction(applyCanvasBackground));
  $("saveAndStay")?.addEventListener("click", () => { if (!_isSaving) runPanelAction(saveCurrentShotGuarded); });
  $("saveAndNext")?.addEventListener("click", () => { if (!_isSaving) runPanelAction(saveAndGoNextGuarded); });
  $("autoAddShot")?.addEventListener("change", () => runPanelAction(() => updateAutoAddAtEndSetting("autoAddShot")));
  $("settingsAutoAddShot")?.addEventListener("change", () => runPanelAction(() => updateAutoAddAtEndSetting("settingsAutoAddShot")));
  $("focusStoryboardAfterExport")?.addEventListener("change", () =>
    runPanelAction(() => updateFocusStoryboardAfterExportSetting("focusStoryboardAfterExport")),
  );
  $("settingsFocusStoryboardAfterExport")?.addEventListener("change", () =>
    runPanelAction(() => updateFocusStoryboardAfterExportSetting("settingsFocusStoryboardAfterExport")),
  );
  $("recoverPsd")?.addEventListener("click", () => runPanelAction(recoverCurrentShotPsd));
  $("relinkNow")?.addEventListener("click", () => runPanelAction(reconnectStoryboardBridge));

  // Scene 2D export buttons (Part 9)
  $("scene2dSaveAndStay")?.addEventListener("click", () => {
    if (!_isScene2DSaving) runPanelAction(saveScene2DGuarded);
  });
  $("scene2dSaveAndNext")?.addEventListener("click", () => {
    if (!_isScene2DSaving) runPanelAction(saveAndGoNextScene2DGuarded);
  });

  // Scene 2D work-panel navigation (Part 7)
  $("previousPerspective")?.addEventListener("click", () => runPanelAction(goToPreviousPerspective));
  $("nextPerspective")?.addEventListener("click", () => runPanelAction(goToNextPerspective));
  $("openPerspective")?.addEventListener("click", () => runPanelAction(openSelectedPerspective));
  $("focusCurrentPerspectiveTab")?.addEventListener("click", () => runPanelAction(focusCurrentPerspectiveTab));
  $("perspectiveSelect")?.addEventListener("change", (event) => {
    const select = event.target;
    const option = select?.selectedOptions?.[0] || null;
    const perspectiveType = String(option?.dataset?.perspectiveType || "psd").toLowerCase();
    if (perspectiveType === "image") {
      setStatus("Image perspectives can be referenced from Storyboarder, but cannot be opened as PSD tabs.");
      return;
    }
    const key = select?.value || "";
    const [, sceneId, perspectiveId] = key.split(":");
    if (sceneId && perspectiveId) {
      runPanelAction(() => openPerspectiveById(sceneId, perspectiveId));
    }
  });

  setPluginView("main");
  setLinkedUi(false);
  setLinkStatus("Connecting…", true);
  startStoryboardBridgePolling();
  registerDocumentBackgroundListeners();
  startActiveDocumentWatch();
  syncWorkContextFromActiveDocument().catch(() => {});
  scheduleBackgroundSyncForActiveDocument();
  updateCurrentShotIndicator();
  renderCurrentShotCard();
  loadPluginSettings().catch(() => {});
}

function setLinkedUi(linked) {
  const linkedPanel = $("linkedPanel");
  const colorSection = $("colorSection");
  if (linkedPanel) linkedPanel.hidden = !linked;
  if (colorSection) colorSection.hidden = linked;
}

function clearScene2DWorkNavigation() {
  const select = $("perspectiveSelect");
  if (select) select.innerHTML = "";
  const groupLabel = $("workScene2dGroup");
  if (groupLabel) groupLabel.textContent = "";
  for (const id of ["previousPerspective", "nextPerspective", "openPerspective", "focusCurrentPerspectiveTab"]) {
    const button = $(id);
    if (button) button.disabled = true;
  }
}

function renderDisconnectedState(message = "Not connected") {
  connectionMode = "disconnected";
  linkedFromStoryboard = false;
  lastPluginContext = null;
  projectData = null;
  setLinkedUi(false);
  setLinkStatus(message, true);
  if (typeof setWorkContext === "function") {
    setWorkContext(null);
  }
  clearScene2DWorkNavigation();
  const currentShotCard = $("currentShotCard");
  const linkedPanel = $("linkedPanel");
  const scene2dPanel = $("scene2dPanel");
  const scene2dCard = $("scene2dCard");
  const scene2dImageCard = $("scene2dImageCard");
  const scene2dExportPanel = $("scene2dExportPanel");
  const unmatchedCard = $("unmatchedCard");
  const shotNav = $("workShotNav");
  const scene2dNav = $("workScene2dNav");
  const onionSkin = $("workOnionSkin");
  const workNoCtx = $("workNoContext");
  if (currentShotCard) currentShotCard.hidden = true;
  if (linkedPanel) linkedPanel.hidden = true;
  if (scene2dPanel) scene2dPanel.hidden = true;
  if (scene2dCard) scene2dCard.hidden = true;
  if (scene2dImageCard) scene2dImageCard.hidden = true;
  if (scene2dExportPanel) scene2dExportPanel.hidden = true;
  if (unmatchedCard) unmatchedCard.hidden = true;
  if (shotNav) shotNav.hidden = true;
  if (scene2dNav) scene2dNav.hidden = true;
  if (onionSkin) onionSkin.hidden = true;
  if (workNoCtx) {
    workNoCtx.hidden = false;
    const msg = workNoCtx.querySelector?.(".empty-msg");
    if (msg) msg.textContent = message;
  }
  const shotSelect = $("shotSelect");
  if (shotSelect) shotSelect.innerHTML = "";
  renderQuickStatusButtons(null, false);
  for (const id of [
    "saveAndStay",
    "saveAndNext",
    "scene2dSaveAndStay",
    "scene2dSaveAndNext",
    "previousShot",
    "nextShot",
    "openShot",
    "focusCurrentTab",
  ]) {
    const button = $(id);
    if (button) button.disabled = true;
  }
  for (const id of [
    "shotCardMode",
    "shotCardIndex",
    "shotCardTitle",
    "shotCardStatus",
    "shotCardMeta",
    "shotCardAction",
    "shotCardCamera",
    "shotCardNotes",
    "scene2dSceneTitle",
    "scene2dPerspectiveTitle",
    "scene2dPerspectiveType",
    "scene2dPerspectiveIndex",
  ]) {
    const node = $(id);
    if (node) node.textContent = "";
  }
}

function renderFolderAccessErrorState(message = "Folder access failed") {
  renderDisconnectedState(message);
  connectionMode = "folder-error";
  setLinkStatus("Folder access failed", true);
  setStatus("Use Advanced to choose the project folder or reconnect.");
}

function setPluginView(view) {
  const next = view === "settings" || view === "advanced" ? view : "main";
  const mainView = $("mainView");
  const settingsView = $("settingsView");
  const advancedView = $("advancedView");
  if (mainView) mainView.hidden = next !== "main";
  if (settingsView) settingsView.hidden = next !== "settings";
  if (advancedView) advancedView.hidden = next !== "advanced";
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
  const projectLabelEl = $("projectLabel");
  if (projectLabelEl) projectLabelEl.textContent = `Project: ${folder.nativePath || folder.name}`;
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
  connectionMode = "manual-project";
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
  const folderLabelEl = $("folderLabel");
  if (folderLabelEl) folderLabelEl.textContent = `Folder: ${shotFolder.nativePath || shotFolder.name}`;
  const folderName = shotFolder.name || "";
  if (isValidShotId(folderName)) {
    setSelectedShotId(folderName);
  }
  const root = await findProjectRoot(shotFolder);
  if (root) {
    projectRoot = root;
    projectData = await loadProjectJson();
    const rootLabelEl = $("projectLabel");
    if (rootLabelEl) rootLabelEl.textContent = `Project: ${root.nativePath || root.name}`;
    populateShotSelect();
  }
  canvasColor = await readProjectCanvasColor(shotFolder);
  updateColorSwatch();
  linkedFromStoryboard = false;
  connectionMode = "manual-folder";
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
  const isConnected = !waiting && (message.startsWith("Linked") || message.startsWith("Manual"));
  node.classList.toggle("connected", isConnected);
  const dot = $("connDot");
  if (dot) {
    dot.setAttribute("data-state", waiting ? "waiting" : isConnected ? "connected" : "off");
  }
}

function pathToFileUrl(nativePath) {
  const path = String(nativePath || "").trim().replace(/\\/g, "/");
  if (!path) return "";
  if (path.startsWith("file:")) return path;
  if (/^[A-Za-z]:\//.test(path)) return `file:///${path}`;
  return `file://${path.startsWith("/") ? "" : "/"}${path}`;
}

async function documentNativePath(doc) {
  if (!doc) return "";
  for (const key of ["path", "fullName", "_path"]) {
    const candidate = nativePathFromEntryLike(doc[key]);
    if (candidate) return candidate;
  }
  try {
    if (typeof doc.savePath === "function") {
      const candidate = nativePathFromEntryLike(await doc.savePath());
      if (candidate) return candidate;
    }
  } catch {
    // Unsaved/cloud documents may not expose a local path.
  }
  return "";
}

async function detectWorkItemFromDocument(docOrContext = app.activeDocument, maybeContext = lastPluginContext) {
  let doc = docOrContext;
  let context = maybeContext;
  if (docOrContext && Array.isArray(docOrContext.work_items)) {
    doc = app.activeDocument;
    context = docOrContext;
  }
  if (!doc) return null;
  const nativePath = await documentNativePath(doc);
  const item = nativePath ? findWorkItemByNativePath(nativePath, context, linkedProjectRootPath) : null;
  if (item) return workContextFromItem(item);

  const shotId = shotIdFromDocumentName(doc.name);
  if (shotId) {
    const items = Array.isArray(context?.work_items) ? context.work_items : [];
    const shotItem = items.find((candidate) => candidate.kind === "shot" && candidate.shot_id === shotId);
    return workContextFromItem(shotItem) || { kind: "shot", key: `shot:${shotId}`, shot_id: shotId };
  }
  return null;
}

async function findOpenDocumentForWorkItem(workItemOrContext) {
  const item = workItemOrContext || {};
  for (const doc of Array.from(app.documents || [])) {
    const nativePath = await documentNativePath(doc);
    if (!nativePath) continue;
    if (
      sameNativePath(nativePath, item.source_native_path) ||
      sameNativePath(nativePath, projectRelativeNativePath(lastPluginContext, item.source_file_path, linkedProjectRootPath))
    ) {
      return doc;
    }
  }
  return null;
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
    autoAddAtEnd = settings?.auto_add_at_end !== false;
  } catch {
    focusStoryboardAfterPreviewExport = false;
    autoAddAtEnd = true;
  }
  syncPluginSettingsCheckboxes();
}

function syncPluginSettingsCheckboxes() {
  for (const id of ["focusStoryboardAfterExport", "settingsFocusStoryboardAfterExport"]) {
    const checkbox = $(id);
    if (checkbox) checkbox.checked = focusStoryboardAfterPreviewExport;
  }
  for (const id of ["autoAddShot", "settingsAutoAddShot"]) {
    const checkbox = $(id);
    if (checkbox) checkbox.checked = autoAddAtEnd;
  }
}

async function savePluginSettings() {
  const dataFolder = await fs.getDataFolder();
  const file = await dataFolder.createFile(PLUGIN_SETTINGS_FILE, { overwrite: true });
  await writeEntryText(
    file,
    JSON.stringify(
      {
        focus_storyboard_after_preview_export: focusStoryboardAfterPreviewExport,
        auto_add_at_end: autoAddAtEnd,
      },
      null,
      2,
    ),
  );
}

async function updateFocusStoryboardAfterExportSetting(sourceId = "focusStoryboardAfterExport") {
  const checkbox = $(sourceId);
  focusStoryboardAfterPreviewExport = Boolean(checkbox?.checked);
  syncPluginSettingsCheckboxes();
  await savePluginSettings();
}

async function updateAutoAddAtEndSetting(sourceId = "autoAddShot") {
  const checkbox = $(sourceId);
  autoAddAtEnd = checkbox?.checked !== false;
  syncPluginSettingsCheckboxes();
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

async function getOpenWorkKeys() {
  // Enumerate all open documents and map each to a work key.
  const keys = new Set();
  try {
    for (const doc of app.documents) {
      const item = await detectWorkItemFromDocument(doc, lastPluginContext);
      if (item?.key) {
        keys.add(item.key);
      }
    }
  } catch {
    // Document enumeration is best-effort.
  }
  return [...keys];
}

async function sendPluginHeartbeat(live) {
  const openShotIds = getOpenShotIds();
  const openWorkKeys = await getOpenWorkKeys();
  const activeItem = await detectWorkItemFromDocument(app.activeDocument, lastPluginContext);
  const activeWorkKey = activeItem?.key || "";
  const selectedShotId = activeItem?.kind === "shot" ? activeItem.shot_id : "";
  const payload = JSON.stringify({
    at: new Date().toISOString(),
    plugin: "storyboard-bridge",
    project_root: live?.project_root || "",
    selected_shot_id: selectedShotId,
    open_shot_ids: openShotIds,
    active_work_key: activeWorkKey,
    open_work_keys: openWorkKeys,
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
  const body = JSON.stringify({
    open_shot_ids: openShotIds,
    selected_shot_id: selectedShotId,
    active_work_key: activeWorkKey,
    open_work_keys: openWorkKeys,
  });
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
    if (shouldPreserveManualMode(connectionMode)) {
      setLinkStatus("Storyboarder unavailable", true);
      return;
    }
    renderDisconnectedState("Not connected");
    return;
  }

  if (!live.app_running) {
    if (shouldPreserveManualMode(connectionMode)) {
      setLinkStatus("Storyboard not running", true);
      return;
    }
    renderDisconnectedState("Storyboard not running");
    return;
  }
  if (!live.connected) {
    if (shouldPreserveManualMode(connectionMode)) {
      setLinkStatus("Open a project in Storyboard", true);
      return;
    }
    renderDisconnectedState("Open a project in Storyboard");
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

  const root = await resolveFolderEntry(live.project_root);
  if (!root) {
    renderFolderAccessErrorState("Folder access failed");
    canvasColor = normalizeHexColor(live.canvas_background_color);
    const fallbackSize = normalizeCanvasSize(live.canvas_width, live.canvas_height);
    canvasWidth = fallbackSize.width;
    canvasHeight = fallbackSize.height;
    updateColorSwatch();
    return;
  }

  connectionMode = "linked";
  linkedFromStoryboard = true;
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

  // Determine the effective shot ID:
  // - When the active document IS a shot, trust it (not Storyboarder's selection).
  // - When there is no active document, use Storyboarder's pending selection as a hint.
  // - When the active document is a Scene 2D or unmatched, do NOT fall back to
  //   live.selected_shot_id — that would map shot-only automation onto the wrong PSD.
  const activeCtx = activeWorkContext();
  let shotId;
  if (activeCtx?.kind === "shot") {
    shotId = activeCtx.shot_id;
  } else if (!app.activeDocument) {
    shotId = live.selected_shot_id || null;
  } else {
    shotId = null;
  }
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

  // Only apply the canvas color to the active document when it is a shot.
  // Scene 2D and unmatched documents must not receive shot background automation.
  if (colorChanged && app.activeDocument && activeCtx?.kind === "shot" && isAutoApplyColorEnabled()) {
    await applyCanvasBackground();
  }

  const projectLabel = context?.project_name || live.project_name || "Storyboarder";
  setLinkStatus(`Linked · ${projectLabel}`);
  if (!isSame && shotId) {
    const workItem = shotWorkItemById(shotId);
    const displayLabel = workItem
      ? formatShotDisplayLabel(workItem)
      : shotDisplayLabel(shotId, currentShotIndex(), currentShotFromProjectData()?.title);
    setStatus(`Synced · ${displayLabel || "Shot"}`);
  }

  if (shotId && app.activeDocument && activeCtx?.kind === "shot" && detectShotFromDocument() === shotId) {
    scheduleBackgroundSyncForActiveDocument();
  }

  await maybeHandleFocusRequest(live);

  // Project data may have just loaded; refresh the label so it can show titles.
  updateCurrentShotIndicator();
}

// Storyboard Tool sets a focus request (kind + key/shot_id + monotonic token)
// when the user asks to open a work item that is already a tab in Photoshop.
// Acting only on a new token prevents passive polls from yanking tabs, and
// adopting the current token as a baseline on first sight stops stale replay.
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

  const kind = String(request?.kind || "shot");

  if (kind === "scene2d") {
    const sceneId = String(request?.scene_id || "").trim();
    const perspectiveId = String(request?.perspective_id || "").trim();
    if (!sceneId || !perspectiveId) return;
    focusSwitchInFlight = true;
    try {
      const doc = await findOpenDocumentForWorkItem(request);
      if (doc) {
        await app.setActiveDocument(doc);
        await syncWorkContextFromActiveDocument(lastPluginContext);
        setStatus(`Switched to perspective ${perspectiveId} (already open).`);
      } else {
        setStatus(`Perspective ${perspectiveId} not open in Photoshop.`);
      }
    } catch (error) {
      setStatus(error.message || String(error));
    } finally {
      focusSwitchInFlight = false;
    }
    return;
  }

  // Default: shot focus
  const shotId = String(request?.shot_id || "").trim().toLowerCase();
  if (!shotId) {
    return;
  }
  focusSwitchInFlight = true;
  try {
    const doc = await findOpenDocumentForWorkItem(request);
    if (doc) {
      await app.setActiveDocument(doc);
      await syncWorkContextFromActiveDocument(lastPluginContext);
    } else {
      await switchToShot(shotId);
    }
    const switchLabel = shotDisplayLabel(shotId, currentShotIndex(), currentShotFromProjectData()?.title);
    setStatus(`Switched to ${switchLabel || "Shot"}.`);
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
  // Use work-item metadata when available (provides backend-authoritative index + shot_title).
  if (typeof shotDisplayLabel === "function") {
    return shotDisplayLabel(shot.shot_id, index, shot?.title);
  }
  const order = index + 1;
  const title = String(shot?.title || "").trim();
  return title ? `${order}. ${title}` : `${order}. Untitled shot`;
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
  const shotIdEl = $("shotId");
  if (shotIdEl) shotIdEl.value = shotId;
  const select = $("shotSelect");
  if (select) {
    select.value = shotId;
  }
  updateOverlayCountLimits();
  renderCurrentShotCard();
}

function currentShotIndex() {
  const shotId = String($("shotId")?.value || $("shotSelect")?.value || "").trim().toLowerCase();
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
  const overlayPrev = $("overlayPrevious");
  if (overlayPrev) overlayPrev.disabled = previousAvailable === 0;
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
  const focusLabel = shotDisplayLabel(shotId, currentShotIndex(), currentShotFromProjectData()?.title);
  setStatus(`Focused tab for ${focusLabel || "Shot"}.`);
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
  const value = String($("shotId")?.value || $("shotSelect")?.value || "").trim();
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
  if (index < 0) return "No shot selected";
  // Use work-item index/count when available; fall back to array position.
  const workItem = (typeof shotWorkItemById === "function") ? shotWorkItemById(shot.shot_id) : null;
  const pos = workItem?.index ?? (index + 1);
  const total = workItem?.count ?? shots.length;
  const dur = shot?.duration_seconds ? ` · ${Number(shot.duration_seconds).toFixed(1)}s` : "";
  return `${pos} / ${total}${dur}`;
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
  // Shot card must not appear in scene2d or unmatched mode.
  const ctx = (typeof activeWorkContext === "function") ? activeWorkContext() : null;
  if (ctx?.kind === "scene2d" || ctx?.kind === "unmatched") {
    card.hidden = true;
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
  $("shotCardMode").textContent = "SHOT";
  $("shotCardIndex").textContent = shot ? currentShotIndexLabel(shot) : "";
  $("shotCardTitle").textContent = compactText(shot?.title, "Untitled shot");
  $("shotCardStatus").textContent = compactText(shot?.status, linkedFromStoryboard ? "Draft" : "—");
  const meta = [];
  if (compactText(shot?.scene)) meta.push(`Scene: ${shot.scene}`);
  if (compactText(shot?.sequence)) meta.push(`Seq: ${shot.sequence}`);
  $("shotCardMeta").textContent = meta.join(" · ");
  setCardSection("shotCardAction", "Action", shot?.action_note || shot?.description);
  setCardSection("shotCardCamera", "Camera", shot?.camera_note);
  setCardSection("shotCardNotes", "Notes", latestCommentSummary(shot));
  renderQuickStatusButtons(shot, Boolean(linkedFromStoryboard && shot));
}

// ── Work mode UI routing (Parts 4–6) ────────────────────────────────────────
// Switches both panels between shot / scene2d / unmatched modes and updates
// the Work-panel context eyebrow to show the current mode label.
// CRITICAL: only one context card may be visible at a time.
function renderWorkModeUI(ctx) {
  const mode = ctx?.kind === "scene2d" ? "scene2d" : (ctx?.kind === "unmatched" ? "unmatched" : "shot");

  // ── Work-panel eyebrow (Part 5) ──────────────────────────────────────────
  const modeEl  = $("workContextMode");
  const sceneEl = $("workScene2dGroup");
  if (modeEl) {
    if (mode === "scene2d") {
      modeEl.textContent = "SCENE 2D";
    } else if (mode === "unmatched") {
      modeEl.textContent = "UNLINKED DOCUMENT";
    } else {
      modeEl.textContent = "SHOT";
    }
  }
  if (sceneEl) {
    if (mode === "scene2d" && ctx?.scene_title) {
      sceneEl.textContent = `· ${ctx.scene_title}`;
      sceneEl.hidden = false;
    } else {
      sceneEl.textContent = "";
      sceneEl.hidden = true;
    }
  }

  // ── Bridge panel — exactly one context section visible ───────────────────
  const currentShotCard = $("currentShotCard");
  const linkedPanel     = $("linkedPanel");
  const scene2dPanel    = $("scene2dPanel");
  const unmatchedCard   = $("unmatchedCard");
  if (currentShotCard) currentShotCard.hidden = mode !== "shot";
  if (linkedPanel)     linkedPanel.hidden     = mode !== "shot";
  if (scene2dPanel)    scene2dPanel.hidden    = mode !== "scene2d";
  if (unmatchedCard) {
    unmatchedCard.hidden = mode !== "unmatched";
    if (mode === "unmatched") {
      const nameEl = $("unmatchedDocName");
      if (nameEl) nameEl.textContent = ctx?.document_name || "";
    }
  }

  // ── Work panel ────────────────────────────────────────────────────────────
  const shotNav   = $("workShotNav");
  const scene2dNav = $("workScene2dNav");
  const onionSkin = $("workOnionSkin");
  const workNoCtx = $("workNoContext");
  if (shotNav)    shotNav.hidden    = mode !== "shot";
  if (scene2dNav) scene2dNav.hidden = mode !== "scene2d";
  if (onionSkin)  onionSkin.hidden  = mode !== "shot";
  if (workNoCtx)  workNoCtx.hidden  = mode !== "unmatched";
  renderScene2DWorkNavigation(mode === "scene2d" ? ctx : null, lastPluginContext);
  if (mode === "shot") {
    for (const id of ["previousShot", "nextShot", "openShot", "focusCurrentTab"]) {
      const button = $(id);
      if (button) button.disabled = false;
    }
  }

  for (const id of ["saveAndStay", "saveAndNext", "scene2dSaveAndStay", "scene2dSaveAndNext"]) {
    const button = $(id);
    if (button) button.disabled = mode === "unmatched";
  }

  if (mode === "scene2d") {
    renderScene2DCard(ctx);
  }
}

function renderScene2DWorkNavigation(ctx, pluginContext) {
  if (!ctx?.scene_id) {
    clearScene2DWorkNavigation();
    return;
  }
  const workItems = Array.isArray(pluginContext?.work_items) ? pluginContext.work_items : [];
  populatePerspectiveSelect(workItems, ctx.scene_id);
  const select = $("perspectiveSelect");
  if (select) {
    const key = ctx.key || `scene2d:${ctx.scene_id}:${ctx.perspective_id}`;
    select.value = key;
  }
  const isImage = String(ctx.perspective_type || "psd").toLowerCase() === "image";
  const previousButton = $("previousPerspective");
  const nextButton = $("nextPerspective");
  const openButton = $("openPerspective");
  const focusButton = $("focusCurrentPerspectiveTab");
  if (previousButton) previousButton.disabled = !ctx.previous_key;
  if (nextButton) nextButton.disabled = !ctx.next_key;
  if (openButton) openButton.disabled = isImage;
  if (focusButton) focusButton.disabled = isImage;
}

function renderScene2DCard(ctx) {
  if (!ctx) return;

  // PSD perspective card
  const card = $("scene2dCard");
  const imageCard = $("scene2dImageCard");
  const exportPanel = $("scene2dExportPanel");

  if (ctx.perspective_type === "image") {
    if (card) card.hidden = true;
    if (imageCard) imageCard.hidden = false;
    if (exportPanel) exportPanel.hidden = true;
    return;
  }

  // PSD perspective
  if (card) {
    card.hidden = false;
    const indexEl = $("scene2dPerspectiveIndex");
    if (indexEl) {
      const idx = ctx.index != null ? ctx.index : "?";
      const total = ctx.count != null ? ctx.count : "?";
      indexEl.textContent = `${idx} / ${total}`;
    }
    const sceneTitleEl = $("scene2dSceneTitle");
    if (sceneTitleEl) sceneTitleEl.textContent = ctx.scene_title || "";
    const perspTitleEl = $("scene2dPerspectiveTitle");
    if (perspTitleEl) perspTitleEl.textContent = ctx.perspective_title || "";
    const typeEl = $("scene2dPerspectiveType");
    if (typeEl) typeEl.textContent = (ctx.perspective_type || "psd").toUpperCase();
  }
  if (imageCard) imageCard.hidden = true;
  if (exportPanel) exportPanel.hidden = false;
}

// ── Scene 2D navigation (Work panel, Part 7) ─────────────────────────────────

async function goToPreviousPerspective() {
  const ctx = activeScene2DContext();
  if (!ctx?.previous_key) {
    setStatus("No previous perspective.");
    return;
  }
  const [, sceneId, perspectiveId] = ctx.previous_key.split(":");
  if (sceneId && perspectiveId) {
    await openPerspectiveById(sceneId, perspectiveId);
  }
}

async function goToNextPerspective() {
  const ctx = activeScene2DContext();
  if (!ctx?.next_key) {
    setStatus("No next perspective.");
    return;
  }
  const [, sceneId, perspectiveId] = ctx.next_key.split(":");
  if (sceneId && perspectiveId) {
    await openPerspectiveById(sceneId, perspectiveId);
  }
}

async function openPerspectiveById(sceneId, perspectiveId) {
  const payload = await requestStoryboardApi(
    `/api/project/scenes2d/${encodeURIComponent(sceneId)}/perspectives/${encodeURIComponent(perspectiveId)}/open`,
    { method: "POST" }
  );
  if (payload?.work_context) {
    applyWorkContext(payload.work_context);
  }
}

async function openSelectedPerspective() {
  const ctx = activeScene2DContext();
  if (!ctx?.scene_id || !ctx?.perspective_id) {
    throw new Error("No active Scene 2D perspective to open.");
  }
  await openPerspectiveById(ctx.scene_id, ctx.perspective_id);
}

async function focusCurrentPerspectiveTab() {
  const ctx = activeScene2DContext();
  if (!ctx?.perspective_id) throw new Error("No active perspective.");
  const doc = await findOpenDocumentForWorkItem(ctx);
  if (!doc) {
    throw new Error("This perspective source.psd is not open. Use 'Open perspective' to open it first.");
  }
  await app.setActiveDocument(doc);
  await syncWorkContextFromActiveDocument(lastPluginContext);
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
  const workItemForStatus = shotWorkItemById(shot.shot_id);
  const statusLabel = workItemForStatus ? formatShotDisplayLabel(workItemForStatus) : (shot.title || "Shot");
  setStatus(`Marked ${statusLabel} as ${status}.`);
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

// ── Generic work-item detection (Part 6) ─────────────────────────────────────
// Checks the active document path against all work_items from the plugin context
// (both shots and PSD perspectives). Returns a minimal work context object or null.
function detectWorkItemFromDocumentByNameOnlyDeprecated(context) {
  const docName = String(app.activeDocument?.name || "");
  if (!docName) return null;
  const docBase = docName.replace(/\.[^.]+$/, "").toLowerCase();

  // Check PSD perspectives first (higher specificity: UUID filename)
  const items = Array.isArray(context?.work_items) ? context.work_items : [];
  for (const item of items) {
    if (item.kind !== "scene2d") continue;
    // Perspective PSDs are stored as <perspective_id>.psd inside their folder
    const perspBase = String(item.perspective_id || "").toLowerCase();
    if (docBase === perspBase) {
      return {
        kind: "scene2d",
        key: item.key || `scene2d:${item.scene_id}:${item.perspective_id}`,
        scene_id: item.scene_id,
        perspective_id: item.perspective_id,
        scene_title: item.scene_title || "",
        perspective_title: item.perspective_title || "",
        perspective_type: item.perspective_type || "psd",
        source_file_path: item.source_file_path || "",
        index: item.index,
        count: item.count,
        previous_key: item.previous_key || null,
        next_key: item.next_key || null,
      };
    }
  }

  // Fall back to shot detection
  const shotId = shotIdFromDocumentName(docName);
  if (shotId) {
    return { kind: "shot", shot_id: shotId };
  }
  return null;
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
  return checkbox ? checkbox.checked !== false : autoAddAtEnd;
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

async function syncWorkContextFromActiveDocument(context = lastPluginContext) {
  lastPluginContext = context || lastPluginContext;
  if (workContextSyncInFlight) {
    workContextSyncPending = true;
    return;
  }
  workContextSyncInFlight = true;
  try {
    let doc = null;
    try {
      doc = app.activeDocument;
    } catch {
      doc = null;
    }
    if (!doc) {
      applyWorkContext(lastPluginContext?.work_context || null);
      updateCurrentShotIndicator();
      return;
    }
    const detected = await detectWorkItemFromDocument(doc, lastPluginContext);
    if (detected) {
      applyWorkContext(detected);
      if (detected.kind === "shot" && detected.shot_id) {
        setSelectedShotId(detected.shot_id);
      }
    } else {
      applyWorkContext({ kind: "unmatched", document_name: String(doc.name || "") });
    }
    updateCurrentShotIndicator();
  } finally {
    workContextSyncInFlight = false;
    if (workContextSyncPending) {
      workContextSyncPending = false;
      syncWorkContextFromActiveDocument(lastPluginContext).catch(() => {});
    }
  }
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
      syncWorkContextFromActiveDocument().catch(() => updateCurrentShotIndicator());
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
      syncWorkContextFromActiveDocument().catch(() => updateCurrentShotIndicator());
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

  const ctx = (typeof activeWorkContext === "function") ? activeWorkContext() : null;
  if (ctx?.kind === "scene2d") {
    node.classList.remove("muted");
    const label = ctx.label || [ctx.scene_title, ctx.perspective_title].filter(Boolean).join(" / ");
    const count = ctx.count ? ` · ${ctx.index || "?"} of ${ctx.count}` : "";
    node.textContent = `Editing Scene 2D · ${label || ctx.perspective_id}${count}`;
    node.hidden = false;
    renderCurrentShotCard();
    return;
  }
  if (ctx?.kind === "unmatched") {
    node.textContent = `Editing: ${ctx.document_name || doc.name} · Not linked to this project`;
    node.classList.add("muted");
    node.hidden = false;
    return;
  }

  const shotId = detectShotFromDocument();
  if (!shotId) {
    node.textContent = `Editing: ${doc.name} · Not linked to this project`;
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
  // Use human-readable label (no UUID) — prefer work item, fall back to array.
  const displayLabel = (typeof shotDisplayLabel === "function")
    ? shotDisplayLabel(shotId, index, shots[index]?.title)
    : `Shot ${index + 1}`;
  let text = `Editing ${displayLabel}`;
  if (index >= 0) {
    const shot = shots[index];
    const warnings = [];
    if (shot.broken_or_zero_byte_psd) warnings.push("PSD broken");
    else if (shot.source_path_missing || shot.psd_exists === false) warnings.push("PSD missing");
    if (shot.preview_out_of_date) warnings.push("preview stale");
    if (warnings.length) text += ` · ${warnings.join(", ")}`;
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
  // Scene 2D and unmatched documents must never receive shot background automation.
  const activeCtx = activeWorkContext();
  if (activeCtx && activeCtx.kind !== "shot") {
    return;
  }
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
  const ctx = activeWorkContext();
  if (ctx && ctx.kind !== "shot") {
    throw new Error(
      "The active Photoshop document is not a storyboard shot. Activate a linked shot PSD first.",
    );
  }
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
  const ctx = activeWorkContext();
  if (ctx && ctx.kind !== "shot") {
    throw new Error(
      "The active Photoshop document is not a storyboard shot. Activate a linked shot PSD first.",
    );
  }
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
  const switchFolderLabel = $("folderLabel");
  if (switchFolderLabel) switchFolderLabel.textContent = `Folder: ${shotFolder.nativePath || shotFolder.name}`;
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
  // Defense in depth: callers guard at the call site for automated paths;
  // this function-level check protects user-triggered button invocations.
  const ctx = activeWorkContext();
  if (ctx && ctx.kind !== "shot") {
    throw new Error(
      "The active Photoshop document is not a storyboard shot. Activate a linked shot PSD first.",
    );
  }
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
  const node = $("status");
  if (node) node.textContent = message;
}

// ── UXP multi-panel entrypoints ───────────────────────────────────────────
// A UXP plugin runs ONE shared document + JS context. Each panel is handed its
// own root node through the show() lifecycle hook; we move that panel's
// container (defined once in index.html) into it. appendChild relocates the
// node — including any listeners init() attached — so the Bridge and Work panels
// render different parts of the same document.
function attachPanelContent(rootNode, containerId) {
  const content = document.getElementById(containerId);
  if (!content || !rootNode) {
    return;
  }
  if (content.parentNode !== rootNode) {
    rootNode.appendChild(content);
  }
  content.hidden = false;
}

try {
  require("uxp").entrypoints.setup({
    panels: {
      storyboardBridgePanel: {
        show(rootNode) { attachPanelContent(rootNode, "bridge-panel"); },
      },
      storyboardWorkPanel: {
        show(rootNode) { attachPanelContent(rootNode, "work-panel"); },
      },
    },
  });
} catch (e) {
  // entrypoints.setup unavailable (e.g. opened outside Photoshop) — the document
  // still loads and wires up; the panels just are not split.
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}
