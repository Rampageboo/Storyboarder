import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  applyRefSegment,
  applyRefSegment3d,
  applyRefSegmentImage,
  deleteRefSegment,
  projectFileUrl,
  removeShotImage,
  restoreRefApply,
  updateSettings,
  uploadProjectReference,
  type ApplyRefSegmentRequest,
} from '../api'
import type { ProjectPayload, ReferenceLink } from '../types'
import { useProject } from '../state/ProjectContext'
import { shotDisplayLabel } from '../utils/shotDisplay'
import { findRefSegment, segmentHasPendingBoards } from '../utils/refSegmentDisplay'
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

type FitMode = 'fit' | 'fill' | 'stretch'

const FIT_MODES: FitMode[] = ['fit', 'fill', 'stretch']

function fitModeToObjectFit(mode: FitMode): 'contain' | 'cover' | 'fill' {
  if (mode === 'fill') return 'cover'
  if (mode === 'stretch') return 'fill'
  return 'contain'
}

function normalizeFitMode(value: unknown): FitMode {
  const mode = String(value || 'fit').trim().toLowerCase()
  return FIT_MODES.includes(mode as FitMode) ? (mode as FitMode) : 'fit'
}

function formatClock(seconds: number) {
  const totalMs = Math.max(0, Math.round((Number(seconds) || 0) * 1000))
  const mins = Math.floor(totalMs / 60000)
  const secs = Math.floor((totalMs % 60000) / 1000)
  const ms = totalMs % 1000
  return `${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}.${String(ms).padStart(3, '0')}`
}

function maxMediaSegmentStart(mediaDuration: number, boardDuration: number, mode: string) {
  if (mode === 'image') return 0
  if (!mediaDuration) return 0
  const segLen = Math.max(0.001, boardDuration)
  if (segLen >= mediaDuration) return 0
  return Math.max(0, mediaDuration - segLen)
}

function clampMediaSegmentStart(
  start: number,
  mediaDuration: number,
  boardDuration: number,
  mode: string,
) {
  if (mode === 'image') return 0
  return Math.min(maxMediaSegmentStart(mediaDuration, boardDuration, mode), Math.max(0, Number(start) || 0))
}

function segmentVisualEnd(start: number, mediaDuration: number, boardDuration: number, mode: string) {
  const segLen = Math.max(0.001, boardDuration)
  if (mode === 'image') return segLen
  if (!mediaDuration) return start + segLen
  return Math.min(start + segLen, mediaDuration)
}

const TIMELINE_INSET = 12

function MediaSegmentTimeline({
  mode,
  mediaDuration,
  boardDuration,
  segmentStart,
  playheadTime,
  onSegmentStartChange,
}: {
  mode: string
  mediaDuration: number
  boardDuration: number
  segmentStart: number
  playheadTime: number
  onSegmentStartChange: (start: number) => void
}) {
  const timelineRef = useRef<HTMLDivElement | null>(null)
  const dragRef = useRef<{ startX: number; segmentStart: number; pointerId: number } | null>(null)
  const [dragging, setDragging] = useState(false)

  const segLen = Math.max(0.001, boardDuration)
  const trackDuration = mode === 'image' ? segLen : mediaDuration
  const draggable = mode !== 'image' && trackDuration > 0 && boardDuration > 0
  const start = clampMediaSegmentStart(segmentStart, mediaDuration, boardDuration, mode)

  useEffect(() => {
    const onMove = (event: PointerEvent) => {
      const drag = dragRef.current
      const timeline = timelineRef.current
      if (!drag || !timeline || !draggable) return
      const rect = timeline.getBoundingClientRect()
      const innerWidth = Math.max(1, rect.width - TIMELINE_INSET * 2)
      const deltaSec = ((event.clientX - drag.startX) / innerWidth) * mediaDuration
      onSegmentStartChange(
        clampMediaSegmentStart(drag.segmentStart + deltaSec, mediaDuration, boardDuration, mode),
      )
    }

    const onUp = (event: PointerEvent) => {
      if (!dragRef.current) return
      dragRef.current = null
      setDragging(false)
      try {
        timelineRef.current?.releasePointerCapture(event.pointerId)
      } catch {
        // ignore
      }
    }

    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
    window.addEventListener('pointercancel', onUp)
    return () => {
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
      window.removeEventListener('pointercancel', onUp)
    }
  }, [boardDuration, draggable, mediaDuration, mode, onSegmentStartChange])

  if (!trackDuration || boardDuration <= 0) {
    return <div className="ref-assign-seg-viz ref-assign-seg-viz--empty">Select boards on the filmstrip first</div>
  }

  const startPct = mode === 'image' ? 0 : (100 * start) / trackDuration
  const widthPct =
    mode === 'image' ? 100 : Math.min((100 * segLen) / trackDuration, Math.max(0, 100 - startPct))
  const playheadPct = trackDuration > 0 ? (100 * Math.max(0, playheadTime)) / trackDuration : 0

  return (
    <div
      ref={timelineRef}
      className={`ref-assign-seg-viz ref-assign-seg-viz--${mode} ${dragging ? 'is-dragging' : ''}`}
      aria-label="Reference media segment"
    >
      <div className="ref-assign-seg-rail" aria-hidden="true" />
      <div className="ref-assign-seg-layer">
        <div
          className={`ref-assign-seg-bar ${draggable ? 'is-draggable' : ''}`}
          style={{ left: `${startPct}%`, width: `${Math.max(mode === 'image' ? 100 : 0.25, widthPct)}%` }}
          title={draggable ? 'Drag to choose which part of the reference maps to these boards' : undefined}
          onPointerDown={(event) => {
            if (!draggable || event.button !== 0) return
            event.preventDefault()
            event.stopPropagation()
            dragRef.current = {
              startX: event.clientX,
              segmentStart: start,
              pointerId: event.pointerId,
            }
            setDragging(true)
            timelineRef.current?.setPointerCapture(event.pointerId)
          }}
        />
        {mode !== 'image' ? (
          <div className="ref-assign-seg-playhead" style={{ left: `${playheadPct}%` }} aria-hidden="true" />
        ) : null}
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
    activeAppliedSegmentId,
    dismissRefSegmentUi,
    refSegmentInspectOpen,
    closeRefSegmentInspect,
    refApplyUndoToken,
    setRefApplyUndoToken,
  } = useProject()
  const [busy, setBusy] = useState(false)
  const [refId, setRefId] = useState('')
  const [formAnchorShotId, setFormAnchorShotId] = useState('')
  const [formEndShotId, setFormEndShotId] = useState('')
  const [fitMode, setFitMode] = useState<FitMode>('fit')
  const [segmentStart, setSegmentStart] = useState(0)
  const [mediaDuration, setMediaDuration] = useState(0)
  const [playheadTime, setPlayheadTime] = useState(0)
  const [toast, setToast] = useState('')
  const [previewFailed, setPreviewFailed] = useState(false)
  const importRef = useRef<HTMLInputElement | null>(null)
  const previewVideoRef = useRef<HTMLVideoElement | null>(null)

  const links = useMemo(() => project?.settings?.reference_links ?? [], [project?.settings?.reference_links])
  const segments = useMemo(
    () => (project?.settings?.ref_segments ?? []) as unknown as Segment[],
    [project?.settings?.ref_segments],
  )
  const shots = project?.shots ?? []

  const draftComplete = !!(segmentRange.anchorShotId && segmentRange.endShotId)
  const isInspectMode = refSegmentInspectOpen && !!activeAppliedSegmentId && !draftComplete
  const open = draftComplete || isInspectMode
  const inspectSegment = useMemo(
    () => findRefSegment(segments, activeAppliedSegmentId),
    [segments, activeAppliedSegmentId],
  )

  const startShot = isInspectMode ? formAnchorShotId : (segmentRange.anchorShotId ?? '')
  const endShot = isInspectMode ? formEndShotId : (segmentRange.endShotId ?? '')

  const anchorIdx = startShot ? shots.findIndex((s) => s.shot_id === startShot) : -1
  const endIdx = endShot ? shots.findIndex((s) => s.shot_id === endShot) : -1
  const lo = anchorIdx >= 0 && endIdx >= 0 ? Math.min(anchorIdx, endIdx) : -1
  const hi = anchorIdx >= 0 && endIdx >= 0 ? Math.max(anchorIdx, endIdx) : -1
  const boardCount = lo >= 0 && hi >= 0 ? hi - lo + 1 : 0
  const durationSec = lo >= 0 && hi >= 0 ? segmentDurationSeconds(shots, lo, hi) : 0
  const selectedRef = useMemo(() => links.find((l) => l.id === refId) ?? null, [links, refId])
  const refMode = selectedRef?.type ?? 'none'
  const hasPendingBoards = useMemo(() => {
    const seg = isInspectMode ? inspectSegment : null
    if (!seg) return false
    return segmentHasPendingBoards(seg, shots, links)
  }, [isInspectMode, inspectSegment, shots, links])

  useEffect(() => {
    if (!isInspectMode || !inspectSegment) return
    const ref = inspectSegment.reference_id
      ? String(inspectSegment.reference_id)
      : links.find((l) => l.path === inspectSegment.reference_path)?.id ?? ''
    if (ref) setRefId(ref)
    setFormAnchorShotId(String(inspectSegment.anchor_shot_id || ''))
    setFormEndShotId(String(inspectSegment.end_shot_id || ''))
    setFitMode(normalizeFitMode(inspectSegment.fit_mode))
    const start = Number(inspectSegment.video_start)
    setSegmentStart(Number.isFinite(start) && start > 0 ? start : 0)
    setPreviewFailed(false)
    setPlayheadTime(0)
    setMediaDuration(0)
  }, [isInspectMode, inspectSegment, links])

  useEffect(() => {
    setPreviewFailed(false)
    if (isInspectMode) return
    setFitMode('fit')
    setSegmentStart(0)
    setMediaDuration(0)
    setPlayheadTime(0)
  }, [refId, isInspectMode])

  useEffect(() => {
    if (isInspectMode) return
    setRefId((cur) => (cur && links.some((l) => l.id === cur) ? cur : links[0]?.id ?? ''))
  }, [links, isInspectMode])

  useEffect(() => {
    if (isInspectMode) return
    setSegmentStart(0)
  }, [startShot, endShot, isInspectMode])

  useEffect(() => {
    if (refMode === 'model' && durationSec > 0) {
      setMediaDuration((cur) => Math.max(cur, Math.max(durationSec * 2, 30)))
    }
  }, [refMode, durationSec])

  const updateSegmentStart = useCallback(
    (next: number) => {
      const clamped = clampMediaSegmentStart(next, mediaDuration, durationSec, refMode)
      setSegmentStart(clamped)
      if (refMode === 'video' && previewVideoRef.current) {
        previewVideoRef.current.currentTime = clamped
        setPlayheadTime(clamped)
      }
    },
    [durationSec, mediaDuration, refMode],
  )

  useEffect(() => {
    if (!refSegmentInspectOpen || !activeAppliedSegmentId || draftComplete) return
    if (!findRefSegment(segments, activeAppliedSegmentId)) dismissRefSegmentUi()
  }, [refSegmentInspectOpen, activeAppliedSegmentId, draftComplete, segments, dismissRefSegmentUi])

  useEffect(() => {
    if (!toast) return
    const t = window.setTimeout(() => setToast(''), 3200)
    return () => window.clearTimeout(t)
  }, [toast])

  if (!project || !open) {
    return toast ? <div className="ref-assign-toast">{toast}</div> : null
  }

  const disabled = busy || projectActionBusy
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
    if (isInspectMode) closeRefSegmentInspect()
    else dismissRefSegmentUi()
  }

  const setFormStartShot = (shotId: string | null) => {
    if (isInspectMode) setFormAnchorShotId(shotId ?? '')
    else setSegmentAnchor(shotId)
  }

  const setFormEndShot = (shotId: string | null) => {
    if (isInspectMode) setFormEndShotId(shotId ?? '')
    else setSegmentEnd(shotId)
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
    const segId = isInspectMode && activeAppliedSegmentId ? activeAppliedSegmentId : newSegmentId()
    const seg: Segment = {
      id: segId,
      anchor_shot_id: startShot,
      end_shot_id: endShot,
      source_type: selectedRef.type,
      reference_id: selectedRef.id,
      reference_path: selectedRef.path,
      video_start: clampMediaSegmentStart(segmentStart, mediaDuration, durationSec, refMode),
      fit_mode: fitMode,
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
        if (isInspectMode) closeRefSegmentInspect()
        else dismissRefSegmentUi()
        setToast(
          isInspectMode
            ? `Reapplied to ${count} board${count === 1 ? '' : 's'}`
            : `Applied to ${count} board${count === 1 ? '' : 's'}`,
        )
      } catch (error) {
        reportError(error)
      } finally {
        setBusy(false)
      }
    })()
  }

  const deleteSegment = () => {
    if (!activeAppliedSegmentId) return
    if (!window.confirm('Delete this applied reference segment and clear its generated board backgrounds/previews?')) return
    const appliedShotIds = shots
      .filter((shot) => String(shot.camera_data?.ref_segment_id || '').trim() === activeAppliedSegmentId)
      .map((shot) => shot.shot_id)
    const rangeShotIds = inspectSegment
      ? shots
          .slice(
            Math.max(0, Math.min(anchorIdx, endIdx)),
            Math.max(0, Math.max(anchorIdx, endIdx)) + 1,
          )
          .map((shot) => shot.shot_id)
      : []
    const shotIdsToClear = Array.from(new Set(appliedShotIds.length ? appliedShotIds : rangeShotIds))
    setBusy(true)
    void (async () => {
      try {
        await flushDirtyShots()
        let payload = await deleteRefSegment(activeAppliedSegmentId)
        for (const shotId of shotIdsToClear) {
          payload = await removeShotImage(shotId)
        }
        setProject(payload)
        dismissRefSegmentUi()
        setToast(
          shotIdsToClear.length
            ? `Reference segment deleted; cleared ${shotIdsToClear.length} board${shotIdsToClear.length === 1 ? '' : 's'}.`
            : 'Reference segment deleted.',
        )
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

  const previewObjectFit = fitModeToObjectFit(fitMode)
  const visualEnd = segmentVisualEnd(segmentStart, mediaDuration, durationSec, refMode)
  const segmentSummaryPrimary =
    refMode === 'image'
      ? `Image segment: ${durationSec.toFixed(1)}s · boards ${boardLabel}`
      : refMode === 'model'
        ? `3D segment: ${formatClock(durationSec)} · anim ${formatClock(segmentStart)} → ${formatClock(visualEnd)} · boards ${boardLabel}`
        : `Video segment: ${formatClock(durationSec)} · ${formatClock(segmentStart)} → ${formatClock(visualEnd)} · boards ${boardLabel}`
  const segmentSummarySecondary = `Reference segment: ${durationSec.toFixed(1)}s · boards ${boardLabel}`

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
          <h3>{isInspectMode ? 'Inspect reference segment' : 'Reference segment'}</h3>
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
            {hasPendingBoards ? (
              <div className="ref-assign-pending-note" role="status">
                Some boards in this segment range have not been applied yet. Reapply to regenerate the full range.
              </div>
            ) : null}
            <div className="ref-assign-preview-head">
              <span className="ref-assign-section-label">{segmentTypeLabel} segment</span>
              <span className="ref-assign-preview-meta">{previewLabel}</span>
            </div>

            <div className="ref-assign-player">
              {!selectedRef ? (
                <div className="ref-assign-player-empty">Select a reference on the left</div>
              ) : selectedRef.type === 'model' ? (
                <div className="ref-assign-player-empty ref-assign-player-model-safe">
                  <strong>3D model reference</strong>
                  <span>{previewLabel}</span>
                  <span>Inline GLB rendering is disabled here to keep the assignment UI stable.</span>
                  <button type="button" onClick={() => window.open('/ref-scene3d', '_blank', 'noopener')}>
                    Open 3D viewer
                  </button>
                </div>
              ) : previewFailed ? (
                <div className="ref-assign-player-empty">Preview unavailable</div>
              ) : selectedRef.type === 'video' ? (
                <video
                  ref={previewVideoRef}
                  key={selectedRef.id}
                  src={previewUrl}
                  controls
                  preload="metadata"
                  playsInline
                  style={{ objectFit: previewObjectFit }}
                  onLoadedMetadata={(event) => {
                    const duration = event.currentTarget.duration
                    if (Number.isFinite(duration) && duration > 0) setMediaDuration(duration)
                  }}
                  onTimeUpdate={(event) => setPlayheadTime(event.currentTarget.currentTime || 0)}
                  onError={() => setPreviewFailed(true)}
                />
              ) : (
                <img
                  key={selectedRef.id}
                  src={previewUrl}
                  alt={previewLabel}
                  style={{ objectFit: previewObjectFit }}
                  onError={() => setPreviewFailed(true)}
                />
              )}
            </div>

            <div className="ref-assign-fit-mode" role="group" aria-label="Reference fit">
              <span className="ref-assign-fit-label">Fit</span>
              {FIT_MODES.map((mode) => (
                <button
                  key={mode}
                  type="button"
                  className={`ref-assign-fit-btn ${fitMode === mode ? 'is-active' : ''}`}
                  title={
                    mode === 'fit'
                      ? 'Fit inside canvas'
                      : mode === 'fill'
                        ? 'Fill canvas, crop edges'
                        : 'Stretch to canvas'
                  }
                  onClick={() => setFitMode(normalizeFitMode(mode))}
                  disabled={disabled}
                >
                  {mode === 'fit' ? 'Fit' : mode === 'fill' ? 'Fill' : 'Stretch'}
                </button>
              ))}
            </div>

            <section className="ref-assign-segment-box">
              <div className="ref-assign-segment-toolbar">
                <span className="ref-assign-section-label">Board segment</span>
                <div className="ref-assign-board-picks">
                  <select value={startShot} onChange={(e) => setFormStartShot(e.target.value || null)} disabled={disabled}>
                    {shots.map((s) => (
                      <option key={s.shot_id} value={s.shot_id}>
                        {shotLabel(s.shot_id)}
                      </option>
                    ))}
                  </select>
                  <span>→</span>
                  <select value={endShot} onChange={(e) => setFormEndShot(e.target.value || null)} disabled={disabled}>
                    {shots.map((s) => (
                      <option key={s.shot_id} value={s.shot_id}>
                        {shotLabel(s.shot_id)}
                      </option>
                    ))}
                  </select>
                </div>
                <button
                  type="button"
                  className="ref-assign-reset-start"
                  onClick={() => updateSegmentStart(0)}
                  disabled={disabled || refMode === 'image' || segmentStart <= 0}
                >
                  Reset start
                </button>
                <button
                  type="button"
                  className="ref-assign-apply"
                  onClick={() => applySegment()}
                  disabled={disabled || !links.length || shots.length === 0}
                >
                  {isInspectMode ? 'Reapply to boards' : 'Apply to boards'}
                </button>
                {isInspectMode ? (
                  <button type="button" className="ref-assign-delete" onClick={() => deleteSegment()} disabled={disabled}>
                    Delete segment
                  </button>
                ) : null}
              </div>

              <MediaSegmentTimeline
                mode={refMode}
                mediaDuration={mediaDuration}
                boardDuration={durationSec}
                segmentStart={segmentStart}
                playheadTime={playheadTime}
                onSegmentStartChange={updateSegmentStart}
              />

              <div className="ref-assign-segment-summary">
                <span>{segmentSummaryPrimary}</span>
                <span>{segmentSummarySecondary}</span>
              </div>
            </section>

            <div className="ref-assign-footer">
              <button type="button" onClick={cancel} disabled={disabled}>
                {isInspectMode ? 'Close' : 'Cancel / clear range'}
              </button>
              {isInspectMode ? (
                <button type="button" className="primary" onClick={() => applySegment()} disabled={disabled || !links.length}>
                  Reapply
                </button>
              ) : null}
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
