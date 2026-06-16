import { useCallback, useMemo, useState } from 'react'
import { addShot, deleteShot, moveShotDown, moveShotUp } from '../api'
import { useProject } from '../state/ProjectContext'
import './Timeline.css'

export function Timeline() {
  const {
    project,
    selectedShotId,
    setSelectedShotId,
    setProject,
    flushDirtyShots,
    isShotDirty,
    initialLoading,
    projectActionBusy,
  } = useProject()
  const [busy, setBusy] = useState(false)

  const shots = project?.shots || []
  const selectedIndex = useMemo(() => shots.findIndex((s) => s.shot_id === selectedShotId), [shots, selectedShotId])
  const disabled = busy || projectActionBusy || initialLoading

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

  return (
    <div className="timeline">
      <div className="timeline-header">
        <div className="timeline-title">Shots</div>
        <div className="timeline-actions">
          <button type="button" onClick={() => void handleAdd()} disabled={!project || disabled} title="Add shot">
            + Add
          </button>
          <button
            type="button"
            onClick={() => void handleDelete()}
            disabled={!project || !selectedShotId || disabled}
            title="Delete selected shot"
          >
            Delete
          </button>
          <button
            type="button"
            onClick={() => void handleMoveUp()}
            disabled={!project || !selectedShotId || selectedIndex <= 0 || disabled}
            title="Move up"
          >
            ↑
          </button>
          <button
            type="button"
            onClick={() => void handleMoveDown()}
            disabled={!project || !selectedShotId || selectedIndex < 0 || selectedIndex >= shots.length - 1 || disabled}
            title="Move down"
          >
            ↓
          </button>
        </div>
      </div>

      <div className="timeline-list" role="list">
        {!project && !initialLoading ? (
          <div className="timeline-empty">
            <p>No project open</p>
            <p className="timeline-empty-hint">Use New or Open in the top bar.</p>
          </div>
        ) : null}

        {project && shots.length === 0 ? (
          <div className="timeline-empty">
            <p>No shots yet</p>
            <button type="button" className="timeline-empty-cta" onClick={() => void handleAdd()} disabled={disabled}>
              Add first shot
            </button>
          </div>
        ) : null}

        {shots.map((shot, index) => {
          const isSelected = selectedShotId === shot.shot_id
          const hasDraft = isShotDirty(shot.shot_id)
          return (
            <button
              key={shot.shot_id}
              type="button"
              className={`timeline-item ${isSelected ? 'is-selected' : ''}`}
              onClick={() => setSelectedShotId(shot.shot_id)}
            >
              <div className="timeline-item-top">
                <span className="timeline-item-index">#{index + 1}</span>
                {hasDraft ? <span className="timeline-item-dirty">●</span> : null}
              </div>
              <div className="timeline-item-title">{shot.title || shot.shot_id}</div>
              <div className="timeline-item-meta">
                <span>{shot.status || 'Draft'}</span>
                <span>{shot.duration_seconds ?? 3}s</span>
              </div>
            </button>
          )
        })}
      </div>
    </div>
  )
}
