/**
 * Primitive mesh factory and preview-style helpers for the Scene3D workspace.
 */

import {
  applyObjectColorPreview,
  applyWireframeModeToRoots,
  clearWireframeOverlays,
  createWireframeResources,
  generateObjectColor,
  loadPreviewStyle,
  normalizeWireframeMode,
  type PreviewStyleModule,
  type Scene3dWireframeMode,
  type WireframeOverlayResources,
} from '../previewStyleBridge'

import {
  WORKSPACE_PRIMITIVE_TYPE_SET,
  colorFrom,
  createPrimitiveMesh,
  defaultAddObjectSpec,
  defaultBuiltinSceneData,
  eulerFrom,
  isWorkspacePrimitiveType,
  makeWorkspaceObjectId,
  vec3From,
} from './workspacePrimitives'

export {
  WORKSPACE_PRIMITIVE_TYPE_SET,
  colorFrom,
  createPrimitiveMesh,
  defaultAddObjectSpec,
  defaultBuiltinSceneData,
  eulerFrom,
  isWorkspacePrimitiveType,
  makeWorkspaceObjectId,
  vec3From,
}

/** Re-export shared preview style loader for workspace consumers. */
export { loadPreviewStyle as loadWorkspacePreviewStyle }

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type ThreeModule = Record<string, any>
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type ThreeObject = any

export function createWorkspaceWireframeResources(previewStyle: PreviewStyleModule): WireframeOverlayResources {
  return createWireframeResources(previewStyle)
}

export function applyWorkspaceObjectColorPreview(
  THREE: ThreeModule,
  previewStyle: PreviewStyleModule,
  root: unknown,
  rootRef: unknown,
  previewMaterials: Set<unknown>,
  enabled: boolean,
): void {
  applyObjectColorPreview(previewStyle, THREE, root, rootRef, previewMaterials, enabled)
}

export function applyWorkspaceWireframeMode(
  THREE: ThreeModule,
  previewStyle: PreviewStyleModule,
  roots: unknown[] | unknown,
  mode: Scene3dWireframeMode,
  resources: WireframeOverlayResources,
): void {
  applyWireframeModeToRoots(previewStyle, THREE, roots, mode, resources)
}

export function clearWorkspaceWireframeOverlays(
  previewStyle: PreviewStyleModule,
  roots: unknown[] | unknown,
  resources: WireframeOverlayResources,
): void {
  clearWireframeOverlays(previewStyle, roots, resources)
}

export function normalizeWorkspaceWireframeMode(
  previewStyle: PreviewStyleModule,
  mode: unknown,
): Scene3dWireframeMode {
  return normalizeWireframeMode(previewStyle, mode)
}

export function generateWorkspaceObjectColor(
  THREE: ThreeModule,
  previewStyle: PreviewStyleModule,
  seed: string,
): ThreeObject {
  return generateObjectColor(previewStyle, THREE, seed) as ThreeObject
}
