import { requestJson } from './client'
import type {
  MissingFilesPayload,
  OpenProjectRequest,
  ProjectPathRequest,
  ProjectPayload,
} from '../types'

export function getProject(): Promise<ProjectPayload> {
  return requestJson<ProjectPayload>('/api/project')
}

export function getMissingFiles(): Promise<MissingFilesPayload> {
  return requestJson<MissingFilesPayload>('/api/project/missing-files')
}

export function createProject(body: ProjectPathRequest = {}): Promise<ProjectPayload> {
  return requestJson<ProjectPayload>('/api/project/new', {
    method: 'POST',
    body,
  })
}

export function openProject(body: OpenProjectRequest): Promise<ProjectPayload> {
  return requestJson<ProjectPayload>('/api/project/open', {
    method: 'POST',
    body,
  })
}

export function saveProject(): Promise<ProjectPayload> {
  return requestJson<ProjectPayload>('/api/project/save', {
    method: 'POST',
  })
}

export function openBlenderScene(): Promise<Record<string, unknown>> {
  return requestJson<Record<string, unknown>>('/api/project/scene3d/open-blender', {
    method: 'POST',
  })
}
