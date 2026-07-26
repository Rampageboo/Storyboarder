import { requestJson } from './client'

export type PdfLayout = 'one_per_page' | 'two_per_page' | 'thumbnails'
export type ExportType = 'pdf' | 'animatic' | 'contact_sheet' | 'shot_list' | 'timing' | 'image_sequence'

export interface ExportResult {
  path: string
  download_url?: string
}

/**
 * Empty (or omitted) shot_id exports the whole storyboard. A shot_id narrows the
 * export to that one board and gives its output a `_board-NNN` suffix, so a
 * single-board export never overwrites the whole-storyboard one.
 */
export interface ExportScope {
  shot_id?: string
}

export interface AnimaticOptions extends ExportScope {
  fps?: number
  seconds_per_board?: number | null
  captions?: boolean
}

export function exportPdf(layout: PdfLayout, scope: ExportScope = {}): Promise<ExportResult> {
  return requestJson<ExportResult>('/api/export/pdf', { method: 'POST', body: { layout, ...scope } })
}

export function exportAnimatic(options: AnimaticOptions = {}): Promise<ExportResult> {
  return requestJson<ExportResult>('/api/export/animatic', { method: 'POST', body: options })
}

export function exportContactSheet(scope: ExportScope = {}): Promise<ExportResult> {
  return requestJson<ExportResult>('/api/export/contact-sheet', { method: 'POST', body: scope })
}

export function exportShotList(scope: ExportScope = {}): Promise<ExportResult> {
  return requestJson<ExportResult>('/api/export/shot-list', { method: 'POST', body: scope })
}

export function exportTiming(scope: ExportScope = {}): Promise<ExportResult> {
  return requestJson<ExportResult>('/api/export/timing', { method: 'POST', body: scope })
}

export function exportImageSequence(scope: ExportScope = {}): Promise<ExportResult> {
  return requestJson<ExportResult>('/api/export/image-sequence', { method: 'POST', body: scope })
}

/** Opens a generated export. Pass the same scope it was exported with. */
export function openExport(type: ExportType, scope: ExportScope = {}): Promise<{ path: string }> {
  return requestJson<{ path: string }>('/api/export/open', { method: 'POST', body: { type, ...scope } })
}
