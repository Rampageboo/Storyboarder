/**
 * Scene3D workspace runtime — incremental migration from scene3d.js.
 *
 * React still loads `/static/runtime/scene3d.js`; shared helpers are built to
 * `/static/runtime/scene3d_workspace.js`.
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
  WORKSPACE_BACKGROUND,
  DEFAULT_CAMERA_FOV,
  DEFAULT_CAMERA_POSITION,
  DEFAULT_ORBIT_TARGET,
  createWorkspacePmremGenerator,
  createWorkspaceRenderer,
  createWorkspaceSceneGraph,
  type WorkspaceSceneGraph,
} from './workspaceScene'

export {
  createWorkspaceOrbitControls,
  createWorkspaceTransformControls,
  type WorkspaceOrbitControls,
  type WorkspaceTransformControls,
} from './workspaceControls'

export {
  exportViewState,
  fovToFocalLength,
  getCameraStateFromEditor,
  getProjectCanvasAspect,
  getProjectCanvasSize,
  loadShotCameraIntoEditor,
  applyFollowCameraToEditor,
  type WorkspaceCameraState,
  type WorkspaceFollowCameraScratch,
  type WorkspaceImportedCameraObject,
  type WorkspaceImportedCameraRef,
} from './workspaceCamera'

export {
  exportBlenderSceneData,
  exportBuiltinSceneData,
  exportBuiltinSceneObjects,
  formatWorkspaceTime,
  meshToObjectSpec,
  normalizeWorkspaceSceneMeta,
  type BlenderSceneExportState,
} from './workspaceState'

export {
  initWorkspaceEditorThree,
  type InitWorkspaceEditorThreeOptions,
  type WorkspaceEditorThreeBoot,
} from './workspaceBridge'

export {
  applyWorkspaceObjectColorPreview,
  applyWorkspaceWireframeMode,
  clearWorkspaceWireframeOverlays,
  createWorkspaceWireframeResources,
  generateWorkspaceObjectColor,
  isWorkspacePrimitiveType,
  loadWorkspacePreviewStyle,
  normalizeWorkspaceWireframeMode,
} from './workspaceObjects'

export {
  WORKSPACE_PRIMITIVE_TYPE_SET,
  colorFrom,
  createPrimitiveMesh,
  defaultAddObjectSpec,
  defaultBuiltinSceneData,
  eulerFrom,
  makeWorkspaceObjectId,
  vec3From,
} from './workspacePrimitives'

export {
  captureCanvasPng,
  captureRendererPng,
  isBlankCanvas,
  type CaptureCanvasPngOptions,
  type CaptureRendererPngOptions,
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

export {
  loadScene3DEditorClass,
  type Scene3DEditorConstructor,
  type Scene3DEditorInstance,
} from './loadScene3DEditor'

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
  type WorkspaceTransformInputs,
} from './workspaceTransform'
