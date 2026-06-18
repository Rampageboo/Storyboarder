/**
 * Shared GLB preview styling for Scene3D workspace and React reference preview.
 * Single source of truth — keep workspace and reference panel visually identical.
 * Replaces the former hand-written storyboard_tool/web/static/runtime/scene3d_preview_style.js.
 */

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type ThreeModule = Record<string, any>
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type ThreeMesh = any
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type ThreeMaterial = any

export type Scene3dWireframeMode = 'off' | 'on' | 'strong'

export type WireframeOverlayResources = {
  geometries: Set<unknown>
  materials: Set<unknown>
}

export type Scene3dPreviewSettings = {
  wireframeMode: Scene3dWireframeMode
  objectColorPreview: boolean
  sceneBackground: number
}

export const SCENE3D_WORKSPACE_BACKGROUND = 0x1a1d21

export const VIEWPORT_OBJECT_PALETTE: number[] = [
  0xc87a6e, 0x6eb87a, 0x6e8ec8, 0xc8b06e, 0xb06ec8, 0x6ec8b8,
  0xc86e8a, 0x8ac86e, 0x6e6ec8, 0xc8946e, 0x6eb0c8, 0xa0c86e,
  0xc87878, 0x78c878, 0x7878c8, 0xc8c878,
]

export function hashString(value: string): number {
  let hash = 0
  for (let i = 0; i < value.length; i += 1) {
    hash = (hash * 31 + value.charCodeAt(i)) | 0
  }
  return Math.abs(hash)
}

export function normalizeWireframeMode(mode: unknown): Scene3dWireframeMode {
  return mode === 'on' || mode === 'strong' ? mode : 'off'
}

export function resolvePreviewSettings(scene3dMeta: Record<string, unknown> = {}): Scene3dPreviewSettings {
  return {
    wireframeMode: normalizeWireframeMode(scene3dMeta.wireframe_mode),
    objectColorPreview: scene3dMeta.object_color_preview !== false,
    sceneBackground: SCENE3D_WORKSPACE_BACKGROUND,
  }
}

export function objectColorKey(mesh: ThreeMesh, root: ThreeMesh): string {
  let node: ThreeMesh = mesh
  while (node.parent && node.parent !== root) {
    if (node.name) return node.name as string
    node = node.parent
  }
  return (mesh.name || mesh.uuid) as string
}

export function generateObjectColorHex(seed: string): number {
  const index = hashString(String(seed)) % VIEWPORT_OBJECT_PALETTE.length
  return VIEWPORT_OBJECT_PALETTE[index]
}

export function generateObjectColor(THREE: ThreeModule, seed: string): unknown {
  return new THREE.Color(generateObjectColorHex(seed))
}

function trackMaterial(previewMaterials: ThreeMaterial[] | Set<ThreeMaterial>, material: ThreeMaterial): void {
  if (previewMaterials instanceof Set) previewMaterials.add(material)
  else previewMaterials.push(material)
}

export function cacheOriginalMaterials(root: ThreeMesh | null | undefined): void {
  root?.traverse((node: ThreeMesh) => {
    if (!node.isMesh || node.userData.scene3dOriginalMaterial !== undefined) return
    node.userData.scene3dOriginalMaterial = node.material
  })
}

export function restoreOriginalMaterials(root: ThreeMesh | null | undefined): void {
  root?.traverse((node: ThreeMesh) => {
    if (!node.isMesh || node.userData.scene3dOriginalMaterial === undefined) return
    node.material = node.userData.scene3dOriginalMaterial
    delete node.userData.scene3dOriginalMaterial
  })
}

export function disposePreviewMaterials(previewMaterials: ThreeMaterial[] | Set<ThreeMaterial>): void {
  const items = previewMaterials instanceof Set ? [...previewMaterials] : previewMaterials
  for (const material of items) {
    try {
      (material as { dispose?: () => void }).dispose?.()
    } catch {
      // best effort
    }
  }
  if (previewMaterials instanceof Set) previewMaterials.clear()
  else (previewMaterials as ThreeMaterial[]).length = 0
}

export function applyObjectColorPreview(
  THREE: ThreeModule,
  root: ThreeMesh | null | undefined,
  rootRef: ThreeMesh | null | undefined,
  previewMaterials: ThreeMaterial[] | Set<ThreeMaterial>,
  enabled: boolean,
): void {
  if (!root) return
  if (!enabled) {
    restoreOriginalMaterials(root)
    disposePreviewMaterials(previewMaterials)
    return
  }

  cacheOriginalMaterials(root)
  disposePreviewMaterials(previewMaterials)
  const colorByKey = new Map<string, unknown>()
  const keys = new Set<string>()
  root.traverse((node: ThreeMesh) => {
    if (node.isMesh) keys.add(objectColorKey(node, rootRef ?? root))
  })
  for (const key of [...keys].sort()) {
    colorByKey.set(key, generateObjectColor(THREE, key))
  }
  root.traverse((node: ThreeMesh) => {
    if (!node.isMesh) return
    const key = objectColorKey(node, rootRef ?? root)
    const previewMat = new THREE.MeshBasicMaterial({
      color: colorByKey.get(key) || generateObjectColor(THREE, key),
    })
    trackMaterial(previewMaterials, previewMat)
    node.material = previewMat
    node.frustumCulled = false
  })
}

export function createWireframeResources(): WireframeOverlayResources {
  return { geometries: new Set(), materials: new Set() }
}

function restoreWireframeFillOpacity(root: ThreeMesh | null | undefined): void {
  root?.traverse((node: ThreeMesh) => {
    if (!node.isMesh || node.userData.scene3dWireframeFillOpacity == null) return
    const materials: ThreeMaterial[] = Array.isArray(node.material) ? node.material : [node.material]
    for (const mat of materials) {
      if (!mat) continue
      mat.opacity = node.userData.scene3dWireframeFillOpacity
      mat.transparent = node.userData.scene3dWireframeFillTransparent
      mat.needsUpdate = true
    }
    delete node.userData.scene3dWireframeFillOpacity
    delete node.userData.scene3dWireframeFillTransparent
  })
}

export function clearWireframeOverlays(
  roots: ThreeMesh[] | ThreeMesh | null | undefined,
  resources: WireframeOverlayResources,
): void {
  const rootList: (ThreeMesh | null | undefined)[] = Array.isArray(roots) ? roots : [roots]
  for (const root of rootList) {
    if (!root) continue
    restoreWireframeFillOpacity(root)
    root.traverse((node: ThreeMesh) => {
      const line = node.userData?.scene3dWireframeLine
      if (!line) return
      node.remove(line)
      delete node.userData.scene3dWireframeLine
    })
  }
  for (const geometry of resources.geometries) {
    try {
      (geometry as { dispose?: () => void }).dispose?.()
    } catch {
      // best effort
    }
  }
  for (const material of resources.materials) {
    try {
      (material as { dispose?: () => void }).dispose?.()
    } catch {
      // best effort
    }
  }
  resources.geometries.clear()
  resources.materials.clear()
}

export function applyWireframeModeToRoots(
  THREE: ThreeModule,
  roots: ThreeMesh[] | ThreeMesh | null | undefined,
  mode: Scene3dWireframeMode,
  resources: WireframeOverlayResources,
): void {
  const rootList: (ThreeMesh | null | undefined)[] = Array.isArray(roots) ? roots : [roots]
  const wireframeMode = normalizeWireframeMode(mode)
  clearWireframeOverlays(rootList, resources)
  if (wireframeMode === 'off') return

  const strong = wireframeMode === 'strong'
  const threshold = strong ? 1 : 35
  const lineMaterial = new THREE.LineBasicMaterial({
    color: strong ? 0xffffff : 0x151515,
    transparent: !strong,
    opacity: strong ? 1 : 0.72,
    depthTest: true,
    depthWrite: false,
  })
  resources.materials.add(lineMaterial)

  for (const root of rootList) {
    if (!root) continue
    root.traverse((node: ThreeMesh) => {
      if (!node.isMesh || !node.geometry || node.userData.scene3dWireframeLine) return
      const edges = new THREE.EdgesGeometry(node.geometry, threshold)
      const lines = new THREE.LineSegments(edges, lineMaterial)
      lines.renderOrder = strong ? 2 : 1
      lines.frustumCulled = false
      node.add(lines)
      node.userData.scene3dWireframeLine = lines
      resources.geometries.add(edges)

      if (strong && node.material) {
        const materials: ThreeMaterial[] = Array.isArray(node.material) ? node.material : [node.material]
        for (const mat of materials) {
          if (!mat || node.userData.scene3dWireframeFillOpacity != null) continue
          node.userData.scene3dWireframeFillOpacity = mat.opacity ?? 1
          node.userData.scene3dWireframeFillTransparent = Boolean(mat.transparent)
          mat.transparent = true
          mat.opacity = Math.min(mat.opacity ?? 1, 0.42)
          mat.needsUpdate = true
        }
      }
    })
  }
}
