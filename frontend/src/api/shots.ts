import { requestJson } from './client'
import type {
  AddShotRequest,
  AnnotationSaveRequest,
  CanvasRequest,
  CommentRequest,
  CommentResolveRequest,
  DrawingSaveRequest,
  ImportImagePathRequest,
  ProjectPayload,
  RelinkRequest,
  RemoveReferenceRequest,
  ReorderShotsRequest,
  RestoreShotRequest,
  SetReferencePathsRequest,
  ShotUpdate,
} from '../types'

export function addShot(body: AddShotRequest = {}): Promise<ProjectPayload> {
  return requestJson<ProjectPayload>('/api/shots', {
    method: 'POST',
    body,
  })
}

export function duplicateShot(shotId: string): Promise<ProjectPayload> {
  return requestJson<ProjectPayload>(`/api/shots/${encodeURIComponent(shotId)}/duplicate`, {
    method: 'POST',
  })
}

export function updateShot(shotId: string, body: ShotUpdate): Promise<ProjectPayload> {
  return requestJson<ProjectPayload>(`/api/shots/${encodeURIComponent(shotId)}`, {
    method: 'PATCH',
    body,
  })
}

export function deleteShot(shotId: string): Promise<ProjectPayload> {
  return requestJson<ProjectPayload>(`/api/shots/${encodeURIComponent(shotId)}`, {
    method: 'DELETE',
  })
}

export function restoreShot(body: RestoreShotRequest): Promise<ProjectPayload> {
  return requestJson<ProjectPayload>('/api/shots/restore', {
    method: 'POST',
    body,
  })
}

export function reorderShots(body: ReorderShotsRequest): Promise<ProjectPayload> {
  return requestJson<ProjectPayload>('/api/shots/reorder', {
    method: 'POST',
    body,
  })
}

export function importImagePath(shotId: string, body: ImportImagePathRequest): Promise<ProjectPayload> {
  return requestJson<ProjectPayload>(`/api/shots/${encodeURIComponent(shotId)}/import-image-path`, {
    method: 'POST',
    body,
  })
}

export function moveShotUp(shotId: string): Promise<ProjectPayload> {
  return requestJson<ProjectPayload>(`/api/shots/${encodeURIComponent(shotId)}/move-up`, {
    method: 'POST',
  })
}

export function moveShotDown(shotId: string): Promise<ProjectPayload> {
  return requestJson<ProjectPayload>(`/api/shots/${encodeURIComponent(shotId)}/move-down`, {
    method: 'POST',
  })
}

export function uploadShotImage(shotId: string, file: File): Promise<ProjectPayload> {
  const form = new FormData()
  form.append('file', file)
  return requestJson<ProjectPayload>(`/api/shots/${encodeURIComponent(shotId)}/image`, {
    method: 'POST',
    body: form,
  })
}

export function uploadShotReference(shotId: string, file: File): Promise<ProjectPayload> {
  const form = new FormData()
  form.append('file', file)
  return requestJson<ProjectPayload>(`/api/shots/${encodeURIComponent(shotId)}/references`, {
    method: 'POST',
    body: form,
  })
}

export function removeShotReference(shotId: string, body: RemoveReferenceRequest): Promise<ProjectPayload> {
  return requestJson<ProjectPayload>(`/api/shots/${encodeURIComponent(shotId)}/references`, {
    method: 'DELETE',
    body,
  })
}

export function setShotReferencePaths(
  shotId: string,
  body: SetReferencePathsRequest,
): Promise<ProjectPayload> {
  return requestJson<ProjectPayload>(`/api/shots/${encodeURIComponent(shotId)}/references`, {
    method: 'PUT',
    body,
  })
}

export function uploadShotSource(shotId: string, file: File): Promise<ProjectPayload> {
  const form = new FormData()
  form.append('file', file)
  return requestJson<ProjectPayload>(`/api/shots/${encodeURIComponent(shotId)}/source`, {
    method: 'POST',
    body: form,
  })
}

export function relinkPreview(shotId: string, body: RelinkRequest): Promise<ProjectPayload> {
  return requestJson<ProjectPayload>(`/api/shots/${encodeURIComponent(shotId)}/relink-preview`, {
    method: 'POST',
    body,
  })
}

export function createShotCanvas(shotId: string, body: CanvasRequest): Promise<ProjectPayload> {
  return requestJson<ProjectPayload>(`/api/shots/${encodeURIComponent(shotId)}/canvas`, {
    method: 'POST',
    body,
  })
}

export function saveShotDrawing(shotId: string, body: DrawingSaveRequest): Promise<ProjectPayload> {
  return requestJson<ProjectPayload>(`/api/shots/${encodeURIComponent(shotId)}/drawing`, {
    method: 'POST',
    body,
  })
}

export function syncShot(shotId: string, force = false): Promise<ProjectPayload> {
  const query = force ? '?force=true' : ''
  return requestJson<ProjectPayload>(`/api/shots/${encodeURIComponent(shotId)}/sync${query}`, {
    method: 'POST',
  })
}

export function openShotSource(shotId: string): Promise<Record<string, string>> {
  return requestJson<Record<string, string>>(`/api/shots/${encodeURIComponent(shotId)}/open-source`, {
    method: 'POST',
  })
}

export function recoverShotSource(
  shotId: string,
  preserveLayers = true,
): Promise<ProjectPayload> {
  const query = preserveLayers ? '' : '?preserve_layers=false'
  return requestJson<ProjectPayload>(
    `/api/shots/${encodeURIComponent(shotId)}/recover-source${query}`,
    { method: 'POST' },
  )
}

export function openShotPreview(shotId: string): Promise<Record<string, string>> {
  return requestJson<Record<string, string>>(`/api/shots/${encodeURIComponent(shotId)}/open-preview`, {
    method: 'POST',
  })
}

export function removeShotImage(shotId: string): Promise<ProjectPayload> {
  return requestJson<ProjectPayload>(`/api/shots/${encodeURIComponent(shotId)}/image`, {
    method: 'DELETE',
  })
}

export function removeShotLayer(shotId: string, layerId: 'background' | 'codex'): Promise<ProjectPayload> {
  return requestJson<ProjectPayload>(
    `/api/shots/${encodeURIComponent(shotId)}/layers/${encodeURIComponent(layerId)}`,
    { method: 'DELETE' },
  )
}

export function shotImageUrl(shotId: string): string {
  return `/api/shots/${encodeURIComponent(shotId)}/image`
}

export function shotThumbnailUrl(shotId: string): string {
  return `/api/shots/${encodeURIComponent(shotId)}/thumbnail`
}

export function shotBoardBackgroundUrl(shotId: string): string {
  return `/api/shots/${encodeURIComponent(shotId)}/board-background`
}

export function shotCodexLayerUrl(shotId: string): string {
  return `/api/shots/${encodeURIComponent(shotId)}/codex-layer`
}

/** URL that serves any project-relative file (e.g. a shot reference image) via GET /api/files. */
export function projectFileUrl(path: string): string {
  return `/api/files?path=${encodeURIComponent(path)}`
}

export function addComment(shotId: string, body: CommentRequest): Promise<ProjectPayload> {
  return requestJson<ProjectPayload>(`/api/shots/${encodeURIComponent(shotId)}/comments`, {
    method: 'POST',
    body,
  })
}

export function resolveComment(
  shotId: string,
  commentId: number,
  body: CommentResolveRequest,
): Promise<ProjectPayload> {
  return requestJson<ProjectPayload>(
    `/api/shots/${encodeURIComponent(shotId)}/comments/${commentId}`,
    {
      method: 'PATCH',
      body,
    },
  )
}

export function getAnnotations(shotId: string): Promise<Record<string, unknown>> {
  return requestJson<Record<string, unknown>>(`/api/shots/${encodeURIComponent(shotId)}/annotations`)
}

export function saveAnnotations(
  shotId: string,
  body: AnnotationSaveRequest,
): Promise<{ annotations: Record<string, unknown>[] }> {
  return requestJson<{ annotations: Record<string, unknown>[] }>(
    `/api/shots/${encodeURIComponent(shotId)}/annotations`,
    {
      method: 'PUT',
      body,
    },
  )
}
