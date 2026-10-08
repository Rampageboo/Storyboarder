import { requestJson } from './client'
import type { Scene3DCreateRequest, Scene3DListResponse, Scene3DSceneResponse, Scene3DUpdateRequest } from '../types'

export function listScene3D(): Promise<Scene3DListResponse> {
  return requestJson<Scene3DListResponse>('/api/project/scenes3d')
}

export function createScene3D(body: Scene3DCreateRequest = {}): Promise<Scene3DSceneResponse> {
  return requestJson<Scene3DSceneResponse>('/api/project/scenes3d', {
    method: 'POST',
    body,
  })
}

export function updateScene3D(scene3dId: string, body: Scene3DUpdateRequest): Promise<Scene3DSceneResponse> {
  return requestJson<Scene3DSceneResponse>(`/api/project/scenes3d/${encodeURIComponent(scene3dId)}`, {
    method: 'PATCH',
    body,
  })
}

export function deleteScene3D(scene3dId: string): Promise<Scene3DListResponse> {
  return requestJson<Scene3DListResponse>(`/api/project/scenes3d/${encodeURIComponent(scene3dId)}`, {
    method: 'DELETE',
  })
}

export function setActiveScene3D(scene3dId: string): Promise<Scene3DSceneResponse> {
  return requestJson<Scene3DSceneResponse>(`/api/project/scenes3d/${encodeURIComponent(scene3dId)}/set-active`, {
    method: 'POST',
  })
}

export function importScene3DToScene(scene3dId: string, file: File): Promise<Scene3DSceneResponse> {
  const form = new FormData()
  form.append('file', file)
  return requestJson<Scene3DSceneResponse>(`/api/project/scenes3d/${encodeURIComponent(scene3dId)}/import`, {
    method: 'POST',
    body: form,
  })
}

export type Scene3DSessionState = 'offline' | 'launching' | 'connected' | 'closed' | 'conflict'

/** External Blender session snapshot; GET is read-only, the backend syncs on its own. */
export type Scene3DSession = {
  state: Scene3DSessionState
  owner: 'external' | 'none'
  external_blender_owned: boolean
  external_blender_connected: boolean
  external_blender_pending: boolean
  external_blender_process_running: boolean
  external_blender_scene3d_id: string
  external_blender_camera: string
  external_blender_dirty: boolean
  sync_error: string
  last_synced_at: number
  preview_path: string
  preview_revision: number
  manifest_revision: number
  preview_exporting: boolean
  preview_error: string
}

export type Scene3DCamera = {
  name: string
  is_active: boolean
  lens_mm: number
  sensor_width_mm: number
  projection: string
  location: [number, number, number]
  rotation_deg: [number, number, number]
  animated: boolean
}

export type Scene3DManifest = {
  scene3d_id: string
  revision: number
  fps: number | null
  frame_start: number | null
  frame_end: number | null
  active_camera: string
  cameras: Scene3DCamera[]
  object_count: number
  exported_at: number | null
}

export function getScene3DSession(): Promise<Scene3DSession> {
  return requestJson<Scene3DSession>('/api/project/scene3d/session')
}

export function resolveScene3DSession(action: 'use_blender' | 'discard'): Promise<Scene3DSession> {
  return requestJson<Scene3DSession>('/api/project/scene3d/session/resolve', {
    method: 'POST',
    body: { action },
  })
}

export function getScene3DManifest(scene3dId: string): Promise<Scene3DManifest> {
  return requestJson<Scene3DManifest>(`/api/project/scenes3d/${encodeURIComponent(scene3dId)}/manifest`)
}
