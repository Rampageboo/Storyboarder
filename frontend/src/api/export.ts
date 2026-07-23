import { requestJson } from './client'

export type PdfLayout = 'one_per_page' | 'two_per_page' | 'thumbnails'
export type ExportType = 'pdf' | 'animatic' | 'contact_sheet' | 'shot_list' | 'timing' | 'image_sequence'

export interface ExportResult {
  path: string
  download_url?: string
}

export interface AnimaticOptions {
  fps?: number
  seconds_per_board?: number | null
  captions?: boolean
}

export function exportPdf(layout: PdfLayout): Promise<ExportResult> {
  return requestJson<ExportResult>('/api/export/pdf', { method: 'POST', body: { layout } })
}

export function exportAnimatic(options: AnimaticOptions = {}): Promise<ExportResult> {
  return requestJson<ExportResult>('/api/export/animatic', { method: 'POST', body: options })
}

export function exportContactSheet(): Promise<ExportResult> {
  return requestJson<ExportResult>('/api/export/contact-sheet', { method: 'POST' })
}

export function exportShotList(): Promise<ExportResult> {
  return requestJson<ExportResult>('/api/export/shot-list', { method: 'POST' })
}

export function exportTiming(): Promise<ExportResult> {
  return requestJson<ExportResult>('/api/export/timing', { method: 'POST' })
}

export function exportImageSequence(): Promise<ExportResult> {
  return requestJson<ExportResult>('/api/export/image-sequence', { method: 'POST' })
}

export function openExport(type: ExportType): Promise<{ path: string }> {
  return requestJson<{ path: string }>('/api/export/open', { method: 'POST', body: { type } })
}
