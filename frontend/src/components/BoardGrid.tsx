import { useEffect, useRef, useState, type DragEvent, type MouseEvent } from 'react'
import { useProject } from '../state/useProject'
import { shotDisplayLabel } from '../utils/shotDisplay'
import {
  shotDisplayVersion,
  shotHasBoardBackground,
  shotHasCodexLayer,
  shotShouldOverlayPreview,
} from '../utils/shotPreview'
import { ShotThumb } from './ShotThumb'
import './BoardGrid.css'

function dropIsAfter(e: DragEvent<HTMLButtonElement>): boolean {
  const rect = e.currentTarget.getBoundingClientRect()
  return e.clientX > rect.left + rect.width / 2
}

/** Grid overview of every board. Selecting a tile drives the same shot detail
 *  inspector as the strip; the trailing tile adds a board. */
export function BoardGrid() {
  const {
    project,
    selectedShotId,
    selectedShotIds,
    selectShot,
    addShotAfterSelection,
    isShotDirty,
    flushDirtyShots,
    reorderBoards,
    reportError,
    projectActionBusy,
    visualEpoch,
  } = useProject()
  const shots = project?.shots ?? []
  const [dragShotId, setDragShotId] = useState<string | null>(null)
  const [dropTarget, setDropTarget] = useState<{ id: string; after: boolean } | null>(null)
  const gridRef = useRef<HTMLDivElement | null>(null)
  const selectedSet = new Set(selectedShotIds)

  const handleSelect = (event: MouseEvent<HTMLButtonElement>, shotId: string) => {
    const mode = event.shiftKey
      ? 'range'
      : event.ctrlKey || event.metaKey
        ? 'toggle'
        : 'replace'
    selectShot(shotId, mode)
  }

  useEffect(() => {
    if (!selectedShotId || !gridRef.current) return
    const tile = gridRef.current.querySelector<HTMLButtonElement>(`[data-shot-id="${CSS.escape(selectedShotId)}"]`)
    tile?.scrollIntoView({ block: 'nearest' })
  }, [selectedShotId])

  const handleDragStart = (e: DragEvent<HTMLButtonElement>, shotId: string) => {
    setDragShotId(shotId)
    e.dataTransfer.effectAllowed = 'move'
    try {
      e.dataTransfer.setData('text/plain', shotId)
    } catch {
      // some environments disallow setData; drag still works via component state
    }
  }

  const handleCardDragOver = (e: DragEvent<HTMLButtonElement>, shotId: string) => {
    if (!dragShotId || dragShotId === shotId) return
    e.preventDefault()
    e.dataTransfer.dropEffect = 'move'
    const after = dropIsAfter(e)
    setDropTarget((prev) => (prev && prev.id === shotId && prev.after === after ? prev : { id: shotId, after }))
  }

  const handleCardDrop = async (e: DragEvent<HTMLButtonElement>, shotId: string) => {
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
    try {
      await flushDirtyShots()
      await reorderBoards(ids, dragId)
    } catch (error) {
      reportError(error)
    }
  }

  const handleDragEnd = () => {
    setDragShotId(null)
    setDropTarget(null)
  }

  return (
    <div className="board-grid" ref={gridRef} role="list" aria-label="Boards">
      {shots.map((shot, index) => {
        const isSelected = selectedSet.has(shot.shot_id)
        const isPrimary = selectedShotId === shot.shot_id
        const label = shotDisplayLabel(shot)
        return (
          <button
            key={shot.shot_id}
            type="button"
            role="listitem"
            data-shot-id={shot.shot_id}
            draggable={!projectActionBusy && selectedShotIds.length <= 1}
            className={`board-grid-tile ${isSelected ? 'is-selected' : ''} ${isPrimary ? 'is-primary' : ''} ${dragShotId === shot.shot_id ? 'is-dragging' : ''} ${dropTarget?.id === shot.shot_id ? (dropTarget.after ? 'drop-after' : 'drop-before') : ''}`}
            onClick={(event) => handleSelect(event, shot.shot_id)}
            onDragStart={(e) => handleDragStart(e, shot.shot_id)}
            onDragOver={(e) => handleCardDragOver(e, shot.shot_id)}
            onDrop={(e) => void handleCardDrop(e, shot.shot_id)}
            onDragEnd={handleDragEnd}
            title={label}
          >
            <div className="board-grid-thumb">
              <ShotThumb
                shotId={shot.shot_id}
                version={shotDisplayVersion(shot, visualEpoch, index)}
                hasImage={shotShouldOverlayPreview(shot)}
                hasBg={shotHasBoardBackground(shot)}
                hasCodex={shotHasCodexLayer(shot)}
              />
              <span className="board-grid-index">#{index + 1}</span>
              {isShotDirty(shot.shot_id) ? (
                <span className="board-grid-dirty" title="Unsaved edits" aria-hidden="true">
                  ●
                </span>
              ) : null}
            </div>
            <div className="board-grid-meta">
              <span className="board-grid-label">{label}</span>
              <span className="board-grid-sub">
                <span>{shot.status || 'Draft'}</span>
                <span>{shot.duration_seconds ?? 3}s</span>
              </span>
            </div>
          </button>
        )
      })}
      <button
        type="button"
        className="board-grid-add"
        onClick={() => void addShotAfterSelection()}
        disabled={projectActionBusy}
        title="Add board"
      >
        <span className="board-grid-add-plus" aria-hidden="true">
          +
        </span>
        <span>Add board</span>
      </button>
    </div>
  )
}
