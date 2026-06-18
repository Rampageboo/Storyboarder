import type { ReferenceLink } from '../types'
import type { Shot } from '../types'

export type RefSegmentRecord = {
  id?: string
  anchor_shot_id?: string
  end_shot_id?: string
  source_type?: string
  reference_id?: string
  reference_path?: string
  video_start?: number
  fit_mode?: string
  [key: string]: unknown
}

export type SegmentMarkerKind = 'applied' | 'pending'

export type SegmentMarkerSpan = {
  segmentId: string
  lo: number
  hi: number
  kind: SegmentMarkerKind
  anchorShotId: string
  endShotId: string
  sourceType: string
  typeLabel: string
  sourceTitle: string
  sourcePath: string
  isSelected: boolean
  needsRepair: boolean
}

/** @deprecated Use SegmentMarkerSpan */
export type AppliedSegmentMarker = SegmentMarkerSpan

function fileName(path: string) {
  return path.split(/[/\\]/).pop() || path
}

function normalizePath(path: string) {
  return path.replace(/\\/g, '/').trim()
}

export function segmentTypeLabel(sourceType: string): string {
  const t = sourceType.toLowerCase()
  if (t === 'image') return 'IMAGE'
  if (t === 'video') return 'VIDEO'
  if (t === 'model') return 'MODEL / 3D'
  return sourceType.toUpperCase() || 'REFERENCE'
}

export function segmentCssType(sourceType: string): 'image' | 'video' | 'model' | 'other' {
  const t = sourceType.toLowerCase()
  if (t === 'image') return 'image'
  if (t === 'video') return 'video'
  if (t === 'model') return 'model'
  return 'other'
}

function resolveSourceTitle(segment: RefSegmentRecord, links: ReferenceLink[]): string {
  if (segment.reference_id) {
    const link = links.find((l) => l.id === segment.reference_id)
    if (link?.title) return link.title
    if (link?.path) return fileName(link.path)
  }
  if (segment.reference_path) return fileName(String(segment.reference_path))
  return ''
}

function segmentReferencePath(segment: RefSegmentRecord, links: ReferenceLink[]): string {
  if (segment.reference_path) return normalizePath(String(segment.reference_path))
  if (segment.reference_id) {
    const link = links.find((l) => l.id === segment.reference_id)
    if (link?.path) return normalizePath(link.path)
  }
  return ''
}

export function isShotAppliedToSegment(shot: Shot, segment: RefSegmentRecord, links: ReferenceLink[]): boolean {
  const segId = segment.id ? String(segment.id) : ''
  const cam = shot.camera_data || {}
  if (segId && String(cam.ref_segment_id || '') === segId) return true

  const refPath = segmentReferencePath(segment, links)
  const shotRef = normalizePath(shot.ref_video_path || '')
  if (!refPath || !shotRef || shotRef !== refPath) return false

  return Boolean(
    shot.preview_image_path ||
      shot.image_path ||
      shot.has_board_background ||
      (shot.ref_segment_time ?? 0) > 0 ||
      (shot.ref_video_time ?? 0) > 0,
  )
}

type ParsedSegment = {
  segmentId: string
  anchorShotId: string
  endShotId: string
  lo: number
  hi: number
  sourceType: string
  typeLabel: string
  sourceTitle: string
  sourcePath: string
  needsRepair: boolean
  record: RefSegmentRecord
}

function parseSegmentRecord(
  seg: RefSegmentRecord,
  shots: Shot[],
  links: ReferenceLink[],
): ParsedSegment | null {
  const segmentId = seg.id ? String(seg.id) : ''
  if (!segmentId) return null

  const shotIndex = new Map(shots.map((s, i) => [s.shot_id, i]))
  const anchor = seg.anchor_shot_id ? String(seg.anchor_shot_id) : ''
  const end = seg.end_shot_id ? String(seg.end_shot_id) : ''
  const anchorIdx = anchor ? shotIndex.get(anchor) : undefined
  const endIdx = end ? shotIndex.get(end) : undefined

  const appliedIndices = shots
    .map((shot, index) => (isShotAppliedToSegment(shot, seg, links) ? index : -1))
    .filter((index) => index >= 0)

  let lo: number
  let hi: number
  let needsRepair = false

  if (anchorIdx !== undefined && endIdx !== undefined) {
    lo = Math.min(anchorIdx, endIdx)
    hi = Math.max(anchorIdx, endIdx)
  } else if (appliedIndices.length > 0) {
    lo = Math.min(...appliedIndices)
    hi = Math.max(...appliedIndices)
    needsRepair = true
  } else {
    return null
  }

  const sourceType = String(seg.source_type || 'reference')

  return {
    segmentId,
    anchorShotId: anchor || shots[lo]?.shot_id || '',
    endShotId: end || shots[hi]?.shot_id || '',
    lo,
    hi,
    sourceType,
    typeLabel: segmentTypeLabel(sourceType),
    sourceTitle: resolveSourceTitle(seg, links),
    sourcePath: segmentReferencePath(seg, links),
    needsRepair,
    record: seg,
  }
}

function mergeSpanRuns(
  runs: { index: number; segmentId: string; kind: SegmentMarkerKind }[],
  records: Map<string, ParsedSegment>,
  selectedSegmentId?: string | null,
): SegmentMarkerSpan[] {
  const spans: SegmentMarkerSpan[] = []
  let i = 0
  while (i < runs.length) {
    const run = runs[i]
    let end = i
    while (
      end + 1 < runs.length &&
      runs[end + 1].segmentId === run.segmentId &&
      runs[end + 1].kind === run.kind
    ) {
      end += 1
    }
    const record = records.get(run.segmentId)
    if (record) {
      spans.push({
        segmentId: record.segmentId,
        lo: runs[i].index,
        hi: runs[end].index,
        kind: run.kind,
        anchorShotId: record.anchorShotId,
        endShotId: record.endShotId,
        sourceType: record.sourceType,
        typeLabel: record.typeLabel,
        sourceTitle: record.sourceTitle,
        sourcePath: record.sourcePath,
        isSelected: Boolean(selectedSegmentId && record.segmentId === selectedSegmentId),
        needsRepair: record.needsRepair,
      })
    }
    i = end + 1
  }
  return spans
}

/**
 * Filmstrip markers: newest segment wins per board; solid = applied, dashed = pending gap.
 */
export function resolveVisibleSegmentMarkerSpans(
  segments: RefSegmentRecord[] | undefined,
  shots: Shot[],
  links: ReferenceLink[],
  selectedSegmentId?: string | null,
): SegmentMarkerSpan[] {
  if (!segments?.length || !shots.length) return []

  const records = new Map<string, ParsedSegment>()
  const owner: (string | null)[] = Array(shots.length).fill(null)

  segments.forEach((seg) => {
    const parsed = parseSegmentRecord(seg, shots, links)
    if (!parsed) return
    records.set(parsed.segmentId, parsed)
    for (let i = parsed.lo; i <= parsed.hi; i += 1) {
      owner[i] = parsed.segmentId
    }
  })

  const runs: { index: number; segmentId: string; kind: SegmentMarkerKind }[] = []
  for (let i = 0; i < shots.length; i += 1) {
    const segmentId = owner[i]
    if (!segmentId) continue
    const record = records.get(segmentId)
    if (!record) continue
    const kind: SegmentMarkerKind = isShotAppliedToSegment(shots[i], record.record, links) ? 'applied' : 'pending'
    runs.push({ index: i, segmentId, kind })
  }

  return mergeSpanRuns(runs, records, selectedSegmentId)
}

/** @deprecated Use resolveVisibleSegmentMarkerSpans */
export function resolveVisibleAppliedMarkers(
  segments: RefSegmentRecord[] | undefined,
  shots: Shot[],
  links: ReferenceLink[],
  selectedSegmentId?: string | null,
): SegmentMarkerSpan[] {
  return resolveVisibleSegmentMarkerSpans(segments, shots, links, selectedSegmentId)
}

export function segmentMarkerTooltip(span: SegmentMarkerSpan): string {
  const boards = span.lo === span.hi ? `#${span.lo + 1}` : `#${span.lo + 1}–#${span.hi + 1}`
  const source = span.sourceTitle || span.sourcePath || 'unknown source'
  if (span.kind === 'pending') {
    return `${span.typeLabel} · ${source} · boards ${boards} — inside segment, not applied. Reapply to include.`
  }
  if (span.needsRepair) {
    return `${span.typeLabel} · ${source} · boards ${boards} — segment range needs review`
  }
  return `${span.typeLabel} · ${source} · boards ${boards}`
}

/** @deprecated Use segmentMarkerTooltip */
export function appliedSegmentTooltip(marker: SegmentMarkerSpan): string {
  return segmentMarkerTooltip(marker)
}

export function findRefSegment(
  segments: RefSegmentRecord[] | undefined,
  segmentId: string | null | undefined,
): RefSegmentRecord | null {
  if (!segmentId || !segments?.length) return null
  return segments.find((s) => s.id === segmentId) ?? null
}

export function segmentBoardIndexRange(
  segment: Pick<RefSegmentRecord, 'anchor_shot_id' | 'end_shot_id'>,
  shots: Pick<Shot, 'shot_id'>[],
): { lo: number; hi: number } | null {
  const anchor = segment.anchor_shot_id ? String(segment.anchor_shot_id) : ''
  const end = segment.end_shot_id ? String(segment.end_shot_id) : ''
  const anchorIdx = shots.findIndex((shot) => shot.shot_id === anchor)
  const endIdx = shots.findIndex((shot) => shot.shot_id === end)
  if (anchorIdx < 0 || endIdx < 0) return null
  return { lo: Math.min(anchorIdx, endIdx), hi: Math.max(anchorIdx, endIdx) }
}

export function segmentsOverlapBoardRange(
  left: Pick<RefSegmentRecord, 'anchor_shot_id' | 'end_shot_id'>,
  right: Pick<RefSegmentRecord, 'anchor_shot_id' | 'end_shot_id'>,
  shots: Pick<Shot, 'shot_id'>[],
): boolean {
  const leftRange = segmentBoardIndexRange(left, shots)
  const rightRange = segmentBoardIndexRange(right, shots)
  if (!leftRange || !rightRange) return false
  return leftRange.lo <= rightRange.hi && rightRange.lo <= leftRange.hi
}

/** Drop older segments that overlap a new apply range so markers do not stack. */
export function refSegmentsWithoutOverlap(
  segments: RefSegmentRecord[],
  nextSegment: Pick<RefSegmentRecord, 'id' | 'anchor_shot_id' | 'end_shot_id'>,
  shots: Pick<Shot, 'shot_id'>[],
): RefSegmentRecord[] {
  const nextId = nextSegment.id ? String(nextSegment.id) : ''
  return segments.filter((segment) => {
    if (!segment.id || String(segment.id) === nextId) return false
    return !segmentsOverlapBoardRange(segment, nextSegment, shots)
  })
}

export function segmentHasPendingBoards(
  segment: RefSegmentRecord,
  shots: Shot[],
  links: ReferenceLink[],
): boolean {
  const parsed = parseSegmentRecord(segment, shots, links)
  if (!parsed) return false
  for (let i = parsed.lo; i <= parsed.hi; i += 1) {
    if (!isShotAppliedToSegment(shots[i], segment, links)) return true
  }
  return false
}
