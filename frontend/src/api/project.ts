import { requestJson } from './client'
import type {
  MissingFilesPayload,
  OpenProjectRequest,
  ProjectPathRequest,
  ProjectPayload,
  SaveProjectAsRequest,
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

export function saveProjectAs(body: SaveProjectAsRequest): Promise<ProjectPayload> {
  return requestJson<ProjectPayload>('/api/project/save-as', {
    method: 'POST',
    body,
  })
}

/** Open the project's Blender scene with the configured Blender executable. Returns a ProjectPayload. */
export function openBlenderScene(): Promise<ProjectPayload> {
  return requestJson<ProjectPayload>('/api/project/scene3d/open-blender', {
    method: 'POST',
  })
}

/** Import a Blender-exported GLB/GLTF as the project's 3D scene. Returns a ProjectPayload. */
export function importScene3d(file: File): Promise<ProjectPayload> {
  const form = new FormData()
  form.append('file', file)
  return requestJson<ProjectPayload>('/api/project/scene3d/import', {
    method: 'POST',
    body: form,
  })
}
