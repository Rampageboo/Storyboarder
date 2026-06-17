import * as THREE from "three";
// Absolute path so this module resolves the loader regardless of where it lives
// (it now lives under /static/runtime/, the vendor bundle stays under /static/vendor/).
import { GLTFLoader } from "/static/vendor/three/GLTFLoader.js";

const previewState = new WeakMap();

function disposeMaterial(material) {
  if (!material) return;
  const materials = Array.isArray(material) ? material : [material];
  for (const item of materials) {
    if (!item) continue;
    for (const key of Object.keys(item)) {
      const value = item[key];
      if (value && typeof value === "object" && typeof value.dispose === "function") {
        try {
          value.dispose();
        } catch {
          // best effort
        }
      }
    }
    try {
      item.dispose?.();
    } catch {
      // best effort
    }
  }
}

function disposeObject3D(root) {
  if (!root) return;
  root.traverse?.((node) => {
    try {
      node.geometry?.dispose?.();
      disposeMaterial(node.material);
    } catch {
      // best effort
    }
  });
}

function markCanvasFailed(canvas, url = canvas.dataset.refModelPreview || "") {
  canvas.dataset.refModelFailed = "true";
  canvas.dataset.refModelStatus = "failed";
  canvas.dataset.refModelFailedUrl = url;
  canvas.setAttribute("aria-label", "3D preview unavailable");
}

function disposePreview(canvas) {
  const state = previewState.get(canvas);
  if (!state) return;
  state.disposed = true;
  if (state.rafId) cancelAnimationFrame(state.rafId);
  state.rafId = 0;
  state.observer?.disconnect();
  state.resizeObserver?.disconnect();
  canvas.removeEventListener("webglcontextlost", state.onContextLost);
  disposeObject3D(state.root);
  try {
    state.renderer?.dispose?.();
  } catch {
    // best effort
  }
  previewState.delete(canvas);
}

export function disposeReferenceModelPreviews(root = document) {
  root.querySelectorAll("[data-ref-model-preview]").forEach((canvas) => disposePreview(canvas));
}

function frameObject(camera, object, offset = 1.35) {
  const box = new THREE.Box3().setFromObject(object);
  if (box.isEmpty()) return null;
  const size = box.getSize(new THREE.Vector3());
  const center = box.getCenter(new THREE.Vector3());
  const radius = Math.max(size.x, size.y, size.z) * offset || 2;
  camera.position.set(center.x + radius, center.y + radius * 0.55, center.z + radius);
  camera.near = Math.max(0.01, radius / 200);
  camera.far = Math.max(200, radius * 40);
  camera.lookAt(center);
  camera.updateProjectionMatrix();
  return center;
}

function parseTriple(value) {
  if (Array.isArray(value) && value.length >= 3) {
    const out = [Number(value[0]), Number(value[1]), Number(value[2])];
    if (out.every((n) => Number.isFinite(n))) return out;
  }
  return null;
}

// Parse the optional view descriptor serialized onto the canvas by ReferenceModelPreview.
function parseView(canvas) {
  const raw = canvas.dataset.refModelView;
  if (!raw) return null;
  try {
    const data = JSON.parse(raw);
    return data && typeof data === "object" ? data : null;
  } catch {
    return null;
  }
}

function findNamedCamera(root, name) {
  if (!root || !name) return null;
  let found = null;
  root.traverse?.((node) => {
    if (found) return;
    if (node?.isCamera && node.name === name) found = node;
  });
  return found;
}

// Set sane near/far from the model bounds so a supplied camera view never clips the model away.
// Returns the model center for use as a lookAt fallback.
function applyClipPlanesFromBounds(camera, object) {
  const box = new THREE.Box3().setFromObject(object);
  if (box.isEmpty()) return new THREE.Vector3();
  const size = box.getSize(new THREE.Vector3());
  const radius = Math.max(size.x, size.y, size.z) || 2;
  camera.near = Math.max(0.001, radius / 500);
  camera.far = Math.max(200, radius * 60);
  camera.updateProjectionMatrix();
  return box.getCenter(new THREE.Vector3());
}

function copySceneCameraToPreviewCamera(sourceCamera, previewCamera) {
  sourceCamera.updateWorldMatrix(true, false);
  const pos = new THREE.Vector3();
  const quat = new THREE.Quaternion();
  const scl = new THREE.Vector3();
  sourceCamera.matrixWorld.decompose(pos, quat, scl);
  previewCamera.position.copy(pos);
  previewCamera.quaternion.copy(quat);
  if (sourceCamera.isPerspectiveCamera && Number.isFinite(sourceCamera.fov)) {
    previewCamera.fov = sourceCamera.fov;
  }
  previewCamera.updateProjectionMatrix();
}

// Apply a supplied view to the preview camera. Returns a diagnostic label if a usable view was
// applied, or an empty string when the caller should fall back to generic framing.
function applySuppliedView(state, view) {
  if (!view || !state.root) return "";
  const camera = state.camera;
  const center = applyClipPlanesFromBounds(camera, state.root);

  const mode = typeof view.mode === "string" ? view.mode : "";
  const name = typeof view.camera_name === "string" ? view.camera_name.trim() : "";
  if (mode === "scene_camera" && name) {
    const cam = findNamedCamera(state.root, name);
    if (cam) {
      copySceneCameraToPreviewCamera(cam, camera);
      applyClipPlanesFromBounds(camera, state.root);
      return `scene-camera:${name}`;
    }
  }

  const position = parseTriple(view.position);
  if (position) {
    camera.position.set(position[0], position[1], position[2]);
    const fov = Number(view.fov);
    if (Number.isFinite(fov) && fov > 0) {
      camera.fov = fov;
      camera.updateProjectionMatrix();
    }
    const target = parseTriple(view.target);
    const rotation = parseTriple(view.rotation);
    if (rotation) {
      // Euler from the workspace camera — reproduces orientation including roll/banking, which a
      // lookAt(target) with world-up would silently drop for a rolled scene camera.
      camera.rotation.set(rotation[0], rotation[1], rotation[2]);
    } else if (target) {
      camera.lookAt(target[0], target[1], target[2]);
    } else {
      camera.lookAt(center);
    }
    return mode === "scene_camera" && name ? `saved-camera-transform:${name}` : "free-view-transform";
  }

  if (name) {
    const cam = findNamedCamera(state.root, name);
    if (cam) {
      copySceneCameraToPreviewCamera(cam, camera);
      applyClipPlanesFromBounds(camera, state.root);
      return `named-camera:${name}`;
    }
  }

  return "";
}

// Frame the model with the supplied view if present/usable, else the default orbit framing.
// Records whether a view drove the camera (state.hasView) so the render loop can skip the
// idle auto-rotate when reproducing a specific camera.
function applyViewOrFrame(state) {
  let path = "";
  const view = parseView(state.canvas);
  if (view) {
    try {
      path = applySuppliedView(state, view);
    } catch (error) {
      console.warn("Reference 3D preview view apply failed:", error);
      path = "";
    }
  }
  if (!path) {
    state.root.rotation.set(0, 0, 0);
    const center = frameObject(state.camera, state.root);
    if (center) state.center.copy(center);
    path = "generic-frame";
  }
  state.hasView = path !== "generic-frame";
  state.viewKey = state.canvas.dataset.refModelView || "";
  state.viewPath = path;
}

function safeRender(state) {
  if (!state || state.disposed || !state.renderer) return;
  try {
    state.renderer.render(state.scene, state.camera);
  } catch (error) {
    console.warn("Reference 3D preview render failed:", error);
    markCanvasFailed(state.canvas, state.url);
    disposePreview(state.canvas);
  }
}

function isProbablyBlankFrame(canvas) {
  const width = canvas.width || 0;
  const height = canvas.height || 0;
  if (width <= 1 || height <= 1) return true;
  const sample = document.createElement("canvas");
  sample.width = 32;
  sample.height = 32;
  const ctx = sample.getContext("2d", { willReadFrequently: true });
  if (!ctx) return false;
  ctx.drawImage(canvas, 0, 0, sample.width, sample.height);
  const pixels = ctx.getImageData(0, 0, sample.width, sample.height).data;
  let min = 255;
  let max = 0;
  let transparent = 0;
  let brightness = 0;
  const count = sample.width * sample.height;
  for (let i = 0; i < pixels.length; i += 4) {
    const r = pixels[i];
    const g = pixels[i + 1];
    const b = pixels[i + 2];
    const a = pixels[i + 3];
    if (a < 8) transparent += 1;
    min = Math.min(min, r, g, b);
    max = Math.max(max, r, g, b);
    brightness += (r + g + b) / 3;
  }
  const avg = brightness / count;
  if (transparent / count > 0.8) return true;
  return max - min < 3 && (avg < 8 || avg > 247);
}

async function mountPreview(canvas) {
  const url = canvas.dataset.refModelPreview;
  if (!url) return;
  if (canvas.dataset.refModelFailed === "true" && canvas.dataset.refModelFailedUrl === url) return;
  const existing = previewState.get(canvas);
  if (existing?.url === url) return;
  if (existing) disposePreview(canvas);

  canvas.dataset.refModelStatus = "loading";
  delete canvas.dataset.refModelFailed;
  delete canvas.dataset.refModelFailedUrl;

  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({
      canvas,
      antialias: true,
      alpha: true,
      preserveDrawingBuffer: true,
      powerPreference: "low-power",
    });
  } catch (error) {
    console.warn("Reference 3D preview WebGL unavailable:", error);
    markCanvasFailed(canvas, url);
    return;
  }

  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
  renderer.outputColorSpace = THREE.SRGBColorSpace;

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x111827);
  const camera = new THREE.PerspectiveCamera(42, 1, 0.01, 500);
  scene.add(new THREE.AmbientLight(0xffffff, 0.65));
  const sun = new THREE.DirectionalLight(0xffffff, 1.1);
  sun.position.set(4, 8, 6);
  scene.add(sun);

  const state = {
    url,
    canvas,
    renderer,
    scene,
    camera,
    root: null,
    mixer: null,
    actions: [],
    center: new THREE.Vector3(),
    hasView: false,
    viewKey: "",
    viewPath: "",
    rafId: 0,
    visible: false,
    observer: null,
    resizeObserver: null,
    disposed: false,
    onContextLost: (event) => {
      event.preventDefault?.();
      markCanvasFailed(canvas, url);
      disposePreview(canvas);
    },
  };
  previewState.set(canvas, state);
  canvas.addEventListener("webglcontextlost", state.onContextLost, false);

  const resize = () => {
    if (state.disposed) return;
    const rect = canvas.getBoundingClientRect();
    const width = Math.max(1, Math.floor(rect.width || canvas.clientWidth || 1));
    const height = Math.max(1, Math.floor(rect.height || canvas.clientHeight || 1));
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
  };
  resize();

  const renderFrame = (time = 0) => {
    if (state.disposed) return;
    // Idle spin for generic library thumbnails; hold still when reproducing a specific camera.
    if (state.root && !state.hasView) state.root.rotation.y = time * 0.00035;
    safeRender(state);
  };

  const startLoop = () => {
    if (state.disposed || state.rafId) return;
    const tick = (time) => {
      if (!previewState.has(canvas) || state.disposed) return;
      renderFrame(time);
      state.rafId = requestAnimationFrame(tick);
    };
    state.rafId = requestAnimationFrame(tick);
  };

  const stopLoop = () => {
    if (!state.rafId) return;
    cancelAnimationFrame(state.rafId);
    state.rafId = 0;
    renderFrame();
  };

  state.observer = new IntersectionObserver(
    (entries) => {
      const visible = entries.some((entry) => entry.isIntersecting);
      state.visible = visible;
      if (visible) startLoop();
      else stopLoop();
    },
    { threshold: 0.12 },
  );
  state.observer.observe(canvas);

  const ro = new ResizeObserver(resize);
  ro.observe(canvas);
  state.resizeObserver = ro;

  try {
    const gltf = await new GLTFLoader().loadAsync(url);
    if (state.disposed || !previewState.has(canvas)) {
      disposeObject3D(gltf.scene);
      return;
    }
    state.root = gltf.scene;
    if (Array.isArray(gltf.animations) && gltf.animations.length > 0) {
      state.mixer = new THREE.AnimationMixer(state.root);
      state.actions = gltf.animations.map((clip) => {
        const action = state.mixer.clipAction(clip);
        action.play();
        return action;
      });
      state.mixer.setTime(0);
    }
    scene.add(state.root);
    applyViewOrFrame(state);
    canvas.dataset.refModelStatus = "ready";
    resize();
    renderFrame();
    if (state.visible) startLoop();
  } catch (error) {
    if (state.disposed) return;
    console.warn("Reference 3D preview failed:", error);
    markCanvasFailed(canvas, url);
    disposePreview(canvas);
  }
}

function canvasFromRoot(root = document) {
  if (root instanceof HTMLCanvasElement && root.matches("[data-ref-model-preview]")) return root;
  return root.querySelector?.("[data-ref-model-preview]") || null;
}

async function waitForReady(canvas, timeoutMs = 10000) {
  if (!previewState.has(canvas)) mountPreview(canvas);
  const start = performance.now();
  while (performance.now() - start < timeoutMs) {
    const state = previewState.get(canvas);
    if (state?.root && !state.disposed && canvas.dataset.refModelStatus === "ready") return state;
    if (canvas.dataset.refModelStatus === "failed") throw new Error("3D preview failed to load.");
    await new Promise((resolve) => requestAnimationFrame(resolve));
  }
  throw new Error("Timed out waiting for 3D preview to load.");
}

export async function captureReferenceModelFrame(root = document, options = {}) {
  const canvas = canvasFromRoot(root);
  if (!canvas) throw new Error("3D preview canvas not found.");
  const state = await waitForReady(canvas);
  if (!state.root || state.disposed) throw new Error("3D preview is not ready.");

  const wasAnimating = state.rafId;
  if (wasAnimating) {
    cancelAnimationFrame(state.rafId);
    state.rafId = 0;
  }

  const previousPixelRatio = state.renderer.getPixelRatio();
  const previousSize = state.renderer.getSize(new THREE.Vector2());
  const previousAspect = state.camera.aspect;
  const previousRootRotation = state.root.rotation.clone();
  const previousViewKey = state.viewKey;
  const previousHasView = state.hasView;
  const previousViewPath = state.viewPath;

  const width = Math.max(1, Math.floor(Number(options.width) || canvas.width || canvas.clientWidth || 1920));
  const height = Math.max(1, Math.floor(Number(options.height) || canvas.height || canvas.clientHeight || 1080));
  const time = Math.max(0, Number(options.time) || 0);
  const view = options.view && typeof options.view === "object" ? options.view : parseView(canvas);

  try {
    state.renderer.setPixelRatio(1);
    state.renderer.setSize(width, height, false);
    state.camera.aspect = width / height;
    state.camera.updateProjectionMatrix();

    if (state.mixer) state.mixer.setTime(time);

    let path = "";
    if (view) {
      path = applySuppliedView(state, view);
    }
    if (!path) {
      state.root.rotation.set(0, 0, 0);
      const center = frameObject(state.camera, state.root);
      if (center) state.center.copy(center);
      path = "generic-frame";
    }
    state.hasView = path !== "generic-frame";

    safeRender(state);
    if (isProbablyBlankFrame(canvas)) {
      throw new Error("3D capture produced a blank frame; refusing to overwrite boards.");
    }
    const dataUrl = canvas.toDataURL("image/png");
    console.debug?.("[ref3d] capture", { path, time, width, height, camera: view?.camera_name || "" });
    return dataUrl;
  } finally {
    state.renderer.setPixelRatio(previousPixelRatio);
    state.renderer.setSize(previousSize.x, previousSize.y, false);
    state.camera.aspect = previousAspect;
    state.camera.updateProjectionMatrix();
    state.root.rotation.copy(previousRootRotation);
    state.viewKey = previousViewKey;
    state.hasView = previousHasView;
    state.viewPath = previousViewPath;
    applyViewOrFrame(state);
    safeRender(state);
    if (wasAnimating && state.visible && !state.disposed) {
      const tick = (tickTime) => {
        if (!previewState.has(canvas) || state.disposed) return;
        if (state.root && !state.hasView) state.root.rotation.y = tickTime * 0.00035;
        safeRender(state);
        state.rafId = requestAnimationFrame(tick);
      };
      state.rafId = requestAnimationFrame(tick);
    }
  }
}

export function hydrateReferenceModelPreviews(root = document) {
  root.querySelectorAll("[data-ref-model-preview]").forEach((canvas) => {
    mountPreview(canvas);
  });
}

// Re-apply the camera/view to an already-mounted preview when its data-ref-model-view changes,
// without recreating the WebGL context. Previews still loading are skipped — mountPreview reads
// the latest view attribute when its model finishes loading.
export function applyReferenceModelView(root = document) {
  root.querySelectorAll("[data-ref-model-preview]").forEach((canvas) => {
    const state = previewState.get(canvas);
    if (!state || state.disposed || !state.root) return;
    if ((canvas.dataset.refModelView || "") === state.viewKey) return;
    applyViewOrFrame(state);
    safeRender(state);
  });
}

window.disposeReferenceModelPreviews = disposeReferenceModelPreviews;
window.hydrateReferenceModelPreviews = hydrateReferenceModelPreviews;
window.applyReferenceModelView = applyReferenceModelView;
window.captureReferenceModelFrame = captureReferenceModelFrame;
window.dispatchEvent(new Event("reference-model-preview-ready"));
document.querySelectorAll(".reference-media-panel").forEach((panel) => hydrateReferenceModelPreviews(panel));
