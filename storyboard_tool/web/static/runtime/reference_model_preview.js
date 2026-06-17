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
    center: new THREE.Vector3(),
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
    if (state.root) state.root.rotation.y = time * 0.00035;
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
    const center = frameObject(camera, state.root);
    if (center) state.center.copy(center);
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

window.disposeReferenceModelPreviews = disposeReferenceModelPreviews;
window.hydrateReferenceModelPreviews = hydrateReferenceModelPreviews;
window.dispatchEvent(new Event("reference-model-preview-ready"));
document.querySelectorAll(".reference-media-panel").forEach((panel) => hydrateReferenceModelPreviews(panel));
