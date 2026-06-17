/**
 * GLB import helpers for the Scene3D workspace (extracted from scene3d.js).
 */

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type ThreeObject = any

export type WorkspaceImportedCamera = {
  id: string
  name: string
  object3d: ThreeObject
  source?: string
  orphan?: boolean
  viewNode?: ThreeObject
}

export function countImportedLights(root: ThreeObject | null | undefined): number {
  let count = 0
  root?.traverse?.((node: ThreeObject) => {
    if (node.isLight) count += 1
  })
  return count
}

export function calibrateImportedLights(root: ThreeObject | null | undefined): void {
  root?.traverse?.((node: ThreeObject) => {
    if (!node.isLight || typeof node.intensity !== 'number') return
    if (node.isDirectionalLight) {
      node.intensity = Math.min(node.intensity * Math.PI * 0.35, 4)
    } else if (node.isPointLight || node.isSpotLight) {
      if (node.intensity > 0 && node.intensity < 800) {
        node.intensity = Math.min(node.intensity * 1.5, 600)
      }
    }
  })
}

export function isNodeInSceneGraph(root: ThreeObject, node: ThreeObject): boolean {
  let current: ThreeObject | null = node
  while (current) {
    if (current === root) return true
    current = current.parent ?? null
  }
  return false
}

export function collectImportedCameras(gltf: {
  scene: ThreeObject
  scenes?: ThreeObject[]
  cameras?: ThreeObject[]
  parser?: { associations?: Map<ThreeObject, unknown>; json?: { nodes?: { camera?: number }[] } }
}): WorkspaceImportedCamera[] {
  const cameras: WorkspaceImportedCamera[] = []
  const seen = new Set<string>()
  const root = gltf.scene

  const addCamera = (node: ThreeObject, meta: Record<string, unknown> = {}) => {
    if (!node?.isCamera || seen.has(node.uuid)) return
    seen.add(node.uuid)
    const name = String(node.name || node.userData?.name || '').trim() || `Camera ${cameras.length + 1}`
    cameras.push({
      id: node.uuid,
      name,
      object3d: node,
      ...meta,
    })
  }

  const sceneRoots = gltf.scenes?.length ? gltf.scenes : [root]
  for (const sceneRoot of sceneRoots) {
    sceneRoot?.traverse?.((node: ThreeObject) => addCamera(node, { source: 'scene' }))
  }

  if (gltf.parser?.associations) {
    for (const [object3d] of gltf.parser.associations.entries()) {
      addCamera(object3d, { source: 'parser' })
    }
  }

  for (const cam of gltf.cameras || []) {
    addCamera(cam, { source: 'gltf.cameras' })
  }

  for (const item of cameras) {
    if (!isNodeInSceneGraph(root, item.object3d)) {
      root.add(item.object3d)
      item.orphan = true
    }
  }

  return cameras.sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true }))
}

export function diagnoseMissingCameras(gltf: {
  cameras?: unknown[]
  parser?: { json?: { nodes?: { camera?: number }[] } }
}): string {
  const json = gltf.parser?.json || {}
  const nodeCameraCount = (json.nodes || []).filter((node) => node.camera !== undefined).length
  const gltfCameraCount = gltf.cameras?.length || 0
  if (gltfCameraCount > 0 || nodeCameraCount > 0) {
    return (
      `GLB 元数据含 ${Math.max(gltfCameraCount, nodeCameraCount)} 个相机，但未能正确挂到场景。` +
      ' 请检查 Blender：相机不要隐藏（眼睛图标），Limit to 不要勾选 Visible/Active Collection，或把相机放进导出集合。'
    )
  }
  return (
    'GLB 内完全没有相机数据（不是勾选 Cameras 就行）。' +
    ' 请确认场景里有 Camera 对象、导出时 Limit to 留空、相机可见，并重新导出。'
  )
}

export function scoreCameraForAnimation(
  item: WorkspaceImportedCamera,
  animatedNodeNames: Set<string>,
): number {
  let score = 0
  let node: ThreeObject | null = item.object3d
  while (node) {
    if (node.name && animatedNodeNames.has(node.name)) score += 10
    node = node.parent ?? null
  }
  return score
}

export function pickBestCameraId(
  cameras: WorkspaceImportedCamera[],
  animatedNodeNames: Set<string>,
  preferredName = '',
): string {
  if (!cameras.length) return ''
  if (preferredName) {
    const match = cameras.find((item) => item.name === preferredName)
    if (match) return match.id
  }
  let best = cameras[0]
  let bestScore = scoreCameraForAnimation(best, animatedNodeNames)
  for (const item of cameras.slice(1)) {
    const score = scoreCameraForAnimation(item, animatedNodeNames)
    if (score > bestScore) {
      best = item
      bestScore = score
    }
  }
  return best.id
}

export function frameImportedScene(
  THREE: Record<string, unknown>,
  blenderRoot: ThreeObject,
  camera: ThreeObject,
  orbit: { target: ThreeObject; update(): void },
): void {
  const box = new (THREE.Box3 as new () => ThreeObject)().setFromObject(blenderRoot)
  if (box.isEmpty?.()) return
  const size = box.getSize(new (THREE.Vector3 as new () => ThreeObject)())
  const center = box.getCenter(new (THREE.Vector3 as new () => ThreeObject)())
  const radius = Math.max(size.x, size.y, size.z) * 0.6 || 4
  orbit.target.copy(center)
  camera.position.copy(
    center.clone().add(new (THREE.Vector3 as new (x: number, y: number, z: number) => ThreeObject)(radius, radius * 0.7, radius)),
  )
  camera.near = Math.max(0.01, radius / 100)
  camera.far = Math.max(100, radius * 40)
  camera.updateProjectionMatrix()
  orbit.update()
}

export type CameraMotionProbe = {
  animationDuration: number
  animationTime: number
  probeA: ThreeObject
  probeB: ThreeObject
  setMixerTime: (time: number) => void
}

export function cameraMovesOverTime(object3d: ThreeObject, probe: CameraMotionProbe): boolean {
  if (!object3d || probe.animationDuration <= 0) return false
  const saved = probe.animationTime
  probe.setMixerTime(0)
  object3d.getWorldPosition(probe.probeA)
  const probeTime = Math.min(Math.max(probe.animationDuration * 0.25, 0.1), probe.animationDuration)
  probe.setMixerTime(probeTime)
  object3d.getWorldPosition(probe.probeB)
  probe.setMixerTime(saved)
  return probe.probeA.distanceToSquared(probe.probeB) > 1e-10
}

export function resolveViewNode(
  item: WorkspaceImportedCamera,
  blenderRoot: ThreeObject,
  animatedNodeNames: Set<string>,
  probe: CameraMotionProbe,
): ThreeObject {
  if (cameraMovesOverTime(item.object3d, probe)) return item.object3d
  let node: ThreeObject | null = item.object3d.parent ?? null
  while (node && node !== blenderRoot) {
    if (node.name && animatedNodeNames.has(node.name) && cameraMovesOverTime(node, probe)) {
      return item.object3d
    }
    node = node.parent ?? null
  }
  return item.object3d
}

export function setImportedLightsVisible(root: ThreeObject | null | undefined, visible: boolean): void {
  root?.traverse?.((node: ThreeObject) => {
    if (node.isLight) node.visible = visible
  })
}

export function prepareImportedMaterials(root: ThreeObject | null | undefined, envMapIntensity: number): void {
  root?.traverse?.((node: ThreeObject) => {
    if (!node.isMesh) return
    const materials = Array.isArray(node.material) ? node.material : [node.material]
    for (const mat of materials) {
      if (!mat?.isMeshStandardMaterial) continue
      mat.envMapIntensity = envMapIntensity
      mat.needsUpdate = true
    }
  })
}
