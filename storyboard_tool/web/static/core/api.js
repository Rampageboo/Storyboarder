let desktopBridgeReady = null;
let desktopBridgeReadyResolved = false;

function whenDesktopBridgeReady() {
  if (!window.pywebview) return Promise.resolve(null);
  if (window.pywebview.api?.request || window.pywebview.api?.apiCall || window.pywebview.api?.api_call) {
    return Promise.resolve(window.pywebview.api);
  }
  if (!desktopBridgeReady) {
    desktopBridgeReady = new Promise((resolve) => {
      const finish = () => {
        if (desktopBridgeReadyResolved) return;
        desktopBridgeReadyResolved = true;
        const api = window.pywebview?.api;
        resolve(api?.request || api?.apiCall || api?.api_call ? api : null);
      };
      window.addEventListener("pywebviewready", finish, { once: true });
      window.setTimeout(finish, 1500);
    });
  }
  return desktopBridgeReady;
}

function preferHttpApi() {
  return window.location.protocol === "http:" || window.location.protocol === "https:";
}

async function fetchApiJson(url, options = {}) {
  const { silent = false, headers: customHeaders, ...fetchOptions } = options;
  const headers = { ...(customHeaders || {}) };
  if (!(fetchOptions.body instanceof FormData) && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json";
  }
  const body =
    fetchOptions.body &&
    !(fetchOptions.body instanceof FormData) &&
    typeof fetchOptions.body !== "string"
      ? JSON.stringify(fetchOptions.body)
      : fetchOptions.body;
  const response = await fetch(url, { ...fetchOptions, headers, body });
  if (!response.ok) {
    let message = response.statusText;
    try {
      const payload = await response.json();
      message = payload.detail || payload.error || message;
    } catch {
      // Keep HTTP status when body is not JSON.
    }
    if (!silent) showToast(message);
    throw new Error(message);
  }
  if (response.status === 204) return {};
  return response.json();
}

async function bridgeUpload(bridge, url, formData) {
  const file = formData.get("file");
  if (!file || typeof file.arrayBuffer !== "function") {
    throw new Error("No file selected");
  }
  const buffer = await file.arrayBuffer();
  const bytes = Array.from(new Uint8Array(buffer));
  const upload = bridge.upload_multipart || bridge.uploadMultipart;
  if (!upload) {
    throw new Error("Desktop bridge upload is unavailable");
  }
  return upload.call(bridge, url, file.name, file.type || "application/octet-stream", bytes);
}

async function api(url, options = {}) {
  const { silent = false, headers: customHeaders, bypassBridge, ...fetchOptions } = options;
  const useHttp = bypassBridge !== undefined ? bypassBridge : preferHttpApi();
  const httpMethod = (fetchOptions.method || "GET").toUpperCase();

  if (!(fetchOptions.body instanceof FormData)) {
    const resolved = resolveDispatchRoute(httpMethod, url, fetchOptions.body ?? null);
    if (resolved) {
      try {
        return await apiDispatch(resolved.dispatch, resolved.args, { silent, bypassBridge: useHttp });
      } catch (error) {
        throw error instanceof Error ? error : new Error(String(error));
      }
    }
  }

  if (useHttp) {
    return fetchApiJson(url, { silent, headers: customHeaders, ...fetchOptions });
  }

  if (fetchOptions.body instanceof FormData) {
    const resolved = resolveDispatchRoute(httpMethod, url, null);
    if (resolved) {
      try {
        return await apiDispatch(resolved.dispatch, resolved.args, { silent, bypassBridge: false });
      } catch (error) {
        throw error instanceof Error ? error : new Error(String(error));
      }
    }
  }

  const bridge = await whenDesktopBridgeReady();

  if (bridge) {
    try {
      const method = httpMethod;
      if (fetchOptions.body instanceof FormData) {
        return await bridgeUpload(bridge, url, fetchOptions.body);
      }
      const body =
        fetchOptions.body && typeof fetchOptions.body !== "string"
          ? JSON.stringify(fetchOptions.body)
          : fetchOptions.body || null;
      return await bridge.request(method, url, body);
    } catch (error) {
      const message = error?.message || String(error);
      if (!silent) showToast(message);
      throw error instanceof Error ? error : new Error(message);
    }
  }

  const headers = customHeaders ?? { "Content-Type": "application/json" };
  const body =
    fetchOptions.body &&
    !(fetchOptions.body instanceof FormData) &&
    typeof fetchOptions.body !== "string"
      ? JSON.stringify(fetchOptions.body)
      : fetchOptions.body;
  const response = await fetch(url, { ...fetchOptions, headers, body });
  if (!response.ok) {
    let message = response.statusText;
    try {
      const payload = await response.json();
      message = payload.detail || message;
    } catch {
      // Keep the HTTP status text when the server does not return JSON.
    }
    if (!silent) showToast(message);
    throw new Error(message);
  }
  return response.json();
}

function showToast(message) {
  el.toast.textContent = message;
  el.toast.hidden = false;
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => {
    el.toast.hidden = true;
  }, 3500);
}
