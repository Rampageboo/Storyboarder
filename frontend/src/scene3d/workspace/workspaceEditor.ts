/**
 * Scene3DEditor — TypeScript migration of scene3d.js.
 * Vendor Three.js imports are externalized by vite.workspace.config.ts.
 */

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type ThreeObject = any

// Vendor runtime imports — externalized by rollup, not bundled
// eslint-disable-next-line @typescript-eslint/ban-ts-comment
// @ts-ignore
import * as THREE from '/static/vendor/three/three.module.js'
// eslint-disable-next-line @typescript-eslint/ban-ts-comment
// @ts-ignore
import { OrbitControls } from '/static/vendor/three/OrbitControls.js'
// eslint-disable-next-line @typescript-eslint/ban-ts-comment
// @ts-ignore
import { TransformControls } from '/static/vendor/three/TransformControls.js'
// eslint-disable-next-line @typescript-eslint/ban-ts-comment
// @ts-ignore
import { GLTFLoader } from '/static/vendor/three/GLTFLoader.js'
// eslint-disable-next-line @typescript-eslint/ban-ts-comment
// @ts-ignore
import { RoomEnvironment } from '/static/vendor/three/RoomEnvironment.js'

// Preview style helpers — externalized runtime module
// eslint-disable-next-line @typescript-eslint/ban-ts-comment
// @ts-ignore
import {
  generateObjectColor,
  normalizeWireframeMode,
  objectColorKey,
  applyObjectColorPreview as applySharedObjectColorPreview,
  applyWireframeModeToRoots,
  clearWireframeOverlays,
  createWireframeResources,
  disposePreviewMaterials,
// eslint-disable-next-line @typescript-eslint/ban-ts-comment
// @ts-ignore
} from '/static/runtime/scene3d_preview_style.js'

// TS workspace helpers (bundled)
import {
  makeWorkspaceObjectId,
  vec3From,
  defaultBuiltinSceneData,
  defaultAddObjectSpec,
  createPrimitiveMesh,
  WORKSPACE_PRIMITIVE_TYPE_SET,
} from './workspacePrimitives'
import type { WorkspacePrimitiveType, WorkspaceTransformMode } from './workspaceTypes'
import type { Scene3dWireframeMode } from '../previewStyleBridge'
import { captureRendererPng } from './workspaceCapture'
import {
  exportViewState,
  getCameraStateFromEditor,
  fovToFocalLength,
  getProjectCanvasSize,
  getProjectCanvasAspect,
  loadShotCameraIntoEditor,
  applyFollowCameraToEditor,
} from './workspaceCamera'
import { initWorkspaceEditorThree } from './workspaceBridge'
import { exportBuiltinSceneData, exportBlenderSceneData, formatWorkspaceTime } from './workspaceState'
import { disposeObject3DRoot, disposePrimitiveMesh } from './workspaceDispose'
import {
  countImportedLights,
  calibrateImportedLights,
  isNodeInSceneGraph,
  collectImportedCameras,
  diagnoseMissingCameras,
  scoreCameraForAnimation,
  pickBestCameraId,
  frameImportedScene,
  cameraMovesOverTime,
  resolveViewNode,
  setImportedLightsVisible,
  prepareImportedMaterials,
} from './workspaceGlb'
import {
  normalizeProgramLightingMode,
  shouldUseProgramIbl,
  shouldUseProgramFill,
  shouldUseProgramWeakFill,
  getEnvMapIntensity,
  programLightingReason,
  programLightingModeLabel,
  buildLightStatusText,
  applyWorkspaceProgramLighting,
  createBlenderEnvMap,
  type ProgramLightingMode,
  type ProgramLightingContext,
} from './workspaceLighting'
import {
  trackNodeName,
  collectAnimatedNodeNames,
  computeClipDuration,
  selectAnimationClips,
  clampAnimationTime,
  syncMixerActionsTime,
  buildTimelineUiState,
  buildAnimationHint,
  advancePlaybackTime,
} from './workspaceAnimation'
import {
  cacheImportedMaterialsOnRoot,
  restoreImportedMaterialsOnRoot,
  collectMeshObjectColorKeys,
} from './workspaceMaterials'
import {
  createWorkspaceAnimationMixer,
  buildGlbLoadNotifications,
  resolveInitialAnimationTime,
  resolveReloadAnimationTime,
  formatWorkspaceFileName,
  getWireframeRoots,
  filterBuiltinObjectSpecs,
} from './workspaceGlbLoad'
import { applyTransformFromInputs, syncTransformInputsFromMesh, WIREFRAME_MODE_LABELS } from './workspaceTransform'
import {
  buildOutlinerEntries,
  renderOutlinerDom,
  buildCameraSelectOptions,
  populateCameraSelectDom,
} from './workspaceOutliner'
import { applyWorkspaceModeUi, applyWorkspaceSceneModeFlags, shouldUseOrbitControls } from './workspaceMode'
import {
  canDeleteWorkspaceObject,
  shouldAttachTransformToSelection,
  getWorkspaceFocusTarget,
  resetBuiltinCameraView,
} from './workspaceSelection'
import {
  shouldIgnoreWorkspaceKeyboard,
  resolveBlenderKeyboardAction,
  resolveBuiltinKeyboardAction,
  applyWorkspaceKeyboardAction,
} from './workspaceInput'
import { createEmptyBlenderPlaybackState, stopWorkspaceMixer } from './workspaceClear'

export type Scene3DEditorCallbacks = {
  getShotCamera?: () => Record<string, unknown> | null
  getShotScene3dTime?: () => number | null
  getBoardPreviewUrl?: () => string
  getBoardLabel?: () => string
  onApplyShotCamera?: (cameraState: unknown) => void
  onImportBlender?: () => void
  onOpenBlender?: () => void
  onCaptureToBoard?: () => void
  onMessage?: (message: string) => void
  onSceneSettingsChange?: (nextScene: Record<string, unknown>) => void
  onViewChange?: () => void
}

export class Scene3DEditor {
  rootEl: HTMLElement
  callbacks: Scene3DEditorCallbacks
  sceneData: ThreeObject
  sceneMeta: Record<string, unknown>
  mode: 'builtin' | 'blender'
  objects: Map<string, ThreeObject>
  selectedId: string | null
  transformMode: WorkspaceTransformMode
  shotCameraHelper: ThreeObject
  animationId: number | null
  clock: ThreeObject
  blenderRoot: ThreeObject
  mixer: ThreeObject
  mixerActions: ThreeObject[]
  importedCameras: ThreeObject[]
  activeCameraId: string
  followCamera: boolean
  isPlaying: boolean
  programLightingMode: ProgramLightingMode
  importedLightCount: number
  objectColorPreview: boolean
  previewMaterials: Set<unknown>
  wireframeMode: Scene3dWireframeMode
  wireframeResources: ThreeObject
  animationTime: number
  animationDuration: number
  animatedNodeNames: Set<string>
  _followPos: ThreeObject
  _followQuat: ThreeObject
  _followScale: ThreeObject
  _probePosA: ThreeObject
  _probePosB: ThreeObject
  _sceneSettingsSaveTimer: number | null
  _suppressViewChange: boolean
  _disposed: boolean
  renderer: ThreeObject
  scene: ThreeObject
  camera: ThreeObject
  defaultAmbient: ThreeObject
  defaultSun: ThreeObject
  programAmbient: ThreeObject
  programHemisphere: ThreeObject
  grid: ThreeObject
  axes: ThreeObject
  builtinBackground: ThreeObject
  pmremGenerator: ThreeObject
  blenderEnvMap: ThreeObject
  orbit: ThreeObject
  transform: ThreeObject
  raycaster: ThreeObject
  pointer: ThreeObject
  outlinerEl!: HTMLElement
  viewportEl!: HTMLElement
  formatFrameEl!: HTMLElement
  fileNameEl!: HTMLElement
  cameraSelectEl!: HTMLSelectElement
  followCameraEl!: HTMLInputElement
  objectColorsEl!: HTMLInputElement | null
  wireframeModeEl!: HTMLSelectElement | null
  programLightingEl!: HTMLSelectElement | null
  lightStatusEl!: HTMLElement | null
  timeSliderEl!: HTMLInputElement
  timeDisplayEl!: HTMLElement
  boardPreviewImg!: HTMLImageElement | null
  boardPreviewEmpty!: HTMLElement | null
  boardLabelEl!: HTMLElement | null
  playPauseBtn!: HTMLElement | null
  hintEl!: HTMLElement | null
  transformInputs: Record<string, HTMLInputElement>
  _resizeObserver!: ResizeObserver
  _keydownHandler!: (event: KeyboardEvent) => void
  _pointerdownHandler!: (event: PointerEvent) => void

  constructor(rootEl: HTMLElement, callbacks: Scene3DEditorCallbacks = {}) {
    this.rootEl = rootEl
    this.callbacks = callbacks
    this.sceneData = defaultBuiltinSceneData()
    this.sceneMeta = {}
    this.mode = 'builtin' as const
    this.objects = new Map()
    this.selectedId = null
    this.transformMode = 'translate' as WorkspaceTransformMode
    this.shotCameraHelper = null
    this.animationId = null
    this.clock = new THREE.Clock()

    this.blenderRoot = null
    this.mixer = null
    this.mixerActions = []
    this.importedCameras = []
    this.activeCameraId = ''
    this.followCamera = true
    this.isPlaying = false
    this.programLightingMode = 'auto'
    this.importedLightCount = 0
    this.objectColorPreview = true
    this.previewMaterials = new Set()
    this.wireframeMode = 'off' as Scene3dWireframeMode
    this.wireframeResources = createWireframeResources()
    this.animationTime = 0
    this.animationDuration = 0
    this.animatedNodeNames = new Set()
    this._followPos = new THREE.Vector3()
    this._followQuat = new THREE.Quaternion()
    this._followScale = new THREE.Vector3()
    this._probePosA = new THREE.Vector3()
    this._probePosB = new THREE.Vector3()
    this._sceneSettingsSaveTimer = null
    this._suppressViewChange = false
    this._disposed = false

    // Initialized via _buildDom / _initThree
    this.renderer = null
    this.scene = null
    this.camera = null
    this.defaultAmbient = null
    this.defaultSun = null
    this.programAmbient = null
    this.programHemisphere = null
    this.grid = null
    this.axes = null
    this.builtinBackground = null
    this.pmremGenerator = null
    this.blenderEnvMap = null
    this.orbit = null
    this.transform = null
    this.raycaster = null
    this.pointer = null
    this.transformInputs = {}

    this._buildDom()
    this._initThree()
    this._bindUi()
  }

  _buildDom(): void {
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
    `
    this.outlinerEl = this.rootEl.querySelector('[data-outliner]') as HTMLElement
    this.viewportEl = this.rootEl.querySelector('[data-viewport]') as HTMLElement
    this.formatFrameEl = this.rootEl.querySelector('[data-format-frame]') as HTMLElement
    this.fileNameEl = this.rootEl.querySelector('[data-blend-name]') as HTMLElement
    this.cameraSelectEl = this.rootEl.querySelector('[data-camera-select]') as HTMLSelectElement
    this.followCameraEl = this.rootEl.querySelector('[data-follow-camera]') as HTMLInputElement
    this.objectColorsEl = this.rootEl.querySelector('[data-object-colors]')
    this.wireframeModeEl = this.rootEl.querySelector('[data-wireframe-mode]')
    this.programLightingEl = this.rootEl.querySelector('[data-program-lighting]')
    this.lightStatusEl = this.rootEl.querySelector('[data-light-status]')
    this.timeSliderEl = this.rootEl.querySelector('[data-time-slider]') as HTMLInputElement
    this.timeDisplayEl = this.rootEl.querySelector('[data-time-display]') as HTMLElement
    this.boardPreviewImg = this.rootEl.querySelector('[data-board-preview-img]')
    this.boardPreviewEmpty = this.rootEl.querySelector('[data-board-preview-empty]')
    this.boardLabelEl = this.rootEl.querySelector('[data-board-label]')
    this.playPauseBtn = this.rootEl.querySelector("[data-action='play-pause']")
    this.hintEl = this.rootEl.querySelector('[data-hint]')
    this.transformInputs = {}
    this.rootEl.querySelectorAll('[data-tf]').forEach((input) => {
      const el = input as HTMLInputElement
      this.transformInputs[el.dataset.tf!] = el
    })
  }

  _initThree(): void {
    const boot = initWorkspaceEditorThree(THREE, OrbitControls, TransformControls, {
      mountEl: this.formatFrameEl,
      transformMode: this.transformMode as 'translate' | 'rotate' | 'scale',
      onOrbitChange: () => {
        if (this.mode === 'blender' && !this.followCamera) this._notifyViewChange()
      },
      onTransformDraggingChanged: (dragging: boolean) => {
        this.orbit.enabled = !dragging && !this.followCamera
      },
      onTransformObjectChange: () => {
        this._syncSelectedFromMesh()
        this._renderOutliner()
      },
    })
    this.renderer = boot.renderer
    this.scene = boot.scene
    this.camera = boot.camera
    this.defaultAmbient = boot.defaultAmbient
    this.defaultSun = boot.defaultSun
    this.programAmbient = boot.programAmbient
    this.programHemisphere = boot.programHemisphere
    this.grid = boot.grid
    this.axes = boot.axes
    this.builtinBackground = boot.builtinBackground
    this.pmremGenerator = boot.pmremGenerator
    this.blenderEnvMap = null
    this.orbit = boot.orbit
    this.transform = boot.transform

    this.raycaster = new THREE.Raycaster()
    this.pointer = new THREE.Vector2()

    this._pointerdownHandler = (event: PointerEvent) => this._onPointerDown(event)
    this.renderer.domElement.addEventListener('pointerdown', this._pointerdownHandler)

    this._keydownHandler = (event: KeyboardEvent) => this._onKeyDown(event)
    window.addEventListener('keydown', this._keydownHandler)

    this._resizeObserver = new ResizeObserver(() => this._resize())
    this._resizeObserver.observe(this.viewportEl)
    this._resize()
    this._animate()
  }

  _bindUi(): void {
    this.rootEl.querySelectorAll('[data-mode]').forEach((button) => {
      const btn = button as HTMLButtonElement
      btn.addEventListener('click', () => this.setTransformMode(btn.dataset.mode! as WorkspaceTransformMode))
    })
    this.rootEl.querySelectorAll('[data-add]').forEach((button) => {
      const btn = button as HTMLButtonElement
      btn.addEventListener('click', () => this.addObject(btn.dataset.add!))
    })
    this.rootEl.querySelectorAll('[data-action]').forEach((button) => {
      const btn = button as HTMLButtonElement
      btn.addEventListener('click', () => this._runAction(btn.dataset.action!))
    })
    Object.entries(this.transformInputs).forEach(([key, input]) => {
      input.addEventListener('change', () => this._applyTransformInputs(key))
      input.addEventListener('input', () => this._applyTransformInputs(key))
    })
    this.outlinerEl.addEventListener('click', (event) => {
      const cameraItem = (event.target as HTMLElement).closest('[data-camera-id]') as HTMLElement | null
      if (cameraItem) {
        this.setFollowCamera(true, { persist: false })
        this.setActiveCamera(cameraItem.dataset.cameraId!)
        return
      }
      const objectItem = (event.target as HTMLElement).closest('[data-object-id]') as HTMLElement | null
      if (!objectItem) return
      this.selectObject(objectItem.dataset.objectId!)
    })
    this.followCameraEl.addEventListener('change', () => {
      this.setFollowCamera(this.followCameraEl.checked)
    })
    this.objectColorsEl?.addEventListener('change', () => {
      this.setObjectColorPreview(this.objectColorsEl!.checked)
    })
    this.wireframeModeEl?.addEventListener('change', () => {
      this.setWireframeMode(this.wireframeModeEl!.value)
    })
    this.programLightingEl?.addEventListener('change', () => {
      this.setProgramLightingMode(this.programLightingEl!.value)
    })
    this.cameraSelectEl.addEventListener('change', () => {
      this.setActiveCamera(this.cameraSelectEl.value)
    })
    this.timeSliderEl.addEventListener('input', () => {
      if (this.isPlaying) {
        this.isPlaying = false
        this._updatePlayButton()
      }
      this.setAnimationTime(Number(this.timeSliderEl.value || 0))
    })
  }

  _runAction(action: string): void {
    switch (action) {
      case 'delete':
        this.deleteSelected()
        break
      case 'focus':
        this.focusSelected()
        break
      case 'reset-view':
        this.resetView()
        break
      case 'load-shot-camera':
        this.loadShotCamera(this.callbacks.getShotCamera?.())
        break
      case 'apply-shot-camera':
        this.callbacks.onApplyShotCamera?.(this.getCameraState())
        break
      case 'import-blender':
        this.callbacks.onImportBlender?.()
        break
      case 'open-blender':
        this.callbacks.onOpenBlender?.()
        break
      case 'play-pause':
        this.toggleAnimationPlayback()
        break
      case 'go-to-start':
        this.goToAnimationStart()
        break
      case 'step-back':
        this.stepAnimation(-0.1)
        break
      case 'step-forward':
        this.stepAnimation(0.1)
        break
      case 'reload-glb':
        this.reloadBlenderScene()
        break
      case 'free-view':
        this.setFollowCamera(false)
        break
      case 'capture-board':
        this.callbacks.onCaptureToBoard?.()
        break
      default:
        break
    }
  }

  _onKeyDown(event: KeyboardEvent): void {
    if (shouldIgnoreWorkspaceKeyboard(event.target)) return
    const action =
      this.mode === 'blender'
        ? resolveBlenderKeyboardAction(event)
        : resolveBuiltinKeyboardAction(event)
    if (!action) return
    if (this.mode === 'blender') event.preventDefault()
    applyWorkspaceKeyboardAction(action, {
      togglePlayback: () => this.toggleAnimationPlayback(),
      reloadGlb: () => this.reloadBlenderScene(),
      goToStart: () => this.goToAnimationStart(),
      stepAnimation: (delta: number) => this.stepAnimation(delta),
      setTransformMode: (mode: WorkspaceTransformMode) => this.setTransformMode(mode),
      deleteSelected: () => this.deleteSelected(),
      focusSelected: () => this.focusSelected(),
    })
  }

  _onPointerDown(event: PointerEvent): void {
    if (this.mode !== 'builtin' || this.transform.dragging) return
    const rect = this.renderer.domElement.getBoundingClientRect()
    this.pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1
    this.pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1
    this.raycaster.setFromCamera(this.pointer, this.camera)
    const hits = this.raycaster.intersectObjects([...this.objects.values()], false)
    if (hits.length) {
      this.selectObject(hits[0].object.userData.objectId)
    } else {
      this.selectObject(null)
    }
  }

  setTransformMode(mode: WorkspaceTransformMode): void {
    this.transformMode = mode
    this.transform.setMode(mode)
    this.rootEl.querySelectorAll('[data-mode]').forEach((button) => {
      const btn = button as HTMLButtonElement
      btn.classList.toggle('active', btn.dataset.mode === mode)
    })
  }

  _scheduleSceneSettingsSave(): void {
    if (!this.callbacks.onSceneSettingsChange) return
    window.clearTimeout(this._sceneSettingsSaveTimer ?? undefined)
    this._sceneSettingsSaveTimer = window.setTimeout(() => {
      this.callbacks.onSceneSettingsChange!(this.exportSceneData())
    }, 350)
  }

  applyDisplaySettings(meta: Record<string, unknown> = {}): void {
    if (!meta || typeof meta !== 'object') return
    this.setFollowCamera(meta.follow_camera !== false, { persist: false })
    this.setProgramLightingMode(String(meta.program_lighting || 'auto'), { persist: false, notify: false })
    this.setObjectColorPreview(meta.object_color_preview !== false, { persist: false, notify: false })
    this.setWireframeMode(String(meta.wireframe_mode || 'off'), { persist: false, notify: false })
  }

  async loadSceneData(settings: Record<string, unknown> | null): Promise<void> {
    this.sceneMeta = settings && typeof settings === 'object' ? { ...settings } : {}
    this.setWireframeMode(String(this.sceneMeta.wireframe_mode || 'off'), { persist: false, notify: false })
    if (this.sceneMeta.source === 'blender' && this.sceneMeta.file_path) {
      await this.loadBlenderFromProject(this.sceneMeta)
      return
    }
    this.setMode('builtin' as const)
    this.sceneData = filterBuiltinObjectSpecs(this.sceneMeta, defaultBuiltinSceneData, WORKSPACE_PRIMITIVE_TYPE_SET)
    this.clearBlenderScene()
    this.clearObjects()
    for (const spec of (this.sceneData.objects as ThreeObject[]) || []) {
      this._addMeshFromSpec(spec)
    }
    this.selectObject((this.sceneData.objects as ThreeObject[])?.[0]?.id || null)
    this._renderOutliner()
    this._updateFileName()
    this._applyWireframeMode()
  }

  _normalizeWireframeMode(mode: unknown): Scene3dWireframeMode {
    return normalizeWireframeMode(mode) as Scene3dWireframeMode
  }

  setWireframeMode(mode: string, { persist = true, notify = false } = {}): void {
    this.wireframeMode = this._normalizeWireframeMode(mode)
    if (this.wireframeModeEl) this.wireframeModeEl.value = this.wireframeMode
    if (persist) {
      this.sceneMeta = { ...(this.sceneMeta || {}), wireframe_mode: this.wireframeMode }
    }
    this._applyWireframeMode()
    if (persist) this._scheduleSceneSettingsSave()
    if (notify) {
      this.callbacks.onMessage?.(
        `线框：${(WIREFRAME_MODE_LABELS as Record<string, string>)[this.wireframeMode] || this.wireframeMode}`,
      )
    }
  }

  _getWireframeRoots(): ThreeObject[] {
    return getWireframeRoots(this.blenderRoot, this.objects.values())
  }

  _clearWireframeOverlays(): void {
    if (!this.wireframeResources) {
      this.wireframeResources = createWireframeResources()
    }
    clearWireframeOverlays(this._getWireframeRoots(), this.wireframeResources)
  }

  _applyWireframeMode(): void {
    if (!this.wireframeResources) {
      this.wireframeResources = createWireframeResources()
    }
    applyWireframeModeToRoots(THREE, this._getWireframeRoots(), this.wireframeMode, this.wireframeResources)
  }

  async loadBlenderFromProject(meta: Record<string, unknown>): Promise<void> {
    this.setMode('blender' as const)
    this._suppressViewChange = true
    try {
      this.sceneMeta = { ...meta }
      this.followCamera = meta.follow_camera !== false
      this.followCameraEl.checked = this.followCamera
      this.programLightingMode =
        meta.program_lighting === 'on' || meta.program_lighting === 'off'
          ? (meta.program_lighting as ProgramLightingMode)
          : 'auto'
      if (this.programLightingEl) this.programLightingEl.value = this.programLightingMode
      this.objectColorPreview = meta.object_color_preview !== false
      if (this.objectColorsEl) this.objectColorsEl.checked = this.objectColorPreview
      this.setWireframeMode(String(meta.wireframe_mode || 'off'), { persist: false, notify: false })
      const url = `/api/project/scene3d/file?t=${Date.now()}`
      await this._loadBlenderUrl(url, String(meta.file_name || meta.file_path || ''))
      if (meta.camera_name) {
        this.setActiveCamera(this._pickBestCameraId(String(meta.camera_name)), false)
      } else if (this.importedCameras.length) {
        this.setActiveCamera(this._pickBestCameraId(''), false)
      }
      const shotTime = this.callbacks.getShotScene3dTime?.()
      const startTime = resolveInitialAnimationTime(meta, shotTime)
      if (startTime != null) {
        this.setAnimationTime(startTime)
      }
      this._updateFileName()
      this._updateAnimationHint()
    } finally {
      this._suppressViewChange = false
    }
  }

  async reloadBlenderScene(): Promise<void> {
    if (!this.sceneMeta?.file_path) {
      this.callbacks.onMessage?.('当前项目没有 GLB，请先 Import GLB')
      return
    }
    const savedTime = this.animationTime
    const savedCameraName =
      this.importedCameras.find((item: ThreeObject) => item.id === this.activeCameraId)?.name ||
      this.sceneMeta.camera_name ||
      ''
    this.isPlaying = false
    this._updatePlayButton()
    this._suppressViewChange = true
    try {
      const url = `/api/project/scene3d/file?t=${Date.now()}`
      await this._loadBlenderUrl(url, String(this.sceneMeta.file_name || this.sceneMeta.file_path))
      if (savedCameraName) {
        this.setActiveCamera(this._pickBestCameraId(String(savedCameraName)), false)
      }
      if (savedTime > 0) {
        this.setAnimationTime(resolveReloadAnimationTime(savedTime, this.animationDuration))
      }
      this.callbacks.onMessage?.('已刷新 GLB（保留时间与显示设置）')
    } catch (error: unknown) {
      this.callbacks.onMessage?.(
        `刷新 GLB 失败：${error instanceof Error ? error.message : String(error)}`,
      )
    } finally {
      this._suppressViewChange = false
    }
  }

  _programLightingContext(): ProgramLightingContext {
    return {
      mode: this.programLightingMode,
      workspaceMode: this.mode,
      importedLightCount: this.importedLightCount,
      objectColorPreview: this.objectColorPreview,
    }
  }

  _cameraMotionProbe(): { animationDuration: number; animationTime: number; probeA: ThreeObject; probeB: ThreeObject; setMixerTime: (time: number) => void } {
    return {
      animationDuration: this.animationDuration,
      animationTime: this.animationTime,
      probeA: this._probePosA,
      probeB: this._probePosB,
      setMixerTime: (time: number) => this._syncMixerTime(time),
    }
  }

  _trackNodeName(trackName: string): string {
    return trackNodeName(trackName)
  }

  _collectAnimatedNodeNames(animations: ThreeObject[]): Set<string> {
    return collectAnimatedNodeNames(animations)
  }

  _isNodeInSceneGraph(root: ThreeObject, node: ThreeObject): boolean {
    return isNodeInSceneGraph(root, node)
  }

  _collectImportedCameras(gltf: ThreeObject): ThreeObject[] {
    return collectImportedCameras(gltf)
  }

  _diagnoseMissingCameras(gltf: ThreeObject): string {
    return diagnoseMissingCameras(gltf)
  }

  _scoreCameraForAnimation(item: ThreeObject): number {
    return scoreCameraForAnimation(item, this.animatedNodeNames)
  }

  _pickBestCameraId(preferredName: string): string {
    return pickBestCameraId(this.importedCameras, this.animatedNodeNames, preferredName)
  }

  _computeClipDuration(clips: ThreeObject[]): number {
    return computeClipDuration(clips)
  }

  _selectAnimationClips(animations: ThreeObject[]): ThreeObject[] {
    return selectAnimationClips(animations)
  }

  _cameraMovesOverTime(object3d: ThreeObject): boolean {
    if (!this.mixer || !object3d || this.animationDuration <= 0) return false
    return cameraMovesOverTime(object3d, this._cameraMotionProbe())
  }

  _resolveViewNode(item: ThreeObject): ThreeObject {
    return resolveViewNode(item, this.blenderRoot, this.animatedNodeNames, this._cameraMotionProbe())
  }

  _updateAnimationHint(): void {
    if (!this.hintEl) return
    const active = this.importedCameras.find((item: ThreeObject) => item.id === this.activeCameraId)
    const moves = active?.object3d ? this._cameraMovesOverTime(active.object3d) : false
    this.hintEl.textContent = buildAnimationHint({
      animationDuration: this.animationDuration,
      activeCameraName: active?.name || '',
      cameraMoves: moves,
      formatTime: formatWorkspaceTime,
    })
  }

  _countImportedLights(root: ThreeObject): number {
    return countImportedLights(root)
  }

  _shouldUseProgramIbl(): boolean {
    return shouldUseProgramIbl(this._programLightingContext())
  }

  _shouldUseProgramFill(): boolean {
    return shouldUseProgramFill(this._programLightingContext())
  }

  _shouldUseProgramWeakFill(): boolean {
    return shouldUseProgramWeakFill(this._programLightingContext())
  }

  _getEnvMapIntensity(): number {
    return getEnvMapIntensity(this._programLightingContext())
  }

  _calibrateImportedLights(root: ThreeObject): void {
    calibrateImportedLights(root)
  }

  _setImportedLightsVisible(visible: boolean): void {
    setImportedLightsVisible(this.blenderRoot, visible)
  }

  _programLightingReason(): string {
    return programLightingReason(this._programLightingContext())
  }

  setProgramLightingMode(mode: unknown, { persist = true, notify = true } = {}): void {
    const next = normalizeProgramLightingMode(mode)
    this.programLightingMode = next
    if (this.programLightingEl) this.programLightingEl.value = next
    if (persist) {
      this.sceneMeta = { ...(this.sceneMeta || {}), program_lighting: next }
    }
    this._applyProgramLighting()
    if (this.blenderRoot) this._prepareImportedMaterials(this.blenderRoot)
    if (this.objectColorPreview) this._applyObjectColorPreview(true)
    if (persist) this._scheduleSceneSettingsSave()
    if (notify) {
      this.callbacks.onMessage?.(`灯光设置：${this._programLightingReason()}`)
    }
  }

  _updateLightStatusUi(): void {
    if (!this.lightStatusEl) return
    if (this.mode !== 'blender') {
      this.lightStatusEl.textContent = '—'
      return
    }
    this.lightStatusEl.textContent = buildLightStatusText(this._programLightingContext())
  }

  _ensureBlenderEnvMap(): ThreeObject {
    if (this.blenderEnvMap) return this.blenderEnvMap
    this.blenderEnvMap = createBlenderEnvMap(RoomEnvironment, this.pmremGenerator)
    return this.blenderEnvMap
  }

  _applyProgramLighting(): void {
    applyWorkspaceProgramLighting(THREE, this._programLightingContext(), {
      scene: this.scene,
      programAmbient: this.programAmbient,
      programHemisphere: this.programHemisphere,
      builtinBackground: this.builtinBackground,
      blenderEnvMap: this.blenderEnvMap,
      ensureBlenderEnvMap: () => this._ensureBlenderEnvMap(),
      setImportedLightsVisible: (visible: boolean) => this._setImportedLightsVisible(visible),
    })
    this._updateLightStatusUi()
  }

  _generateBlenderObjectColor(seed: string): ThreeObject {
    return generateObjectColor(THREE, seed)
  }

  _collectObjectColorKeys(root: ThreeObject): string[] {
    return collectMeshObjectColorKeys(root, (mesh: ThreeObject) => this._objectColorKey(mesh))
  }

  _objectColorKey(mesh: ThreeObject): string {
    return objectColorKey(mesh, this.blenderRoot)
  }

  _cacheImportedMaterials(root: ThreeObject): void {
    cacheImportedMaterialsOnRoot(root)
  }

  _restoreImportedMaterials(root: ThreeObject): void {
    restoreImportedMaterialsOnRoot(root)
  }

  _disposePreviewMaterials(): void {
    disposePreviewMaterials(this.previewMaterials)
  }

  setObjectColorPreview(enabled: boolean | unknown, { persist = true, notify = false } = {}): void {
    this.objectColorPreview = Boolean(enabled)
    if (this.objectColorsEl) this.objectColorsEl.checked = this.objectColorPreview
    if (persist) {
      this.sceneMeta = { ...(this.sceneMeta || {}), object_color_preview: this.objectColorPreview }
    }
    this._applyProgramLighting()
    this._applyObjectColorPreview(this.objectColorPreview)
    if (!this.objectColorPreview && this.blenderRoot) {
      this._prepareImportedMaterials(this.blenderRoot)
    }
    this._applyWireframeMode()
    if (persist) this._scheduleSceneSettingsSave()
    if (notify) {
      this.callbacks.onMessage?.(
        this.objectColorPreview
          ? '已启用对象随机色（不受灯光影响，便于区分）'
          : '已恢复 GLB 原始材质',
      )
    }
  }

  _applyObjectColorPreview(enabled: boolean): void {
    if (!this.blenderRoot) return
    applySharedObjectColorPreview(THREE, this.blenderRoot, this.blenderRoot, this.previewMaterials, enabled)
    if (!enabled && this.blenderRoot) {
      this._prepareImportedMaterials(this.blenderRoot)
    }
  }

  _prepareImportedMaterials(root: ThreeObject): void {
    if (this.objectColorPreview) return
    prepareImportedMaterials(root, this._getEnvMapIntensity())
  }

  async _loadBlenderUrl(url: string, label: string): Promise<void> {
    this.clearBlenderScene()
    this.clearObjects()
    const loader = new GLTFLoader()
    const gltf = await loader.loadAsync(url)
    this.blenderRoot = gltf.scene
    this.scene.add(this.blenderRoot)
    this.importedLightCount = this._countImportedLights(gltf.scene)
    this._calibrateImportedLights(this.blenderRoot)
    this._applyProgramLighting()
    this._prepareImportedMaterials(this.blenderRoot)
    this._cacheImportedMaterials(this.blenderRoot)
    this._applyObjectColorPreview(this.objectColorPreview)
    if (this.objectColorPreview) {
      this._applyProgramLighting()
    }
    this._applyWireframeMode()

    this.importedCameras = this._collectImportedCameras(gltf)
    this.animatedNodeNames = this._collectAnimatedNodeNames(gltf.animations)

    const mixerBoot = createWorkspaceAnimationMixer(THREE, gltf.scene, gltf.animations || [])
    this.mixer = mixerBoot.mixer
    this.mixerActions = mixerBoot.mixerActions
    this.animationDuration = mixerBoot.animationDuration
    this.animationTime = 0
    this.isPlaying = false
    this._syncMixerTime(0)
    this._populateCameraSelect()
    this._renderOutliner()
    this._updateTimelineUi()
    if (!this.followCamera || !this.importedCameras.length) {
      this._frameImportedScene()
    }
    this.sceneMeta.file_name = label || this.sceneMeta.file_name
    if (this.importedCameras.length) {
      const bestId = this._pickBestCameraId('')
      const best = this.importedCameras.find((item: ThreeObject) => item.id === bestId)
      if (best) best.viewNode = this._resolveViewNode(best)
      this.setActiveCamera(bestId, false)
    }
    this.setFollowCamera(this.followCamera)
    this._updateAnimationHint()

    for (const message of buildGlbLoadNotifications({
      gltf,
      importedCameras: this.importedCameras,
      animationDuration: this.animationDuration,
      importedLightCount: this.importedLightCount,
      programLightingMode: this.programLightingMode,
    })) {
      this.callbacks.onMessage?.(message)
    }
  }

  _programLightingModeLabel(): string {
    return programLightingModeLabel(this.programLightingMode)
  }

  _frameImportedScene(): void {
    if (!this.blenderRoot) return
    frameImportedScene(THREE, this.blenderRoot, this.camera, this.orbit)
  }

  _populateCameraSelect(): void {
    populateCameraSelectDom(
      this.cameraSelectEl,
      buildCameraSelectOptions(this.importedCameras),
      this.activeCameraId,
    )
  }

  setActiveCamera(cameraId: string, showMessage = true): void {
    const match = this.importedCameras.find((item: ThreeObject) => item.id === cameraId)
    if (!match) return
    this.activeCameraId = cameraId
    this.cameraSelectEl.value = cameraId
    match.viewNode = this._resolveViewNode(match)
    this._renderOutliner()
    if (showMessage) {
      this.callbacks.onMessage?.(`已切换相机：${match.name}`)
    }
    if (this.followCamera) {
      this._applyFollowCamera()
    }
    this._updateAnimationHint()
    if (showMessage) this._notifyViewChange()
  }

  setFollowCamera(enabled: boolean, { persist = true } = {}): void {
    this.followCamera = Boolean(enabled)
    this.followCameraEl.checked = this.followCamera
    this.orbit.enabled = !this.followCamera
    if (this.followCamera) {
      this._applyFollowCamera()
    }
    if (persist) {
      this.sceneMeta = { ...(this.sceneMeta || {}), follow_camera: this.followCamera }
      this._scheduleSceneSettingsSave()
      this._notifyViewChange()
    }
  }

  _notifyViewChange(): void {
    if (this._suppressViewChange) return
    this.callbacks.onViewChange?.()
  }

  setMode(mode: 'builtin' | 'blender'): void {
    this.mode = mode
    applyWorkspaceModeUi(this.rootEl, mode)
    applyWorkspaceSceneModeFlags(mode, {
      grid: this.grid,
      axes: this.axes,
      defaultAmbient: this.defaultAmbient,
      defaultSun: this.defaultSun,
      programAmbient: this.programAmbient,
      programHemisphere: this.programHemisphere,
      scene: this.scene,
      builtinBackground: this.builtinBackground,
    })
    if (mode === 'blender') {
      this._applyProgramLighting()
      this.transform.detach()
      this.selectObject(null)
    } else {
      this._updateLightStatusUi()
    }
  }

  exportSceneData(): Record<string, unknown> {
    if (this.mode === 'blender') {
      const active = this.importedCameras.find((item: ThreeObject) => item.id === this.activeCameraId)
      return exportBlenderSceneData({
        sceneMeta: this.sceneMeta,
        activeCameraName: active?.name || String(this.sceneMeta.camera_name || ''),
        followCamera: this.followCamera,
        animationTime: this.animationTime,
        programLightingMode: this.programLightingMode,
        importedLightCount: this.importedLightCount,
        objectColorPreview: this.objectColorPreview,
        wireframeMode: this.wireframeMode,
      })
    }
    return exportBuiltinSceneData(this.objects.entries(), this.wireframeMode, this.objectColorPreview) as unknown as Record<string, unknown>
  }

  clearBlenderScene(): void {
    stopWorkspaceMixer(this.mixer)
    Object.assign(this, createEmptyBlenderPlaybackState())
    this._clearWireframeOverlays()
    if (this.blenderRoot) {
      this._restoreImportedMaterials(this.blenderRoot)
      this._disposePreviewMaterials()
      this.scene.remove(this.blenderRoot)
      disposeObject3DRoot(this.blenderRoot)
      this.blenderRoot = null
    }
    this._populateCameraSelect()
    this._updateTimelineUi()
  }

  clearObjects(): void {
    for (const mesh of this.objects.values()) {
      this.scene.remove(mesh)
      disposePrimitiveMesh(mesh)
    }
    this.objects.clear()
    this.transform.detach()
    this.selectedId = null
  }

  _addMeshFromSpec(spec: ThreeObject): ThreeObject {
    const mesh = createPrimitiveMesh(THREE, spec)
    this.objects.set(spec.id, mesh)
    this.scene.add(mesh)
    return mesh
  }

  addObject(type: string): void {
    const spec = defaultAddObjectSpec(type as WorkspacePrimitiveType, this.objects.size, '')
    spec.color = `#${this._generateBlenderObjectColor(spec.name).getHexString()}`
    this._addMeshFromSpec(spec)
    this.selectObject(spec.id)
    this._renderOutliner()
    this._applyWireframeMode()
  }

  selectObject(id: string | null): void {
    this.selectedId = id
    const mesh = id ? this.objects.get(id) : null
    if (shouldAttachTransformToSelection(this.mode, mesh)) {
      this.transform.attach(mesh)
    } else {
      this.transform.detach()
    }
    this._renderOutliner()
    this._updateTransformInputs()
  }

  deleteSelected(): void {
    if (!canDeleteWorkspaceObject(this.selectedId)) return
    const mesh = this.objects.get(this.selectedId!)
    if (!mesh) return
    this.transform.detach()
    this.scene.remove(mesh)
    disposePrimitiveMesh(mesh)
    this.objects.delete(this.selectedId!)
    this.selectedId = null
    this._renderOutliner()
    this._updateTransformInputs()
  }

  focusSelected(): void {
    const mesh = this.selectedId ? this.objects.get(this.selectedId) : null
    const target = getWorkspaceFocusTarget(mesh, this.orbit)
    this.orbit.target.copy(target)
    this.orbit.update()
  }

  resetView(): void {
    if (this.mode === 'blender') {
      this._frameImportedScene()
      return
    }
    resetBuiltinCameraView(this.camera, this.orbit)
  }

  getCameraState(): ThreeObject {
    return getCameraStateFromEditor(this.camera, this.orbit)
  }

  getViewState(): Record<string, unknown> | null {
    const active = this.importedCameras.find((item: ThreeObject) => item.id === this.activeCameraId) || null
    return exportViewState(THREE, {
      camera: this.camera,
      orbit: this.orbit,
      followCamera: this.followCamera,
      activeCamera: active ? { id: active.id, name: active.name } : null,
      animationTime: this.animationTime,
    }) as unknown as Record<string, unknown>
  }

  loadShotCamera(cameraData: Record<string, unknown> | null | undefined): void {
    if (!cameraData?.position) {
      this.callbacks.onMessage?.('当前镜头没有保存的 3D 相机数据')
      return
    }
    this.setFollowCamera(false)
    loadShotCameraIntoEditor(THREE, this.camera, this.orbit, cameraData)
  }

  _fovToFocalLength(fov: number): number {
    return fovToFocalLength(fov)
  }

  _syncSelectedFromMesh(): void {
    this._updateTransformInputs()
  }

  _applyTransformInputs(changedKey: string): void {
    const mesh = this.selectedId ? this.objects.get(this.selectedId) : null
    if (!mesh) return
    applyTransformFromInputs(THREE, mesh, this.transformInputs, changedKey, this.transform)
  }

  _updateTransformInputs(): void {
    const mesh = this.selectedId ? this.objects.get(this.selectedId) : null
    syncTransformInputsFromMesh(THREE, mesh, this.transformInputs)
  }

  _renderOutliner(): void {
    renderOutlinerDom(
      this.outlinerEl,
      buildOutlinerEntries(
        this.mode,
        this.objects,
        this.importedCameras,
        this.activeCameraId,
        this.selectedId,
      ),
    )
  }

  refreshBoardPreview(): void {
    const url = this.callbacks.getBoardPreviewUrl?.() || ''
    const label = this.callbacks.getBoardLabel?.() || '—'
    if (this.boardLabelEl) this.boardLabelEl.textContent = label
    if (!this.boardPreviewImg || !this.boardPreviewEmpty) return
    if (url) {
      this.boardPreviewImg.src = url
      this.boardPreviewImg.hidden = false
      this.boardPreviewEmpty.hidden = true
    } else {
      this.boardPreviewImg.hidden = true
      this.boardPreviewEmpty.hidden = false
    }
  }

  _updateFileName(): void {
    this.fileNameEl.textContent = formatWorkspaceFileName(this.mode, this.sceneMeta)
  }

  setBlendFilePath(relativePath: string | undefined): void {
    this.sceneMeta = {
      ...(this.sceneMeta || {}),
      blend_file_path: relativePath || 'scene3d/scene.blend',
    }
    this._updateFileName()
  }

  _syncMixerTime(seconds: number): void {
    if (!this.mixer || !this.mixerActions.length) return
    this.animationTime = syncMixerActionsTime(this.mixerActions, this.mixer, seconds)
    this.blenderRoot?.updateMatrixWorld(true)
  }

  setAnimationTime(seconds: number): void {
    const clamped = clampAnimationTime(seconds, this.animationDuration || 0)
    this._syncMixerTime(clamped)
    this._updateTimelineUi()
    if (this.followCamera) {
      this._applyFollowCamera()
    }
    this._notifyViewChange()
  }

  toggleAnimationPlayback(): void {
    if (this.mode !== 'blender' || !this.mixer) {
      this.callbacks.onMessage?.('请先导入带相机动画的 GLB')
      return
    }
    if (
      !this.isPlaying &&
      this.animationDuration > 0 &&
      this.animationTime >= this.animationDuration - 0.001
    ) {
      this.setAnimationTime(0)
    }
    this.isPlaying = !this.isPlaying
    this._updatePlayButton()
  }

  pauseAnimation(): void {
    this.isPlaying = false
    this._updatePlayButton()
  }

  goToAnimationStart(): void {
    this.isPlaying = false
    this.setAnimationTime(0)
    this._updatePlayButton()
  }

  stepAnimation(deltaSeconds: number): void {
    if (this.mode !== 'blender' || !this.mixer) return
    if (this.isPlaying) {
      this.isPlaying = false
      this._updatePlayButton()
    }
    this.setAnimationTime(this.animationTime + Number(deltaSeconds || 0))
  }

  captureFrameDataUrl(): string {
    const followPrep = () => {
      if (this.followCamera && this.mode === 'blender') this._applyFollowCamera()
    }
    return captureRendererPng(THREE, this.renderer, this.camera, this.scene, {
      getProjectCanvasSize,
      prepareExport: followPrep,
      finishDisplay: () => {
        followPrep()
        this.renderer.render(this.scene, this.camera)
      },
    })
  }

  getAnimationState(): { time: number; duration: number; camera_name: string } {
    return {
      time: this.animationTime,
      duration: this.animationDuration,
      camera_name:
        this.importedCameras.find((item: ThreeObject) => item.id === this.activeCameraId)?.name || '',
    }
  }

  _updatePlayButton(): void {
    if (!this.playPauseBtn) return
    this.playPauseBtn.textContent = this.isPlaying ? '⏸ 暂停' : '▶ 播放'
  }

  _updateTimelineUi(): void {
    const ui = buildTimelineUiState(this.animationTime, this.animationDuration, formatWorkspaceTime)
    this.timeSliderEl.max = String(ui.max)
    this.timeSliderEl.value = String(ui.value)
    this.timeSliderEl.disabled = ui.disabled
    this.timeDisplayEl.textContent = ui.displayText
  }

  _applyFollowCamera(): void {
    const active = this.importedCameras.find((item: ThreeObject) => item.id === this.activeCameraId)
    applyFollowCameraToEditor(this.camera, this.orbit, active, {
      position: this._followPos,
      quaternion: this._followQuat,
      scale: this._followScale,
    })
  }

  _projectAspect(): number {
    return getProjectCanvasAspect()
  }

  _resize(): void {
    const frame = this.formatFrameEl || this.viewportEl
    const width = Math.max(1, Math.floor(frame.clientWidth))
    const height = Math.max(1, Math.floor(frame.clientHeight))
    if (!width || !height) return
    this.camera.aspect = this._projectAspect()
    this.camera.updateProjectionMatrix()
    this.renderer.setSize(width, height, false)
  }

  _animate(): void {
    this.animationId = requestAnimationFrame(() => this._animate())
    const delta = this.clock.getDelta()
    if (this.mode === 'blender' && this.mixer && this.isPlaying) {
      const duration = this.animationDuration || 0
      const { nextTime, reachedEnd } = advancePlaybackTime(this.animationTime, delta, duration)
      if (reachedEnd) {
        this.isPlaying = false
        this._updatePlayButton()
      }
      this._syncMixerTime(nextTime)
      this._updateTimelineUi()
    }
    if (shouldUseOrbitControls(this.mode, this.followCamera)) {
      this.orbit.update()
    } else {
      this._applyFollowCamera()
    }
    this.renderer.render(this.scene, this.camera)
  }

  dispose(): void {
    if (this._disposed) return
    this._disposed = true

    if (this.animationId) cancelAnimationFrame(this.animationId)
    this.animationId = null

    if (this._sceneSettingsSaveTimer != null) {
      window.clearTimeout(this._sceneSettingsSaveTimer)
      this._sceneSettingsSaveTimer = null
    }

    this._resizeObserver?.disconnect()
    if (this._keydownHandler) window.removeEventListener('keydown', this._keydownHandler)
    if (this._pointerdownHandler && this.renderer?.domElement) {
      this.renderer.domElement.removeEventListener('pointerdown', this._pointerdownHandler)
    }

    this.clearBlenderScene()
    this.clearObjects()
    this.transform?.dispose()
    this.orbit?.dispose()
    this.blenderEnvMap?.dispose()
    this.blenderEnvMap = null
    this.pmremGenerator?.dispose()
    this.pmremGenerator = null
    this._clearWireframeOverlays()

    if (this.renderer) {
      this.renderer.dispose()
      if (this.renderer.domElement.parentNode) {
        this.renderer.domElement.parentNode.removeChild(this.renderer.domElement)
      }
    }
  }
}

// Keep vec3From exported for any callers that reference it
export { vec3From, makeWorkspaceObjectId, fovToFocalLength }
