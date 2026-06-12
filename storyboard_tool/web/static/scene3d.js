import * as THREE from "./vendor/three/three.module.js";
import { OrbitControls } from "./vendor/three/OrbitControls.js";
import { TransformControls } from "./vendor/three/TransformControls.js";
import { GLTFLoader } from "./vendor/three/GLTFLoader.js";

const PRIMITIVE_TYPES = new Set(["cube", "sphere", "plane", "cylinder", "cone"]);

function makeId() {
  return crypto.randomUUID().replaceAll("-", "").slice(0, 12);
}

function vec3From(value, fallback = [0, 0, 0]) {
  if (Array.isArray(value) && value.length >= 3) {
    return [Number(value[0]) || 0, Number(value[1]) || 0, Number(value[2]) || 0];
  }
  return [...fallback];
}

function eulerFrom(value) {
  const [x, y, z] = vec3From(value);
  return [x, y, z];
}

function colorFrom(value, fallback = 0x808080) {
  if (typeof value === "string" && value.startsWith("#")) {
    return new THREE.Color(value).getHex();
  }
  return fallback;
}

function defaultSceneData() {
  return {
    source: "builtin",
    objects: [
      {
        id: "ground",
        name: "Ground",
        type: "plane",
        position: [0, 0, 0],
        rotation: [-Math.PI / 2, 0, 0],
        scale: [10, 10, 1],
        color: "#3a4048",
      },
      {
        id: "cube1",
        name: "Cube",
        type: "cube",
        position: [0, 0.5, 0],
        rotation: [0, 0, 0],
        scale: [1, 1, 1],
        color: "#3d8bfd",
      },
    ],
  };
}

function createMeshFromSpec(spec) {
  const color = colorFrom(spec.color);
  const material = new THREE.MeshStandardMaterial({ color, roughness: 0.55, metalness: 0.05 });
  let geometry;
  switch (spec.type) {
    case "sphere":
      geometry = new THREE.SphereGeometry(0.5, 32, 24);
      break;
    case "plane":
      geometry = new THREE.PlaneGeometry(1, 1);
      break;
    case "cylinder":
      geometry = new THREE.CylinderGeometry(0.5, 0.5, 1, 32);
      break;
    case "cone":
      geometry = new THREE.ConeGeometry(0.5, 1, 32);
      break;
    default:
      geometry = new THREE.BoxGeometry(1, 1, 1);
      break;
  }
  const mesh = new THREE.Mesh(geometry, material);
  mesh.castShadow = spec.type !== "plane";
  mesh.receiveShadow = spec.type === "plane";
  mesh.userData.objectId = spec.id;
  mesh.userData.objectName = spec.name || spec.type;
  mesh.userData.objectType = spec.type;
  const [px, py, pz] = vec3From(spec.position, [0, 0.5, 0]);
  const [rx, ry, rz] = eulerFrom(spec.rotation);
  const [sx, sy, sz] = vec3From(spec.scale, [1, 1, 1]);
  mesh.position.set(px, py, pz);
  mesh.rotation.set(rx, ry, rz);
  mesh.scale.set(sx, sy, sz);
  return mesh;
}

function formatTime(seconds) {
  const value = Math.max(0, Number(seconds) || 0);
  const mins = Math.floor(value / 60);
  const secs = (value % 60).toFixed(1).padStart(mins > 0 ? 4 : 1, "0");
  return mins > 0 ? `${mins}:${secs}` : `${secs}s`;
}

export class Scene3DEditor {
  constructor(rootEl, callbacks = {}) {
    this.rootEl = rootEl;
    this.callbacks = callbacks;
    this.sceneData = defaultSceneData();
    this.sceneMeta = {};
    this.mode = "builtin";
    this.objects = new Map();
    this.selectedId = null;
    this.transformMode = "translate";
    this.shotCameraHelper = null;
    this.animationId = null;
    this.clock = new THREE.Clock();

    this.blenderRoot = null;
    this.mixer = null;
    this.mixerActions = [];
    this.importedCameras = [];
    this.activeCameraId = "";
    this.followCamera = true;
    this.syncTimeline = true;
    this.isPlaying = false;
    this.animationTime = 0;
    this.animationDuration = 0;

    this._buildDom();
    this._initThree();
    this._bindUi();
  }

  _buildDom() {
    this.rootEl.innerHTML = `
      <div class="scene3d-layout">
        <aside class="scene3d-sidebar">
          <div class="scene3d-panel-title">Blender 场景</div>
          <div class="scene3d-blender-panel">
            <div class="scene3d-file-name" data-blend-name>scene3d/scene.blend</div>
            <button type="button" data-action="open-blender" class="scene3d-import-btn">在 Blender 中打开</button>
            <button type="button" data-action="import-blender" class="scene3d-import-btn">导入 GLB / GLTF</button>
            <label class="scene3d-check">
              <input type="checkbox" data-follow-camera checked />
              跟随相机视角
            </label>
            <label class="scene3d-check">
              <input type="checkbox" data-sync-timeline checked />
              同步分镜时间轴
            </label>
            <label class="scene3d-field">
              <span>相机</span>
              <select data-camera-select disabled>
                <option value="">（无相机）</option>
              </select>
            </label>
          </div>
          <div class="scene3d-panel-title">Outliner</div>
          <ul class="scene3d-outliner" data-outliner></ul>
          <div class="scene3d-panel-title scene3d-builtin-only">Transform</div>
          <div class="scene3d-transform-fields scene3d-builtin-only">
            <label>位置 X <input type="number" step="0.1" data-tf="px" /></label>
            <label>位置 Y <input type="number" step="0.1" data-tf="py" /></label>
            <label>位置 Z <input type="number" step="0.1" data-tf="pz" /></label>
            <label>旋转 X <input type="number" step="1" data-tf="rx" /></label>
            <label>旋转 Y <input type="number" step="1" data-tf="ry" /></label>
            <label>旋转 Z <input type="number" step="1" data-tf="rz" /></label>
            <label>缩放 X <input type="number" step="0.1" min="0.01" data-tf="sx" /></label>
            <label>缩放 Y <input type="number" step="0.1" min="0.01" data-tf="sy" /></label>
            <label>缩放 Z <input type="number" step="0.1" min="0.01" data-tf="sz" /></label>
          </div>
        </aside>
        <div class="scene3d-main">
          <div class="scene3d-toolbar">
            <div class="scene3d-tool-group scene3d-builtin-only">
              <button type="button" data-mode="translate" class="active" title="移动 (G)">移动</button>
              <button type="button" data-mode="rotate" title="旋转 (R)">旋转</button>
              <button type="button" data-mode="scale" title="缩放 (S)">缩放</button>
            </div>
            <div class="scene3d-tool-group scene3d-builtin-only">
              <button type="button" data-add="cube">立方体</button>
              <button type="button" data-add="sphere">球体</button>
              <button type="button" data-add="plane">平面</button>
              <button type="button" data-add="cylinder">圆柱</button>
              <button type="button" data-add="cone">圆锥</button>
            </div>
            <div class="scene3d-tool-group scene3d-blender-only" hidden>
              <button type="button" data-action="play-pause">▶ 播放</button>
              <button type="button" data-action="stop-animation">■ 停止</button>
              <button type="button" data-action="free-view">自由视角</button>
            </div>
            <div class="scene3d-tool-group scene3d-builtin-only">
              <button type="button" data-action="delete" title="删除 (Del)">删除</button>
              <button type="button" data-action="focus" title="聚焦 (F)">聚焦</button>
              <button type="button" data-action="reset-view">重置视图</button>
            </div>
            <div class="scene3d-tool-group scene3d-tool-group-right scene3d-builtin-only">
              <button type="button" data-action="load-shot-camera">加载镜头相机</button>
              <button type="button" data-action="apply-shot-camera">保存镜头相机</button>
            </div>
          </div>
          <div class="scene3d-viewport" data-viewport></div>
          <div class="scene3d-timeline scene3d-blender-only" hidden>
            <input type="range" min="0" max="0" step="0.01" value="0" data-time-slider />
            <span data-time-display>0.0s / 0.0s</span>
          </div>
          <div class="scene3d-hint" data-hint>
            从 Blender 导出 GLB（勾选 Cameras + Animation）后导入 · 开启「跟随相机」可实时查看动画镜头
          </div>
        </div>
      </div>
    `;
    this.outlinerEl = this.rootEl.querySelector("[data-outliner]");
    this.viewportEl = this.rootEl.querySelector("[data-viewport]");
    this.fileNameEl = this.rootEl.querySelector("[data-blend-name]");
    this.cameraSelectEl = this.rootEl.querySelector("[data-camera-select]");
    this.followCameraEl = this.rootEl.querySelector("[data-follow-camera]");
    this.syncTimelineEl = this.rootEl.querySelector("[data-sync-timeline]");
    this.timeSliderEl = this.rootEl.querySelector("[data-time-slider]");
    this.timeDisplayEl = this.rootEl.querySelector("[data-time-display]");
    this.hintEl = this.rootEl.querySelector("[data-hint]");
    this.playPauseBtn = this.rootEl.querySelector("[data-action='play-pause']");
    this.transformInputs = {};
    this.rootEl.querySelectorAll("[data-tf]").forEach((input) => {
      this.transformInputs[input.dataset.tf] = input;
    });
  }

  _initThree() {
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    this.viewportEl.appendChild(this.renderer.domElement);

    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x1a1d21);

    this.camera = new THREE.PerspectiveCamera(50, 1, 0.01, 1000);
    this.camera.position.set(6, 4, 8);

    this.orbit = new OrbitControls(this.camera, this.renderer.domElement);
    this.orbit.enableDamping = true;
    this.orbit.target.set(0, 0.5, 0);

    this.transform = new TransformControls(this.camera, this.renderer.domElement);
    this.transform.setMode(this.transformMode);
    this.transform.addEventListener("dragging-changed", (event) => {
      this.orbit.enabled = !event.value && !this.followCamera;
    });
    this.transform.addEventListener("objectChange", () => {
      this._syncSelectedFromMesh();
      this._renderOutliner();
    });
    this.scene.add(this.transform);

    this.defaultAmbient = new THREE.AmbientLight(0xffffff, 0.45);
    this.scene.add(this.defaultAmbient);
    this.defaultSun = new THREE.DirectionalLight(0xffffff, 1.1);
    this.defaultSun.position.set(6, 10, 4);
    this.scene.add(this.defaultSun);

    this.grid = new THREE.GridHelper(20, 20, 0x4a515a, 0x3a4048);
    this.scene.add(this.grid);

    this.axes = new THREE.AxesHelper(2);
    this.scene.add(this.axes);

    this.raycaster = new THREE.Raycaster();
    this.pointer = new THREE.Vector2();

    this.renderer.domElement.addEventListener("pointerdown", (event) => this._onPointerDown(event));
    window.addEventListener("keydown", (event) => this._onKeyDown(event));
    this._resizeObserver = new ResizeObserver(() => this._resize());
    this._resizeObserver.observe(this.viewportEl);
    this._resize();
    this._animate();
  }

  _bindUi() {
    this.rootEl.querySelectorAll("[data-mode]").forEach((button) => {
      button.addEventListener("click", () => this.setTransformMode(button.dataset.mode));
    });
    this.rootEl.querySelectorAll("[data-add]").forEach((button) => {
      button.addEventListener("click", () => this.addObject(button.dataset.add));
    });
    this.rootEl.querySelectorAll("[data-action]").forEach((button) => {
      button.addEventListener("click", () => this._runAction(button.dataset.action));
    });
    Object.entries(this.transformInputs).forEach(([key, input]) => {
      input.addEventListener("change", () => this._applyTransformInputs(key));
      input.addEventListener("input", () => this._applyTransformInputs(key));
    });
    this.outlinerEl.addEventListener("click", (event) => {
      const item = event.target.closest("[data-object-id]");
      if (!item) return;
      if (item.dataset.cameraId) {
        this.setActiveCamera(item.dataset.cameraId);
        return;
      }
      this.selectObject(item.dataset.objectId);
    });
    this.followCameraEl.addEventListener("change", () => {
      this.setFollowCamera(this.followCameraEl.checked);
    });
    this.syncTimelineEl.addEventListener("change", () => {
      this.syncTimeline = this.syncTimelineEl.checked;
      if (this.syncTimeline) {
        this.pauseAnimation();
        this.syncTimelineTime(this.callbacks.getTimelineSeconds?.() || 0, this.callbacks.getTimelineTotal?.() || 0);
      }
    });
    this.cameraSelectEl.addEventListener("change", () => {
      this.setActiveCamera(this.cameraSelectEl.value);
    });
    this.timeSliderEl.addEventListener("input", () => {
      if (this.syncTimeline) return;
      this.setAnimationTime(Number(this.timeSliderEl.value || 0));
    });
  }

  _runAction(action) {
    switch (action) {
      case "delete":
        this.deleteSelected();
        break;
      case "focus":
        this.focusSelected();
        break;
      case "reset-view":
        this.resetView();
        break;
      case "load-shot-camera":
        this.loadShotCamera(this.callbacks.getShotCamera?.());
        break;
      case "apply-shot-camera":
        this.callbacks.onApplyShotCamera?.(this.getCameraState());
        break;
      case "import-blender":
        this.callbacks.onImportBlender?.();
        break;
      case "open-blender":
        this.callbacks.onOpenBlender?.();
        break;
      case "play-pause":
        this.toggleAnimationPlayback();
        break;
      case "stop-animation":
        this.stopAnimation();
        break;
      case "free-view":
        this.setFollowCamera(false);
        break;
      default:
        break;
    }
  }

  _onKeyDown(event) {
    if (event.target.matches("input, textarea, select")) return;
    if (this.mode === "blender") {
      if (event.code === "Space") {
        event.preventDefault();
        this.toggleAnimationPlayback();
      }
      return;
    }
    const key = event.key.toLowerCase();
    if (key === "g") this.setTransformMode("translate");
    if (key === "r") this.setTransformMode("rotate");
    if (key === "s") this.setTransformMode("scale");
    if (key === "delete") this.deleteSelected();
    if (key === "f") this.focusSelected();
  }

  _onPointerDown(event) {
    if (this.mode !== "builtin" || this.transform.dragging) return;
    const rect = this.renderer.domElement.getBoundingClientRect();
    this.pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
    this.pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
    this.raycaster.setFromCamera(this.pointer, this.camera);
    const hits = this.raycaster.intersectObjects([...this.objects.values()], false);
    if (hits.length) {
      this.selectObject(hits[0].object.userData.objectId);
    } else {
      this.selectObject(null);
    }
  }

  setTransformMode(mode) {
    this.transformMode = mode;
    this.transform.setMode(mode);
    this.rootEl.querySelectorAll("[data-mode]").forEach((button) => {
      button.classList.toggle("active", button.dataset.mode === mode);
    });
  }

  async loadSceneData(settings) {
    this.sceneMeta = settings && typeof settings === "object" ? { ...settings } : {};
    if (this.sceneMeta.source === "blender" && this.sceneMeta.file_path) {
      await this.loadBlenderFromProject(this.sceneMeta);
      return;
    }
    this.setMode("builtin");
    this.sceneData = this.sceneMeta.objects?.length ? this.sceneMeta : defaultSceneData();
    this.clearBlenderScene();
    this.clearObjects();
    for (const spec of this.sceneData.objects || []) {
      if (!PRIMITIVE_TYPES.has(spec.type)) continue;
      this._addMeshFromSpec(spec);
    }
    this.selectObject(this.sceneData.objects?.[0]?.id || null);
    this._renderOutliner();
    this._updateFileName();
  }

  async loadBlenderFromProject(meta) {
    this.setMode("blender");
    this.sceneMeta = { ...meta };
    this.followCamera = meta.follow_camera !== false;
    this.syncTimeline = meta.sync_timeline !== false;
    this.followCameraEl.checked = this.followCamera;
    this.syncTimelineEl.checked = this.syncTimeline;
    const url = `/api/project/scene3d/file?t=${Date.now()}`;
    await this._loadBlenderUrl(url, meta.file_name || meta.file_path);
    if (meta.camera_name) {
      const match = this.importedCameras.find((item) => item.name === meta.camera_name);
      if (match) this.setActiveCamera(match.id, false);
    } else if (this.importedCameras.length) {
      this.setActiveCamera(this.importedCameras[0].id, false);
    }
    const startTime = Number(meta.animation_time);
    if (!Number.isNaN(startTime) && startTime >= 0) {
      this.setAnimationTime(startTime);
    }
    this._updateFileName();
  }

  async _loadBlenderUrl(url, label) {
    this.clearBlenderScene();
    this.clearObjects();
    const loader = new GLTFLoader();
    const gltf = await loader.loadAsync(url);
    this.blenderRoot = gltf.scene;
    this.scene.add(this.blenderRoot);

    this.importedCameras = [];
    gltf.scene.updateMatrixWorld(true);
    gltf.scene.traverse((node) => {
      if (node.isCamera) {
        this.importedCameras.push({
          id: node.uuid,
          name: node.name || `Camera ${this.importedCameras.length + 1}`,
          camera: node,
        });
      }
    });
    if (Array.isArray(gltf.cameras)) {
      gltf.cameras.forEach((camera, index) => {
        if (this.importedCameras.some((item) => item.camera === camera)) return;
        this.importedCameras.push({
          id: camera.uuid,
          name: camera.name || `Camera ${index + 1}`,
          camera,
        });
      });
    }

    this.mixer = new THREE.AnimationMixer(gltf.scene);
    this.mixerActions = [];
    for (const clip of gltf.animations || []) {
      const action = this.mixer.clipAction(clip);
      action.play();
      action.paused = true;
      this.mixerActions.push(action);
    }
    this.animationDuration = Math.max(0, ...(gltf.animations || []).map((clip) => clip.duration));
    if (!this.animationDuration) this.animationDuration = 0;
    this.animationTime = 0;
    this.isPlaying = false;
    this._populateCameraSelect();
    this._renderOutliner();
    this._updateTimelineUi();
    this._frameImportedScene();
    this.sceneMeta.file_name = label || this.sceneMeta.file_name;
    this.setFollowCamera(this.followCamera);
    if (this.importedCameras.length === 0) {
      this.callbacks.onMessage?.("场景已加载，但未找到相机。请在 Blender 导出时勾选 Cameras。");
    } else if (!(gltf.animations || []).length) {
      this.callbacks.onMessage?.("场景已加载，但未找到动画。请在 Blender 导出时勾选 Animation。");
    }
  }

  _frameImportedScene() {
    if (!this.blenderRoot) return;
    const box = new THREE.Box3().setFromObject(this.blenderRoot);
    if (box.isEmpty()) return;
    const size = box.getSize(new THREE.Vector3());
    const center = box.getCenter(new THREE.Vector3());
    const radius = Math.max(size.x, size.y, size.z) * 0.6 || 4;
    this.orbit.target.copy(center);
    this.camera.position.copy(center.clone().add(new THREE.Vector3(radius, radius * 0.7, radius)));
    this.camera.near = Math.max(0.01, radius / 100);
    this.camera.far = Math.max(100, radius * 40);
    this.camera.updateProjectionMatrix();
    this.orbit.update();
  }

  _populateCameraSelect() {
    this.cameraSelectEl.innerHTML = "";
    if (!this.importedCameras.length) {
      const option = document.createElement("option");
      option.value = "";
      option.textContent = "（无相机）";
      this.cameraSelectEl.appendChild(option);
      this.cameraSelectEl.disabled = true;
      return;
    }
    for (const item of this.importedCameras) {
      const option = document.createElement("option");
      option.value = item.id;
      option.textContent = item.name;
      this.cameraSelectEl.appendChild(option);
    }
    this.cameraSelectEl.disabled = false;
    if (this.activeCameraId) {
      this.cameraSelectEl.value = this.activeCameraId;
    }
  }

  setActiveCamera(cameraId, showMessage = true) {
    const match = this.importedCameras.find((item) => item.id === cameraId);
    if (!match) return;
    this.activeCameraId = cameraId;
    this.cameraSelectEl.value = cameraId;
    this._renderOutliner();
    if (showMessage) {
      this.callbacks.onMessage?.(`已切换相机：${match.name}`);
    }
    if (this.followCamera) {
      this._applyFollowCamera();
    }
  }

  setFollowCamera(enabled) {
    this.followCamera = Boolean(enabled);
    this.followCameraEl.checked = this.followCamera;
    this.orbit.enabled = !this.followCamera;
    if (this.followCamera) {
      this._applyFollowCamera();
    }
  }

  setMode(mode) {
    this.mode = mode;
    this.rootEl.classList.toggle("scene3d-mode-blender", mode === "blender");
    this.rootEl.classList.toggle("scene3d-mode-builtin", mode === "builtin");
    this.rootEl.querySelectorAll(".scene3d-blender-only").forEach((node) => {
      node.hidden = mode !== "blender";
    });
    this.rootEl.querySelectorAll(".scene3d-builtin-only").forEach((node) => {
      node.hidden = mode === "blender";
    });
    this.grid.visible = mode === "builtin";
    this.axes.visible = mode === "builtin";
    this.defaultAmbient.visible = mode === "builtin";
    this.defaultSun.visible = mode === "builtin";
    if (mode === "blender") {
      this.transform.detach();
      this.selectObject(null);
    }
  }

  exportSceneData() {
    if (this.mode === "blender") {
      const active = this.importedCameras.find((item) => item.id === this.activeCameraId);
      return {
        ...this.sceneMeta,
        source: "blender",
        camera_name: active?.name || this.sceneMeta.camera_name || "",
        follow_camera: this.followCamera,
        sync_timeline: this.syncTimeline,
        animation_time: this.animationTime,
      };
    }
    const objects = [];
    for (const [id, mesh] of this.objects.entries()) {
      objects.push({
        id,
        name: mesh.userData.objectName,
        type: mesh.userData.objectType,
        position: mesh.position.toArray(),
        rotation: mesh.rotation.toArray().slice(0, 3),
        scale: mesh.scale.toArray(),
        color: `#${mesh.material.color.getHexString()}`,
      });
    }
    return { source: "builtin", objects };
  }

  clearBlenderScene() {
    if (this.mixer) {
      this.mixer.stopAllAction();
      this.mixer = null;
    }
    this.mixerActions = [];
    this.importedCameras = [];
    this.activeCameraId = "";
    this.animationDuration = 0;
    this.animationTime = 0;
    this.isPlaying = false;
    if (this.blenderRoot) {
      this.scene.remove(this.blenderRoot);
      this.blenderRoot.traverse((node) => {
        if (node.geometry) node.geometry.dispose();
        if (node.material) {
          if (Array.isArray(node.material)) node.material.forEach((item) => item.dispose());
          else node.material.dispose();
        }
      });
      this.blenderRoot = null;
    }
    this._populateCameraSelect();
    this._updateTimelineUi();
  }

  clearObjects() {
    for (const mesh of this.objects.values()) {
      this.scene.remove(mesh);
      mesh.geometry.dispose();
      mesh.material.dispose();
    }
    this.objects.clear();
    this.transform.detach();
    this.selectedId = null;
  }

  _addMeshFromSpec(spec) {
    const mesh = createMeshFromSpec(spec);
    this.objects.set(spec.id, mesh);
    this.scene.add(mesh);
    return mesh;
  }

  addObject(type) {
    const labels = { cube: "Cube", sphere: "Sphere", plane: "Plane", cylinder: "Cylinder", cone: "Cone" };
    const id = makeId();
    const spec = {
      id,
      name: `${labels[type] || "Object"} ${this.objects.size + 1}`,
      type,
      position: [0, type === "plane" ? 0 : 0.5, 0],
      rotation: type === "plane" ? [-Math.PI / 2, 0, 0] : [0, 0, 0],
      scale: type === "plane" ? [4, 4, 1] : [1, 1, 1],
      color: type === "plane" ? "#3a4048" : "#3d8bfd",
    };
    this._addMeshFromSpec(spec);
    this.selectObject(id);
    this._renderOutliner();
  }

  selectObject(id) {
    this.selectedId = id;
    const mesh = id ? this.objects.get(id) : null;
    if (mesh && this.mode === "builtin") {
      this.transform.attach(mesh);
    } else {
      this.transform.detach();
    }
    this._renderOutliner();
    this._updateTransformInputs();
  }

  deleteSelected() {
    if (!this.selectedId || this.selectedId === "ground") return;
    const mesh = this.objects.get(this.selectedId);
    if (!mesh) return;
    this.transform.detach();
    this.scene.remove(mesh);
    mesh.geometry.dispose();
    mesh.material.dispose();
    this.objects.delete(this.selectedId);
    this.selectedId = null;
    this._renderOutliner();
    this._updateTransformInputs();
  }

  focusSelected() {
    const mesh = this.selectedId ? this.objects.get(this.selectedId) : null;
    const target = mesh ? mesh.position.clone() : this.orbit.target.clone();
    this.orbit.target.copy(target);
    this.orbit.update();
  }

  resetView() {
    if (this.mode === "blender") {
      this._frameImportedScene();
      return;
    }
    this.camera.position.set(6, 4, 8);
    this.orbit.target.set(0, 0.5, 0);
    this.orbit.update();
  }

  getCameraState() {
    const target = this.orbit.target.clone();
    return {
      position: this.camera.position.toArray(),
      target: target.toArray(),
      rotation: this.camera.rotation.toArray().slice(0, 3),
      fov: this.camera.fov,
      focal_length: Math.round(this._fovToFocalLength(this.camera.fov)),
    };
  }

  loadShotCamera(cameraData) {
    if (!cameraData?.position) {
      this.callbacks.onMessage?.("当前镜头没有保存的 3D 相机数据");
      return;
    }
    this.setFollowCamera(false);
    const pos = vec3From(cameraData.position, [6, 4, 8]);
    this.camera.position.set(pos[0], pos[1], pos[2]);
    if (cameraData.target) {
      const target = vec3From(cameraData.target, [0, 0.5, 0]);
      this.orbit.target.set(target[0], target[1], target[2]);
    } else if (cameraData.rotation) {
      const [rx, ry, rz] = eulerFrom(cameraData.rotation);
      this.camera.rotation.set(rx, ry, rz);
      this.orbit.target.copy(this.camera.position.clone().add(this.camera.getWorldDirection(new THREE.Vector3())));
    }
    if (cameraData.fov) {
      this.camera.fov = Number(cameraData.fov) || 50;
      this.camera.updateProjectionMatrix();
    }
    this.orbit.update();
  }

  _fovToFocalLength(fov) {
    const sensor = 36;
    return sensor / (2 * Math.tan((fov * Math.PI) / 360));
  }

  _syncSelectedFromMesh() {
    this._updateTransformInputs();
  }

  _applyTransformInputs(changedKey) {
    const mesh = this.selectedId ? this.objects.get(this.selectedId) : null;
    if (!mesh) return;
    const read = (key, fallback) => Number(this.transformInputs[key]?.value) || fallback;
    mesh.position.set(read("px", mesh.position.x), read("py", mesh.position.y), read("pz", mesh.position.z));
    mesh.rotation.set(
      THREE.MathUtils.degToRad(read("rx", THREE.MathUtils.radToDeg(mesh.rotation.x))),
      THREE.MathUtils.degToRad(read("ry", THREE.MathUtils.radToDeg(mesh.rotation.y))),
      THREE.MathUtils.degToRad(read("rz", THREE.MathUtils.radToDeg(mesh.rotation.z))),
    );
    mesh.scale.set(
      Math.max(0.01, read("sx", mesh.scale.x)),
      Math.max(0.01, read("sy", mesh.scale.y)),
      Math.max(0.01, read("sz", mesh.scale.z)),
    );
    if (changedKey) {
      this.transform.updateMatrixWorld();
    }
  }

  _updateTransformInputs() {
    const mesh = this.selectedId ? this.objects.get(this.selectedId) : null;
    const disabled = !mesh;
    Object.values(this.transformInputs).forEach((input) => {
      input.disabled = disabled;
    });
    if (!mesh) return;
    this.transformInputs.px.value = mesh.position.x.toFixed(2);
    this.transformInputs.py.value = mesh.position.y.toFixed(2);
    this.transformInputs.pz.value = mesh.position.z.toFixed(2);
    this.transformInputs.rx.value = THREE.MathUtils.radToDeg(mesh.rotation.x).toFixed(1);
    this.transformInputs.ry.value = THREE.MathUtils.radToDeg(mesh.rotation.y).toFixed(1);
    this.transformInputs.rz.value = THREE.MathUtils.radToDeg(mesh.rotation.z).toFixed(1);
    this.transformInputs.sx.value = mesh.scale.x.toFixed(2);
    this.transformInputs.sy.value = mesh.scale.y.toFixed(2);
    this.transformInputs.sz.value = mesh.scale.z.toFixed(2);
  }

  _renderOutliner() {
    this.outlinerEl.innerHTML = "";
    if (this.mode === "blender") {
      for (const item of this.importedCameras) {
        const li = document.createElement("li");
        li.dataset.cameraId = item.id;
        li.className = item.id === this.activeCameraId ? "active" : "";
        li.textContent = `📷 ${item.name}`;
        this.outlinerEl.appendChild(li);
      }
      if (!this.importedCameras.length) {
        const empty = document.createElement("li");
        empty.className = "scene3d-empty";
        empty.textContent = "无相机";
        this.outlinerEl.appendChild(empty);
      }
      return;
    }
    for (const [id, mesh] of this.objects.entries()) {
      const li = document.createElement("li");
      li.dataset.objectId = id;
      li.className = id === this.selectedId ? "active" : "";
      li.textContent = mesh.userData.objectName;
      this.outlinerEl.appendChild(li);
    }
  }

  _updateFileName() {
    const blendPath = this.sceneMeta.blend_file_path || "scene3d/scene.blend";
    const glbName = this.sceneMeta.file_name || this.sceneMeta.file_path || "";
    if (this.mode === "blender" && glbName) {
      this.fileNameEl.textContent = `GLB: ${String(glbName).split("/").pop()}`;
      return;
    }
    this.fileNameEl.textContent = blendPath.split("/").pop() || "scene.blend";
  }

  setBlendFilePath(relativePath) {
    this.sceneMeta = { ...(this.sceneMeta || {}), blend_file_path: relativePath || "scene3d/scene.blend" };
    this._updateFileName();
  }

  setAnimationTime(seconds) {
    const duration = this.animationDuration || 0;
    this.animationTime = duration > 0 ? Math.min(Math.max(0, seconds), duration) : Math.max(0, seconds);
    if (this.mixer) {
      this.mixer.setTime(this.animationTime);
    }
    this._updateTimelineUi();
    if (this.followCamera) {
      this._applyFollowCamera();
    }
  }

  toggleAnimationPlayback() {
    if (this.syncTimeline) {
      this.callbacks.onMessage?.("已开启分镜同步，请使用底部时间轴播放");
      return;
    }
    this.isPlaying = !this.isPlaying;
    this._updatePlayButton();
  }

  pauseAnimation() {
    this.isPlaying = false;
    this._updatePlayButton();
  }

  stopAnimation() {
    this.isPlaying = false;
    this.setAnimationTime(0);
    this._updatePlayButton();
  }

  syncTimelineTime(storyboardSeconds, storyboardTotal) {
    if (!this.syncTimeline || this.mode !== "blender" || !this.mixer) return;
    const total = Math.max(storyboardTotal || 0, 0.001);
    const duration = this.animationDuration || total;
    const mapped = (Math.max(0, storyboardSeconds) / total) * duration;
    this.setAnimationTime(mapped);
  }

  _updatePlayButton() {
    if (!this.playPauseBtn) return;
    this.playPauseBtn.textContent = this.isPlaying ? "⏸ 暂停" : "▶ 播放";
  }

  _updateTimelineUi() {
    const duration = this.animationDuration || 0;
    this.timeSliderEl.max = duration.toFixed(2);
    this.timeSliderEl.value = this.animationTime.toFixed(2);
    this.timeSliderEl.disabled = this.syncTimeline || duration <= 0;
    this.timeDisplayEl.textContent = `${formatTime(this.animationTime)} / ${formatTime(duration)}`;
  }

  _applyFollowCamera() {
    const active = this.importedCameras.find((item) => item.id === this.activeCameraId);
    if (!active) return;
    active.camera.updateWorldMatrix(true, false);
    const source = active.camera;
    this.camera.position.setFromMatrixPosition(source.matrixWorld);
    const rotation = new THREE.Matrix4().extractRotation(source.matrixWorld);
    this.camera.quaternion.setFromRotationMatrix(rotation);
    if (source.isPerspectiveCamera) {
      this.camera.fov = source.fov;
      this.camera.near = Math.max(0.001, source.near);
      this.camera.far = Math.max(this.camera.near + 1, source.far);
      this.camera.updateProjectionMatrix();
    }
    this.orbit.enabled = false;
  }

  _resize() {
    const width = this.viewportEl.clientWidth;
    const height = this.viewportEl.clientHeight;
    if (!width || !height) return;
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(width, height, false);
  }

  _animate() {
    this.animationId = requestAnimationFrame(() => this._animate());
    const delta = this.clock.getDelta();
    if (this.mode === "blender" && this.mixer && this.isPlaying && !this.syncTimeline) {
      this.animationTime += delta;
      if (this.animationDuration > 0 && this.animationTime >= this.animationDuration) {
        this.animationTime = this.animationDuration;
        this.isPlaying = false;
        this._updatePlayButton();
      }
      this.mixer.setTime(this.animationTime);
      this._updateTimelineUi();
    }
    if (this.followCamera && this.mode === "blender") {
      this._applyFollowCamera();
    } else {
      this.orbit.update();
    }
    this.renderer.render(this.scene, this.camera);
  }

  dispose() {
    if (this.animationId) cancelAnimationFrame(this.animationId);
    this._resizeObserver?.disconnect();
    this.clearBlenderScene();
    this.clearObjects();
    this.transform.dispose();
    this.orbit.dispose();
    this.renderer.dispose();
    if (this.renderer.domElement.parentNode) {
      this.renderer.domElement.parentNode.removeChild(this.renderer.domElement);
    }
  }
}
