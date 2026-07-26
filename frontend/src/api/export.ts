import { requestJson } from './client'

export type PdfLayout = 'one_per_page' | 'two_per_page' | 'thumbnails'
export type ExportType = 'pdf' | 'animatic' | 'contact_sheet' | 'shot_list' | 'timing' | 'image_sequence'

export interface ExportResult {
  path: string
  download_url?: string
}

/**
 * Which boards an export covers, as the range spec the dialog collects —
 * `3`, `1-5`, `8-`, `1-3, 6, 9-10`. Empty (or omitted) exports the whole
 * storyboard. A partial export gets a `_board-NNN` / `_boards-NNN-MMM` suffix,
 * so it never overwrites the whole-storyboard output.
 */
export interface ExportScope {
  boards?: string
}

export interface ResolvedRange {
  /** 1-based board numbers, ascending. Empty when the spec is invalid. */
  boards: number[]
  count: number
  /** Short summary for the dialog, e.g. "Boards 2-4 (3 of 10)". */
  label: string
  /** Filename suffix these boards produce; empty for a whole-storyboard export. */
  suffix: string
  /** User-facing problem with the spec, or '' when it is valid. */
  error: string
}

/**
 * Validate a range spec without exporting. Keeps the dialog's live feedback on
 * the same parser the export itself uses, rather than a second copy here.
 */
export function resolveBoardRange(boards: string): Promise<ResolvedRange> {
  return requestJson<ResolvedRange>('/api/export/resolve-range', { method: 'POST', body: { boards } })
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
