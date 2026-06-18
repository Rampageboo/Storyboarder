/** Types for the Scene3D workspace runtime (mirrors scene3d.js metadata shapes). */

import type { Scene3dWireframeMode } from '../previewStyle'

export const WORKSPACE_PRIMITIVE_TYPES = ['cube', 'sphere', 'plane', 'cylinder', 'cone'] as const

export type WorkspacePrimitiveType = (typeof WORKSPACE_PRIMITIVE_TYPES)[number]

export type WorkspaceVec3 = [number, number, number]

export interface WorkspaceObjectSpec {
  id: string
  name: string
  type: WorkspacePrimitiveType | string
  position?: WorkspaceVec3
  rotation?: WorkspaceVec3
  scale?: WorkspaceVec3
  color?: string
}

export type WorkspaceSceneSource = 'builtin' | 'blender'

export interface WorkspaceSceneData {
  source: WorkspaceSceneSource
  objects: WorkspaceObjectSpec[]
  wireframe_mode?: Scene3dWireframeMode | string
  object_color_preview?: boolean
}

export type WorkspaceTransformMode = 'translate' | 'rotate' | 'scale'

export interface WorkspaceCaptureOptions {
  width?: number
  height?: number
  /** Defaults to `image/png`. */
  mimeType?: string
  /** When true, throw if the canvas appears blank or nearly uniform. */
  rejectBlank?: boolean
}

export interface WorkspaceCaptureResult {
  dataUrl: string
  width: number
  height: number
}

export type WorkspacePreviewMaterials = Set<unknown> | unknown[]
