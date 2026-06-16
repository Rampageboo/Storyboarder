import { useState } from 'react'
import { shotThumbnailUrl } from '../api'
import { useProject } from '../state/ProjectContext'
import './BoardOverview.css'

export function BoardOverview() {
  const { project, selectedShotId, setSelectedShotId } = useProject()
  const [open, setOpen] = useState(false)

  if (!project) return null
  const shots = project.shots

  return (
    <section className={`overview ${open ? 'is-open' : ''}`}>
      <button type="button" className="overview-toggle" onClick={() => setOpen((v) => !v)}>
        <span>
          Board overview ({shots.length} shot{shots.length === 1 ? '' : 's'})
        </span>
        <span className="overview-toggle-icon">{open ? '▾' : '▸'}</span>
      </button>

      {open ? (
        <div className="overview-grid">
          {shots.map((shot, index) => {
            const isSelected = shot.shot_id === selectedShotId
            const v = shot.preview_disk_mtime || shot.thumbnail_disk_mtime || index
            return (
              <button
                key={shot.shot_id}
                type="button"
                className={`overview-card ${isSelected ? 'is-selected' : ''}`}
                onClick={() => setSelectedShotId(shot.shot_id)}
                title={shot.title || shot.shot_id}
              >
                <div className="overview-thumb">
                  {shot.image_path ? (
                    <img
                      src={`${shotThumbnailUrl(shot.shot_id)}?v=${encodeURIComponent(String(v))}`}
                      alt=""
                      loading="lazy"
                    />
                  ) : (
                    <div className="overview-thumb-empty">—</div>
                  )}
                  <span className="overview-card-index">#{index + 1}</span>
                </div>
                <div className="overview-card-title">{shot.title || shot.shot_id}</div>
                <div className="overview-card-meta">
                  <span>{shot.status || 'Draft'}</span>
                  <span>{shot.duration_seconds ?? 3}s</span>
                </div>
              </button>
            )
          })}
        </div>
      ) : null}
    </section>
  )
}
