/**
 * Primitive mesh factory and preview-style helpers for the Scene3D workspace.
 */

import {
  applyObjectColorPreview,
  applyWireframeModeToRoots,
  clearWireframeOverlays,
  createWireframeResources,
  generateObjectColor,
  normalizeWireframeMode,
  type Scene3dWireframeMode,
  type WireframeOverlayResources,
} from '../previewStyle'

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

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type ThreeModule = Record<string, any>
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type ThreeObject = any

export function createWorkspaceWireframeResources(): WireframeOverlayResources {
  return createWireframeResources()
}

export function applyWorkspaceObjectColorPreview(
  THREE: ThreeModule,
  root: unknown,
  rootRef: unknown,
  previewMaterials: Set<unknown>,
  enabled: boolean,
): void {
  applyObjectColorPreview(THREE, root, rootRef, previewMaterials, enabled)
}

export function applyWorkspaceWireframeMode(
  THREE: ThreeModule,
  roots: unknown[] | unknown,
  mode: Scene3dWireframeMode,
  resources: WireframeOverlayResources,
): void {
  applyWireframeModeToRoots(THREE, roots, mode, resources)
}

export function clearWorkspaceWireframeOverlays(
  roots: unknown[] | unknown,
  resources: WireframeOverlayResources,
): void {
  clearWireframeOverlays(roots, resources)
}

export function normalizeWorkspaceWireframeMode(
  mode: unknown,
): Scene3dWireframeMode {
  return normalizeWireframeMode(mode)
}

export function generateWorkspaceObjectColor(
  THREE: ThreeModule,
  seed: string,
): ThreeObject {
  return generateObjectColor(THREE, seed) as ThreeObject
}
