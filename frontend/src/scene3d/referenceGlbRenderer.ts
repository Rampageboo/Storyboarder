import type { Scene3dReferenceView } from '../utils/scene3dView'

type ThreeModule = Record<string, any>

type Runtime = {
  THREE: ThreeModule
  GLTFLoader: new () => any
}

export type GlbCaptureOptions = {
  time?: number
  view?: Scene3dReferenceView | null
  width?: number
  height?: number
}

const OBJECT_PALETTE = [
  0x9cc9ff,
  0xb8e986,
  0xf8d57e,
  0xffa8a8,
  0xcdb4ff,
  0x8fd3ff,
  0xffc08a,
  0xa7f3d0,
]

let runtimePromise: Promise<Runtime> | null = null

function loadRuntime(): Promise<Runtime> {
  if (!runtimePromise) {
    const threeUrl = '/static/vendor/three/three.module.js'
    const loaderUrl = '/static/vendor/three/GLTFLoader.js'
    runtimePromise = Promise.all([
      import(/* @vite-ignore */ threeUrl) as Promise<ThreeModule>,
      import(/* @vite-ignore */ loaderUrl) as Promise<ThreeModule>,
    ]).then(([THREE, loader]) => ({ THREE, GLTFLoader: loader.GLTFLoader as new () => any }))
  }
  return runtimePromise
}

function triple(value: unknown): [number, number, number] | null {
  if (!Array.isArray(value) || value.length < 3) return null
  const out: [number, number, number] = [Number(value[0]), Number(value[1]), Number(value[2])]
  return out.every((n) => Number.isFinite(n)) ? out : null
}

function hashString(value: string): number {
  let hash = 2166136261
  for (let i = 0; i < value.length; i += 1) {
    hash ^= value.charCodeAt(i)
    hash = Math.imul(hash, 16777619)
  }
  return hash >>> 0
}

function disposeMaterial(material: any) {
  const materials = Array.isArray(material) ? material : [material]
  for (const item of materials) {
    if (!item) continue
    for (const key of Object.keys(item)) {
      const value = item[key]
      if (value && typeof value.dispose === 'function') {
        try {
          value.dispose()
        } catch {
          // best effort
        }
      }
    }
    try {
      item.dispose?.()
    } catch {
      // best effort
    }
  }
}

function disposeObject(root: any) {
  root?.traverse?.((node: any) => {
    try {
      node.geometry?.dispose?.()
      disposeMaterial(node.material)
    } catch {
      // best effort
    }
  })
}

function isBlankCanvas(canvas: HTMLCanvasElement): boolean {
  if (canvas.width <= 1 || canvas.height <= 1) return true
  const probe = document.createElement('canvas')
  probe.width = 32
  probe.height = 32
  const ctx = probe.getContext('2d', { willReadFrequently: true })
  if (!ctx) return false
  ctx.drawImage(canvas, 0, 0, probe.width, probe.height)
  const pixels = ctx.getImageData(0, 0, probe.width, probe.height).data
  let min = 255
  let max = 0
  let transparent = 0
  let brightness = 0
  const count = probe.width * probe.height
  for (let i = 0; i < pixels.length; i += 4) {
    const r = pixels[i]
    const g = pixels[i + 1]
    const b = pixels[i + 2]
    const a = pixels[i + 3]
    if (a < 8) transparent += 1
    min = Math.min(min, r, g, b)
    max = Math.max(max, r, g, b)
    brightness += (r + g + b) / 3
  }
  const avg = brightness / count
  if (transparent / count > 0.8) return true
  return max - min < 3 && (avg < 8 || avg > 247)
}

export class ReferenceGlbRenderer {
  canvas: HTMLCanvasElement
  url: string
  runtime: Runtime | null = null
  renderer: any = null
  scene: any = null
  camera: any = null
  root: any = null
  mixer: any = null
  center: any = null
  resizeObserver: ResizeObserver | null = null
  intersectionObserver: IntersectionObserver | null = null
  frameId = 0
  visible = false
  disposed = false
  currentView: Scene3dReferenceView | null = null
  readyPromise: Promise<void> | null = null
  previewMaterials: any[] = []

  constructor(canvas: HTMLCanvasElement, url: string) {
    this.canvas = canvas
    this.url = url
  }

  init(view: Scene3dReferenceView | null = null): Promise<void> {
    this.currentView = view
    if (!this.readyPromise) this.readyPromise = this.load(view)
    return this.readyPromise
  }

  async load(view: Scene3dReferenceView | null) {
    const runtime = await loadRuntime()
    if (this.disposed) return
    const { THREE, GLTFLoader } = runtime
    this.runtime = runtime
    this.renderer = new THREE.WebGLRenderer({
      canvas: this.canvas,
      antialias: true,
      alpha: false,
      preserveDrawingBuffer: true,
      powerPreference: 'high-performance',
    })
    this.renderer.setPixelRatio(1)
    this.renderer.outputColorSpace = THREE.SRGBColorSpace
    if ('toneMapping' in this.renderer) this.renderer.toneMapping = THREE.AgXToneMapping ?? THREE.ACESFilmicToneMapping
    if ('toneMappingExposure' in this.renderer) this.renderer.toneMappingExposure = 1

    this.scene = new THREE.Scene()
    this.scene.background = new THREE.Color(0x1a1d21)
    this.camera = new THREE.PerspectiveCamera(42, 1, 0.01, 500)
    this.center = new THREE.Vector3()
    this.scene.add(new THREE.AmbientLight(0xffffff, 0.75))
    const sun = new THREE.DirectionalLight(0xffffff, 1.1)
    sun.position.set(4, 8, 6)
    this.scene.add(sun)

    this.resize()
    this.resizeObserver = new ResizeObserver(() => this.resize())
    this.resizeObserver.observe(this.canvas)
    this.intersectionObserver = new IntersectionObserver(
      (entries) => {
        this.visible = entries.some((entry) => entry.isIntersecting)
        if (this.visible) this.start()
        else this.stop()
      },
      { threshold: 0.05 },
    )
    this.intersectionObserver.observe(this.canvas)

    const gltf = await new GLTFLoader().loadAsync(this.url)
    if (this.disposed) {
      disposeObject(gltf.scene)
      return
    }
    this.root = gltf.scene
    this.preparePreviewMaterials()
    this.scene.add(this.root)
    if (Array.isArray(gltf.animations) && gltf.animations.length > 0) {
      this.mixer = new THREE.AnimationMixer(this.root)
      for (const clip of gltf.animations) this.mixer.clipAction(clip).play()
      this.mixer.setTime(0)
    }
    this.applyViewOrFrame(view)
    this.render()
    if (this.visible) this.start()
  }

  preparePreviewMaterials() {
    if (!this.runtime || !this.root) return
    const { THREE } = this.runtime
    let meshIndex = 0
    this.root.traverse((node: any) => {
      if (!node?.isMesh) return
      const key = node.name || node.uuid || String(meshIndex)
      const color = OBJECT_PALETTE[hashString(`${key}:${meshIndex}`) % OBJECT_PALETTE.length]
      const material = new THREE.MeshBasicMaterial({ color, side: THREE.DoubleSide })
      this.previewMaterials.push(material)
      node.material = material
      node.frustumCulled = false
      meshIndex += 1
    })
  }

  setView(view: Scene3dReferenceView | null) {
    this.currentView = view
    if (!this.root) return
    this.applyViewOrFrame(view)
    this.render()
  }

  resize() {
    if (!this.renderer || !this.camera) return
    const rect = this.canvas.getBoundingClientRect()
    const width = Math.max(1, Math.floor(rect.width || this.canvas.clientWidth || 1))
    const height = Math.max(1, Math.floor(rect.height || this.canvas.clientHeight || 1))
    this.renderer.setSize(width, height, false)
    this.camera.aspect = width / height
    this.camera.updateProjectionMatrix()
  }

  start() {
    if (this.frameId || this.disposed) return
    const tick = (time: number) => {
      if (this.disposed) return
      if (this.root && !this.currentView) this.root.rotation.y = time * 0.00035
      this.render()
      this.frameId = requestAnimationFrame(tick)
    }
    this.frameId = requestAnimationFrame(tick)
  }

  stop() {
    if (!this.frameId) return
    cancelAnimationFrame(this.frameId)
    this.frameId = 0
    this.render()
  }

  render() {
    if (!this.renderer || !this.scene || !this.camera || this.disposed) return
    this.renderer.render(this.scene, this.camera)
  }

  frameObject() {
    if (!this.runtime || !this.root || !this.camera || !this.center) return
    const { THREE } = this.runtime
    const box = new THREE.Box3().setFromObject(this.root)
    if (box.isEmpty()) return
    const size = box.getSize(new THREE.Vector3())
    const center = box.getCenter(new THREE.Vector3())
    const radius = Math.max(size.x, size.y, size.z) * 1.35 || 2
    this.center.copy(center)
    this.camera.position.set(center.x + radius, center.y + radius * 0.55, center.z + radius)
    this.camera.near = Math.max(0.01, radius / 200)
    this.camera.far = Math.max(200, radius * 40)
    this.camera.lookAt(center)
    this.camera.updateProjectionMatrix()
  }

  applyClipPlanes() {
    if (!this.runtime || !this.root || !this.camera) return
    const { THREE } = this.runtime
    const box = new THREE.Box3().setFromObject(this.root)
    if (box.isEmpty()) return
    const size = box.getSize(new THREE.Vector3())
    const radius = Math.max(size.x, size.y, size.z) || 2
    this.camera.near = Math.max(0.001, radius / 500)
    this.camera.far = Math.max(200, radius * 60)
    this.camera.updateProjectionMatrix()
    if (this.center) box.getCenter(this.center)
  }

  findCamera(name: string): any | null {
    let found: any | null = null
    if (!this.root || !name) return null
    this.root.traverse((node: any) => {
      if (!found && node?.isCamera && node.name === name) found = node
    })
    return found
  }

  copyCamera(source: any) {
    if (!this.runtime || !this.camera) return
    const { THREE } = this.runtime
    source.updateWorldMatrix(true, false)
    const pos = new THREE.Vector3()
    const quat = new THREE.Quaternion()
    const scl = new THREE.Vector3()
    source.matrixWorld.decompose(pos, quat, scl)
    this.camera.position.copy(pos)
    this.camera.quaternion.copy(quat)
    if (source.isPerspectiveCamera && Number.isFinite(source.fov)) this.camera.fov = source.fov
    this.applyClipPlanes()
  }

  applyView(view: Scene3dReferenceView | null): boolean {
    if (!view || !this.camera) return false
    this.applyClipPlanes()
    const name = typeof view.camera_name === 'string' ? view.camera_name.trim() : ''
    if (view.mode === 'scene_camera' && name) {
      const camera = this.findCamera(name)
      if (camera) {
        this.copyCamera(camera)
        return true
      }
    }
    const position = triple(view.position)
    if (!position) return false
    this.camera.position.set(position[0], position[1], position[2])
    const fov = Number(view.fov)
    if (Number.isFinite(fov) && fov > 0) this.camera.fov = fov
    const rotation = triple(view.rotation)
    const target = triple(view.target)
    if (rotation) this.camera.rotation.set(rotation[0], rotation[1], rotation[2])
    else if (target) this.camera.lookAt(target[0], target[1], target[2])
    else if (this.center) this.camera.lookAt(this.center)
    this.camera.updateProjectionMatrix()
    return true
  }

  applyViewOrFrame(view: Scene3dReferenceView | null) {
    if (!this.applyView(view)) {
      if (this.root) this.root.rotation.set(0, 0, 0)
      this.frameObject()
    }
  }

  async capture(options: GlbCaptureOptions = {}): Promise<string> {
    await this.readyPromise
    if (!this.renderer || !this.camera || !this.root || !this.runtime) throw new Error('3D renderer is not ready.')
    const savedFrameId = this.frameId
    if (savedFrameId) {
      cancelAnimationFrame(savedFrameId)
      this.frameId = 0
    }

    const { THREE } = this.runtime
    const oldPixelRatio = this.renderer.getPixelRatio()
    const oldSize = this.renderer.getSize(new THREE.Vector2())
    const oldAspect = this.camera.aspect
    const oldRotation = this.root.rotation.clone()
    const oldView = this.currentView
    const width = Math.max(1, Math.floor(Number(options.width) || this.canvas.width || 1920))
    const height = Math.max(1, Math.floor(Number(options.height) || this.canvas.height || 1080))
    const time = Math.max(0, Number(options.time) || 0)
    const view = options.view === undefined ? this.currentView : (options.view ?? null)

    try {
      this.renderer.setPixelRatio(1)
      this.renderer.setSize(width, height, false)
      this.camera.aspect = width / height
      this.camera.updateProjectionMatrix()
      if (this.mixer) this.mixer.setTime(time)
      this.currentView = view
      this.applyViewOrFrame(view)
      this.render()
      if (isBlankCanvas(this.canvas)) throw new Error('3D capture produced a blank frame; refusing to overwrite boards.')
      return this.canvas.toDataURL('image/png')
    } finally {
      this.renderer.setPixelRatio(oldPixelRatio)
      this.renderer.setSize(oldSize.x, oldSize.y, false)
      this.camera.aspect = oldAspect
      this.camera.updateProjectionMatrix()
      this.root.rotation.copy(oldRotation)
      this.currentView = oldView
      this.applyViewOrFrame(oldView)
      this.render()
      if (savedFrameId && this.visible && !this.disposed) this.start()
    }
  }

  dispose() {
    this.disposed = true
    this.stop()
    this.resizeObserver?.disconnect()
    this.intersectionObserver?.disconnect()
    disposeObject(this.root)
    for (const material of this.previewMaterials) disposeMaterial(material)
    this.previewMaterials = []
    this.renderer?.dispose?.()
  }
}
