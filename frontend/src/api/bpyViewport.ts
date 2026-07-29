import { requestJson } from './client'

export type BpyViewportStatus = {
  running: boolean
  blend_path?: string
  engine: 'bpy'
  owner?: 'built-in' | 'external' | 'none'
  external_blender_owned?: boolean
  external_blender_connected?: boolean
  external_blender_pending?: boolean
  external_blender_blend_path?: string
  external_blender_scene3d_id?: string
  external_blender_camera?: string
  external_blender_dirty?: boolean
  preview_path?: string
  preview_revision?: number
  preview_exporting?: boolean
  preview_error?: string
}

export type BpyCameraPathRequest = {
  points: number[][]
  width: number
  height: number
  yaw: number
  pitch: number
  distance: number
  target: [number, number, number]
  duration_frames: number
}

export type BpyCameraPathResult = {
  ok: boolean
  path: string
  camera: string
  target: string
  blend_path: string
  point_count: number
}

export function startBpyViewport(): Promise<BpyViewportStatus> {
  return requestJson<BpyViewportStatus>('/api/project/bpy-viewport/start', {
    method: 'POST',
  })
}

export function getBpyViewportStatus(): Promise<BpyViewportStatus> {
  return requestJson<BpyViewportStatus>('/api/project/bpy-viewport/status')
}

export function stopBpyViewport(): Promise<BpyViewportStatus> {
  return requestJson<BpyViewportStatus>('/api/project/bpy-viewport/stop', {
    method: 'POST',
  })
}

export function createBpyCameraPath(body: BpyCameraPathRequest): Promise<BpyCameraPathResult> {
  return requestJson<BpyCameraPathResult>('/api/project/bpy-viewport/camera-path', {
    method: 'POST',
    body,
  })
}

export function saveBpyScene(): Promise<{ ok: boolean; blend_path: string }> {
  return requestJson<{ ok: boolean; blend_path: string }>('/api/project/bpy-viewport/save', {
    method: 'POST',
  })
}
