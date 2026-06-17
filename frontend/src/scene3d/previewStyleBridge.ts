/**
 * Loads the shared scene3d_preview_style.js module used by both the Scene3D workspace
 * (scene3d.js) and the React reference GLB renderer — one implementation, identical output.
 */

type ThreeModule = Record<string, any>

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

export type PreviewStyleModule = {
  SCENE3D_WORKSPACE_BACKGROUND: number
  normalizeWireframeMode: (mode: unknown) => Scene3dWireframeMode
  resolvePreviewSettings: (scene3dMeta?: Record<string, unknown>) => Scene3dPreviewSettings
  createWireframeResources: () => WireframeOverlayResources
  applyObjectColorPreview: (
    THREE: ThreeModule,
    root: unknown,
    rootRef: unknown,
    previewMaterials: unknown[] | Set<unknown>,
    enabled: boolean,
  ) => void
  applyWireframeModeToRoots: (
    THREE: ThreeModule,
    roots: unknown[] | unknown,
    mode: Scene3dWireframeMode,
    resources: WireframeOverlayResources,
  ) => void
  clearWireframeOverlays: (roots: unknown[] | unknown, resources: WireframeOverlayResources) => void
  generateObjectColor: (THREE: ThreeModule, seed: string) => unknown
  generateObjectColorHex: (seed: string) => number
  objectColorKey: (mesh: unknown, root: unknown) => string
  disposePreviewMaterials: (previewMaterials: unknown[] | Set<unknown>) => void
}

let previewStylePromise: Promise<PreviewStyleModule> | null = null

export function loadPreviewStyle(): Promise<PreviewStyleModule> {
  if (!previewStylePromise) {
    const url = '/static/runtime/scene3d_preview_style.js'
    previewStylePromise = import(/* @vite-ignore */ url) as Promise<PreviewStyleModule>
  }
  return previewStylePromise
}
