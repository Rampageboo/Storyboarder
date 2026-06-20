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
