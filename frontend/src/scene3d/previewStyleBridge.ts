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

export function createWireframeResources(previewStyle: PreviewStyleModule): WireframeOverlayResources {
  return previewStyle.createWireframeResources()
}

export function applyObjectColorPreview(
  previewStyle: PreviewStyleModule,
  THREE: ThreeModule,
  root: unknown,
  rootRef: unknown,
  previewMaterials: unknown[] | Set<unknown>,
  enabled: boolean,
): void {
  previewStyle.applyObjectColorPreview(THREE, root, rootRef, previewMaterials, enabled)
}

export function applyWireframeModeToRoots(
  previewStyle: PreviewStyleModule,
  THREE: ThreeModule,
  roots: unknown[] | unknown,
  mode: Scene3dWireframeMode,
  resources: WireframeOverlayResources,
): void {
  previewStyle.applyWireframeModeToRoots(THREE, roots, mode, resources)
}

export function clearWireframeOverlays(
  previewStyle: PreviewStyleModule,
  roots: unknown[] | unknown,
  resources: WireframeOverlayResources,
): void {
  previewStyle.clearWireframeOverlays(roots, resources)
}

export function normalizeWireframeMode(previewStyle: PreviewStyleModule, mode: unknown): Scene3dWireframeMode {
  return previewStyle.normalizeWireframeMode(mode)
}

export function generateObjectColor(previewStyle: PreviewStyleModule, THREE: ThreeModule, seed: string): unknown {
  return previewStyle.generateObjectColor(THREE, seed)
}

export function objectColorKey(previewStyle: PreviewStyleModule, mesh: unknown, root: unknown): string {
  return previewStyle.objectColorKey(mesh, root)
}

export function disposePreviewMaterials(
  previewStyle: PreviewStyleModule,
  previewMaterials: unknown[] | Set<unknown>,
): void {
  previewStyle.disposePreviewMaterials(previewMaterials)
}
