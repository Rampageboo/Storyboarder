// Single API contract: REST over HTTP, with the desktop pywebview bridge as a
// passthrough fallback when the page is not served over http(s). The backend
// FastAPI routes are the one source of truth; there is no parallel dispatch map.

let desktopBridgeReady = null;
let desktopBridgeReadyResolved = false;

export function whenDesktopBridgeReady() {
  if (!window.pywebview) return Promise.resolve(null);
  if (window.pywebview.api?.request) {
    return Promise.resolve(window.pywebview.api);
  }
  if (!desktopBridgeReady) {
    desktopBridgeReady = new Promise((resolve) => {
      const finish = () => {
        if (desktopBridgeReadyResolved) return;
        desktopBridgeReadyResolved = true;
        const api = window.pywebview?.api;
        resolve(api?.request ? api : null);
      };
      window.addEventListener("pywebviewready", finish, { once: true });
      window.setTimeout(finish, 1500);
    });
  }
  return desktopBridgeReady;
}

export function preferHttpApi() {
  return window.location.protocol === "http:" || window.location.protocol === "https:";
}

export async function fetchApiJson(url, options = {}) {
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

export async function bridgeUpload(bridge, url, formData) {
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

export async function api(url, options = {}) {
  const { silent = false, headers: customHeaders, bypassBridge, ...fetchOptions } = options;
  const useHttp = bypassBridge !== undefined ? bypassBridge : preferHttpApi();

  if (useHttp) {
    return fetchApiJson(url, { silent, headers: customHeaders, ...fetchOptions });
  }

  const bridge = await whenDesktopBridgeReady();
  if (bridge) {
    try {
      if (fetchOptions.body instanceof FormData) {
        return await bridgeUpload(bridge, url, fetchOptions.body);
      }
      const method = (fetchOptions.method || "GET").toUpperCase();
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

  return fetchApiJson(url, { silent, headers: customHeaders, ...fetchOptions });
}

export function showToast(message) {
  const el = globalThis.el;
  if (!el?.toast) return;
  el.toast.textContent = message;
  el.toast.hidden = false;
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => {
    el.toast.hidden = true;
  }, 3500);
}
