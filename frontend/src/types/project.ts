import type { ProjectSettings } from './settings'
import type { Shot, ShotStatus } from './shot'

export interface ProjectPayload {
  project_path: string
  project_json_path: string
  document_path?: string
  name: string
  layout: 1 | 2
  project_id: string
  storage_revision: number
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

export interface SaveProjectAsRequest {
  path: string
}

export interface MissingFileRow {
  shot_id: string
  field: string
  path: string
}

/** GET /api/project/missing-files response (key is `missing_files`; each row points at one
 * metadata path that no longer exists on disk). */
export interface MissingFilesPayload {
  missing_files?: MissingFileRow[]
  [key: string]: unknown
}
