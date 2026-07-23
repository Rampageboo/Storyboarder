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

/** Grid overview of every board. Selecting a tile drives the same shot detail
 *  inspector as the strip; the trailing tile adds a board. */
export function BoardGrid() {
  const {
    project,
    selectedShotId,
    setSelectedShotId,
    addShotAfterSelection,
    isShotDirty,
    projectActionBusy,
    visualEpoch,
  } = useProject()
  const shots = project?.shots ?? []

  return (
    <div className="board-grid" role="list" aria-label="Boards">
      {shots.map((shot, index) => {
        const isSelected = selectedShotId === shot.shot_id
        const label = shotDisplayLabel(shot)
        return (
          <button
            key={shot.shot_id}
            type="button"
            role="listitem"
            data-shot-id={shot.shot_id}
            className={`board-grid-tile ${isSelected ? 'is-selected' : ''}`}
            onClick={() => setSelectedShotId(shot.shot_id)}
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
