import type { CSSProperties } from 'react'

const STATUS_TOKENS: Record<string, string> = {
  draft: 'var(--st-draft)',
  'in progress': 'var(--st-progress)',
  review: 'var(--st-review)',
  approved: 'var(--st-approved)',
  final: 'var(--st-final)',
}

/** Colour token for a shot status; unknown custom statuses read as Draft. */
export function statusColor(status: unknown): string {
  return STATUS_TOKENS[String(status ?? '').trim().toLowerCase()] ?? STATUS_TOKENS.draft
}

/** Inline style that feeds `.status-chip` / `.status-dot`. */
export function statusStyle(status: unknown): CSSProperties {
  return { '--status-color': statusColor(status) } as CSSProperties
}
