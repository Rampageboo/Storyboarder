import { requestJson } from './client'
import { apiBase } from './base'
import type { ComicDocument } from '../types/comic'
import type { ProjectPayload } from '../types'

export function updateComic(document: ComicDocument, projectPath: string): Promise<ProjectPayload> {
  return requestJson('/api/project/comic', { method: 'PUT', body: { document, project_path: projectPath } })
}
export function comicImageUrl(pageId: string): string {
  return `${apiBase()}/api/project/comic/pages/${encodeURIComponent(pageId)}/image`
}

export interface ComicExportScope { project_path: string; page_id?: string; chapter_id?: string; format?: 'png' | 'zip' | 'pdf' | 'cbz' }
export function exportComic(scope: ComicExportScope): Promise<{ path: string }> {
  return requestJson('/api/project/comic/export', { method: 'POST', body: scope })
}
export function openComicExport(scope: ComicExportScope): Promise<{ path: string }> {
  return requestJson('/api/project/comic/export/open', { method: 'POST', body: scope })
}
export function previewComicPrompt(shotId: string): Promise<{ prompt: { compiled_prompt: string; negative_prompt: string } }> {
  return requestJson(`/api/project/comic/prompts/${encodeURIComponent(shotId)}`)
}
