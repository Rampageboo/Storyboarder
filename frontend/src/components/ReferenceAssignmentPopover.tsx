import { useEffect, useMemo, useRef, useState } from 'react'
import {
  applyRefSegment,
  applyRefSegment3d,
  applyRefSegmentImage,
  projectFileUrl,
  restoreRefApply,
  updateSettings,
  uploadProjectReference,
  type ApplyRefSegmentRequest,
} from '../api'
import type { ProjectPayload, ReferenceLink } from '../types'
import { useProject } from '../state/ProjectContext'
import { shotDisplayLabel } from '../utils/shotDisplay'
import './ReferenceAssignmentPopover.css'

type Segment = {
  id?: string
  anchor_shot_id?: string
  end_shot_id?: string
  source_type?: string
  reference_id?: string
  reference_path?: string
  video_start?: number
  [key: string]: unknown
}

function newSegmentId(): string {
  const c = globalThis.crypto as Crypto | undefined
  if (c && typeof c.randomUUID === 'function') return c.randomUUID().replace(/-/g, '')
  return `seg_${Date.now().toString(36)}${Math.floor(Math.random() * 1e6).toString(36)}`
}

function fileName(path: string) {
  return path.split(/[/\\]/).pop() || path
}

function segmentDurationSeconds(shots: { duration_seconds?: number }[], lo: number, hi: number) {
  let total = 0
  for (let i = lo; i <= hi; i += 1) {
    total += Math.max(0.1, shots[i]?.duration_seconds ?? 3)
  }
  return total
}

function RefThumb({ link, selected }: { link: ReferenceLink; selected: boolean }) {
  const [failed, setFailed] = useState(false)
  const url = projectFileUrl(link.path)

  useEffect(() => {
    setFailed(false)
  }, [link.id, link.path])

  return (
    <div className={`ref-assign-ref-thumb ${selected ? 'is-selected' : ''}`}>
      {link.type === 'model' ? (
        <div className="ref-assign-ref-fallback">3D</div>
      ) : failed ? (
        <div className="ref-assign-ref-fallback">{link.type}</div>
      ) : link.type === 'video' ? (
        <video src={url} muted preload="metadata" playsInline onError={() => setFailed(true)} />
      ) : (
        <img src={url} alt="" loading="lazy" onError={() => setFailed(true)} />
      )}
    </div>
  )
}

function BoardSegmentViz({
  shotCount,
  lo,
  hi,
  mode,
}: {
  shotCount: number
  lo: number
  hi: number
  mode: string
}) {
  const trackRef = useRef<HTMLDivElement | null>(null)
  const cells = useMemo(() => Array.from({ length: shotCount }, (_, i) => i), [shotCount])
  const inRange = (i: number) => i >= lo && i <= hi

  useEffect(() => {
    const track = trackRef.current
    if (!track || lo < 0) return
    const cell = track.querySelector(`[data-board-index="${lo}"]`)
    if (cell instanceof HTMLElement) {
      cell.scrollIntoView({ block: 'nearest', inline: 'center', behavior: 'smooth' })
    }
  }, [lo, hi])

  if (shotCount === 0 || lo < 0 || hi < 0) {
    return <div className="ref-assign-seg-viz ref-assign-seg-viz--empty">No boards in range</div>
  }

  const spanLeft = (lo / shotCount) * 100
  const spanWidth = ((hi - lo + 1) / shotCount) * 100

  return (
    <div className={`ref-assign-seg-viz ref-assign-seg-viz--${mode}`}>
      <div className="ref-assign-seg-rail" aria-hidden="true" />
      <div
        className="ref-assign-seg-bar"
        style={{ left: `${spanLeft}%`, width: `${spanWidth}%` }}
        title={`Boards #${lo + 1}–#${hi + 1}`}
      />
      <div className="ref-assign-seg-track" ref={trackRef}>
        {cells.map((i) => (
          <div
            key={i}
            data-board-index={i}
            className={[
              'ref-assign-seg-cell',
              inRange(i) ? 'in-range' : '',
              i === lo ? 'range-start' : '',
              i === hi ? 'range-end' : '',
            ]
              .filter(Boolean)
              .join(' ')}
            title={`Board #${i + 1}`}
          >
            <span className="ref-assign-seg-dot" />
          </div>
        ))}
      </div>
    </div>
  )
}

export function ReferenceAssignmentPopover() {
  const {
    project,
    flushDirtyShots,
    setProject,
    projectActionBusy,
    reportError,
    segmentRange,
    setSegmentAnchor,
    setSegmentEnd,
    clearSegmentRange,
    refApplyUndoToken,
    setRefApplyUndoToken,
  } = useProject()
  const [busy, setBusy] = useState(false)
  const [refId, setRefId] = useState('')
  const [startTime, setStartTime] = useState('0')
  const [toast, setToast] = useState('')
  const [previewFailed, setPreviewFailed] = useState(false)
  const importRef = useRef<HTMLInputElement | null>(null)

  const links = useMemo(() => project?.settings?.reference_links ?? [], [project?.settings?.reference_links])
  const segments = useMemo(
    () => (project?.settings?.ref_segments ?? []) as unknown as Segment[],
    [project?.settings?.ref_segments],
  )
  const shots = project?.shots ?? []

  const startShot = segmentRange.anchorShotId ?? ''
  const endShot = segmentRange.endShotId ?? ''
  const open = !!(startShot && endShot)

  const anchorIdx = startShot ? shots.findIndex((s) => s.shot_id === startShot) : -1
  const endIdx = endShot ? shots.findIndex((s) => s.shot_id === endShot) : -1
  const lo = anchorIdx >= 0 && endIdx >= 0 ? Math.min(anchorIdx, endIdx) : -1
  const hi = anchorIdx >= 0 && endIdx >= 0 ? Math.max(anchorIdx, endIdx) : -1
  const boardCount = lo >= 0 && hi >= 0 ? hi - lo + 1 : 0
  const durationSec = lo >= 0 && hi >= 0 ? segmentDurationSeconds(shots, lo, hi) : 0

  useEffect(() => {
    setRefId((cur) => (cur && links.some((l) => l.id === cur) ? cur : links[0]?.id ?? ''))
  }, [links])

  useEffect(() => {
    setPreviewFailed(false)
  }, [refId])

  useEffect(() => {
    if (!toast) return
    const t = window.setTimeout(() => setToast(''), 3200)
    return () => window.clearTimeout(t)
  }, [toast])

  if (!project || !open) {
    return toast ? <div className="ref-assign-toast">{toast}</div> : null
  }

  const disabled = busy || projectActionBusy
  const selectedRef = links.find((l) => l.id === refId) || null
  const refMode = selectedRef?.type ?? 'none'
  const previewUrl = selectedRef ? projectFileUrl(selectedRef.path) : ''
  const previewLabel = selectedRef ? selectedRef.title || fileName(selectedRef.path) : 'No reference selected'
  const segmentTypeLabel =
    refMode === 'image' ? 'Image' : refMode === 'video' ? 'Video' : refMode === 'model' ? '3D' : 'Reference'
  const boardLabel = lo === hi ? `#${lo + 1}` : `#${lo + 1}–#${hi + 1}`

  const shotLabel = (id: string) => {
    const s = shots.find((sh) => sh.shot_id === id)
    return s ? shotDisplayLabel(s) : id
  }

  const cancel = () => {
    clearSegmentRange()
  }

  const importReference = (file: File | undefined) => {
    if (!file) return
    setBusy(true)
    void (async () => {
      try {
        await flushDirtyShots()
        const payload = await uploadProjectReference(file)
        setProject(payload)
        const imported = payload.settings?.reference_links?.find((l) => l.path.includes(file.name))
        if (imported) setRefId(imported.id)
      } catch (error) {
        reportError(error)
      } finally {
        setBusy(false)
      }
    })()
  }

  const applySegment = () => {
    if (!selectedRef) {
      window.alert('Choose a source reference first.')
      return
    }
    if (!startShot || !endShot) return
    const start = Number(startTime)
    const videoStart = Number.isFinite(start) && start > 0 ? start : 0
    const segId = newSegmentId()
    const seg: Segment = {
      id: segId,
      anchor_shot_id: startShot,
      end_shot_id: endShot,
      source_type: selectedRef.type,
      reference_id: selectedRef.id,
      reference_path: selectedRef.path,
      video_start: videoStart,
    }
    setBusy(true)
    void (async () => {
      try {
        await flushDirtyShots()
        const existing = segments.filter((s) => s.id && s.id !== segId)
        await updateSettings({ ref_segments: [...existing, seg], active_ref_segment_id: segId })
        const body: ApplyRefSegmentRequest = { anchor_shot_id: startShot, end_shot_id: endShot, segment_id: segId }
        let payload: ProjectPayload
        if (selectedRef.type === 'image') payload = await applyRefSegmentImage(body)
        else if (selectedRef.type === 'model') payload = await applyRefSegment3d({ ...body, camera_name: '' })
        else payload = await applyRefSegment(body)
        setProject(payload)
        const result = payload as unknown as { board_count?: number; undo_token?: string }
        const count = result.board_count ?? boardCount
        setRefApplyUndoToken(typeof result.undo_token === 'string' ? result.undo_token : null)
        clearSegmentRange()
        setToast(`Applied to ${count} board${count === 1 ? '' : 's'}`)
      } catch (error) {
        reportError(error)
      } finally {
        setBusy(false)
      }
    })()
  }

  const undoLastApply = () => {
    if (!refApplyUndoToken) return
    setBusy(true)
    void (async () => {
      try {
        await flushDirtyShots()
        setProject(await restoreRefApply(refApplyUndoToken))
        setRefApplyUndoToken(null)
        setToast('Reference apply undone.')
      } catch (error) {
        reportError(error)
      } finally {
        setBusy(false)
      }
    })()
  }

  return (
    <>
      <div className="ref-assign-backdrop" onClick={cancel} aria-hidden="true" />
      <div
        className={`ref-assign-modal ref-assign-modal--${refMode}`}
        role="dialog"
        aria-modal="true"
        aria-label="Assign reference to board range"
      >
        <div className="ref-assign-modal-header">
          <h3>Reference segment</h3>
          <button type="button" className="ref-assign-close" onClick={cancel} aria-label="Cancel">
            ×
          </button>
        </div>

        <div className="ref-assign-layout">
          <aside className="ref-assign-refs" aria-label="References">
            <div className="ref-assign-refs-head">
              <span>References</span>
              <button type="button" onClick={() => importRef.current?.click()} disabled={disabled}>
                Import
              </button>
            </div>
            <input
              ref={importRef}
              type="file"
              accept="image/*,video/*,.glb,.gltf"
              hidden
              onChange={(e) => {
                importReference(e.target.files?.[0] ?? undefined)
                e.target.value = ''
              }}
            />
            {links.length === 0 ? (
              <div className="ref-assign-refs-empty">Import images, video, or GLB models.</div>
            ) : (
              <div className="ref-assign-ref-list">
                {links.map((link) => {
                  const label = link.title || fileName(link.path)
                  const selected = refId === link.id
                  return (
                    <button
                      key={link.id}
                      type="button"
                      className={`ref-assign-ref-item ${selected ? 'is-selected' : ''}`}
                      onClick={() => setRefId(link.id)}
                      title={link.path}
                    >
                      <RefThumb link={link} selected={selected} />
                      <span className="ref-assign-ref-name">{label}</span>
                      <span className="ref-assign-ref-type">{link.type}</span>
                    </button>
                  )
                })}
              </div>
            )}
          </aside>

          <main className="ref-assign-main">
            <div className="ref-assign-preview-head">
              <span className="ref-assign-section-label">{segmentTypeLabel} segment</span>
              <span className="ref-assign-preview-meta">{previewLabel}</span>
            </div>

            <div className="ref-assign-player">
              {!selectedRef ? (
                <div className="ref-assign-player-empty">Select a reference on the left</div>
              ) : selectedRef.type === 'model' ? (
                <div className="ref-assign-player-empty">3D model · {previewLabel}</div>
              ) : previewFailed ? (
                <div className="ref-assign-player-empty">Preview unavailable</div>
              ) : selectedRef.type === 'video' ? (
                <video
                  key={selectedRef.id}
                  src={previewUrl}
                  controls
                  preload="metadata"
                  playsInline
                  onError={() => setPreviewFailed(true)}
                />
              ) : (
                <img
                  key={selectedRef.id}
                  src={previewUrl}
                  alt={previewLabel}
                  onError={() => setPreviewFailed(true)}
                />
              )}
            </div>

            {selectedRef?.type === 'video' ? (
              <label className="ref-assign-field ref-assign-field--inline">
                <span>Start time (s)</span>
                <input
                  type="number"
                  min="0"
                  step="0.1"
                  value={startTime}
                  onChange={(e) => setStartTime(e.target.value)}
                  disabled={disabled}
                />
              </label>
            ) : null}

            <section className="ref-assign-segment-box">
              <div className="ref-assign-segment-toolbar">
                <span className="ref-assign-section-label">Board segment</span>
                <div className="ref-assign-board-picks">
                  <select value={startShot} onChange={(e) => setSegmentAnchor(e.target.value || null)} disabled={disabled}>
                    {shots.map((s) => (
                      <option key={s.shot_id} value={s.shot_id}>
                        {shotLabel(s.shot_id)}
                      </option>
                    ))}
                  </select>
                  <span>→</span>
                  <select value={endShot} onChange={(e) => setSegmentEnd(e.target.value || null)} disabled={disabled}>
                    {shots.map((s) => (
                      <option key={s.shot_id} value={s.shot_id}>
                        {shotLabel(s.shot_id)}
                      </option>
                    ))}
                  </select>
                </div>
                <button
                  type="button"
                  className="ref-assign-apply"
                  onClick={() => applySegment()}
                  disabled={disabled || !links.length || shots.length === 0}
                >
                  Apply to boards
                </button>
              </div>

              <BoardSegmentViz shotCount={shots.length} lo={lo} hi={hi} mode={refMode} />

              <div className="ref-assign-segment-summary">
                <span>
                  {segmentTypeLabel.toLowerCase()} segment: {durationSec.toFixed(1)}s · boards {boardLabel}
                </span>
                <span>
                  reference segment: {durationSec.toFixed(1)}s · boards {boardLabel}
                </span>
              </div>
            </section>

            <div className="ref-assign-footer">
              <button type="button" onClick={cancel} disabled={disabled}>
                Cancel / clear range
              </button>
              {refApplyUndoToken ? (
                <button type="button" onClick={() => undoLastApply()} disabled={disabled}>
                  Undo last apply
                </button>
              ) : null}
            </div>
          </main>
        </div>
      </div>
      {toast ? <div className="ref-assign-toast">{toast}</div> : null}
    </>
  )
}
