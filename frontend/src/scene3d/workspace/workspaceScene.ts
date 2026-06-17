/**
 * Scene3D workspace renderer / scene graph setup (extracted from scene3d.js _initThree).
 */

import type { WorkspaceVec3 } from './workspaceTypes'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type ThreeModule = Record<string, any>
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type ThreeObject = any

export const WORKSPACE_BACKGROUND = 0x1a1d21
export const DEFAULT_CAMERA_POSITION: WorkspaceVec3 = [6, 4, 8]
export const DEFAULT_ORBIT_TARGET: WorkspaceVec3 = [0, 0.5, 0]
export const DEFAULT_CAMERA_FOV = 50

export type WorkspaceSceneGraph = {
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
}

export type WorkspaceRendererOptions = {
  maxPixelRatio?: number
}

export function createWorkspaceRenderer(
  THREE: ThreeModule,
  mountEl: HTMLElement,
  options: WorkspaceRendererOptions = {},
): ThreeObject {
  const renderer = new THREE.WebGLRenderer({
    antialias: true,
    alpha: false,
    preserveDrawingBuffer: true,
  })
  const maxPixelRatio = options.maxPixelRatio ?? 2
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, maxPixelRatio))
  renderer.outputColorSpace = THREE.SRGBColorSpace
  renderer.toneMapping = THREE.AgXToneMapping ?? THREE.ACESFilmicToneMapping
  renderer.toneMappingExposure = 1.0
  renderer.shadowMap.enabled = true
  renderer.shadowMap.type = THREE.PCFSoftShadowMap
  mountEl.appendChild(renderer.domElement)
  return renderer
}

export function createWorkspaceSceneGraph(THREE: ThreeModule): WorkspaceSceneGraph {
  const scene = new THREE.Scene()
  scene.background = new THREE.Color(WORKSPACE_BACKGROUND)

  const camera = new THREE.PerspectiveCamera(DEFAULT_CAMERA_FOV, 1, 0.01, 1000)
  camera.position.set(...DEFAULT_CAMERA_POSITION)

  const defaultAmbient = new THREE.AmbientLight(0xffffff, 0.45)
  scene.add(defaultAmbient)
  const defaultSun = new THREE.DirectionalLight(0xffffff, 1.1)
  defaultSun.position.set(6, 10, 4)
  scene.add(defaultSun)

  const programAmbient = new THREE.AmbientLight(0xffffff, 0.1)
  programAmbient.visible = false
  scene.add(programAmbient)
  const programHemisphere = new THREE.HemisphereLight(0xd8e4ef, 0x404048, 0.28)
  programHemisphere.visible = false
  scene.add(programHemisphere)

  const grid = new THREE.GridHelper(20, 20, 0x4a515a, 0x3a4048)
  scene.add(grid)
  const axes = new THREE.AxesHelper(2)
  scene.add(axes)

  const builtinBackground = new THREE.Color(WORKSPACE_BACKGROUND)

  return {
    scene,
    camera,
    defaultAmbient,
    defaultSun,
    programAmbient,
    programHemisphere,
    grid,
    axes,
    builtinBackground,
    pmremGenerator: null as unknown as ThreeObject,
  }
}

export function createWorkspacePmremGenerator(THREE: ThreeModule, renderer: ThreeObject): ThreeObject {
  const pmremGenerator = new THREE.PMREMGenerator(renderer)
  pmremGenerator.compileEquirectangularShader()
  return pmremGenerator
}
