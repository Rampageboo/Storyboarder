import * as THREE from "three";
import { GLTFLoader } from "./vendor/three/GLTFLoader.js";

const previewState = new WeakMap();

function disposePreview(canvas) {
  const state = previewState.get(canvas);
  if (!state) return;
  if (state.rafId) cancelAnimationFrame(state.rafId);
  state.observer?.disconnect();
  state.resizeObserver?.disconnect();
  state.renderer?.dispose();
  previewState.delete(canvas);
}

export function disposeReferenceModelPreviews(root = document) {
  root.querySelectorAll("[data-ref-model-preview]").forEach((canvas) => disposePreview(canvas));
}

function frameObject(camera, object, offset = 1.35) {
  const box = new THREE.Box3().setFromObject(object);
  if (box.isEmpty()) return;
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

async function mountPreview(canvas) {
  const url = canvas.dataset.refModelPreview;
  if (!url || previewState.has(canvas)) return;

  const renderer = new THREE.WebGLRenderer({
    canvas,
    antialias: true,
    alpha: true,
    powerPreference: "low-power",
  });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.5));
  renderer.outputColorSpace = THREE.SRGBColorSpace;

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x111827);
  const camera = new THREE.PerspectiveCamera(42, 1, 0.01, 500);
  scene.add(new THREE.AmbientLight(0xffffff, 0.65));
  const sun = new THREE.DirectionalLight(0xffffff, 1.1);
  sun.position.set(4, 8, 6);
  scene.add(sun);

  const state = {
    renderer,
    scene,
    camera,
    root: null,
    center: new THREE.Vector3(),
    rafId: 0,
    visible: false,
    observer: null,
  };
  previewState.set(canvas, state);

  const resize = () => {
    const width = Math.max(1, canvas.clientWidth);
    const height = Math.max(1, canvas.clientHeight);
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
  };
  resize();

  const renderFrame = (time = 0) => {
    if (state.root) {
      state.root.rotation.y = time * 0.00035;
    }
    renderer.render(scene, camera);
  };

  const startLoop = () => {
    if (state.rafId) return;
    const tick = (time) => {
      if (!previewState.has(canvas)) return;
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

  try {
    const gltf = await new GLTFLoader().loadAsync(url);
    state.root = gltf.scene;
    scene.add(state.root);
    const center = frameObject(camera, state.root);
    if (center) state.center.copy(center);
    resize();
    renderFrame();
    if (state.visible) startLoop();
  } catch (error) {
    console.warn("Reference 3D preview failed:", error);
    const fallback = document.createElement("div");
    fallback.className = "reference-media-model-fallback";
    fallback.textContent = "3D";
    if (canvas.parentNode) canvas.replaceWith(fallback);
    previewState.delete(canvas);
  }

  const ro = new ResizeObserver(resize);
  ro.observe(canvas);
  state.resizeObserver = ro;
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
