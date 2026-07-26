import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type CSSProperties, type DragEvent } from 'react'
import { useProject } from '../state/useProject'
import { shotDisplayLabel } from '../utils/shotDisplay'
import {
  resolveVisibleSegmentMarkerSpans,
  segmentCssType,
  segmentMarkerTooltip,
  type RefSegmentRecord,
} from '../utils/refSegmentDisplay'
import { shotDisplayVersion, shotHasBoardBackground, shotHasCodexLayer, shotHasPreview, shotShouldOverlayPreview } from '../utils/shotPreview'
import { ShotThumb } from './ShotThumb'
import './BoardStrip.css'

function scrollCardIntoViewport(viewport: HTMLElement, card: HTMLElement, options: { center?: boolean } = {}) {
  const pad = 8
  const viewportRect = viewport.getBoundingClientRect()
  const cardRect = card.getBoundingClientRect()
  if (cardRect.width <= 0 || viewportRect.width <= 0) return
  if (options.center) {
    const delta = cardRect.left + cardRect.width / 2 - (viewportRect.left + viewportRect.width / 2)
    viewport.scrollTo({ left: Math.max(0, viewport.scrollLeft + delta), behavior: 'auto' })
    return
  }
  if (cardRect.left < viewportRect.left + pad) {
    viewport.scrollTo({ left: Math.max(0, viewport.scrollLeft - (viewportRect.left + pad - cardRect.left)), behavior: 'auto' })
  } else if (cardRect.right > viewportRect.right - pad) {
    viewport.scrollTo({ left: viewport.scrollLeft + (cardRect.right - (viewportRect.right - pad)), behavior: 'auto' })
  }
}

function dropIsAfter(e: DragEvent<HTMLButtonElement>): boolean {
  const rect = e.currentTarget.getBoundingClientRect()
  return e.clientX > rect.left + rect.width / 2
}

function shotDurationSeconds(value: unknown): number {
  const duration = Number(value)
  return Number.isFinite(duration) && duration > 0 ? duration : 3
}

function formatClock(seconds: number): string {
  const safeSeconds = Math.max(0, Math.round(seconds))
  const minutes = Math.floor(safeSeconds / 60)
  const remainder = safeSeconds % 60
  return `${minutes}:${String(remainder).padStart(2, '0')}`
}

export function BoardStrip() {
  const {
    project,
    selectedShotId,
    setSelectedShotId,
    flushDirtyShots,
    addShotAfterSelection,
    insertShotAtIndex,
    deleteSelectedShot,
    moveSelectedShot,
    reorderBoards,
    undo,
    redo,
    canUndo,
    canRedo,
    undoLabel,
    redoLabel,
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
    deleteRefSegmentUndoable,
    reportError,
    missingFiles,
  } = useProject()
  const [busy, setBusy] = useState(false)
  const [segmentDeleting, setSegmentDeleting] = useState(false)
  const missingShots = useMemo(() => {
    const s = new Set<string>()
    for (const row of missingFiles ?? []) s.add(row.shot_id)
    return s
  }, [missingFiles])
  const [dragShotId, setDragShotId] = useState<string | null>(null)
  const [dropTarget, setDropTarget] = useState<{ id: string; after: boolean } | null>(null)
  const [playing, setPlaying] = useState(false)
  const [showTransport, setShowTransport] = useState(false)
  const viewportRef = useRef<HTMLDivElement | null>(null)
  const markerClickTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const shots = useMemo(() => project?.shots ?? [], [project?.shots])
  const selectedIndex = useMemo(() => shots.findIndex((s) => s.shot_id === selectedShotId), [shots, selectedShotId])
  const progressPercent = shots.length > 0 && selectedIndex >= 0 ? ((selectedIndex + 1) / shots.length) * 100 : 0
  const progressLabel =
    shots.length > 0 && selectedIndex >= 0
      ? `Board ${selectedIndex + 1} of ${shots.length}`
      : shots.length > 0
        ? `${shots.length} boards`
        : 'No boards'
  const totalDurationSeconds = useMemo(
    () => shots.reduce((total, shot) => total + shotDurationSeconds(shot.duration_seconds), 0),
    [shots],
  )
  const currentDurationSeconds = useMemo(
    () =>
      selectedIndex >= 0
        ? shots.slice(0, selectedIndex + 1).reduce((total, shot) => total + shotDurationSeconds(shot.duration_seconds), 0)
        : 0,
    [selectedIndex, shots],
  )
  const durationLabel = shots.length > 0 ? `${formatClock(currentDurationSeconds)} / ${formatClock(totalDurationSeconds)}` : '0:00 / 0:00'
  const transportPositionLabel = shots.length > 0 ? `${progressLabel} · ${durationLabel}` : progressLabel
  const disabled = busy || projectActionBusy || initialLoading
  const canStepBack = selectedIndex > 0
  const canStepForward = selectedIndex >= 0 && selectedIndex < shots.length - 1
  const showTransportControls = showTransport || playing
  const lastScrollLeftRef = useRef(0)
  const preserveScrollOnSelectRef = useRef(false)
  const forceAlignSelectedRef = useRef(false)
  const alignRetryRef = useRef<number[]>([])

  useEffect(() => {
    if (!playing || disabled || selectedIndex < 0 || shots.length === 0) return
    if (selectedIndex >= shots.length - 1) return
    const durationMs = Math.max(500, shotDurationSeconds(shots[selectedIndex]?.duration_seconds) * 1000)
    const timer = window.setTimeout(() => {
      const nextIndex = selectedIndex + 1
      const next = shots[nextIndex]
      if (next) setSelectedShotId(next.shot_id)
      if (nextIndex >= shots.length - 1) setPlaying(false)
    }, durationMs)
    return () => window.clearTimeout(timer)
  }, [playing, disabled, selectedIndex, shots, setSelectedShotId])

  // Reference-segment range (normalized by board order for display + the connecting line).
  const anchorIdx = segmentRange.anchorShotId ? shots.findIndex((s) => s.shot_id === segmentRange.anchorShotId) : -1
  const endIdx = segmentRange.endShotId ? shots.findIndex((s) => s.shot_id === segmentRange.endShotId) : -1
  const bothSet = anchorIdx >= 0 && endIdx >= 0
  const lo = bothSet ? Math.min(anchorIdx, endIdx) : -1
  const hi = bothSet ? Math.max(anchorIdx, endIdx) : -1
  const showDraftLine = bothSet && !activeAppliedSegmentId

  const referenceLinks = useMemo(() => project?.settings?.reference_links ?? [], [project?.settings?.reference_links])
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
      await deleteRefSegmentUndoable(segmentId)
    } catch (error) {
      reportError(error)
    } finally {
      setSegmentDeleting(false)
      setBusy(false)
    }
  }, [activeAppliedSegmentId, project, flushDirtyShots, deleteRefSegmentUndoable, dismissRefSegmentUi, reportError])

  useLayoutEffect(() => {
    if (!selectedShotId || !viewportRef.current) return
    const viewport = viewportRef.current
    if (preserveScrollOnSelectRef.current && !forceAlignSelectedRef.current) {
      viewport.scrollLeft = lastScrollLeftRef.current
      preserveScrollOnSelectRef.current = false
      return
    }
    for (const id of alignRetryRef.current) window.cancelAnimationFrame(id)
    alignRetryRef.current = []
    let attempts = 0
    const alignSelected = () => {
      const card = viewport.querySelector(`[data-shot-id="${CSS.escape(selectedShotId)}"]`)
      if (!(card instanceof HTMLElement)) return
      if (forceAlignSelectedRef.current) {
        scrollCardIntoViewport(viewport, card, { center: true })
      } else {
        scrollCardIntoViewport(viewport, card)
      }
      lastScrollLeftRef.current = viewport.scrollLeft
      attempts += 1
      if (attempts >= 5) {
        forceAlignSelectedRef.current = false
        return
      }
      alignRetryRef.current.push(window.requestAnimationFrame(alignSelected))
    }
    alignSelected()
    return () => {
      for (const id of alignRetryRef.current) window.cancelAnimationFrame(id)
      alignRetryRef.current = []
    }
  }, [selectedShotId, shots.length])

  useLayoutEffect(() => {
    if (!selectedShotId || selectedIndex < 0 || !viewportRef.current) return
    const viewport = viewportRef.current
    const card = viewport.querySelector(`[data-shot-id="${CSS.escape(selectedShotId)}"]`)
    if (!(card instanceof HTMLElement)) return
    const timer = window.setTimeout(() => {
      const nextCard = viewport.querySelector(`[data-shot-id="${CSS.escape(selectedShotId)}"]`)
      if (nextCard instanceof HTMLElement) {
        scrollCardIntoViewport(viewport, nextCard)
        lastScrollLeftRef.current = viewport.scrollLeft
      }
    }, 0)
    return () => window.clearTimeout(timer)
  }, [project?.project_json_path, selectedShotId, selectedIndex])

  // Convert vertical mouse-wheel delta to horizontal scroll. A raw
  // `scrollLeft += deltaY` jumps a full notch per event, which reads as stepped.
  // Instead accumulate a target and ease toward it each frame for smooth glide.
  // Horizontal trackpad deltas keep scrolling natively (passive:true, no jank).
  useEffect(() => {
    const viewport = viewportRef.current
    if (!viewport) return
    let raf = 0
    let target = viewport.scrollLeft
    let animating = false
    const stopAnimation = () => {
      if (raf) cancelAnimationFrame(raf)
      raf = 0
      animating = false
      target = viewport.scrollLeft
    }
    const tick = () => {
      const diff = target - viewport.scrollLeft
      if (Math.abs(diff) < 0.5) {
        viewport.scrollLeft = target
        animating = false
        raf = 0
        return
      }
      viewport.scrollLeft += diff * 0.22
      raf = requestAnimationFrame(tick)
    }
    const onWheel = (e: WheelEvent) => {
      if (viewport.scrollWidth <= viewport.clientWidth) return
      // Only intercept vertical-dominant events; horizontal (trackpad) scroll natively.
      if (Math.abs(e.deltaX) >= Math.abs(e.deltaY)) {
        stopAnimation()
        return
      }
      const max = viewport.scrollWidth - viewport.clientWidth
      if (!animating) target = viewport.scrollLeft
      target = Math.max(0, Math.min(max, target + e.deltaY))
      if (!animating) {
        animating = true
        raf = requestAnimationFrame(tick)
      }
    }
    viewport.addEventListener('wheel', onWheel, { passive: true })
    // Direct manipulation must win over a target left by wheel easing. Without
    // this, dragging the native scrollbar can be overwritten on the next frame.
    viewport.addEventListener('pointerdown', stopAnimation, { passive: true })
    return () => {
      viewport.removeEventListener('wheel', onWheel)
      viewport.removeEventListener('pointerdown', stopAnimation)
      stopAnimation()
    }
  }, [])

  // missingShots is derived from the shared ProjectContext.missingFiles (no per-strip API call).

  // These delegate to the history-aware project actions so the toolbar buttons and the
  // keyboard shortcuts share one code path and both record undo/redo entries.
  const handleAdd = useCallback(async () => {
    if (!project) return
    setBusy(true)
    try {
      forceAlignSelectedRef.current = true
      await addShotAfterSelection()
    } catch {
      // flush or structural op failed; state unchanged
    } finally {
      setBusy(false)
    }
  }, [project, addShotAfterSelection])

  const handleInsertAt = useCallback(async (index: number) => {
    if (!project) return
    setBusy(true)
    try {
      forceAlignSelectedRef.current = true
      await insertShotAtIndex(index)
    } catch (error) {
      reportError(error)
    } finally {
      setBusy(false)
    }
  }, [project, insertShotAtIndex, reportError])

  const handleDelete = useCallback(async () => {
    if (!project || !selectedShotId) return
    if (!window.confirm('Delete the selected shot?')) return
    setBusy(true)
    try {
      await flushDirtyShots()
      await deleteSelectedShot()
    } catch {
      // aborted
    } finally {
      setBusy(false)
    }
  }, [project, selectedShotId, flushDirtyShots, deleteSelectedShot])

  const handleMoveUp = useCallback(async () => {
    if (!project || !selectedShotId) return
    setBusy(true)
    try {
      await flushDirtyShots()
      await moveSelectedShot('up')
    } catch {
      // aborted
    } finally {
      setBusy(false)
    }
  }, [project, selectedShotId, flushDirtyShots, moveSelectedShot])

  const handleMoveDown = useCallback(async () => {
    if (!project || !selectedShotId) return
    setBusy(true)
    try {
      await flushDirtyShots()
      await moveSelectedShot('down')
    } catch {
      // aborted
    } finally {
      setBusy(false)
    }
  }, [project, selectedShotId, flushDirtyShots, moveSelectedShot])

  const handleUndo = useCallback(async () => {
    setBusy(true)
    try {
      await undo()
    } finally {
      setBusy(false)
    }
  }, [undo])

  const handleRedo = useCallback(async () => {
    setBusy(true)
    try {
      await redo()
    } finally {
      setBusy(false)
    }
  }, [redo])

  const selectShotAt = useCallback(
    (index: number) => {
      const next = shots[index]
      if (!next) return
      setSelectedShotId(next.shot_id)
    },
    [shots, setSelectedShotId],
  )

  const handleTransportFirst = useCallback(() => {
    setPlaying(false)
    selectShotAt(0)
  }, [selectShotAt])

  const handleTransportPrevious = useCallback(() => {
    setPlaying(false)
    selectShotAt(selectedIndex - 1)
  }, [selectShotAt, selectedIndex])

  const handleTransportNext = useCallback(() => {
    setPlaying(false)
    selectShotAt(selectedIndex + 1)
  }, [selectShotAt, selectedIndex])

  const handleTransportLast = useCallback(() => {
    setPlaying(false)
    selectShotAt(shots.length - 1)
  }, [selectShotAt, shots.length])

  const handleTransportPlay = useCallback(() => {
    if (!shots.length || selectedIndex < 0) return
    if (selectedIndex >= shots.length - 1 && !playing) {
      selectShotAt(0)
    }
    setPlaying((value) => !value)
  }, [playing, selectShotAt, selectedIndex, shots.length])

  const handleDragStart = useCallback((e: DragEvent<HTMLButtonElement>, shotId: string) => {
    if (disabled) {
      e.preventDefault()
      return
    }
    setDragShotId(shotId)
    e.dataTransfer.effectAllowed = 'move'
    try {
      e.dataTransfer.setData('text/plain', shotId)
    } catch {
      // some environments disallow setData; drag still works via component state
    }
  }, [disabled])

  const handleCardDragOver = useCallback((e: DragEvent<HTMLButtonElement>, shotId: string) => {
    if (!dragShotId || dragShotId === shotId) return
    e.preventDefault()
    e.dataTransfer.dropEffect = 'move'
    const after = dropIsAfter(e)
    setDropTarget((prev) => (prev && prev.id === shotId && prev.after === after ? prev : { id: shotId, after }))
  }, [dragShotId])

  const handleDragEnd = useCallback(() => {
    setDragShotId(null)
    setDropTarget(null)
  }, [])

  const handleCardDrop = useCallback(
    async (e: DragEvent<HTMLButtonElement>, shotId: string) => {
      e.preventDefault()
      const dragId = dragShotId
      const after = dropIsAfter(e)
      setDragShotId(null)
      setDropTarget(null)
      if (!dragId || dragId === shotId) return
      const ids = shots.map((s) => s.shot_id).filter((id) => id !== dragId)
      const targetIndex = ids.indexOf(shotId)
      if (targetIndex < 0) return
      ids.splice(after ? targetIndex + 1 : targetIndex, 0, dragId)
      setBusy(true)
      try {
        await flushDirtyShots()
        await reorderBoards(ids, dragId)
      } catch (error) {
        reportError(error)
      } finally {
        setBusy(false)
      }
    },
    [dragShotId, shots, flushDirtyShots, reorderBoards, reportError],
  )

  if (!project) return null

  return (
    <section className="board-strip" aria-label="Storyboard strip">
      <button
        type="button"
        className="board-strip-progress"
        aria-label={`${transportPositionLabel}. Show playback controls`}
        aria-pressed={showTransportControls}
        title={`${transportPositionLabel}. Click to show playback controls.`}
        onClick={() => setShowTransport((value) => !value)}
      >
        <div className="board-strip-progress-fill" style={{ width: `${progressPercent}%` }} />
      </button>
      <div className={`board-strip-toolbar ${showTransportControls ? 'is-transport' : ''}`}>
        <span className="board-strip-title">
          Boards <span className="board-strip-count">({shots.length})</span>
        </span>
        <div className="board-strip-transport board-strip-transport-inline" aria-label="Board playback controls">
          <button type="button" className="board-strip-icon-btn" onClick={handleTransportFirst} disabled={disabled || selectedIndex <= 0} title="Jump to first board" aria-label="Jump to first board">
            ⏮
          </button>
          <button type="button" className="board-strip-icon-btn" onClick={handleTransportPrevious} disabled={disabled || !canStepBack} title="Previous board" aria-label="Previous board">
            ◀
          </button>
          <button
            type="button"
            className="board-strip-play"
            onClick={handleTransportPlay}
            disabled={disabled || shots.length === 0 || selectedIndex < 0}
            title={playing ? 'Pause playback' : 'Play boards'}
            aria-pressed={playing}
            aria-label={playing ? 'Pause playback' : 'Play boards'}
          >
            {playing ? '⏸' : '▶'}
          </button>
          <button type="button" className="board-strip-icon-btn" onClick={handleTransportNext} disabled={disabled || !canStepForward} title="Next board" aria-label="Next board">
            ▶
          </button>
          <button
            type="button"
            className="board-strip-icon-btn"
            onClick={handleTransportLast}
            disabled={disabled || selectedIndex < 0 || selectedIndex >= shots.length - 1}
            title="Jump to last board"
            aria-label="Jump to last board"
          >
            ⏭
          </button>
          <span className="board-strip-position">
            <span>{progressLabel}</span>
            <span className="board-strip-duration">{durationLabel}</span>
          </span>
        </div>
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
          <button
            type="button"
            onClick={() => void handleUndo()}
            disabled={!canUndo || disabled}
            title={undoLabel ? `Undo: ${undoLabel} (Ctrl+Z)` : 'Nothing to undo'}
          >
            ⟲ Undo
          </button>
          <button
            type="button"
            onClick={() => void handleRedo()}
            disabled={!canRedo || disabled}
            title={redoLabel ? `Redo: ${redoLabel} (Ctrl+Shift+Z)` : 'Nothing to redo'}
          >
            ⟳ Redo
          </button>
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

      <div
        ref={viewportRef}
        className="board-strip-viewport"
        onScroll={(event) => {
          lastScrollLeftRef.current = event.currentTarget.scrollLeft
        }}
      >
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
                <div className="board-strip-item" role="listitem" key={shot.shot_id}>
                <div className={`board-strip-insert-zone ${index === 0 ? 'is-first' : ''}`}>
                  <button
                    type="button"
                    className="board-strip-insert"
                    onClick={() => void handleInsertAt(index)}
                    disabled={disabled}
                    title={`Insert board before #${index + 1}`}
                    aria-label={`Insert board before ${index + 1}`}
                  >
                    +
                  </button>
                </div>
                <button
                  type="button"
                  data-shot-id={shot.shot_id}
                  draggable={!disabled}
                  className={[
                    'board-strip-card',
                    isSelected ? 'is-selected' : '',
                    dragShotId === shot.shot_id ? 'is-dragging' : '',
                    dropTarget?.id === shot.shot_id ? (dropTarget.after ? 'drop-after' : 'drop-before') : '',
                  ]
                    .filter(Boolean)
                    .join(' ')}
                  onPointerDown={() => {
                    if (!viewportRef.current) return
                    lastScrollLeftRef.current = viewportRef.current.scrollLeft
                    preserveScrollOnSelectRef.current = true
                  }}
                  onClick={() => setSelectedShotId(shot.shot_id)}
                  onDragStart={(e) => handleDragStart(e, shot.shot_id)}
                  onDragOver={(e) => handleCardDragOver(e, shot.shot_id)}
                  onDrop={(e) => void handleCardDrop(e, shot.shot_id)}
                  onDragEnd={handleDragEnd}
                  title={label}
                >
                  <div className="board-strip-thumb">
                    <ShotThumb
                      shotId={shot.shot_id}
                      version={shotDisplayVersion(shot, visualEpoch, index)}
                      hasImage={shotShouldOverlayPreview(shot)}
                      hasBg={shotHasBoardBackground(shot)}
                      hasCodex={shotHasCodexLayer(shot)}
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
                </div>
              )
            })}
            <div className="board-strip-item board-strip-add-item" role="listitem">
              <button
                type="button"
                className="board-strip-add-card"
                onClick={() => void handleInsertAt(shots.length)}
                disabled={disabled}
                title="Add board at the end"
                aria-label="Add board at the end"
              >
                <span className="board-strip-add-mark" aria-hidden="true" />
                <span>Add Board</span>
              </button>
            </div>
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
