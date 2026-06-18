import { useMemo } from 'react'
import type { Shot } from '../types'
import { useProject } from '../state/useProject'
import { shotDisplayLabel } from '../utils/shotDisplay'
import { shotHasPreview, shotThumbVersion } from '../utils/shotPreview'
import { ShotThumb } from './ShotThumb'
import './NeighborContext.css'

function NeighborCard({
  label,
  shot,
  index,
  visualEpoch,
  onSelect,
}: {
  label: string
  shot: Shot | undefined
  index: number
  visualEpoch: number
  onSelect: (id: string) => void
}) {
  if (!shot) {
    return (
      <div className="neighbor neighbor-empty">
        <div className="neighbor-label">{label}</div>
        <div className="neighbor-thumb neighbor-thumb-none">No board</div>
      </div>
    )
  }
  return (
    <button type="button" className="neighbor" onClick={() => onSelect(shot.shot_id)} title={shotDisplayLabel(shot)}>
      <div className="neighbor-label">{label}</div>
      <div className="neighbor-thumb">
        <ShotThumb shotId={shot.shot_id} version={shotThumbVersion(shot, visualEpoch, index)} hasImage={shotHasPreview(shot)} />
      </div>
      <div className="neighbor-name">{shotDisplayLabel(shot)}</div>
    </button>
  )
}

/** Lightweight prev/next context for drawing continuity. The big preview is the CanvasBoard itself. */
export function NeighborContext() {
  const { project, selectedShotId, setSelectedShotId, visualEpoch } = useProject()
  const idx = useMemo(
    () => (project ? project.shots.findIndex((s) => s.shot_id === selectedShotId) : -1),
    [project, selectedShotId],
  )
  if (!project || idx < 0) return null
  const shots = project.shots
  return (
    <div className="neighbors" aria-label="Adjacent boards">
      <NeighborCard label="◀ Prev" shot={shots[idx - 1]} index={idx - 1} visualEpoch={visualEpoch} onSelect={setSelectedShotId} />
      <div className="neighbors-position">
        Board {idx + 1} / {shots.length}
      </div>
      <NeighborCard label="Next ▶" shot={shots[idx + 1]} index={idx + 1} visualEpoch={visualEpoch} onSelect={setSelectedShotId} />
    </div>
  )
}
