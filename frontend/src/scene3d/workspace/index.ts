/**
 * Scene3D workspace runtime — Phase 1 extraction foundation.
 *
 * The React panel still loads `/static/runtime/scene3d.js`; these modules are the
 * typed target for incremental migration.
 */

export type {
  WorkspaceCaptureOptions,
  WorkspaceCaptureResult,
  WorkspaceObjectSpec,
  WorkspacePrimitiveType,
  WorkspaceSceneData,
  WorkspaceSceneSource,
  WorkspaceTransformMode,
  WorkspaceVec3,
  WorkspacePreviewMaterials,
} from './workspaceTypes'

export {
  WORKSPACE_PRIMITIVE_TYPES,
} from './workspaceTypes'

export {
  loadWorkspaceThreeRuntime,
  type WorkspaceThreeRuntime,
} from './workspaceThreeRuntime'

export {
  WORKSPACE_PRIMITIVE_TYPE_SET,
  applyWorkspaceObjectColorPreview,
  applyWorkspaceWireframeMode,
  clearWorkspaceWireframeOverlays,
  createPrimitiveMesh,
  createWorkspaceWireframeResources,
  defaultAddObjectSpec,
  defaultBuiltinSceneData,
  eulerFrom,
  colorFrom,
  generateWorkspaceObjectColor,
  isWorkspacePrimitiveType,
  loadWorkspacePreviewStyle,
  makeWorkspaceObjectId,
  normalizeWorkspaceWireframeMode,
  vec3From,
} from './workspaceObjects'

export {
  captureCanvasPng,
  isBlankCanvas,
  type CaptureCanvasPngOptions,
} from './workspaceCapture'

export {
  disposeGeometry,
  disposeMaterial,
  disposeObject3DNode,
  disposeObject3DRoot,
  disposePreviewMaterials,
  disposePrimitiveMesh,
  disposeWorkspaceWireframe,
} from './workspaceDispose'
