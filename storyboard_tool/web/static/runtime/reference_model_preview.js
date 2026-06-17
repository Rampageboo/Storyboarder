import * as THREE from "three";
// Absolute path so this module resolves the loader regardless of where it lives
// (it now lives under /static/runtime/, the vendor bundle stays under /static/vendor/).
import { GLTFLoader } from "/static/vendor/three/GLTFLoader.js";
import { RoomEnvironment } from "/static/vendor/three/RoomEnvironment.js";

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
  try {
    state.mixer?.stopAllAction?.();
  } catch {
    // best effort
  }
  state.mixer = null;
  state.actions = [];
  if (state.scene) state.scene.environment = null;
  try {
    state.envMap?.dispose?.();
  } catch {
    // best effort
  }
  state.envMap = null;
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

function isNodeInGraph(root, node) {
  let current = node;
  while (current) {
    if (current === root) return true;
    current = current.parent;
  }
  return false;
}

// Collect every camera in the GLB the way the Scene3D workspace does: from all scenes, the active
// root, and gltf.cameras (some exporters leave cameras out of the scene graph). Orphan cameras are
// attached to root so their world matrices resolve. Returns the camera list for name lookup.
function collectGltfCameras(root, gltf) {
  const cameras = [];
  const seen = new Set();
  const addCamera = (node) => {
    if (!node?.isCamera || seen.has(node.uuid)) return;
    seen.add(node.uuid);
    cameras.push(node);
  };
  for (const scene of gltf?.scenes || []) scene?.traverse?.(addCamera);
  root?.traverse?.(addCamera);
  for (const cam of gltf?.cameras || []) addCamera(cam);
  for (const cam of cameras) {
    if (!isNodeInGraph(root, cam)) root?.add?.(cam);
  }
  return cameras;
}

// Evaluate GLB animation clips at the requested time so the model pose (and any animated camera)
// matches the Scene3D workspace instead of staying at frame 0.
function syncAnimationTime(state, seconds) {
  if (!state.mixer || !state.actions?.length) return;
  const time = Math.max(0, Number(seconds) || 0);
  for (const action of state.actions) {
    action.enabled = true;
    action.paused = false;
    action.play();
    action.time = time;
  }
  state.mixer.update(0);
  state.root?.updateMatrixWorld(true);
}

function parseTriple(value) {
  if (Array.isArray(value) && value.length >= 3) {
    const out = [Number(value[0]), Number(value[1]), Number(value[2])];
    if (out.every((n) => Number.isFinite(n))) return out;
  }
  return null;
}

let blankCheckCanvas = null;

// True if the rendered GLB frame is essentially a single flat color (model not visible at this
// time/camera). Lets capture fail early with a clear message instead of uploading a blank board
// that the backend would later reject as a "solid" preview.
function isCapturedFrameBlank(glCanvas) {
  try {
    if (!blankCheckCanvas) blankCheckCanvas = document.createElement("canvas");
    const w = 24;
    const h = 24;
    blankCheckCanvas.width = w;
    blankCheckCanvas.height = h;
    const ctx = blankCheckCanvas.getContext("2d", { willReadFrequently: true });
    if (!ctx) return false;
    ctx.drawImage(glCanvas, 0, 0, w, h);
    const { data } = ctx.getImageData(0, 0, w, h);
    let minR = 255, maxR = 0, minG = 255, maxG = 0, minB = 255, maxB = 0;
    for (let i = 0; i < data.length; i += 4) {
      if (data[i] < minR) minR = data[i];
      if (data[i] > maxR) maxR = data[i];
      if (data[i + 1] < minG) minG = data[i + 1];
      if (data[i + 1] > maxG) maxG = data[i + 1];
      if (data[i + 2] < minB) minB = data[i + 2];
      if (data[i + 2] > maxB) maxB = data[i + 2];
    }
    // Truly-uniform (range < 4/255) means nothing rendered; a lit model exceeds this easily.
    return Math.max(maxR - minR, maxG - minG, maxB - minB) < 4;
  } catch {
    return false; // can't sample (e.g. tainted canvas) — don't block the apply
  }
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

// Find a GLB camera by name, searching the collected camera list first (covers cameras outside the
// scene graph) then the root traversal as a fallback.
function findNamedCamera(state, name) {
  if (!name) return null;
  const collected = (state.cameras || []).find((cam) => cam?.isCamera && cam.name === name);
  if (collected) return collected;
  let found = null;
  state.root?.traverse?.((node) => {
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

// Point the preview camera at a named GLB scene camera's current world transform (the model/camera
// must already be posed at the desired time). Returns true if the named camera was found+applied.
function applyNamedCamera(state, camera, name) {
  const cam = findNamedCamera(state, name);
  if (!cam) return false;
  cam.updateWorldMatrix(true, false);
  const pos = new THREE.Vector3();
  const quat = new THREE.Quaternion();
  const scl = new THREE.Vector3();
  cam.matrixWorld.decompose(pos, quat, scl);
  camera.position.copy(pos);
  camera.quaternion.copy(quat);
  if (cam.isPerspectiveCamera && Number.isFinite(cam.fov)) camera.fov = cam.fov;
  camera.updateProjectionMatrix();
  return true;
}

// Apply a supplied view to the preview camera. Returns a short path label describing which strategy
// drove the camera (for diagnostics), or null if nothing usable was applied (caller falls back to
// generic frameObject() framing — never black-screens).
function applySuppliedView(state, view) {
  if (!view || !state.root) return null;
  const camera = state.camera;
  const center = applyClipPlanesFromBounds(camera, state.root);
  const name = typeof view.camera_name === "string" ? view.camera_name : "";

  // Prefer the actual GLB scene camera for scene_camera views: reproduces the workspace exactly,
  // including an animated camera's motion at the time the model was just posed to.
  if (view.mode === "scene_camera" && name) {
    if (applyNamedCamera(state, camera, name)) return `scene-camera:${name}`;
    console.warn(`[ref3d] scene camera "${name}" not found in GLB — using saved transform`);
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
    return `saved-transform:${view.mode || "free_view"}`;
  }

  // No numeric position — last resort: resolve any camera by name (mode unknown).
  if (name && applyNamedCamera(state, camera, name)) return `named-camera:${name}`;

  return null;
}

// Frame the model with the supplied view if present/usable, else the default orbit framing.
// Records whether a view drove the camera (state.hasView) so the render loop can skip the
// idle auto-rotate when reproducing a specific camera.
function applyViewOrFrame(state) {
  let path = null;
  const view = parseView(state.canvas);
  // Pose the model (and any animated camera) at the view's time before reading camera transforms,
  // so the preview matches the Scene3D workspace at that animation time.
  syncAnimationTime(state, view?.time ?? 0);
  if (view) {
    try {
      path = applySuppliedView(state, view);
    } catch (error) {
      console.warn("Reference 3D preview view apply failed:", error);
      path = null;
    }
    // Diagnostic (fires on view changes, not per frame): which strategy drove the preview camera.
    console.info(
      `[ref3d] preview view: ${path || "fallback-framing"} · mode=${view.mode || "-"} · cam=${view.camera_name || "-"} · t=${view.time ?? 0}`,
    );
  }
  const applied = !!path;
  if (!applied) {
    const center = frameObject(state.camera, state.root);
    if (center) state.center.copy(center);
  }
  state.hasView = applied;
  state.viewKey = state.canvas.dataset.refModelView || "";
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
      powerPreference: "low-power",
      // Required so captureReferenceModelFrame's toDataURL readback is reliable across drivers
      // (matches the Scene3D workspace renderer); without it the buffer may be cleared first.
      preserveDrawingBuffer: true,
    });
  } catch (error) {
    console.warn("Reference 3D preview WebGL unavailable:", error);
    markCanvasFailed(canvas, url);
    return;
  }

  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  // Match the Scene3D workspace renderer so a head-on scene camera doesn't blow out to white:
  // tone mapping compresses bright PBR highlights instead of hard-clipping them.
  renderer.toneMapping = THREE.AgXToneMapping ?? THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.0;

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x111827);
  const camera = new THREE.PerspectiveCamera(42, 1, 0.01, 500);
  scene.add(new THREE.AmbientLight(0xffffff, 0.45));
  const sun = new THREE.DirectionalLight(0xffffff, 1.1);
  sun.position.set(4, 8, 6);
  scene.add(sun);

  // Image-based lighting (same RoomEnvironment the workspace uses) so PBR materials shade like the
  // workspace rather than rendering flat/over-bright. Best-effort: tone mapping alone still helps.
  let envMap = null;
  try {
    const pmrem = new THREE.PMREMGenerator(renderer);
    const room = new RoomEnvironment();
    envMap = pmrem.fromScene(room, 0.04).texture;
    room.dispose?.();
    pmrem.dispose?.(); // generator scratch no longer needed; the env texture stands alone
    scene.environment = envMap;
  } catch (error) {
    console.warn("Reference 3D preview environment unavailable:", error);
  }

  const state = {
    url,
    canvas,
    renderer,
    scene,
    camera,
    root: null,
    center: new THREE.Vector3(),
    cameras: [],
    mixer: null,
    actions: [],
    envMap,
    hasView: false,
    viewKey: "",
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
    scene.add(state.root);
    state.cameras = collectGltfCameras(state.root, gltf);
    if (gltf.animations && gltf.animations.length) {
      state.mixer = new THREE.AnimationMixer(state.root);
      state.actions = gltf.animations.map((clip) => state.mixer.clipAction(clip));
    }
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

// Wait for the preview under `canvas` to finish loading its GLB (so capture can read state.root).
async function waitForPreviewReady(canvas, timeoutMs = 8000) {
  const start = performance.now();
  for (;;) {
    const state = previewState.get(canvas);
    if (state && !state.disposed && state.root) return state;
    if (canvas.dataset.refModelFailed === "true") throw new Error("3D preview failed to load");
    if (performance.now() - start > timeoutMs) throw new Error("3D preview not ready (timed out)");
    await new Promise((resolve) => requestAnimationFrame(() => resolve()));
  }
}

/**
 * Render one frame of the mounted GLB preview under `root` at the given animation time + view and
 * return a PNG data URL. Used by reference assignment to bake a board image per shot from the GLB.
 * Throws an explicit error if no preview/model is available; never silently black-screens.
 */
export async function captureReferenceModelFrame(root, options = {}) {
  const { time = 0, view = null, width = 1920, height = 1080 } = options;
  const canvas = root?.querySelector?.("[data-ref-model-preview]");
  if (!canvas) throw new Error("captureReferenceModelFrame: no 3D preview canvas under root");

  const state = await waitForPreviewReady(canvas);
  const { renderer, camera, scene } = state;

  // Pose the model (and animated camera) at this board's time, then drive the camera from the view.
  syncAnimationTime(state, time);
  // Drop the idle auto-rotation (live preview spins generic models) so captures are deterministic.
  if (state.root) state.root.rotation.y = 0;
  let path = null;
  if (view) {
    try {
      path = applySuppliedView(state, view);
    } catch (error) {
      console.warn("[ref3d] capture view apply failed:", error);
      path = null;
    }
  }
  if (!path) frameObject(camera, state.root);

  const w = Math.max(1, Math.floor(width));
  const h = Math.max(1, Math.floor(height));
  console.info(
    `[ref3d] capture: ${path || "fallback-framing"} · cam=${view?.camera_name || "-"} · t=${time} · ${w}x${h}`,
  );

  // Render at the requested export size, capture, then restore the on-screen preview size + view.
  const prevSize = new THREE.Vector2();
  renderer.getSize(prevSize);
  const prevRatio = renderer.getPixelRatio();
  const prevAspect = camera.aspect;

  let url;
  try {
    renderer.setPixelRatio(1);
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    renderer.render(scene, camera);
    if (isCapturedFrameBlank(renderer.domElement)) {
      throw new Error(
        "Rendered an empty 3D frame — the model is not visible at this animation time/camera. Adjust the camera, time, or range.",
      );
    }
    url = renderer.domElement.toDataURL("image/png");
  } finally {
    renderer.setPixelRatio(prevRatio);
    renderer.setSize(prevSize.x, prevSize.y, false);
    camera.aspect = prevAspect;
    camera.updateProjectionMatrix();
    // Return the live preview to its own (static) view.
    applyViewOrFrame(state);
    safeRender(state);
  }

  if (!url || url.length < 128) throw new Error("captureReferenceModelFrame: empty frame");
  return url;
}

window.disposeReferenceModelPreviews = disposeReferenceModelPreviews;
window.hydrateReferenceModelPreviews = hydrateReferenceModelPreviews;
window.applyReferenceModelView = applyReferenceModelView;
window.captureReferenceModelFrame = captureReferenceModelFrame;
window.dispatchEvent(new Event("reference-model-preview-ready"));
document.querySelectorAll(".reference-media-panel").forEach((panel) => hydrateReferenceModelPreviews(panel));
