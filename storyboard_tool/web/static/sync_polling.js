// Background sync, Photoshop live-bridge heartbeat, and bridge-status polling.
//
// Loaded as a classic script BEFORE app.js (see APP_SCRIPTS in main.js) so the
// lifecycle globals (startSyncPolling/stopSyncPolling, start/stopLiveBridgeHeartbeat,
// start/stopBridgeStatusPolling, publishLiveBridge) exist before app.js's deferred
// startup calls them via setProject. `publishLiveBridge` is also consumed at runtime
// by core/settings.js and canvas_color.js (save handlers). Helpers it relies on
// (syncShot, applyProjectShotsFromServer, renderTimeline, renderBoardInfo, api,
// state, el) resolve at call time from the shared global scope.

function startSyncPolling() {
  stopSyncPolling();
  state.syncPollTimer = window.setInterval(() => {
    if (state.selectedShotId) {
      syncShot(state.selectedShotId);
    }
  }, 3000);
}

function stopSyncPolling() {
  window.clearInterval(state.syncPollTimer);
  state.syncPollTimer = null;
}

window.addEventListener("focus", async () => {
  if (state.selectedShotId) {
    syncShot(state.selectedShotId);
    return;
  }
  if (state.project && !state.project.dirty) {
    try {
      const project = await api("/api/project", { silent: true });
      if (project?.shots) {
        applyProjectShotsFromServer(project);
        renderTimeline();
        renderBoardInfo();
      }
    } catch {
      // Ignore background refresh errors.
    }
  }
});

async function publishLiveBridge() {
  if (!state.project) return;
  await api("/api/bridge/live", {
    method: "PUT",
    body: JSON.stringify({ selected_shot_id: state.selectedShotId || "" }),
    silent: true,
  });
}

function startLiveBridgeHeartbeat() {
  stopLiveBridgeHeartbeat();
  publishLiveBridge().catch(() => {});
  state.liveBridgeTimer = window.setInterval(() => {
    publishLiveBridge().catch(() => {});
  }, 2000);
}

function stopLiveBridgeHeartbeat() {
  window.clearInterval(state.liveBridgeTimer);
  state.liveBridgeTimer = null;
}

function renderPsBridgeState(mode, message) {
  if (!el.psMenuSummary) return;
  el.psMenuSummary.classList.remove("ps-ok", "ps-error");
  if (mode === "ok") {
    el.psMenuSummary.classList.add("ps-ok");
  } else if (mode === "error") {
    el.psMenuSummary.classList.add("ps-error");
  }
  if (el.psMenuStatus) {
    el.psMenuStatus.textContent = message;
  }
  el.psMenuSummary.title = message;
}

function updateBridgeLinkStatus(status) {
  if (!status?.project_open) {
    renderPsBridgeState("idle", "No project open");
    return;
  }
  if (status.plugin_linked) {
    renderPsBridgeState("ok", "Photoshop linked");
    return;
  }
  renderPsBridgeState("error", "Waiting for Photoshop plugin");
}

async function refreshBridgeLinkStatus() {
  try {
    const status = await api("/api/bridge/status", { silent: true });
    updateBridgeLinkStatus(status);
  } catch {
    renderPsBridgeState("error", "Bridge offline");
  }
}

function startBridgeStatusPolling() {
  stopBridgeStatusPolling();
  refreshBridgeLinkStatus().catch(() => {});
  state.bridgeStatusTimer = window.setInterval(() => {
    refreshBridgeLinkStatus().catch(() => {});
  }, 2500);
}

function stopBridgeStatusPolling() {
  window.clearInterval(state.bridgeStatusTimer);
  state.bridgeStatusTimer = null;
  renderPsBridgeState("idle", "No project open");
}
