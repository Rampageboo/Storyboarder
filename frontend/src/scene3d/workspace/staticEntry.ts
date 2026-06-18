/**
 * Static runtime entry — built to storyboard_tool/web/static/runtime/scene3d_workspace.js.
 * Loaded directly by Scene3DPanel.tsx via dynamic import.
 * Do not hand-edit the output; run `npm run build:workspace` to regenerate.
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

export {
  cacheImportedMaterialsOnRoot,
  restoreImportedMaterialsOnRoot,
  collectMeshObjectColorKeys,
} from './workspaceMaterials'

export {
  createWorkspaceAnimationMixer,
  buildGlbLoadNotifications,
  resolveInitialAnimationTime,
  resolveReloadAnimationTime,
  formatWorkspaceFileName,
  getWireframeRoots,
  filterBuiltinObjectSpecs,
} from './workspaceGlbLoad'

export {
  applyTransformFromInputs,
  syncTransformInputsFromMesh,
  WIREFRAME_MODE_LABELS,
} from './workspaceTransform'

export {
  buildOutlinerEntries,
  renderOutlinerDom,
  buildCameraSelectOptions,
  populateCameraSelectDom,
} from './workspaceOutliner'

export {
  applyWorkspaceModeUi,
  applyWorkspaceSceneModeFlags,
  shouldUseOrbitControls,
} from './workspaceMode'

export {
  canDeleteWorkspaceObject,
  shouldAttachTransformToSelection,
  getWorkspaceFocusTarget,
  resetBuiltinCameraView,
} from './workspaceSelection'

export {
  shouldIgnoreWorkspaceKeyboard,
  resolveBlenderKeyboardAction,
  resolveBuiltinKeyboardAction,
  applyWorkspaceKeyboardAction,
} from './workspaceInput'

export {
  createEmptyBlenderPlaybackState,
  stopWorkspaceMixer,
} from './workspaceClear'

export { Scene3DEditor } from './workspaceEditor'
