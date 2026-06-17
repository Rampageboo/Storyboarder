import { requestJson } from './client'

export interface BrowseResult {
  path: string
  cancelled: boolean
}

export interface AppSession {
  last_project_json_path?: string
  selected_shot_id?: string
  recent_projects?: string[]
  [key: string]: unknown
}

export function getAppSession(): Promise<AppSession> {
  return requestJson<AppSession>('/api/app/session')
}

export function updateAppSession(body: AppSession): Promise<AppSession> {
  return requestJson<AppSession>('/api/app/session', { method: 'PUT', body })
}

/** Opens the native folder picker. Used for project roots and new-project locations. */
export function browseFolder(): Promise<BrowseResult> {
  return requestJson<BrowseResult>('/api/system/browse-folder', { method: 'POST' })
}

/** Opens the native file picker (backend tk dialog) to choose a project.json. */
export function browseProjectJson(): Promise<BrowseResult> {
  return requestJson<BrowseResult>('/api/system/browse-project-json', { method: 'POST' })
}
