/** Shared Scene3D view / capture types for the reference preview pipeline. */

export type Scene3dViewMode = 'scene_camera' | 'free_view'

export type Scene3dViewSource = 'shot' | 'workspace' | 'scene_camera' | 'generic'

export interface Scene3dReferenceView {
  mode: Scene3dViewMode
  /** Name of the GLB scene camera (only meaningful when mode === 'scene_camera'). */
  camera_name?: string
  /** Animation time the view was captured at. */
  time?: number
  position?: [number, number, number]
  target?: [number, number, number]
  rotation?: [number, number, number]
  fov?: number
  source: Scene3dViewSource
}

export interface Scene3dCaptureRequest {
  time?: number
  view?: Scene3dReferenceView | null
  width?: number
  height?: number
}

export interface Scene3dCaptureResult {
  dataUrl: string
  animationTime: number
}

export interface RefSegmentModelCapture {
  shot_id: string
  data_url: string
  animation_time: number
}

export type { Scene3dWireframeMode } from './previewStyle'
export { SCENE3D_WORKSPACE_BACKGROUND } from './previewStyle'
