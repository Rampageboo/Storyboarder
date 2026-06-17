import { applyObjectColorPreviewMaterials } from './objectColorPreview'
import type { ThreeRuntime } from './threeRuntime'
import { loadThreeRuntime } from './threeRuntime'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type ThreeObject = any

function disposeMaterial(material: unknown) {
  const materials = Array.isArray(material) ? material : [material]
  for (const item of materials) {
    if (!item || typeof item !== 'object') continue
    const mat = item as Record<string, unknown>
    for (const key of Object.keys(mat)) {
      const value = mat[key]
      if (value && typeof value === 'object' && typeof (value as { dispose?: () => void }).dispose === 'function') {
        try { (value as { dispose: () => void }).dispose() } catch { /* best effort */ }
      }
    }
    try { (mat.dispose as (() => void) | undefined)?.() } catch { /* best effort */ }
  }
}

export function disposeGlbObject(root: ThreeObject | null | undefined) {
  root?.traverse?.((node: ThreeObject) => {
    try {
      node.geometry?.dispose?.()
      disposeMaterial(node.material)
    } catch {
      // best effort
    }
  })
}

export type LoadedGlbScene = {
  runtime: ThreeRuntime
  root: ThreeObject
  mixer: ThreeObject | null
  previewMaterials: ThreeObject[]
  dispose(): void
}

export async function loadGlbScene(url: string, runtime?: ThreeRuntime): Promise<LoadedGlbScene> {
  const resolvedRuntime = runtime ?? await loadThreeRuntime()
  const { THREE, GLTFLoader } = resolvedRuntime
  const gltf = await new GLTFLoader().loadAsync(url)
  const root = gltf.scene as ThreeObject
  const previewMaterials: ThreeObject[] = []
  applyObjectColorPreviewMaterials(resolvedRuntime.THREE, root, previewMaterials)

  let mixer: ThreeObject | null = null
  if (Array.isArray(gltf.animations) && gltf.animations.length > 0) {
    const AnimationMixer = THREE.AnimationMixer as new (root: ThreeObject) => ThreeObject
    mixer = new AnimationMixer(root)
    for (const clip of gltf.animations) {
      mixer.clipAction(clip).play()
    }
    mixer.setTime(0)
  }

  return {
    runtime: resolvedRuntime,
    root,
    mixer,
    previewMaterials,
    dispose() {
      disposeGlbObject(root)
      for (const material of previewMaterials) disposeMaterial(material)
      previewMaterials.length = 0
    },
  }
}
