import { requestJson } from './client'
import type { ProjectPayload } from '../types'

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

/** One Home-screen card. Described without opening the document. */
export interface RecentProject {
  /** User-visible path: the .sbd itself, or the project folder. */
  path: string
  /** What openProject needs — the folder variant points at project.json. */
  open_path: string
  name: string
  kind: 'document' | 'folder'
  location: string
  exists: boolean
  modified_ms: number
  size_bytes: number
  shot_count: number
  /** Data URL of the first board, or '' when none could be read. */
  thumbnail: string
}

export interface BootstrapPayload {
  session: AppSession
  project: ProjectPayload | null
  recents: RecentProject[]
  /** Always false: startup lands on Home and never reopens the last document. */
  opened_last_project: boolean
  startup_timings: Record<string, number>
  warning?: string
}

export function bootstrapApp(): Promise<BootstrapPayload> {
  return requestJson<BootstrapPayload>('/api/app/bootstrap')
}

export function listRecents(): Promise<{ recents: RecentProject[] }> {
  return requestJson<{ recents: RecentProject[] }>('/api/app/recents')
}

export function forgetRecent(path: string): Promise<{ recents: RecentProject[] }> {
  return requestJson<{ recents: RecentProject[] }>('/api/app/recents/forget', { method: 'POST', body: { path } })
}

/** Flush and close the open document, returning the app to Home. */
export function closeProject(): Promise<{ closed: boolean; recents: RecentProject[] }> {
  return requestJson<{ closed: boolean; recents: RecentProject[] }>('/api/app/close-project', { method: 'POST' })
}

export function reportUiReady(): Promise<{ ok: boolean }> {
  return requestJson<{ ok: boolean }>('/api/app/ui-ready', { method: 'POST' })
}

export type PreviewAnalysisStatus = 'no_project' | 'started' | 'already_running' | 'complete' | 'failed' | 'idle'

export interface PreviewAnalysisResult {
  ok: boolean
  status: PreviewAnalysisStatus
  task_id?: string
  project_path?: string
  revision?: number
}

export function refreshPreviewAnalysis(): Promise<PreviewAnalysisResult> {
  return requestJson<PreviewAnalysisResult>('/api/project/preview-analysis/refresh', { method: 'POST' })
}

export function getPreviewAnalysisStatus(): Promise<{ ok: boolean; status: PreviewAnalysisStatus; job: unknown }> {
  return requestJson<{ ok: boolean; status: PreviewAnalysisStatus; job: unknown }>('/api/project/preview-analysis/status')
}

export interface AppFocusResult {
  ok: boolean
  focused: boolean
}

export interface PreheatPhotoshopResult {
  ok: boolean
  attempted: boolean
  launched: boolean
  message: string
}

export function focusApp(): Promise<AppFocusResult> {
  return requestJson<AppFocusResult>('/api/app/focus', { method: 'POST' })
}

export function preheatPhotoshop(): Promise<PreheatPhotoshopResult> {
  return requestJson<PreheatPhotoshopResult>('/api/app/preheat-photoshop', { method: 'POST' })
}

/** Opens the native folder picker. Used for project roots and new-project locations. */
export function browseFolder(): Promise<BrowseResult> {
  return requestJson<BrowseResult>('/api/system/browse-folder', { method: 'POST' })
}

/** Opens the native file picker (backend tk dialog) to choose a project.json. */
export function browseProjectJson(): Promise<BrowseResult> {
  return requestJson<BrowseResult>('/api/system/browse-project-json', { method: 'POST' })
}

/** Opens the native picker for a new project destination or Save As target. */
export function browseProjectSave(): Promise<BrowseResult> {
  return requestJson<BrowseResult>('/api/system/browse-project-save', { method: 'POST' })
}
