import { requestJson } from './client'
import type { ProjectPayload } from '../types'

export interface ApplyRefSegmentRequest {
  anchor_shot_id: string
  end_shot_id: string
  segment_id?: string
  camera_name?: string
}

/** Import a project-level reference asset (image / video / GLB model — dispatched by extension).
 * Appends to settings.reference_links. */
export function uploadProjectReference(file: File): Promise<ProjectPayload> {
  const form = new FormData()
  form.append('file', file)
  return requestJson<ProjectPayload>('/api/project/references', { method: 'POST', body: form })
}

export function deleteProjectReference(refId: string): Promise<ProjectPayload> {
  return requestJson<ProjectPayload>(`/api/project/references/${encodeURIComponent(refId)}`, {
    method: 'DELETE',
  })
}

/** Apply a video reference segment across a shot range. Returns ProjectPayload (+ result fields). */
export function applyRefSegment(body: ApplyRefSegmentRequest): Promise<ProjectPayload> {
  return requestJson<ProjectPayload>('/api/project/ref-segment/apply', { method: 'POST', body })
}

export function applyRefSegmentImage(body: ApplyRefSegmentRequest): Promise<ProjectPayload> {
  return requestJson<ProjectPayload>('/api/project/ref-segment/apply-image', { method: 'POST', body })
}

export function applyRefSegment3d(body: ApplyRefSegmentRequest): Promise<ProjectPayload> {
  return requestJson<ProjectPayload>('/api/project/ref-segment/apply-3d', { method: 'POST', body })
}

export function deleteRefSegment(segmentId: string): Promise<ProjectPayload> {
  return requestJson<ProjectPayload>(`/api/project/ref-segments/${encodeURIComponent(segmentId)}`, {
    method: 'DELETE',
  })
}

/** Undo the most recent reference-segment apply using the token returned by the apply call. */
export function restoreRefApply(token: string): Promise<ProjectPayload> {
  return requestJson<ProjectPayload>('/api/project/ref-apply/undo', {
    method: 'POST',
    body: { token },
  })
}
