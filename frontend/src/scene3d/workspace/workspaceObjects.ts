/**
 * Primitive mesh factory and preview-style helpers for the Scene3D workspace.
 */

import {
  loadPreviewStyle,
  type PreviewStyleModule,
  type Scene3dWireframeMode,
  type WireframeOverlayResources,
} from '../previewStyleBridge'

import {
  WORKSPACE_PRIMITIVE_TYPE_SET,
  colorFrom,
  createPrimitiveMesh,
  defaultBuiltinSceneData,
  eulerFrom,
  isWorkspacePrimitiveType,
  makeWorkspaceObjectId,
  vec3From,
} from './workspacePrimitives'

import type { WorkspaceObjectSpec, WorkspacePrimitiveType } from './workspaceTypes'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type ThreeModule = Record<string, any>
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type ThreeObject = any

export {
  WORKSPACE_PRIMITIVE_TYPE_SET,
  colorFrom,
  createPrimitiveMesh,
  defaultBuiltinSceneData,
  eulerFrom,
  isWorkspacePrimitiveType,
  makeWorkspaceObjectId,
  vec3From,
}

export function defaultAddObjectSpec(
  type: WorkspacePrimitiveType,
  objectCount: number,
  colorHex: string,
): WorkspaceObjectSpec {
  const labels: Record<WorkspacePrimitiveType, string> = {
    cube: 'Cube',
    sphere: 'Sphere',
    plane: 'Plane',
    cylinder: 'Cylinder',
    cone: 'Cone',
  }
  const name = `${labels[type] || 'Object'} ${objectCount + 1}`
  return {
    id: makeWorkspaceObjectId(),
    name,
    type,
    position: [0, type === 'plane' ? 0 : 0.5, 0],
    rotation: type === 'plane' ? [-Math.PI / 2, 0, 0] : [0, 0, 0],
    scale: type === 'plane' ? [4, 4, 1] : [1, 1, 1],
    color: colorHex,
  }
}

/** Re-export shared preview style loader for workspace consumers. */
export { loadPreviewStyle as loadWorkspacePreviewStyle }

export function createWorkspaceWireframeResources(previewStyle: PreviewStyleModule): WireframeOverlayResources {
  return previewStyle.createWireframeResources()
}

export function applyWorkspaceObjectColorPreview(
  THREE: ThreeModule,
  previewStyle: PreviewStyleModule,
  root: unknown,
  rootRef: unknown,
  previewMaterials: Set<unknown>,
  enabled: boolean,
): void {
  previewStyle.applyObjectColorPreview(THREE, root, rootRef, previewMaterials, enabled)
}

export function applyWorkspaceWireframeMode(
  THREE: ThreeModule,
  previewStyle: PreviewStyleModule,
  roots: unknown[] | unknown,
  mode: Scene3dWireframeMode,
  resources: WireframeOverlayResources,
): void {
  previewStyle.applyWireframeModeToRoots(THREE, roots, mode, resources)
}

export function clearWorkspaceWireframeOverlays(
  previewStyle: PreviewStyleModule,
  roots: unknown[] | unknown,
  resources: WireframeOverlayResources,
): void {
  previewStyle.clearWireframeOverlays(roots, resources)
}

export function normalizeWorkspaceWireframeMode(
  previewStyle: PreviewStyleModule,
  mode: unknown,
): Scene3dWireframeMode {
  return previewStyle.normalizeWireframeMode(mode)
}

export function generateWorkspaceObjectColor(
  THREE: ThreeModule,
  previewStyle: PreviewStyleModule,
  seed: string,
): ThreeObject {
  return previewStyle.generateObjectColor(THREE, seed) as ThreeObject
}
