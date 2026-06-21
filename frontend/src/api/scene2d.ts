import { requestJson } from './client'
import type {
  ProjectPayload,
  ReferenceLink,
  Scene2D,
  Scene2DCreateRequest,
  Scene2DPerspective,
  Scene2DPerspectiveCreateRequest,
  Scene2DPerspectiveMoveRequest,
  Scene2DPerspectiveReorderRequest,
  Scene2DPerspectiveUpdateRequest,
  Scene2DUpdateRequest,
} from '../types'

export interface Scene2DListResponse {
  scenes: Scene2D[]
}

export interface Scene2DSceneResponse extends Scene2DListResponse {
  scene: Scene2D
}

export interface Scene2DPerspectiveListResponse {
  scene: Scene2D
  perspectives: Scene2DPerspective[]
}

export interface Scene2DPerspectiveResponse extends Scene2DListResponse {
  scene: Scene2D
  perspective: Scene2DPerspective
}

export interface Scene2DPerspectiveMoveResponse extends Scene2DListResponse {
  source_scene: Scene2D
  target_scene: Scene2D
  scene: Scene2D
  perspective: Scene2DPerspective
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

export function listScene2DPerspectives(sceneId: string): Promise<Scene2DPerspectiveListResponse> {
  return requestJson<Scene2DPerspectiveListResponse>(`/api/project/scenes2d/${encodeURIComponent(sceneId)}/perspectives`)
}

export function createScene2DPerspective(
  sceneId: string,
  body: Scene2DPerspectiveCreateRequest = {},
): Promise<Scene2DPerspectiveResponse> {
  return requestJson<Scene2DPerspectiveResponse>(`/api/project/scenes2d/${encodeURIComponent(sceneId)}/perspectives`, {
    method: 'POST',
    body,
  })
}

export function importScene2DPerspective(
  sceneId: string,
  file: File,
  opts: { title?: string; linked_scene3d_id?: string } = {},
): Promise<Scene2DPerspectiveResponse> {
  const form = new FormData()
  form.append('file', file)
  if (opts.title) form.append('title', opts.title)
  if (opts.linked_scene3d_id) form.append('linked_scene3d_id', opts.linked_scene3d_id)
  return requestJson<Scene2DPerspectiveResponse>(`/api/project/scenes2d/${encodeURIComponent(sceneId)}/perspectives/import`, {
    method: 'POST',
    body: form,
  })
}

export function reorderScene2DPerspectives(
  sceneId: string,
  body: Scene2DPerspectiveReorderRequest,
): Promise<Scene2DSceneResponse> {
  return requestJson<Scene2DSceneResponse>(`/api/project/scenes2d/${encodeURIComponent(sceneId)}/perspectives/reorder`, {
    method: 'POST',
    body,
  })
}

export function updateScene2DPerspective(
  sceneId: string,
  perspectiveId: string,
  body: Scene2DPerspectiveUpdateRequest,
): Promise<Scene2DPerspectiveResponse> {
  return requestJson<Scene2DPerspectiveResponse>(
    `/api/project/scenes2d/${encodeURIComponent(sceneId)}/perspectives/${encodeURIComponent(perspectiveId)}`,
    { method: 'PATCH', body },
  )
}

export function deleteScene2DPerspective(sceneId: string, perspectiveId: string): Promise<Scene2DSceneResponse> {
  return requestJson<Scene2DSceneResponse>(
    `/api/project/scenes2d/${encodeURIComponent(sceneId)}/perspectives/${encodeURIComponent(perspectiveId)}`,
    { method: 'DELETE' },
  )
}

export function openScene2DPerspective(sceneId: string, perspectiveId: string): Promise<Scene2DOpenResponse> {
  return requestJson<Scene2DOpenResponse>(
    `/api/project/scenes2d/${encodeURIComponent(sceneId)}/perspectives/${encodeURIComponent(perspectiveId)}/open`,
    { method: 'POST' },
  )
}

export function refreshScene2DPerspectivePreview(
  sceneId: string,
  perspectiveId: string,
): Promise<Scene2DRefreshResponse & { perspective: Scene2DPerspective }> {
  return requestJson<Scene2DRefreshResponse & { perspective: Scene2DPerspective }>(
    `/api/project/scenes2d/${encodeURIComponent(sceneId)}/perspectives/${encodeURIComponent(perspectiveId)}/refresh-preview`,
    { method: 'POST' },
  )
}

export function setPrimaryScene2DPerspective(sceneId: string, perspectiveId: string): Promise<Scene2DSceneResponse> {
  return requestJson<Scene2DSceneResponse>(
    `/api/project/scenes2d/${encodeURIComponent(sceneId)}/perspectives/${encodeURIComponent(perspectiveId)}/set-primary`,
    { method: 'POST' },
  )
}

export function moveScene2DPerspective(
  sceneId: string,
  perspectiveId: string,
  body: Scene2DPerspectiveMoveRequest,
): Promise<Scene2DPerspectiveMoveResponse> {
  return requestJson<Scene2DPerspectiveMoveResponse>(
    `/api/project/scenes2d/${encodeURIComponent(sceneId)}/perspectives/${encodeURIComponent(perspectiveId)}/move-to-scene`,
    { method: 'POST', body },
  )
}

export function addScene2DPerspectiveToReferences(sceneId: string, perspectiveId: string): Promise<Scene2DReferenceResponse> {
  return requestJson<Scene2DReferenceResponse>(
    `/api/project/scenes2d/${encodeURIComponent(sceneId)}/perspectives/${encodeURIComponent(perspectiveId)}/add-to-references`,
    { method: 'POST' },
  )
}

export function scene2DPerspectivePreviewUrl(scene: Scene2D, perspective: Scene2DPerspective): string {
  return `/api/project/scenes2d/${encodeURIComponent(scene.id)}/perspectives/${encodeURIComponent(perspective.id)}/preview?t=${encodeURIComponent(perspective.updated_at || '')}`
}
