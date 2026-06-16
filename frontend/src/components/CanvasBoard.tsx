import { useMemo, useState } from 'react'
import { shotImageUrl } from '../api'
import { useProject } from '../state/ProjectContext'
import './CanvasBoard.css'

export function CanvasBoard() {
  const { project, selectedShotId } = useProject()
  const [bust, setBust] = useState(0)
  const [loadFailed, setLoadFailed] = useState(false)

  const shot = useMemo(() => {
    if (!project || !selectedShotId) return null
    return project.shots.find((s) => s.shot_id === selectedShotId) || null
  }, [project, selectedShotId])

  const imgSrc = useMemo(() => {
    if (!shot) return ''
    const v = shot.preview_disk_mtime || shot.thumbnail_disk_mtime || bust || Date.now()
    return `${shotImageUrl(shot.shot_id)}?v=${encodeURIComponent(String(v))}`
  }, [shot, bust])

  if (!project) {
    return <div className="canvas-empty">No project open</div>
  }
  if (!shot) {
    return <div className="canvas-empty">No shot selected</div>
  }

  return (
    <div className="canvas">
      <div className="canvas-header">
        <div className="canvas-title">Canvas</div>
        <button
          type="button"
          onClick={() => {
            setLoadFailed(false)
            setBust((x) => x + 1)
          }}
        >
          Refresh
        </button>
      </div>
      <div className="canvas-body">
        {loadFailed || !shot.image_path ? (
          <div className="canvas-placeholder">No preview</div>
        ) : (
          <img
            className="canvas-image"
            src={imgSrc}
            alt=""
            onError={() => setLoadFailed(true)}
            onLoad={() => setLoadFailed(false)}
          />
        )}
      </div>
    </div>
  )
}

