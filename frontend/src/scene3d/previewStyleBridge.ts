/**
 * Compatibility bridge for callers that use the loadPreviewStyle() async pattern.
 * Now backed by a static TypeScript import instead of a dynamic /static/ fetch.
 * Source of truth: frontend/src/scene3d/previewStyle.ts
 */

import * as previewStyleImpl from './previewStyle'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type ThreeModule = Record<string, any>

export type Scene3dWireframeMode = previewStyleImpl.Scene3dWireframeMode
export type WireframeOverlayResources = previewStyleImpl.WireframeOverlayResources
export type Scene3dPreviewSettings = previewStyleImpl.Scene3dPreviewSettings

export const SCENE3D_WORKSPACE_BACKGROUND = previewStyleImpl.SCENE3D_WORKSPACE_BACKGROUND

export type PreviewStyleModule = typeof previewStyleImpl

let previewStylePromise: Promise<PreviewStyleModule> | null = null

export function loadPreviewStyle(): Promise<PreviewStyleModule> {
  if (!previewStylePromise) {
    previewStylePromise = Promise.resolve(previewStyleImpl)
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
