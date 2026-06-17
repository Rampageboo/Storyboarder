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
  defaultAddObjectSpec,
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
  applyFollowCameraToEditor,
} from './workspaceCamera'

export { initWorkspaceEditorThree } from './workspaceBridge'

export {
  exportBuiltinSceneData,
  exportBlenderSceneData,
  exportBuiltinSceneObjects,
  formatWorkspaceTime,
  normalizeWorkspaceSceneMeta,
} from './workspaceState'

export { disposeObject3DRoot, disposePrimitiveMesh } from './workspaceDispose'

export {
  countImportedLights,
  calibrateImportedLights,
  isNodeInSceneGraph,
  collectImportedCameras,
  diagnoseMissingCameras,
  scoreCameraForAnimation,
  pickBestCameraId,
  frameImportedScene,
  cameraMovesOverTime,
  resolveViewNode,
  setImportedLightsVisible,
  prepareImportedMaterials,
} from './workspaceGlb'

export {
  normalizeProgramLightingMode,
  shouldUseProgramIbl,
  shouldUseProgramFill,
  shouldUseProgramWeakFill,
  getEnvMapIntensity,
  programLightingReason,
  programLightingModeLabel,
  buildLightStatusText,
  applyWorkspaceProgramLighting,
  createBlenderEnvMap,
} from './workspaceLighting'

export {
  trackNodeName,
  collectAnimatedNodeNames,
  computeClipDuration,
  selectAnimationClips,
  clampAnimationTime,
  syncMixerActionsTime,
  buildTimelineUiState,
  buildAnimationHint,
  advancePlaybackTime,
} from './workspaceAnimation'
