import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import vm from "node:vm";

function loadClient(fetchImpl) {
  const sandbox = {
    URL,
    fetch: fetchImpl,
    encodeURIComponent,
    loadBridgeCache: async () => ({
      bridge_url: "http://127.0.0.1:8123/api/bridge/live",
      port: 8123,
      api_token: "launch-token",
    }),
  };
  vm.createContext(sandbox);
  vm.runInContext(
    readFileSync(
      new URL("../photoshop_uxp_plugin/work_item_paths.js", import.meta.url),
      "utf8",
    ),
    sandbox,
  );
  vm.runInContext(
    readFileSync(
      new URL("../photoshop_uxp_plugin/backend_client.js", import.meta.url),
      "utf8",
    ),
    sandbox,
  );
  return sandbox;
}

test("context negotiation and every plugin mutation carry protocol v2 freshness", async () => {
  const requests = [];
  const client = loadClient(async (url, options = {}) => {
    requests.push({ url, options });
    return {
      ok: true,
      status: 200,
      json: async () => (
        url.endsWith("/api/plugin/context")
          ? {
              shots: [],
              work_items: [],
              project_session_id: "session-7",
              context_revision: 12,
              path_mode: "explicit-assets",
              offline_write_allowed: false,
            }
          : { ok: true }
      ),
    };
  });

  await client.requestPluginContext();
  await client.requestStoryboardApi("/api/plugin/shots/shot-a/focus", {
    method: "POST",
  });

  const contextHeaders = requests[0].options.headers;
  assert.equal(contextHeaders["X-Storyboarder-Protocol"], "2");
  assert.equal(
    contextHeaders["X-Storyboarder-Capabilities"],
    "explicit_asset_paths_v2",
  );
  assert.equal(contextHeaders["X-Storyboarder-Project-Session"], undefined);

  const mutationHeaders = requests[1].options.headers;
  assert.equal(mutationHeaders["X-Storyboarder-Project-Session"], "session-7");
  assert.equal(mutationHeaders["X-Storyboarder-Context-Revision"], "12");
  assert.equal(mutationHeaders["X-Storyboarder-Token"], "launch-token");
});

test("write intents and commit envelopes are role scoped", async () => {
  const client = loadClient(async () => ({
    ok: true,
    status: 200,
    json: async () => ({
      token: "intent-token",
      write_path: "D:/Portable/.storyboarder/transactions/t/plugin-inbox/a.png",
    }),
  }));
  client.rememberPluginProtocolContext({
    project_session_id: "session-a",
    context_revision: 3,
    path_mode: "explicit-assets",
    offline_write_allowed: false,
  });

  const intent = await client.requestPluginWriteIntent("shot:a", "preview");
  assert.equal(intent.token, "intent-token");
  assert.deepEqual(
    { ...client.pluginWriteHeaders("shot:a", "preview", intent.token) },
    {
      "X-Storyboarder-Work-Key": "shot:a",
      "X-Storyboarder-Asset-Role": "preview",
      "X-Storyboarder-Write-Intent": "intent-token",
    },
  );
});

test("upgrade and stale-context responses fail closed", async () => {
  const client = loadClient(async () => ({
    ok: false,
    status: 426,
    json: async () => ({
      code: "PLUGIN_UPGRADE_REQUIRED",
      detail: "Upgrade required.",
    }),
  }));
  await assert.rejects(
    () => client.requestPluginContext(),
    (error) => error.status === 426 && error.code === "PLUGIN_UPGRADE_REQUIRED",
  );
});

test("UXP v2 source has no fixed shared bridge path and guards legacy bridge writes", () => {
  const panelSource = readFileSync(
    new URL("../photoshop_uxp_plugin/panel.js", import.meta.url),
    "utf8",
  );
  const previewSource = readFileSync(
    new URL("../photoshop_uxp_plugin/preview_export.js", import.meta.url),
    "utf8",
  );
  assert.ok(!panelSource.includes("C:/Users/Public/StoryboardTool"));
  assert.ok(!panelSource.includes("storyboard_plugin_heartbeat.json"));
  assert.match(
    previewSource,
    /if \(isExplicitAssetContext\(lastPluginContext\)\) \{[\s\S]*?return;[\s\S]*?requireOfflineWriteAllowed/,
  );
  assert.match(panelSource, /validateCanonicalPsdAfterNativeSave/);
  assert.ok(!panelSource.includes("resolveAssetParentFolder"));
  assert.match(panelSource, /Layout 2 has no shot folder/);
});
