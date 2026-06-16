import { requestJson } from './client'

export interface BrowseResult {
  path: string
  cancelled: boolean
}

/** Opens the native file picker (backend tk dialog) to choose a project.json. */
export function browseProjectJson(): Promise<BrowseResult> {
  return requestJson<BrowseResult>('/api/system/browse-project-json', { method: 'POST' })
}
