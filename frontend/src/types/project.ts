import type { ProjectSettings } from './settings'
import type { Shot, ShotStatus } from './shot'

export interface ProjectPayload {
  project_path: string
  project_json_path: string
  name: string
  dirty: boolean
  settings: ProjectSettings
  statuses: ShotStatus[]
  shots: Shot[]
}

export interface ProjectPathRequest {
  path?: string | null
  canvas_width?: number | null
  canvas_height?: number | null
}

export interface OpenProjectRequest {
  project_json_path: string
}

export interface MissingFilesPayload {
  missing: string[]
  [key: string]: unknown
}
