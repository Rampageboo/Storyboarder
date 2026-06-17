import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from 'react'
import { addShot, deleteRefSegment, deleteShot, getMissingFiles, moveShotDown, moveShotUp } from '../api'
import { useProject } from '../state/ProjectContext'
import { shotDisplayLabel } from '../utils/shotDisplay'
import {
  resolveVisibleSegmentMarkerSpans,
  segmentCssType,
  segmentMarkerTooltip,
  type RefSegmentRecord,
} from '../utils/refSegmentDisplay'
import { shotHasPreview, shotThumbVersion } from '../utils/shotPreview'
import { ShotThumb } from './ShotThumb'
import './BoardStrip.css'

function scrollCardIntoViewport(viewport: HTMLElement, card: HTMLElement) {
  const pad = 8
  const cardLeft = card.offsetLeft
  const cardRight = cardLeft + card.offsetWidth
  const viewLeft = viewport.scrollLeft
  const viewRight = viewLeft + viewport.clientWidth

  if (cardLeft < viewLeft + pad) {
    viewport.scrollTo({ left: Math.max(0, cardLeft - pad), behavior: 'smooth' })
  } else if (cardRight > viewRight - pad) {
    viewport.scrollTo({ left: cardRight - viewport.clientWidth + pad, behavior: 'smooth' })
  }
}

export function BoardStrip() {
  const {
    project,
    selectedShotId,
    setSelectedShotId,
    setProject,
    flushDirtyShots,
    isShotDirty,
    initialLoading,
    projectActionBusy,
    visualEpoch,
    segmentRange,
    pickSegmentShot,
    clearSegmentRange,
    activeAppliedSegmentId,
    setActiveAppliedSegmentId,
    openRefSegmentInspect,
    closeRefSegmentInspect,
    dismissRefSegmentUi,
    reportError,
  } = useProject()
  const [busy, setBusy] = useState(false)
  const [segmentDeleting, setSegmentDeleting] = useState(false)
  const [missingShots, setMissingShots] = useState<Set<string>>(new Set())
  const viewportRef = useRef<HTMLDivElement | null>(null)
  const markerClickTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const shots = project?.shots ?? []
  const selectedIndex = useMemo(() => shots.findIndex((s) => s.shot_id === selectedShotId), [shots, selectedShotId])
  const disabled = busy || projectActionBusy || initialLoading

  // Reference-segment range (normalized by board order for display + the connecting line).
  const anchorIdx = segmentRange.anchorShotId ? shots.findIndex((s) => s.shot_id === segmentRange.anchorShotId) : -1
  const endIdx = segmentRange.endShotId ? shots.findIndex((s) => s.shot_id === segmentRange.endShotId) : -1
  const bothSet = anchorIdx >= 0 && endIdx >= 0
  const lo = bothSet ? Math.min(anchorIdx, endIdx) : -1
  const hi = bothSet ? Math.max(anchorIdx, endIdx) : -1
  const showDraftLine = bothSet && !activeAppliedSegmentId

  const referenceLinks = project?.settings?.reference_links ?? []
  const visibleMarkers = useMemo(
    () =>
      resolveVisibleSegmentMarkerSpans(
        (project?.settings?.ref_segments ?? []) as RefSegmentRecord[],
        shots,
        referenceLinks,
        activeAppliedSegmentId,
      ),
    [project?.settings?.ref_segments, shots, referenceLinks, activeAppliedSegmentId],
  )

  const selectedMarker = useMemo(() => {
    if (!activeAppliedSegmentId) return null
    return visibleMarkers.find((m) => m.segmentId === activeAppliedSegmentId) ?? null
  }, [visibleMarkers, activeAppliedSegmentId])
  const rangeLabel = showDraftLine
    ? `Selecting reference: #${lo + 1} → #${hi + 1}`
    : anchorIdx >= 0 && !segmentRange.endShotId && !activeAppliedSegmentId
      ? `Reference start: #${anchorIdx + 1} (pick end board)`
      : selectedMarker
        ? segmentMarkerTooltip(selectedMarker)
        : ''

  const selectAppliedSegment = useCallback(
    (segmentId: string) => {
      setActiveAppliedSegmentId(segmentId)
      closeRefSegmentInspect()
    },
    [setActiveAppliedSegmentId, closeRefSegmentInspect],
  )

  const handleMarkerClick = useCallback(
    (segmentId: string) => {
      if (markerClickTimerRef.current) clearTimeout(markerClickTimerRef.current)
      markerClickTimerRef.current = setTimeout(() => {
        selectAppliedSegment(segmentId)
        markerClickTimerRef.current = null
      }, 220)
    },
    [selectAppliedSegment],
  )

  const handleMarkerDoubleClick = useCallback(
    (segmentId: string) => {
      if (markerClickTimerRef.current) {
        clearTimeout(markerClickTimerRef.current)
        markerClickTimerRef.current = null
      }
      openRefSegmentInspect(segmentId)
    },
    [openRefSegmentInspect],
  )

  const handleDeleteSegment = useCallback(async () => {
    if (!activeAppliedSegmentId || !project) return
    if (!window.confirm('Delete this applied reference segment and clear its generated board backgrounds/previews?')) return
    const segmentId = activeAppliedSegmentId
    dismissRefSegmentUi()
    setSegmentDeleting(true)
    setBusy(true)
    try {
      await flushDirtyShots()
      setProject(await deleteRefSegment(segmentId))
    } catch (error) {
      reportError(error)
    } finally {
      setSegmentDeleting(false)
      setBusy(false)
    }
  }, [activeAppliedSegmentId, project, flushDirtyShots, setProject, dismissRefSegmentUi, reportError])

  useEffect(() => {
    if (!selectedShotId || !viewportRef.current) return
    const card = viewportRef.current.querySelector(`[data-shot-id="${CSS.escape(selectedShotId)}"]`)
    if (card instanceof HTMLElement) {
      scrollCardIntoViewport(viewportRef.current, card)
    }
  }, [selectedShotId, shots.length])

  // Project-wide missing-file map for the per-card warning dot. Refetched whenever committed
  // project data changes (visualEpoch). Stale-guarded and silent — no error banner for this.
  useEffect(() => {
    let cancelled = false
    getMissingFiles()
      .then((payload) => {
        if (cancelled) return
        const next = new Set<string>()
        for (const row of payload.missing_files ?? []) next.add(row.shot_id)
        setMissingShots(next)
      })
      .catch(() => {
        if (!cancelled) setMissingShots(new Set())
      })
    return () => {
      cancelled = true
    }
  }, [visualEpoch])

  const handleAdd = useCallback(async () => {
    if (!project) return
    setBusy(true)
    try {
      await flushDirtyShots()
      const afterId = selectedShotId || undefined
      const payload = await addShot(afterId ? { after_shot_id: afterId } : {})
      setProject(payload)
      const nextIndex = afterId
        ? Math.min(payload.shots.findIndex((s) => s.shot_id === afterId) + 1, payload.shots.length - 1)
        : payload.shots.length - 1
      const nextId = payload.shots[nextIndex]?.shot_id
      if (nextId) setSelectedShotId(nextId)
    } catch {
      // flush or structural op failed; state unchanged
    } finally {
      setBusy(false)
    }
  }, [project, selectedShotId, setProject, setSelectedShotId, flushDirtyShots])

  const handleDelete = useCallback(async () => {
    if (!project || !selectedShotId) return
    if (!window.confirm('Delete the selected shot?')) return
    setBusy(true)
    try {
      await flushDirtyShots()
      const payload = await deleteShot(selectedShotId)
      setProject(payload)
      const nextIndex = Math.min(selectedIndex, payload.shots.length - 1)
      setSelectedShotId(payload.shots[nextIndex]?.shot_id ?? null)
    } catch {
      // aborted
    } finally {
      setBusy(false)
    }
  }, [project, selectedShotId, selectedIndex, setProject, setSelectedShotId, flushDirtyShots])

  const handleMoveUp = useCallback(async () => {
    if (!project || !selectedShotId) return
    setBusy(true)
    try {
      await flushDirtyShots()
      const payload = await moveShotUp(selectedShotId)
      setProject(payload)
      setSelectedShotId(selectedShotId)
    } catch {
      // aborted
    } finally {
      setBusy(false)
    }
  }, [project, selectedShotId, setProject, setSelectedShotId, flushDirtyShots])

  const handleMoveDown = useCallback(async () => {
    if (!project || !selectedShotId) return
    setBusy(true)
    try {
      await flushDirtyShots()
      const payload = await moveShotDown(selectedShotId)
      setProject(payload)
      setSelectedShotId(selectedShotId)
    } catch {
      // aborted
    } finally {
      setBusy(false)
    }
  }, [project, selectedShotId, setProject, setSelectedShotId, flushDirtyShots])

  if (!project) return null

  return (
    <section className="board-strip" aria-label="Storyboard strip">
      <div className="board-strip-toolbar">
        <span className="board-strip-title">
          Boards <span className="board-strip-count">({shots.length})</span>
        </span>
        {rangeLabel || segmentDeleting ? (
          <span className="board-strip-segment">
            {segmentDeleting ? 'Deleting segment…' : rangeLabel}
            {activeAppliedSegmentId ? (
              <button
                type="button"
                className="board-strip-segment-delete"
                onClick={() => void handleDeleteSegment()}
                disabled={disabled}
              >
                Delete segment
              </button>
            ) : null}
            <button
              type="button"
              className="board-strip-segment-clear"
              onClick={() => (activeAppliedSegmentId ? dismissRefSegmentUi() : clearSegmentRange())}
            >
              clear
            </button>
          </span>
        ) : (
          <span className="board-strip-hint" title="Keyboard shortcuts">
            ←/→ select · dots set ref range · N add · R sync · O open PS · ⌘/Ctrl+S save
          </span>
        )}
        <div className="board-strip-actions">
          <button type="button" onClick={() => void handleAdd()} disabled={disabled} title="Add board">
            + Add
          </button>
          <button
            type="button"
            onClick={() => void handleDelete()}
            disabled={!selectedShotId || disabled}
            title="Delete selected board"
          >
            Delete
          </button>
          <button
            type="button"
            onClick={() => void handleMoveUp()}
            disabled={!selectedShotId || selectedIndex <= 0 || disabled}
            title="Move left"
          >
            ←
          </button>
          <button
            type="button"
            onClick={() => void handleMoveDown()}
            disabled={!selectedShotId || selectedIndex < 0 || selectedIndex >= shots.length - 1 || disabled}
            title="Move right"
          >
            →
          </button>
        </div>
      </div>

      <div ref={viewportRef} className="board-strip-viewport">
        {shots.length === 0 ? (
          <div className="board-strip-empty">
            <p>No boards yet</p>
            <button type="button" className="board-strip-empty-cta" onClick={() => void handleAdd()} disabled={disabled}>
              Add first board
            </button>
          </div>
        ) : (
          <div className="board-strip-scroller">
            <div className="board-strip-track" role="list">
            {shots.map((shot, index) => {
              const isSelected = selectedShotId === shot.shot_id
              const label = shotDisplayLabel(shot)
              const hasDraft = isShotDirty(shot.shot_id)
              const hasPreview = shotHasPreview(shot)
              const hasSource = !!shot.source_file_path
              const isMissing = missingShots.has(shot.shot_id)
              return (
                <button
                  key={shot.shot_id}
                  type="button"
                  role="listitem"
                  data-shot-id={shot.shot_id}
                  className={`board-strip-card ${isSelected ? 'is-selected' : ''}`}
                  onClick={() => setSelectedShotId(shot.shot_id)}
                  title={label}
                >
                  <div className="board-strip-thumb">
                    <ShotThumb
                      shotId={shot.shot_id}
                      version={shotThumbVersion(shot, visualEpoch, index)}
                      hasImage={shotHasPreview(shot)}
                    />
                    <span className="board-strip-index">#{index + 1}</span>
                    {hasDraft ? (
                      <span className="board-strip-dirty" title="Unsaved edits">
                        ●
                      </span>
                    ) : null}
                  </div>
                  <div className="board-strip-meta">
                    <div className="board-strip-label">{label}</div>
                    <div className="board-strip-details">
                      <span className="board-strip-status">{shot.status || 'Draft'}</span>
                      <span>{shot.duration_seconds ?? 3}s</span>
                    </div>
                    <div className="board-strip-badges">
                      <span
                        className={`bs-badge ${hasPreview ? 'on' : 'off'}`}
                        title={hasPreview ? 'Has preview' : 'No preview'}
                      >
                        P
                      </span>
                      <span
                        className={`bs-badge ${hasSource ? 'on' : 'off'}`}
                        title={hasSource ? 'Has source PSD' : 'No source PSD'}
                      >
                        S
                      </span>
                      {isMissing ? (
                        <span className="bs-badge warn" title="A linked file is missing on disk">
                          !
                        </span>
                      ) : null}
                    </div>
                  </div>
                </button>
              )
            })}
            </div>
            <div className="board-strip-dotrail-wrap">
            <div className="board-strip-dotrail" aria-label="Reference segment range">
              {shots.map((shot, index) => {
                const inRange = showDraftLine && index >= lo && index <= hi
                const isStart = showDraftLine && index === lo
                const isEnd = showDraftLine && index === hi
                const isAnchorOnly = !showDraftLine && !activeAppliedSegmentId && index === anchorIdx
                const cellClass = [
                  'board-strip-dotcell',
                  inRange ? 'in-range' : '',
                  isStart ? 'range-start' : '',
                  isEnd ? 'range-end' : '',
                  bothSet && lo === hi && showDraftLine ? 'range-single' : '',
                ]
                  .filter(Boolean)
                  .join(' ')
                const dotClass = [
                  'board-strip-dot',
                  inRange ? 'in-range' : '',
                  isStart || isEnd ? 'endpoint' : '',
                  isStart ? 'start' : '',
                  isEnd ? 'end' : '',
                  isAnchorOnly ? 'anchor-only' : '',
                ]
                  .filter(Boolean)
                  .join(' ')
                return (
                  <div className={cellClass} key={shot.shot_id}>
                    <button
                      type="button"
                      className={dotClass}
                      onClick={() => pickSegmentShot(shot.shot_id)}
                      title={`Board #${index + 1} — click to set reference range start/end`}
                      aria-label={`Set reference range at board ${index + 1}`}
                    />
                  </div>
                )
              })}
            </div>
            <div className="board-strip-segment-layer" aria-label="Applied reference segments">
              {visibleMarkers.map((seg) => {
                  const span = seg.hi - seg.lo + 1
                  const cssType = segmentCssType(seg.sourceType)
                  const tooltip = segmentMarkerTooltip(seg)
                  return (
                    <button
                      key={`${seg.segmentId}-${seg.kind}-${seg.lo}-${seg.hi}`}
                      type="button"
                      className={[
                        'board-strip-segment-bar',
                        `is-${cssType}`,
                        seg.kind === 'pending' ? 'is-pending' : 'is-applied',
                        seg.isSelected ? 'is-selected' : '',
                      ]
                        .filter(Boolean)
                        .join(' ')}
                      style={
                        {
                          '--seg-lo': seg.lo,
                          '--seg-span': span,
                        } as CSSProperties
                      }
                      title={`${tooltip} — double-click to open`}
                      onClick={(e) => {
                        e.stopPropagation()
                        handleMarkerClick(seg.segmentId)
                      }}
                      onDoubleClick={(e) => {
                        e.stopPropagation()
                        handleMarkerDoubleClick(seg.segmentId)
                      }}
                      aria-label={tooltip}
                      aria-pressed={seg.isSelected}
                    >
                      <span className="board-strip-segment-bar-label">
                        {seg.kind === 'pending' ? '…' : seg.typeLabel}
                      </span>
                    </button>
                  )
                })}
            </div>
            </div>
          </div>
        )}
      </div>
    </section>
  )
}
