import { requestJson } from './client'
import type { ProjectPayload, ReferenceLink, Scene2D, Scene2DCreateRequest, Scene2DUpdateRequest } from '../types'

export interface Scene2DListResponse {
  scenes: Scene2D[]
}

export interface Scene2DSceneResponse extends Scene2DListResponse {
  scene: Scene2D
}

export interface Scene2DOpenResponse {
  path: string
  relative_path: string
  scene: Scene2D
}

export interface Scene2DRefreshResponse {
  scene: Scene2D
  preview_exists: boolean
  message: string
}

export interface Scene2DReferenceResponse {
  reference: ReferenceLink
  scene: Scene2D
  project: ProjectPayload
}

export function listScene2D(): Promise<Scene2DListResponse> {
  return requestJson<Scene2DListResponse>('/api/project/scenes2d')
}

export function createScene2D(body: Scene2DCreateRequest = {}): Promise<Scene2DSceneResponse> {
  return requestJson<Scene2DSceneResponse>('/api/project/scenes2d', {
    method: 'POST',
    body,
  })
}

export function updateScene2D(sceneId: string, body: Scene2DUpdateRequest): Promise<Scene2DSceneResponse> {
  return requestJson<Scene2DSceneResponse>(`/api/project/scenes2d/${encodeURIComponent(sceneId)}`, {
    method: 'PATCH',
    body,
  })
}

export function deleteScene2D(sceneId: string): Promise<Scene2DListResponse> {
  return requestJson<Scene2DListResponse>(`/api/project/scenes2d/${encodeURIComponent(sceneId)}`, {
    method: 'DELETE',
  })
}

export function openScene2D(sceneId: string): Promise<Scene2DOpenResponse> {
  return requestJson<Scene2DOpenResponse>(`/api/project/scenes2d/${encodeURIComponent(sceneId)}/open`, {
    method: 'POST',
  })
}

export function refreshScene2DPreview(sceneId: string): Promise<Scene2DRefreshResponse> {
  return requestJson<Scene2DRefreshResponse>(`/api/project/scenes2d/${encodeURIComponent(sceneId)}/refresh-preview`, {
    method: 'POST',
  })
}

export function addScene2DToReferences(sceneId: string): Promise<Scene2DReferenceResponse> {
  return requestJson<Scene2DReferenceResponse>(`/api/project/scenes2d/${encodeURIComponent(sceneId)}/add-to-references`, {
    method: 'POST',
  })
}

export function scene2DPreviewUrl(scene: Scene2D): string {
  return `/api/project/scenes2d/${encodeURIComponent(scene.id)}/preview?t=${encodeURIComponent(scene.updated_at || '')}`
}
