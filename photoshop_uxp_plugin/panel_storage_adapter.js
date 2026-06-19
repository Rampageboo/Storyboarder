// Compatibility layer for the Photoshop UXP panel after the project storage
// architecture moved from inline project.json / shots.csv to canonical shots.json.
//
// Loaded after panel.js and before DOMContentLoaded. It intentionally overrides a
// small set of global functions instead of editing the large panel.js file.
(() => {
  const SHOTS_JSON_NAME = "shots.json";
  const SHOTS_JSON_VERSION = 1;
  const PROJECT_JSON_VERSION = 3;
  const REF_SEGMENT_COLUMNS = ["ref_video_path", "ref_video_time", "ref_segment_time"];

  try {
    if (Array.isArray(SHOT_CSV_COLUMNS)) {
      for (const column of REF_SEGMENT_COLUMNS) {
        if (!SHOT_CSV_COLUMNS.includes(column)) {
          SHOT_CSV_COLUMNS.push(column);
        }
      }
    }
  } catch {
    // Older panel.js builds may not expose the CSV compatibility constants.
  }

  function asString(value) {
    return value == null ? "" : String(value);
  }

  function asNumber(value, fallback = 0) {
    const parsed = Number.parseFloat(value);
    return Number.isFinite(parsed) ? parsed : fallback;
  }

  function asObject(value, fallback = {}) {
    return value && typeof value === "object" && !Array.isArray(value) ? value : fallback;
  }

  function asArray(value, fallback = []) {
    return Array.isArray(value) ? value : fallback;
  }

  function normalizeShotRecord(raw = {}) {
    const imagePath = asString(raw.image_path);
    const previewPath = asString(raw.preview_image_path || imagePath);
    return {
      shot_id: asString(raw.shot_id).trim().toLowerCase(),
      title: asString(raw.title),
      scene: asString(raw.scene),
      sequence: asString(raw.sequence),
      description: asString(raw.description),
      action_note: asString(raw.action_note),
      camera_note: asString(raw.camera_note),
      character_note: asString(raw.character_note),
      dialogue: asString(raw.dialogue),
      lighting_note: asString(raw.lighting_note),
      transition_note: asString(raw.transition_note),
      duration_seconds: asNumber(raw.duration_seconds, 3.0) || 3.0,
      camera_data: asObject(raw.camera_data, {}),
      tags: asArray(raw.tags, []).map((item) => asString(item)).filter(Boolean),
      comments: asArray(raw.comments, []).filter((item) => item && typeof item === "object"),
      status: asString(raw.status || "Draft"),
      image_path: imagePath,
      preview_image_path: previewPath,
      thumbnail_path: asString(raw.thumbnail_path),
      source_file_path: asString(raw.source_file_path),
      source_sync_mtime: asNumber(raw.source_sync_mtime, 0.0),
      annotation_path: asString(raw.annotation_path),
      reference_image_paths: asArray(raw.reference_image_paths, []).map((item) => asString(item)).filter(Boolean),
      ref_video_path: asString(raw.ref_video_path),
      ref_video_time: asNumber(raw.ref_video_time, 0.0),
      ref_segment_time: asNumber(raw.ref_segment_time, 0.0),
    };
  }

  function projectDataFromPayload(payload = {}) {
    const rawShots = Array.isArray(payload.shots) ? payload.shots : [];
    return {
      version: Number.parseInt(payload.version, 10) || PROJECT_JSON_VERSION,
      name: asString(payload.name),
      settings: asObject(payload.settings, {}),
      shots: rawShots.map(normalizeShotRecord).filter((shot) => shot.shot_id),
    };
  }

  function isBackendLinkedMode() {
    try {
      return Boolean(linkedFromStoryboard);
    } catch {
      return false;
    }
  }

  async function refreshProjectDataFromBackendIfAvailable() {
    try {
      if (typeof refreshProjectDataFromBackend === "function") {
        return await refreshProjectDataFromBackend();
      }
      if (typeof requestPluginContext === "function" && typeof applyPluginContext === "function") {
        const context = await requestPluginContext();
        if (context) {
          applyPluginContext(context);
          return true;
        }
      }
    } catch {
      // Backend refresh is best-effort; linked mode still must not write metadata files.
    }
    return false;
  }

  async function readJsonFile(folder, fileName) {
    try {
      const entry = await folder.getEntry(fileName);
      const text = await readEntryText(entry);
      return JSON.parse(text);
    } catch {
      return null;
    }
  }

  async function writeTextFile(folder, fileName, text) {
    const entry = await folder.createFile(fileName, { overwrite: true });
    await writeEntryText(entry, text);
    return entry;
  }

  async function loadShotsJson() {
    requireProjectRoot();
    const payload = await readJsonFile(projectRoot, SHOTS_JSON_NAME);
    if (!payload) {
      return null;
    }
    const rawShots = Array.isArray(payload) ? payload : payload.shots;
    if (!Array.isArray(rawShots)) {
      return null;
    }
    return rawShots.map(normalizeShotRecord).filter((shot) => shot.shot_id);
  }

  async function saveShotsJson(shots) {
    requireProjectRoot();
    const payload = {
      version: SHOTS_JSON_VERSION,
      shots: shots.map(normalizeShotRecord).filter((shot) => shot.shot_id),
    };
    await writeTextFile(projectRoot, SHOTS_JSON_NAME, JSON.stringify(payload, null, 2));
    return payload.shots;
  }

  if (typeof createEmptyShot === "function") {
    createEmptyShot = function createEmptyShotWithCanonicalFields(shotId) {
      return normalizeShotRecord({
        shot_id: shotId,
        duration_seconds: 3.0,
        camera_data: {},
        tags: [],
        comments: [],
        status: "Draft",
        annotation_path: `shots/${shotId}/${shotId}_annotations.json`,
        reference_image_paths: [],
      });
    };
  }

  if (typeof shotFromCsvRow === "function") {
    shotFromCsvRow = function shotFromCsvRowWithRefFields(row, rowIndex) {
      return normalizeShotRecord({
        shot_id: asString(row.shot_id).trim(),
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
        duration_seconds: row.duration_seconds || 3.0,
        camera_data: readJsonCsvCell(row.camera_data, {}),
        tags: readJsonCsvCell(row.tags, []),
        comments: readJsonCsvCell(row.comments, []),
        status: row.status || "Draft",
        image_path: row.image_path || "",
        preview_image_path: row.preview_image_path || row.image_path || "",
        thumbnail_path: row.thumbnail_path || "",
        source_file_path: row.source_file_path || "",
        source_sync_mtime: row.source_sync_mtime || 0.0,
        annotation_path: row.annotation_path || "",
        reference_image_paths: readJsonCsvCell(row.reference_image_paths, []),
        ref_video_path: row.ref_video_path || "",
        ref_video_time: row.ref_video_time || 0.0,
        ref_segment_time: row.ref_segment_time || 0.0,
        _row: rowIndex,
      });
    };
  }

  if (typeof loadProjectJson === "function") {
    loadProjectJson = async function loadCanonicalProjectData() {
      requireProjectRoot();
      const manifest = (await readJsonFile(projectRoot, "project.json")) || {};
      const jsonShots = await loadShotsJson();
      if (jsonShots !== null) {
        return {
          version: Number.parseInt(manifest.version, 10) || PROJECT_JSON_VERSION,
          shots: jsonShots,
        };
      }

      const csvShots = await loadShotsCsv();
      if (csvShots) {
        return {
          version: Number.parseInt(manifest.version, 10) || PROJECT_JSON_VERSION,
          shots: csvShots.map(normalizeShotRecord).filter((shot) => shot.shot_id),
        };
      }

      const inlineShots = Array.isArray(manifest.shots) ? manifest.shots : [];
      return {
        version: Number.parseInt(manifest.version, 10) || PROJECT_JSON_VERSION,
        shots: inlineShots.map(normalizeShotRecord).filter((shot) => shot.shot_id),
      };
    };
  }

  if (typeof saveShotsCsv === "function") {
    const saveShotsCsvFallback = saveShotsCsv;
    // FALLBACK-OFFLINE-ONLY: shots.csv writes are suppressed in backend-linked
    // mode.  The backend owns canonical metadata; the plugin must not write
    // project files directly when linked.
    saveShotsCsv = async function saveShotsCsvOnlyWhenStandalone(shots) {
      if (isBackendLinkedMode()) {
        await refreshProjectDataFromBackendIfAvailable();
        return;
      }
      return saveShotsCsvFallback(shots);
    };
  }

  if (typeof saveProjectJson === "function") {
    // FALLBACK-OFFLINE-ONLY: project.json / shots.json writes are suppressed in
    // backend-linked mode.  In linked mode the backend is the single writer of
    // canonical project metadata.  Standalone/offline mode may still write these
    // files for round-trip compatibility.
    saveProjectJson = async function saveCanonicalProjectData() {
      if (isBackendLinkedMode()) {
        await refreshProjectDataFromBackendIfAvailable();
        return;
      }
      requireProjectRoot();
      const shots = await saveShotsJson((projectData?.shots || []).map(normalizeShotRecord));
      if (projectData) {
        projectData.shots = shots;
        projectData.version = projectData.version || PROJECT_JSON_VERSION;
      }
      await writeTextFile(
        projectRoot,
        "project.json",
        JSON.stringify({ version: projectData?.version || PROJECT_JSON_VERSION }, null, 2),
      );
      if (typeof saveShotsCsv === "function") {
        await saveShotsCsv(shots);
      }
    };
  }

  async function requestBackendAddShot() {
    if (typeof storyboardApiOrigins !== "function") {
      return null;
    }
    for (const origin of await storyboardApiOrigins()) {
      try {
        const response = await fetch(`${origin}/api/shots`, {
          method: "POST",
          cache: "no-store",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({}),
        });
        if (!response.ok) {
          continue;
        }
        const payload = await response.json();
        const nextProjectData = projectDataFromPayload(payload);
        if (nextProjectData.shots.length) {
          projectData = nextProjectData;
          populateShotSelect();
        }
        const created = normalizeShotRecord(payload.shot || nextProjectData.shots[nextProjectData.shots.length - 1]);
        if (created.shot_id) {
          try {
            await ensureShotStructure(created.shot_id);
          } catch {
            // The backend already created the folder/canvas; this is best-effort.
          }
          return created;
        }
      } catch {
        // Try the next localhost candidate.
      }
    }
    return null;
  }

  if (typeof addShotToProject === "function") {
    // In backend-linked mode the backend is the only writer of shot metadata.
    // If the backend call fails, this throws so the user knows the request did
    // not go through — it must never silently fall through to a local metadata
    // write while linked.
    //
    // FALLBACK-OFFLINE-ONLY: the local create path below runs only when the
    // panel is in standalone/offline mode (linkedFromStoryboard === false).
    addShotToProject = async function addShotViaBackendWhenLinked() {
      if (isBackendLinkedMode()) {
        const created = await requestBackendAddShot();
        if (created) {
          return created;
        }
        // Backend was reachable enough to attempt but returned no shot — surface
        // an error instead of falling through to a local metadata write.
        throw new Error(
          "Could not add shot: Storyboard Tool backend is unavailable. Try relinking.",
        );
      }

      // FALLBACK-OFFLINE-ONLY: standalone mode — backend is not connected.
      requireProjectRoot();
      const shot = createEmptyShot(nextShotId());
      projectData.shots.push(shot);
      await ensureShotStructure(shot.shot_id);
      await saveProjectJson();
      populateShotSelect();
      return shot;
    };
  }

  if (typeof setStatus === "function") {
    setStatus = function showStatus(message) {
      const node = $("status");
      if (!node) {
        return;
      }
      node.textContent = message || "";
      node.hidden = !message;
    };
  }

  function relabelExportButtons() {
    const group = document.querySelector(".panel-group-save .group-label");
    if (group) {
      group.textContent = "Preview export";
    }
    const saveAndStay = $("saveAndStay");
    if (saveAndStay) {
      saveAndStay.textContent = "Export preview";
    }
    const saveAndNext = $("saveAndNext");
    if (saveAndNext) {
      saveAndNext.textContent = "Export & next";
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", relabelExportButtons);
  } else {
    relabelExportButtons();
  }
})();
