import * as THREE from "/static/vendor/three/three.module.js";
import { OrbitControls } from "/static/vendor/three/OrbitControls.js";
import { TransformControls } from "/static/vendor/three/TransformControls.js";
import { GLTFLoader } from "/static/vendor/three/GLTFLoader.js";
import { RoomEnvironment } from "/static/vendor/three/RoomEnvironment.js";
import {
  generateObjectColor,
  normalizeWireframeMode,
  objectColorKey,
  applyObjectColorPreview as applySharedObjectColorPreview,
  applyWireframeModeToRoots,
  clearWireframeOverlays,
  createWireframeResources,
} from "./scene3d_preview_style.js";
import {
  makeId,
  vec3From,
  eulerFrom,
  colorFrom,
  defaultSceneData,
  createMeshFromSpec,
  PRIMITIVE_TYPES,
  captureRendererPng,
  exportViewState,
  getCameraStateFromEditor,
  fovToFocalLength,
  getProjectCanvasSize,
  getProjectCanvasAspect,
  exportBuiltinSceneData,
  exportBlenderSceneData,
  formatWorkspaceTime,
  disposeObject3DRoot,
  disposePrimitiveMesh,
} from "./scene3d_workspace.js";

function formatTime(seconds) {
  return formatWorkspaceTime(seconds);
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
    this.isPlaying = false;
    this.programLightingMode = "auto";
    this.importedLightCount = 0;
    this.objectColorPreview = true;
    this.previewMaterials = new Set();
    this.wireframeMode = "off";
    this.wireframeResources = createWireframeResources();
    this.animationTime = 0;
    this.animationDuration = 0;
    this.animatedNodeNames = new Set();
    this._followPos = new THREE.Vector3();
    this._followQuat = new THREE.Quaternion();
    this._followScale = new THREE.Vector3();
    this._probePosA = new THREE.Vector3();
    this._probePosB = new THREE.Vector3();
    this._sceneSettingsSaveTimer = null;

    this._buildDom();
    this._initThree();
    this._bindUi();
  }

  _buildDom() {
    this.rootEl.innerHTML = `
      <div class="scene3d-layout">
        <aside class="scene3d-sidebar">
          <div class="scene3d-panel-title">当前分镜预览</div>
          <div class="scene3d-board-preview" data-board-preview>
            <img data-board-preview-img alt="" hidden />
            <span class="scene3d-board-preview-empty" data-board-preview-empty>无预览 · Capture 后显示</span>
          </div>
          <div class="scene3d-board-label" data-board-label>—</div>
          <div class="scene3d-panel-title">Blender 场景</div>
          <div class="scene3d-blender-panel">
            <div class="scene3d-file-name" data-blend-name>scene3d/scene.blend</div>
            <button type="button" data-action="open-blender" class="scene3d-import-btn">在 Blender 中打开</button>
            <button type="button" data-action="import-blender" class="scene3d-import-btn">导入 GLB / GLTF</button>
            <button type="button" data-action="reload-glb" class="scene3d-import-btn">刷新 GLB</button>
            <label class="scene3d-check">
              <input type="checkbox" data-follow-camera checked />
              跟随相机视角
            </label>
            <label class="scene3d-check">
              <input type="checkbox" data-object-colors checked />
              对象随机色（低饱和，便于区分）
            </label>
            <label class="scene3d-field">
              <span>线框</span>
              <select data-wireframe-mode>
                <option value="off">关闭</option>
                <option value="on">标准（叠加边线）</option>
                <option value="strong">强化（全边线 + 高亮）</option>
              </select>
            </label>
            <label class="scene3d-field">
              <span>程序补光</span>
              <select data-program-lighting>
                <option value="auto">自动（有灯：环境反射；无灯：全补光）</option>
                <option value="on">始终开启（环境 + 柔光）</option>
                <option value="off">关闭（仅 GLB 灯光）</option>
              </select>
            </label>
            <div class="scene3d-light-status" data-light-status>—</div>
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
              <button type="button" data-action="go-to-start" title="回到开头">⏮ 开头</button>
              <button type="button" data-action="step-back" title="后退 0.1s">◀</button>
              <button type="button" data-action="step-forward" title="前进 0.1s">▶</button>
              <button type="button" data-action="capture-board">印到当前分镜</button>
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
          <div class="scene3d-viewport" data-viewport>
            <div class="scene3d-format-frame" data-format-frame></div>
          </div>
          <div class="scene3d-timeline scene3d-blender-only" hidden>
            <input type="range" min="0" max="0" step="0.01" value="0" data-time-slider />
            <span data-time-display>0.0s / 0.0s</span>
          </div>
          <div class="scene3d-hint" data-hint>
            空格播放/暂停 · ←→ 步进 0.1s（Shift 0.5s）· Home 回开头 · F5 刷新 GLB · 播完停在最后一帧
          </div>
        </div>
      </div>
    `;
    this.outlinerEl = this.rootEl.querySelector("[data-outliner]");
    this.viewportEl = this.rootEl.querySelector("[data-viewport]");
    this.formatFrameEl = this.rootEl.querySelector("[data-format-frame]");
    this.fileNameEl = this.rootEl.querySelector("[data-blend-name]");
    this.cameraSelectEl = this.rootEl.querySelector("[data-camera-select]");
    this.followCameraEl = this.rootEl.querySelector("[data-follow-camera]");
    this.objectColorsEl = this.rootEl.querySelector("[data-object-colors]");
    this.wireframeModeEl = this.rootEl.querySelector("[data-wireframe-mode]");
    this.programLightingEl = this.rootEl.querySelector("[data-program-lighting]");
    this.lightStatusEl = this.rootEl.querySelector("[data-light-status]");
    this.timeSliderEl = this.rootEl.querySelector("[data-time-slider]");
    this.timeDisplayEl = this.rootEl.querySelector("[data-time-display]");
    this.boardPreviewImg = this.rootEl.querySelector("[data-board-preview-img]");
    this.boardPreviewEmpty = this.rootEl.querySelector("[data-board-preview-empty]");
    this.boardLabelEl = this.rootEl.querySelector("[data-board-label]");
    this.playPauseBtn = this.rootEl.querySelector("[data-action='play-pause']");
    this.hintEl = this.rootEl.querySelector("[data-hint]");
    this.transformInputs = {};
    this.rootEl.querySelectorAll("[data-tf]").forEach((input) => {
      this.transformInputs[input.dataset.tf] = input;
    });
  }

  _initThree() {
    this.renderer = new THREE.WebGLRenderer({
      antialias: true,
      alpha: false,
      preserveDrawingBuffer: true,
    });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.toneMapping = THREE.AgXToneMapping ?? THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.0;
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    this.formatFrameEl.appendChild(this.renderer.domElement);

    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x1a1d21);

    this.camera = new THREE.PerspectiveCamera(50, 1, 0.01, 1000);
    this.camera.position.set(6, 4, 8);

    this.orbit = new OrbitControls(this.camera, this.renderer.domElement);
    this.orbit.enableDamping = true;
    this.orbit.target.set(0, 0.5, 0);
    // Persist free-orbit view changes (React debounces). Only for a loaded GLB scene and only when
    // not following a scene camera; suppressed during programmatic scene loads. This also covers
    // resetView()/focusSelected(), which change the view via orbit.update().
    this.orbit.addEventListener("change", () => {
      if (this.mode === "blender" && !this.followCamera) this._notifyViewChange();
    });

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

    this.pmremGenerator = new THREE.PMREMGenerator(this.renderer);
    this.pmremGenerator.compileEquirectangularShader();
    this.blenderEnvMap = null;
    this.builtinBackground = new THREE.Color(0x1a1d21);

    this.programAmbient = new THREE.AmbientLight(0xffffff, 0.1);
    this.programAmbient.visible = false;
    this.scene.add(this.programAmbient);
    this.programHemisphere = new THREE.HemisphereLight(0xd8e4ef, 0x404048, 0.28);
    this.programHemisphere.visible = false;
    this.scene.add(this.programHemisphere);

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
      const cameraItem = event.target.closest("[data-camera-id]");
      if (cameraItem) {
        this.setFollowCamera(true, { persist: false });
        this.setActiveCamera(cameraItem.dataset.cameraId);
        return;
      }
      const objectItem = event.target.closest("[data-object-id]");
      if (!objectItem) return;
      this.selectObject(objectItem.dataset.objectId);
    });
    this.followCameraEl.addEventListener("change", () => {
      this.setFollowCamera(this.followCameraEl.checked);
    });
    this.objectColorsEl?.addEventListener("change", () => {
      this.setObjectColorPreview(this.objectColorsEl.checked);
    });
    this.wireframeModeEl?.addEventListener("change", () => {
      this.setWireframeMode(this.wireframeModeEl.value);
    });
    this.programLightingEl?.addEventListener("change", () => {
      this.setProgramLightingMode(this.programLightingEl.value);
    });
    this.cameraSelectEl.addEventListener("change", () => {
      this.setActiveCamera(this.cameraSelectEl.value);
    });
    this.timeSliderEl.addEventListener("input", () => {
      if (this.isPlaying) {
        this.isPlaying = false;
        this._updatePlayButton();
      }
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
      case "go-to-start":
        this.goToAnimationStart();
        break;
      case "step-back":
        this.stepAnimation(-0.1);
        break;
      case "step-forward":
        this.stepAnimation(0.1);
        break;
      case "reload-glb":
        this.reloadBlenderScene();
        break;
      case "free-view":
        this.setFollowCamera(false);
        break;
      case "capture-board":
        this.callbacks.onCaptureToBoard?.();
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
        return;
      }
      if (event.code === "F5") {
        event.preventDefault();
        this.reloadBlenderScene();
        return;
      }
      if (event.key === "Home") {
        event.preventDefault();
        this.goToAnimationStart();
        return;
      }
      if (event.key === "ArrowLeft") {
        event.preventDefault();
        this.stepAnimation(event.shiftKey ? -0.5 : -0.1);
        return;
      }
      if (event.key === "ArrowRight") {
        event.preventDefault();
        this.stepAnimation(event.shiftKey ? 0.5 : 0.1);
        return;
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

  _scheduleSceneSettingsSave() {
    if (!this.callbacks.onSceneSettingsChange) return;
    window.clearTimeout(this._sceneSettingsSaveTimer);
    this._sceneSettingsSaveTimer = window.setTimeout(() => {
      this.callbacks.onSceneSettingsChange(this.exportSceneData());
    }, 350);
  }

  applyDisplaySettings(meta = {}) {
    if (!meta || typeof meta !== "object") return;
    this.setFollowCamera(meta.follow_camera !== false, { persist: false });
    this.setProgramLightingMode(meta.program_lighting || "auto", { persist: false, notify: false });
    this.setObjectColorPreview(meta.object_color_preview !== false, { persist: false, notify: false });
    this.setWireframeMode(meta.wireframe_mode || "off", { persist: false, notify: false });
  }

  async loadSceneData(settings) {
    this.sceneMeta = settings && typeof settings === "object" ? { ...settings } : {};
    this.setWireframeMode(this.sceneMeta.wireframe_mode || "off", { persist: false, notify: false });
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
    this._applyWireframeMode();
  }

  _normalizeWireframeMode(mode) {
    return normalizeWireframeMode(mode);
  }

  setWireframeMode(mode, { persist = true, notify = false } = {}) {
    this.wireframeMode = this._normalizeWireframeMode(mode);
    if (this.wireframeModeEl) this.wireframeModeEl.value = this.wireframeMode;
    if (persist) {
      this.sceneMeta = { ...(this.sceneMeta || {}), wireframe_mode: this.wireframeMode };
    }
    this._applyWireframeMode();
    if (persist) this._scheduleSceneSettingsSave();
    if (notify) {
      const labels = { off: "关闭", on: "标准", strong: "强化" };
      this.callbacks.onMessage?.(`线框：${labels[this.wireframeMode]}`);
    }
  }

  _getWireframeRoots() {
    const roots = [];
    if (this.blenderRoot) roots.push(this.blenderRoot);
    for (const mesh of this.objects.values()) roots.push(mesh);
    return roots;
  }

  _clearWireframeOverlays() {
    if (!this.wireframeResources) {
      this.wireframeResources = createWireframeResources();
    }
    clearWireframeOverlays(this._getWireframeRoots(), this.wireframeResources);
  }

  _restoreWireframeFillOpacity(_root) {
    // handled by clearWireframeOverlays / applyWireframeModeToRoots in scene3d_preview_style.js
  }

  _applyWireframeMode() {
    if (!this.wireframeResources) {
      this.wireframeResources = createWireframeResources();
    }
    applyWireframeModeToRoots(THREE, this._getWireframeRoots(), this.wireframeMode, this.wireframeResources);
  }

  async loadBlenderFromProject(meta) {
    this.setMode("blender");
    // Suppress reference-view persistence while restoring the saved camera/time/framing below so a
    // scene load never overwrites settings.scene3d.reference_view.
    this._suppressViewChange = true;
    try {
    this.sceneMeta = { ...meta };
    this.followCamera = meta.follow_camera !== false;
    this.followCameraEl.checked = this.followCamera;
    this.programLightingMode = meta.program_lighting === "on" || meta.program_lighting === "off" ? meta.program_lighting : "auto";
    if (this.programLightingEl) this.programLightingEl.value = this.programLightingMode;
    this.objectColorPreview = meta.object_color_preview !== false;
    if (this.objectColorsEl) this.objectColorsEl.checked = this.objectColorPreview;
    this.setWireframeMode(meta.wireframe_mode || "off", { persist: false, notify: false });
    const url = `/api/project/scene3d/file?t=${Date.now()}`;
    await this._loadBlenderUrl(url, meta.file_name || meta.file_path);
    if (meta.camera_name) {
      this.setActiveCamera(this._pickBestCameraId(meta.camera_name), false);
    } else if (this.importedCameras.length) {
      this.setActiveCamera(this._pickBestCameraId(""), false);
    }
    const shotTime = this.callbacks.getShotScene3dTime?.();
    const startTime =
      shotTime != null && !Number.isNaN(Number(shotTime))
        ? Number(shotTime)
        : Number(meta.animation_time);
    if (!Number.isNaN(startTime) && startTime >= 0) {
      this.setAnimationTime(startTime);
    }
    this._updateFileName();
    this._updateAnimationHint();
    } finally {
      this._suppressViewChange = false;
    }
  }

  async reloadBlenderScene() {
    if (!this.sceneMeta?.file_path) {
      this.callbacks.onMessage?.("当前项目没有 GLB，请先 Import GLB");
      return;
    }
    const savedTime = this.animationTime;
    const savedCameraName =
      this.importedCameras.find((item) => item.id === this.activeCameraId)?.name ||
      this.sceneMeta.camera_name ||
      "";
    this.isPlaying = false;
    this._updatePlayButton();
    // Suppress reference-view persistence while restoring the saved camera/time on reload.
    this._suppressViewChange = true;
    try {
      const url = `/api/project/scene3d/file?t=${Date.now()}`;
      await this._loadBlenderUrl(url, this.sceneMeta.file_name || this.sceneMeta.file_path);
      if (savedCameraName) {
        this.setActiveCamera(this._pickBestCameraId(savedCameraName), false);
      }
      if (savedTime > 0) {
        this.setAnimationTime(Math.min(savedTime, this.animationDuration));
      }
      this.callbacks.onMessage?.("已刷新 GLB（保留时间与显示设置）");
    } catch (error) {
      this.callbacks.onMessage?.(`刷新 GLB 失败：${error?.message || error}`);
    } finally {
      this._suppressViewChange = false;
    }
  }

  _trackNodeName(trackName) {
    const dot = String(trackName || "").lastIndexOf(".");
    return dot > 0 ? trackName.slice(0, dot) : trackName;
  }

  _collectAnimatedNodeNames(animations) {
    const names = new Set();
    for (const clip of animations || []) {
      for (const track of clip.tracks || []) {
        const nodeName = this._trackNodeName(track.name);
        if (nodeName) names.add(nodeName);
      }
    }
    return names;
  }

  _isNodeInSceneGraph(root, node) {
    let current = node;
    while (current) {
      if (current === root) return true;
      current = current.parent;
    }
    return false;
  }

  _collectImportedCameras(gltf) {
    const cameras = [];
    const seen = new Set();
    const root = gltf.scene;

    const addCamera = (node, meta = {}) => {
      if (!node?.isCamera || seen.has(node.uuid)) return;
      seen.add(node.uuid);
      const name = String(node.name || node.userData?.name || "").trim() || `Camera ${cameras.length + 1}`;
      cameras.push({
        id: node.uuid,
        name,
        object3d: node,
        ...meta,
      });
    };

    const sceneRoots = gltf.scenes?.length ? gltf.scenes : [root];
    for (const sceneRoot of sceneRoots) {
      sceneRoot?.traverse((node) => addCamera(node, { source: "scene" }));
    }

    if (gltf.parser?.associations) {
      for (const [object3d] of gltf.parser.associations.entries()) {
        addCamera(object3d, { source: "parser" });
      }
    }

    for (const cam of gltf.cameras || []) {
      addCamera(cam, { source: "gltf.cameras" });
    }

    for (const item of cameras) {
      if (!this._isNodeInSceneGraph(root, item.object3d)) {
        root.add(item.object3d);
        item.orphan = true;
      }
    }

    return cameras.sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true }));
  }

  _diagnoseMissingCameras(gltf) {
    const json = gltf.parser?.json || {};
    const nodeCameraCount = (json.nodes || []).filter((node) => node.camera !== undefined).length;
    const gltfCameraCount = gltf.cameras?.length || 0;
    if (gltfCameraCount > 0 || nodeCameraCount > 0) {
      return (
        `GLB 元数据含 ${Math.max(gltfCameraCount, nodeCameraCount)} 个相机，但未能正确挂到场景。` +
        " 请检查 Blender：相机不要隐藏（眼睛图标），Limit to 不要勾选 Visible/Active Collection，或把相机放进导出集合。"
      );
    }
    return (
      "GLB 内完全没有相机数据（不是勾选 Cameras 就行）。" +
      " 请确认场景里有 Camera 对象、导出时 Limit to 留空、相机可见，并重新导出。"
    );
  }

  _scoreCameraForAnimation(item) {
    let score = 0;
    let node = item.object3d;
    while (node) {
      if (node.name && this.animatedNodeNames.has(node.name)) score += 10;
      node = node.parent;
    }
    return score;
  }

  _pickBestCameraId(preferredName) {
    if (!this.importedCameras.length) return "";
    if (preferredName) {
      const match = this.importedCameras.find((item) => item.name === preferredName);
      if (match) return match.id;
    }
    let best = this.importedCameras[0];
    let bestScore = this._scoreCameraForAnimation(best);
    for (const item of this.importedCameras.slice(1)) {
      const score = this._scoreCameraForAnimation(item);
      if (score > bestScore) {
        best = item;
        bestScore = score;
      }
    }
    return best.id;
  }

  _computeClipDuration(clips) {
    let duration = 0;
    for (const clip of clips || []) {
      duration = Math.max(duration, Number(clip.duration) || 0);
      for (const track of clip.tracks || []) {
        const times = track.times;
        if (times?.length) duration = Math.max(duration, times[times.length - 1]);
      }
    }
    return duration;
  }

  _selectAnimationClips(animations) {
    return animations || [];
  }

  _cameraMovesOverTime(object3d) {
    if (!this.mixer || !object3d || this.animationDuration <= 0) return false;
    const saved = this.animationTime;
    this._syncMixerTime(0);
    object3d.getWorldPosition(this._probePosA);
    const probeTime = Math.min(Math.max(this.animationDuration * 0.25, 0.1), this.animationDuration);
    this._syncMixerTime(probeTime);
    object3d.getWorldPosition(this._probePosB);
    this._syncMixerTime(saved);
    return this._probePosA.distanceToSquared(this._probePosB) > 1e-10;
  }

  _resolveViewNode(item) {
    if (this._cameraMovesOverTime(item.object3d)) return item.object3d;
    let node = item.object3d.parent;
    while (node && node !== this.blenderRoot) {
      if (node.name && this.animatedNodeNames.has(node.name) && this._cameraMovesOverTime(node)) {
        return item.object3d;
      }
      node = node.parent;
    }
    return item.object3d;
  }

  _updateAnimationHint() {
    if (!this.hintEl) return;
    const duration = this.animationDuration || 0;
    const active = this.importedCameras.find((item) => item.id === this.activeCameraId);
    const moves = active?.object3d ? this._cameraMovesOverTime(active.object3d) : false;
    if (!duration) {
      this.hintEl.textContent =
        "未检测到 GLB 动画。Blender 导出请勾选 Animation，Animation mode 建议选 Scene，并勾选 Bake All Objects Animations。";
      return;
    }
    if (!active) {
      this.hintEl.textContent = `动画 ${formatTime(duration)} · 请在左侧选择相机`;
      return;
    }
    if (!moves) {
      this.hintEl.textContent =
        `动画 ${formatTime(duration)} · 当前相机「${active.name}」未随时间变化。请换其他相机，或在 Blender 给该相机（或其父级）打关键帧后重新导出。`;
      return;
    }
    this.hintEl.textContent =
      "拖动时间条或点 ▶ 播放 · 跟随相机视角 · 「印到当前分镜」保存当前画面";
  }

  _countImportedLights(root) {
    let count = 0;
    root?.traverse((node) => {
      if (node.isLight) count += 1;
    });
    return count;
  }

  _shouldUseProgramIbl() {
    if (this.mode !== "blender") return false;
    if (this.programLightingMode === "off") return false;
    return true;
  }

  _shouldUseProgramFill() {
    if (this.mode !== "blender") return false;
    if (this.programLightingMode === "off") return false;
    if (this.programLightingMode === "on") return this.importedLightCount === 0;
    return this.importedLightCount === 0;
  }

  _shouldUseProgramWeakFill() {
    if (this.mode !== "blender") return false;
    if (this.programLightingMode === "off") return false;
    if (this.objectColorPreview) return false;
    if (this.programLightingMode === "on") return this.importedLightCount > 0;
    return this.importedLightCount > 0;
  }

  _getEnvMapIntensity() {
    if (!this._shouldUseProgramIbl()) return 0;
    if (this.importedLightCount > 0) return 0.35;
    return 1.0;
  }

  _calibrateImportedLights(root) {
    root?.traverse((node) => {
      if (!node.isLight || typeof node.intensity !== "number") return;
      if (node.isDirectionalLight) {
        node.intensity = Math.min(node.intensity * Math.PI * 0.35, 4);
      } else if (node.isPointLight || node.isSpotLight) {
        if (node.intensity > 0 && node.intensity < 800) {
          node.intensity = Math.min(node.intensity * 1.5, 600);
        }
      }
    });
  }

  _setImportedLightsVisible(visible) {
    this.blenderRoot?.traverse((node) => {
      if (node.isLight) node.visible = visible;
    });
  }

  _programLightingReason() {
    if (this.programLightingMode === "on") return "手动：环境 + 柔光";
    if (this.programLightingMode === "off") return "手动：仅 GLB 灯光";
    if (this.importedLightCount > 0) return `自动：GLB ${this.importedLightCount} 盏灯 + 弱环境反射`;
    return "自动：GLB 无灯，全程序补光";
  }

  setProgramLightingMode(mode, { persist = true, notify = true } = {}) {
    const next = mode === "on" || mode === "off" ? mode : "auto";
    this.programLightingMode = next;
    if (this.programLightingEl) this.programLightingEl.value = next;
    if (persist) {
      this.sceneMeta = { ...(this.sceneMeta || {}), program_lighting: next };
    }
    this._applyProgramLighting();
    if (this.blenderRoot) this._prepareImportedMaterials(this.blenderRoot);
    if (this.objectColorPreview) this._applyObjectColorPreview(true);
    if (persist) this._scheduleSceneSettingsSave();
    if (notify) {
      this.callbacks.onMessage?.(`灯光设置：${this._programLightingReason()}`);
    }
  }

  _updateLightStatusUi() {
    if (!this.lightStatusEl) return;
    if (this.mode !== "blender") {
      this.lightStatusEl.textContent = "—";
      return;
    }
    const exported =
      this.importedLightCount > 0
        ? `GLB 已导出 ${this.importedLightCount} 盏灯`
        : "GLB 未导出灯光（导出时请勾选 Punctual Lights）";
    const ibl = this._shouldUseProgramIbl() && !this.objectColorPreview ? "环境反射：开" : "环境反射：关";
    const fill = this._shouldUseProgramFill()
      ? "柔光补光：开"
      : this._shouldUseProgramWeakFill()
        ? "柔光补光：弱"
        : "柔光补光：关";
    const colors = this.objectColorPreview ? "对象色：开（不受灯光影响）" : "对象色：关";
    this.lightStatusEl.textContent = `${exported} · ${this._programLightingModeLabel()} · ${ibl} · ${fill} · ${colors}`;
  }

  _ensureBlenderEnvMap() {
    if (this.blenderEnvMap) return this.blenderEnvMap;
    const room = new RoomEnvironment();
    this.blenderEnvMap = this.pmremGenerator.fromScene(room, 0.04).texture;
    room.dispose();
    return this.blenderEnvMap;
  }

  _applyProgramLighting() {
    if (this.mode !== "blender") return;
    const useIbl = this._shouldUseProgramIbl() && !this.objectColorPreview;
    const useFill = this._shouldUseProgramFill();
    const useWeakFill = this._shouldUseProgramWeakFill();
    if (useIbl) {
      this.scene.environment = this._ensureBlenderEnvMap();
      this.scene.background = new THREE.Color(0x303030);
    } else if (this.objectColorPreview) {
      this.scene.environment = null;
      this.scene.background = new THREE.Color(0x3a3a3a);
    } else {
      this.scene.environment = null;
      this.scene.background = this.builtinBackground.clone();
    }
    this.programAmbient.intensity = useFill ? 0.1 : 0.22;
    this.programAmbient.visible = useFill || useWeakFill;
    this.programHemisphere.visible = useFill;
    this._setImportedLightsVisible(!this.objectColorPreview);
    this._updateLightStatusUi();
  }

  _generateBlenderObjectColor(seed) {
    return generateObjectColor(THREE, seed);
  }

  _collectObjectColorKeys(root) {
    const keys = new Set();
    root?.traverse((node) => {
      if (node.isMesh) keys.add(this._objectColorKey(node));
    });
    return [...keys].sort();
  }

  _objectColorKey(mesh) {
    return objectColorKey(mesh, this.blenderRoot);
  }

  _cacheImportedMaterials(root) {
    root?.traverse((node) => {
      if (!node.isMesh || node.userData.scene3dOriginalMaterial !== undefined) return;
      node.userData.scene3dOriginalMaterial = node.material;
    });
  }

  _restoreImportedMaterials(root) {
    root?.traverse((node) => {
      if (!node.isMesh || node.userData.scene3dOriginalMaterial === undefined) return;
      node.material = node.userData.scene3dOriginalMaterial;
    });
  }

  _disposePreviewMaterials() {
    for (const material of this.previewMaterials) {
      material.dispose();
    }
    this.previewMaterials.clear();
  }

  setObjectColorPreview(enabled, { persist = true, notify = false } = {}) {
    this.objectColorPreview = Boolean(enabled);
    if (this.objectColorsEl) this.objectColorsEl.checked = this.objectColorPreview;
    if (persist) {
      this.sceneMeta = { ...(this.sceneMeta || {}), object_color_preview: this.objectColorPreview };
    }
    this._applyProgramLighting();
    this._applyObjectColorPreview(this.objectColorPreview);
    if (!this.objectColorPreview && this.blenderRoot) {
      this._prepareImportedMaterials(this.blenderRoot);
    }
    this._applyWireframeMode();
    if (persist) this._scheduleSceneSettingsSave();
    if (notify) {
      this.callbacks.onMessage?.(
        this.objectColorPreview
          ? "已启用对象随机色（不受灯光影响，便于区分）"
          : "已恢复 GLB 原始材质",
      );
    }
  }

  _applyObjectColorPreview(enabled) {
    if (!this.blenderRoot) return;
    applySharedObjectColorPreview(THREE, this.blenderRoot, this.blenderRoot, this.previewMaterials, enabled);
    if (!enabled && this.blenderRoot) {
      this._prepareImportedMaterials(this.blenderRoot);
    }
  }

  _prepareImportedMaterials(root) {
    if (this.objectColorPreview) return;
    const envIntensity = this._getEnvMapIntensity();
    root?.traverse((node) => {
      if (!node.isMesh) return;
      const materials = Array.isArray(node.material) ? node.material : [node.material];
      for (const mat of materials) {
        if (!mat?.isMeshStandardMaterial) continue;
        mat.envMapIntensity = envIntensity;
        mat.needsUpdate = true;
      }
    });
  }

  async _loadBlenderUrl(url, label) {
    this.clearBlenderScene();
    this.clearObjects();
    const loader = new GLTFLoader();
    const gltf = await loader.loadAsync(url);
    this.blenderRoot = gltf.scene;
    this.scene.add(this.blenderRoot);
    this.importedLightCount = this._countImportedLights(gltf.scene);
    this._calibrateImportedLights(this.blenderRoot);
    this._applyProgramLighting();
    this._prepareImportedMaterials(this.blenderRoot);
    this._cacheImportedMaterials(this.blenderRoot);
    this._applyObjectColorPreview(this.objectColorPreview);
    if (this.objectColorPreview) {
      this._applyProgramLighting();
    }
    this._applyWireframeMode();

    this.importedCameras = this._collectImportedCameras(gltf);
    this.animatedNodeNames = this._collectAnimatedNodeNames(gltf.animations);

    const clipsToPlay = this._selectAnimationClips(gltf.animations || []);
    this.mixer = new THREE.AnimationMixer(gltf.scene);
    this.mixerActions = [];
    for (const clip of clipsToPlay) {
      const action = this.mixer.clipAction(clip);
      action.setLoop(THREE.LoopOnce, 1);
      action.play();
      this.mixerActions.push(action);
    }
    this.animationDuration = this._computeClipDuration(clipsToPlay.length ? clipsToPlay : gltf.animations);
    this.animationTime = 0;
    this.isPlaying = false;
    this._syncMixerTime(0);
    this._populateCameraSelect();
    this._renderOutliner();
    this._updateTimelineUi();
    if (!this.followCamera || !this.importedCameras.length) {
      this._frameImportedScene();
    }
    this.sceneMeta.file_name = label || this.sceneMeta.file_name;
    if (this.importedCameras.length) {
      const bestId = this._pickBestCameraId("");
      const best = this.importedCameras.find((item) => item.id === bestId);
      if (best) best.viewNode = this._resolveViewNode(best);
      this.setActiveCamera(bestId, false);
    }
    this.setFollowCamera(this.followCamera);
    this._updateAnimationHint();
    if (this.importedCameras.length === 0) {
      this.callbacks.onMessage?.(this._diagnoseMissingCameras(gltf));
    } else if (this.importedCameras.some((item) => item.orphan)) {
      this.callbacks.onMessage?.(
        `已找到 ${this.importedCameras.length} 个相机（部分未挂到场景树，已自动修复）。`,
      );
    } else if (!(gltf.animations || []).length) {
      this.callbacks.onMessage?.("场景已加载，但未找到动画。请在 Blender 导出时勾选 Animation。");
    } else if (this.animationDuration <= 0) {
      this.callbacks.onMessage?.("已找到动画轨道，但时长为 0。请检查 Blender 时间轴范围与关键帧。");
    } else if (this.programLightingMode === "auto") {
      if (this.importedLightCount > 0) {
        this.callbacks.onMessage?.(
          `检测到 GLB 含 ${this.importedLightCount} 盏灯，已校准强度并启用弱环境反射（模拟 Blender World）。`,
        );
      } else {
        this.callbacks.onMessage?.("GLB 无导出灯光，已自动开启全程序补光。");
      }
    }
  }

  _programLightingModeLabel() {
    switch (this.programLightingMode) {
      case "on":
        return "始终开启";
      case "off":
        return "关闭";
      default:
        return "自动";
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
    match.viewNode = this._resolveViewNode(match);
    this._renderOutliner();
    if (showMessage) {
      this.callbacks.onMessage?.(`已切换相机：${match.name}`);
    }
    if (this.followCamera) {
      this._applyFollowCamera();
    }
    this._updateAnimationHint();
    // Notify after _applyFollowCamera so getViewState() reads the new camera transform.
    // showMessage is false for programmatic load restores, true for user camera switches.
    if (showMessage) this._notifyViewChange();
  }

  setFollowCamera(enabled, { persist = true } = {}) {
    this.followCamera = Boolean(enabled);
    this.followCameraEl.checked = this.followCamera;
    this.orbit.enabled = !this.followCamera;
    if (this.followCamera) {
      this._applyFollowCamera();
    }
    if (persist) {
      this.sceneMeta = { ...(this.sceneMeta || {}), follow_camera: this.followCamera };
      this._scheduleSceneSettingsSave();
      // User toggled follow/free view — let React persist it as the reference view.
      this._notifyViewChange();
    }
  }

  // Tell React the workspace view changed so it can persist settings.scene3d.reference_view.
  // Event-driven only (never per animation frame); suppressed while a scene is loading so the
  // restored camera/time don't clobber a saved reference view.
  _notifyViewChange() {
    if (this._suppressViewChange) return;
    this.callbacks.onViewChange?.();
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
      this._applyProgramLighting();
      this.transform.detach();
      this.selectObject(null);
    } else {
      this.scene.environment = null;
      this.scene.background = this.builtinBackground.clone();
      this.programAmbient.visible = false;
      this.programHemisphere.visible = false;
      this._updateLightStatusUi();
    }
  }

  exportSceneData() {
    if (this.mode === "blender") {
      const active = this.importedCameras.find((item) => item.id === this.activeCameraId);
      return exportBlenderSceneData({
        sceneMeta: this.sceneMeta,
        activeCameraName: active?.name || this.sceneMeta.camera_name || "",
        followCamera: this.followCamera,
        animationTime: this.animationTime,
        programLightingMode: this.programLightingMode,
        importedLightCount: this.importedLightCount,
        objectColorPreview: this.objectColorPreview,
        wireframeMode: this.wireframeMode,
      });
    }
    return exportBuiltinSceneData(this.objects.entries(), this.wireframeMode, this.objectColorPreview);
  }

  clearBlenderScene() {
    if (this.mixer) {
      this.mixer.stopAllAction();
      this.mixer = null;
    }
    this.mixerActions = [];
    this.importedCameras = [];
    this.activeCameraId = "";
    this.importedLightCount = 0;
    this.animationDuration = 0;
    this.animationTime = 0;
    this.isPlaying = false;
    this._clearWireframeOverlays();
    if (this.blenderRoot) {
      this._restoreImportedMaterials(this.blenderRoot);
      this._disposePreviewMaterials();
      this.scene.remove(this.blenderRoot);
      disposeObject3DRoot(this.blenderRoot);
      this.blenderRoot = null;
    }
    this._populateCameraSelect();
    this._updateTimelineUi();
  }

  clearObjects() {
    for (const mesh of this.objects.values()) {
      this.scene.remove(mesh);
      disposePrimitiveMesh(mesh);
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
    const name = `${labels[type] || "Object"} ${this.objects.size + 1}`;
    const spec = {
      id,
      name,
      type,
      position: [0, type === "plane" ? 0 : 0.5, 0],
      rotation: type === "plane" ? [-Math.PI / 2, 0, 0] : [0, 0, 0],
      scale: type === "plane" ? [4, 4, 1] : [1, 1, 1],
      color: `#${this._generateBlenderObjectColor(name).getHexString()}`,
    };
    this._addMeshFromSpec(spec);
    this.selectObject(id);
    this._renderOutliner();
    this._applyWireframeMode();
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
    disposePrimitiveMesh(mesh);
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
    return getCameraStateFromEditor(this.camera, this.orbit);
  }

  // A reproducible snapshot of the current viewport for the GLB reference preview / apply.
  getViewState() {
    const active = this.importedCameras.find((item) => item.id === this.activeCameraId) || null;
    return exportViewState(THREE, {
      camera: this.camera,
      orbit: this.orbit,
      followCamera: this.followCamera,
      activeCamera: active ? { id: active.id, name: active.name } : null,
      animationTime: this.animationTime,
    });
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
    return fovToFocalLength(fov);
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

  refreshBoardPreview() {
    const url = this.callbacks.getBoardPreviewUrl?.() || "";
    const label = this.callbacks.getBoardLabel?.() || "—";
    if (this.boardLabelEl) this.boardLabelEl.textContent = label;
    if (!this.boardPreviewImg || !this.boardPreviewEmpty) return;
    if (url) {
      this.boardPreviewImg.src = url;
      this.boardPreviewImg.hidden = false;
      this.boardPreviewEmpty.hidden = true;
    } else {
      this.boardPreviewImg.hidden = true;
      this.boardPreviewEmpty.hidden = false;
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

  _syncMixerTime(seconds) {
    if (!this.mixer || !this.mixerActions.length) return;
    const time = Math.max(0, Number(seconds) || 0);
    for (const action of this.mixerActions) {
      action.enabled = true;
      action.paused = false;
      action.time = time;
    }
    this.mixer.update(0);
    this.animationTime = time;
    this.blenderRoot?.updateMatrixWorld(true);
  }

  setAnimationTime(seconds) {
    const duration = this.animationDuration || 0;
    const clamped = duration > 0 ? Math.min(Math.max(0, seconds), duration) : Math.max(0, seconds);
    this._syncMixerTime(clamped);
    this._updateTimelineUi();
    if (this.followCamera) {
      this._applyFollowCamera();
    }
    // Persist the new time as part of the reference view (suppressed during scene load; playback
    // advances time via _syncMixerTime, not this method, so this is not per-frame).
    this._notifyViewChange();
  }

  toggleAnimationPlayback() {
    if (this.mode !== "blender" || !this.mixer) {
      this.callbacks.onMessage?.("请先导入带相机动画的 GLB");
      return;
    }
    if (
      !this.isPlaying &&
      this.animationDuration > 0 &&
      this.animationTime >= this.animationDuration - 0.001
    ) {
      this.setAnimationTime(0);
    }
    this.isPlaying = !this.isPlaying;
    this._updatePlayButton();
  }

  pauseAnimation() {
    this.isPlaying = false;
    this._updatePlayButton();
  }

  goToAnimationStart() {
    this.isPlaying = false;
    this.setAnimationTime(0);
    this._updatePlayButton();
  }

  stepAnimation(deltaSeconds) {
    if (this.mode !== "blender" || !this.mixer) return;
    if (this.isPlaying) {
      this.isPlaying = false;
      this._updatePlayButton();
    }
    this.setAnimationTime(this.animationTime + Number(deltaSeconds || 0));
  }

  captureFrameDataUrl() {
    const followPrep = () => {
      if (this.followCamera && this.mode === "blender") this._applyFollowCamera();
    };
    return captureRendererPng(THREE, this.renderer, this.camera, this.scene, {
      getProjectCanvasSize,
      prepareExport: followPrep,
      finishDisplay: () => {
        followPrep();
        this.renderer.render(this.scene, this.camera);
      },
    });
  }

  getAnimationState() {
    return {
      time: this.animationTime,
      duration: this.animationDuration,
      camera_name: this.importedCameras.find((item) => item.id === this.activeCameraId)?.name || "",
    };
  }

  _updatePlayButton() {
    if (!this.playPauseBtn) return;
    this.playPauseBtn.textContent = this.isPlaying ? "⏸ 暂停" : "▶ 播放";
  }

  _updateTimelineUi() {
    const duration = this.animationDuration || 0;
    this.timeSliderEl.max = duration.toFixed(2);
    this.timeSliderEl.value = this.animationTime.toFixed(2);
    this.timeSliderEl.disabled = duration <= 0;
    this.timeDisplayEl.textContent = `${formatTime(this.animationTime)} / ${formatTime(duration)}`;
  }

  _applyFollowCamera() {
    const active = this.importedCameras.find((item) => item.id === this.activeCameraId);
    if (!active?.object3d) return;
    const source = active.viewNode || active.object3d;
    source.updateWorldMatrix(true, false);
    source.matrixWorld.decompose(this._followPos, this._followQuat, this._followScale);
    this.camera.position.copy(this._followPos);
    this.camera.quaternion.copy(this._followQuat);
    const proj = active.object3d.isCamera ? active.object3d : null;
    if (proj?.isPerspectiveCamera) {
      this.camera.fov = proj.fov;
      this.camera.near = Math.max(0.001, proj.near);
      this.camera.far = Math.max(this.camera.near + 1, proj.far);
      this.camera.updateProjectionMatrix();
    }
    this.orbit.enabled = false;
  }

  _projectAspect() {
    return getProjectCanvasAspect();
  }

  _resize() {
    const frame = this.formatFrameEl || this.viewportEl;
    const width = Math.max(1, Math.floor(frame.clientWidth));
    const height = Math.max(1, Math.floor(frame.clientHeight));
    if (!width || !height) return;
    this.camera.aspect = this._projectAspect();
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(width, height, false);
  }

  _animate() {
    this.animationId = requestAnimationFrame(() => this._animate());
    const delta = this.clock.getDelta();
    if (this.mode === "blender" && this.mixer && this.isPlaying) {
      const duration = this.animationDuration || 0;
      let nextTime = this.animationTime + delta;
      if (duration > 0 && nextTime >= duration) {
        nextTime = duration;
        this.isPlaying = false;
        this._updatePlayButton();
      }
      this._syncMixerTime(nextTime);
      this.blenderRoot?.updateMatrixWorld(true);
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
    this.blenderEnvMap?.dispose();
    this.blenderEnvMap = null;
    this.pmremGenerator?.dispose();
    this.pmremGenerator = null;
    this._clearWireframeOverlays();
    this.renderer.dispose();
    if (this.renderer.domElement.parentNode) {
      this.renderer.domElement.parentNode.removeChild(this.renderer.domElement);
    }
  }
}
