const API_DISPATCH_PATTERNS = [
  { method: "GET", pattern: /^\/api\/project$/, dispatch: "get_project", args: () => [] },
  { method: "GET", pattern: /^\/api\/app\/session$/, dispatch: "get_session", args: () => [] },
  {
    method: "PUT",
    pattern: /^\/api\/app\/session$/,
    dispatch: "update_session",
    args: (_, body) => [parseJsonBody(body)],
  },
  {
    method: "POST",
    pattern: /^\/api\/project\/new$/,
    dispatch: "new_project",
    args: (_, body) => {
      const data = parseJsonBody(body);
      return [data.path ?? null];
    },
  },
  {
    method: "POST",
    pattern: /^\/api\/project\/open$/,
    dispatch: "open_project",
    args: (_, body) => [parseJsonBody(body).project_json_path],
  },
  { method: "POST", pattern: /^\/api\/project\/save$/, dispatch: "save_project", args: () => [] },
  {
    method: "GET",
    pattern: /^\/api\/project\/missing-files$/,
    dispatch: "get_missing_files",
    args: () => [],
  },
  { method: "GET", pattern: /^\/api\/bridge\/status$/, dispatch: "bridge_status", args: () => [] },
  { method: "POST", pattern: /^\/api\/bridge\/relink$/, dispatch: "bridge_relink", args: () => [] },
  {
    method: "PUT",
    pattern: /^\/api\/bridge\/live$/,
    dispatch: "touch_live_bridge",
    args: (_, body) => {
      const data = parseJsonBody(body);
      return [data.selected_shot_id ?? null];
    },
  },
  {
    method: "POST",
    pattern: /^\/api\/shots$/,
    dispatch: "add_shot",
    args: (_, body) => {
      const data = parseJsonBody(body);
      return [data.after_shot_id ?? null];
    },
  },
  {
    method: "POST",
    pattern: /^\/api\/shots\/([^/]+)\/duplicate$/,
    dispatch: "duplicate_shot",
    args: (match) => [match[1]],
  },
  {
    method: "PATCH",
    pattern: /^\/api\/shots\/([^/]+)$/,
    dispatch: "update_shot",
    args: (match, body) => [match[1], parseJsonBody(body)],
  },
  {
    method: "DELETE",
    pattern: /^\/api\/shots\/([^/]+)$/,
    dispatch: "delete_shot",
    args: (match) => [match[1]],
  },
  {
    method: "POST",
    pattern: /^\/api\/shots\/restore$/,
    dispatch: "restore_shot",
    args: (_, body) => {
      const data = parseJsonBody(body);
      return [data.shot || {}, data.index ?? 0];
    },
  },
  {
    method: "POST",
    pattern: /^\/api\/shots\/reorder$/,
    dispatch: "reorder_shots",
    args: (_, body) => [parseJsonBody(body).shot_ids || []],
  },
  {
    method: "POST",
    pattern: /^\/api\/project\/ref-segment\/apply$/,
    dispatch: "apply_ref_segment",
    args: (_, body) => {
      const data = parseJsonBody(body);
      return [data.anchor_shot_id || "", data.end_shot_id || "", data.segment_id || ""];
    },
  },
  {
    method: "POST",
    pattern: /^\/api\/project\/ref-segment\/apply-image$/,
    dispatch: "apply_ref_segment_image",
    args: (_, body) => {
      const data = parseJsonBody(body);
      return [data.anchor_shot_id || "", data.end_shot_id || "", data.segment_id || ""];
    },
  },
  {
    method: "POST",
    pattern: /^\/api\/project\/ref-segment\/apply-3d$/,
    dispatch: "apply_ref_segment_3d",
    args: (_, body) => {
      const data = parseJsonBody(body);
      return [
        data.anchor_shot_id || "",
        data.end_shot_id || "",
        data.segment_id || "",
        data.camera_name || "",
      ];
    },
  },
  {
    method: "DELETE",
    pattern: /^\/api\/project\/ref-segments\/([^/]+)$/,
    dispatch: "delete_ref_segment",
    args: (match) => [decodeURIComponent(match[1])],
  },
  {
    method: "POST",
    pattern: /^\/api\/shots\/([^/]+)\/import-image-path$/,
    dispatch: "import_image_path",
    args: (match, body) => [match[1], parseJsonBody(body).source_path || ""],
  },
  {
    method: "POST",
    pattern: /^\/api\/shots\/([^/]+)\/move-up$/,
    dispatch: "move_shot_up",
    args: (match) => [match[1]],
  },
  {
    method: "POST",
    pattern: /^\/api\/shots\/([^/]+)\/move-down$/,
    dispatch: "move_shot_down",
    args: (match) => [match[1]],
  },
  {
    method: "POST",
    pattern: /^\/api\/shots\/([^/]+)\/sync$/,
    dispatch: "sync_shot",
    args: (match, _body, url) => {
      const force = new URL(url, "http://storyboard.local").searchParams.get("force") === "true";
      return [match[1], force];
    },
  },
  {
    method: "GET",
    pattern: /^\/api\/shots\/([^/]+)\/annotations$/,
    dispatch: "get_annotations",
    args: (match) => [match[1]],
  },
  {
    method: "PUT",
    pattern: /^\/api\/shots\/([^/]+)\/annotations$/,
    dispatch: "save_annotations",
    args: (match, body) => [match[1], parseJsonBody(body).annotations || []],
  },
  {
    method: "POST",
    pattern: /^\/api\/shots\/([^/]+)\/comments$/,
    dispatch: "add_comment",
    args: (match, body) => [match[1], parseJsonBody(body).text || ""],
  },
  {
    method: "PATCH",
    pattern: /^\/api\/shots\/([^/]+)\/comments\/(\d+)$/,
    dispatch: "resolve_comment",
    args: (match, body) => [match[1], Number(match[2]), Boolean(parseJsonBody(body).resolved)],
  },
  {
    method: "POST",
    pattern: /^\/api\/export\/pdf$/,
    dispatch: "export_pdf",
    args: (_, body) => [parseJsonBody(body).layout || "two_per_page"],
  },
  { method: "POST", pattern: /^\/api\/export\/shot-list$/, dispatch: "export_shot_list", args: () => [] },
  { method: "POST", pattern: /^\/api\/export\/timing$/, dispatch: "export_timing", args: () => [] },
  {
    method: "POST",
    pattern: /^\/api\/export\/contact-sheet$/,
    dispatch: "export_contact_sheet",
    args: () => [],
  },
  {
    method: "POST",
    pattern: /^\/api\/export\/image-sequence$/,
    dispatch: "export_image_sequence",
    args: () => [],
  },
  {
    method: "PATCH",
    pattern: /^\/api\/project\/settings$/,
    dispatch: "update_settings",
    args: (_, body) => [parseJsonBody(body)],
  },
  { method: "POST", pattern: /^\/api\/system\/browse-folder$/, dispatch: "browse_folder", args: () => [] },
  {
    method: "POST",
    pattern: /^\/api\/system\/browse-project-json$/,
    dispatch: "browse_project_json",
    args: () => [],
  },
  {
    method: "POST",
    pattern: /^\/api\/system\/browse-photoshop$/,
    dispatch: "browse_photoshop",
    args: () => [],
  },
  {
    method: "POST",
    pattern: /^\/api\/system\/browse-blender$/,
    dispatch: "browse_blender",
    args: () => [],
  },
  {
    method: "GET",
    pattern: /^\/api\/system\/photoshop-candidates$/,
    dispatch: "photoshop_candidates",
    args: () => [],
  },
  {
    method: "GET",
    pattern: /^\/api\/system\/blender-candidates$/,
    dispatch: "blender_candidates",
    args: () => [],
  },
  {
    method: "DELETE",
    pattern: /^\/api\/shots\/([^/]+)\/image$/,
    dispatch: "remove_shot_image",
    args: (match) => [match[1]],
  },
  {
    method: "POST",
    pattern: /^\/api\/shots\/([^/]+)\/relink-preview$/,
    dispatch: "relink_preview",
    args: (match, body) => [match[1], parseJsonBody(body).relative_path || ""],
  },
  {
    method: "POST",
    pattern: /^\/api\/shots\/([^/]+)\/open-preview$/,
    dispatch: "open_preview",
    args: (match) => [match[1]],
  },
  {
    method: "POST",
    pattern: /^\/api\/shots\/([^/]+)\/open-source$/,
    dispatch: "open_source",
    args: (match) => [match[1]],
  },
];

function parseJsonBody(body) {
  if (!body) return {};
  if (typeof body === "object") return body;
  try {
    return JSON.parse(body);
  } catch {
    return {};
  }
}

function resolveDispatchRoute(httpMethod, url, body) {
  const path = url.split("?")[0];
  for (const entry of API_DISPATCH_PATTERNS) {
    if (entry.method !== httpMethod) continue;
    const match = path.match(entry.pattern);
    if (!match) continue;
    return { dispatch: entry.dispatch, args: entry.args(match, body, url) };
  }
  return null;
}

async function apiDispatch(dispatchMethod, args, { silent = false, bypassBridge = false } = {}) {
  if (bypassBridge || preferHttpApi()) {
    const payload = await fetchApiJson("/api", {
      method: "POST",
      silent,
      body: JSON.stringify({ method: dispatchMethod, args }),
    });
    if (payload.ok === false) {
      const message = payload.error || "API call failed";
      if (!silent) showToast(message);
      throw new Error(message);
    }
    return payload.result;
  }

  const bridge = await whenDesktopBridgeReady();
  const bridgeApiCall = bridge?.apiCall || bridge?.api_call;
  if (bridgeApiCall) {
    try {
      return await bridgeApiCall.call(bridge, dispatchMethod, JSON.stringify(args));
    } catch (error) {
      const message = error?.message || String(error);
      if (!silent) showToast(message);
      throw error instanceof Error ? error : new Error(message);
    }
  }

  const response = await fetch("/api", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ method: dispatchMethod, args }),
  });
  let payload;
  try {
    payload = await response.json();
  } catch {
    payload = { ok: false, error: response.statusText };
  }
  if (!response.ok || payload.ok === false) {
    const message = payload.error || response.statusText || "API call failed";
    if (!silent) showToast(message);
    throw new Error(message);
  }
  return payload.result;
}
