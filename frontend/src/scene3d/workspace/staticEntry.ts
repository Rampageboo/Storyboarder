/**
 * Static runtime entry — built to storyboard_tool/web/static/runtime/scene3d_workspace.js
 * and imported by scene3d.js during incremental TS migration.
 */

export {
  makeWorkspaceObjectId as makeId,
  vec3From,
  eulerFrom,
  colorFrom,
  defaultBuiltinSceneData as defaultSceneData,
  createPrimitiveMesh as createMeshFromSpec,
  WORKSPACE_PRIMITIVE_TYPE_SET as PRIMITIVE_TYPES,
} from './workspacePrimitives'

export { captureRendererPng } from './workspaceCapture'

export {
  exportViewState,
  getCameraStateFromEditor,
  fovToFocalLength,
  getProjectCanvasSize,
  getProjectCanvasAspect,
  loadShotCameraIntoEditor,
} from './workspaceCamera'

export {
  exportBuiltinSceneData,
  exportBlenderSceneData,
  exportBuiltinSceneObjects,
  formatWorkspaceTime,
  normalizeWorkspaceSceneMeta,
} from './workspaceState'

export { disposeObject3DRoot, disposePrimitiveMesh } from './workspaceDispose'
