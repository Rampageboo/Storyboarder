import type { PreviewStyleModule } from './previewStyleBridge'
import type { ThreeRuntime } from './threeRuntime'
import {
  applyObjectColorPreview,
  loadPreviewStyle,
} from './previewStyleBridge'
import { disposeGlbObject } from './dispose'
import { loadThreeRuntime } from './threeRuntime'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type ThreeObject = any

export { disposeGlbObject } from './dispose'

export type LoadedGlbScene = {
  runtime: ThreeRuntime
  previewStyle: PreviewStyleModule
  root: ThreeObject
  mixer: ThreeObject | null
  previewMaterials: ThreeObject[]
  setObjectColorPreview(enabled: boolean): void
  dispose(): void
}

export type LoadGlbSceneOptions = {
  objectColorPreview?: boolean
}

export async function loadGlbScene(
  url: string,
  runtime?: ThreeRuntime,
  previewStyle?: PreviewStyleModule,
  options: LoadGlbSceneOptions = {},
): Promise<LoadedGlbScene> {
  const resolvedRuntime = runtime ?? await loadThreeRuntime()
  const resolvedStyle = previewStyle ?? await loadPreviewStyle()
  const { THREE, GLTFLoader } = resolvedRuntime
  const gltf = await new GLTFLoader().loadAsync(url)
  const root = gltf.scene as ThreeObject
  const previewMaterials: ThreeObject[] = []
  const objectColorPreview = options.objectColorPreview !== false

  const applyObjectColors = (enabled: boolean) => {
    applyObjectColorPreview(resolvedStyle, resolvedRuntime.THREE, root, root, previewMaterials, enabled)
  }
  applyObjectColors(objectColorPreview)

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
    previewStyle: resolvedStyle,
    root,
    mixer,
    previewMaterials,
    setObjectColorPreview: applyObjectColors,
    dispose() {
      applyObjectColorPreview(resolvedStyle, resolvedRuntime.THREE, root, root, previewMaterials, false)
      disposeGlbObject(root)
    },
  }
}
