import { useEffect, useState } from 'react'
import { listScene2D } from '../api'
import { useProject } from '../state/useProject'
import type { Scene2D } from '../types'
import './BulkBoardActions.css'

export function BulkBoardActions() {
  const {
    project,
    selectedShotIds,
    clearShotSelection,
    deleteSelectedShot,
    sendSelectedShotsToQueue,
    changeSelectedShotsScene,
    projectActionBusy,
    reportError,
  } = useProject()
  const [scenes, setScenes] = useState<Scene2D[]>([])
  const [sceneId, setSceneId] = useState('')
  const [busy, setBusy] = useState(false)
  const projectPath = project?.project_json_path
  const hasMultiSelection = selectedShotIds.length >= 2

  useEffect(() => {
    if (!projectPath || !hasMultiSelection) return
    let cancelled = false
    void listScene2D()
      .then((response) => {
        if (!cancelled) setScenes(response.scenes)
      })
      .catch(reportError)
    return () => {
      cancelled = true
    }
  }, [projectPath, hasMultiSelection, reportError])

  if (!hasMultiSelection) return null

  const run = async (action: () => Promise<void>) => {
    setBusy(true)
    try {
      await action()
    } catch (error) {
      reportError(error)
    } finally {
      setBusy(false)
    }
  }

  const disabled = busy || projectActionBusy
  const selectedScene = scenes.find((scene) => scene.id === sceneId)

  return (
    <div className="bulk-board-actions" role="toolbar" aria-label="Selected board actions">
      <strong>{selectedShotIds.length} boards selected</strong>
      <button
        type="button"
        disabled={disabled}
        onClick={() => void run(sendSelectedShotsToQueue)}
      >
        Send to Queue
      </button>
      <label>
        <span>Scene</span>
        <select value={sceneId} onChange={(event) => setSceneId(event.target.value)} disabled={disabled}>
          <option value="">Choose scene…</option>
          {scenes.map((scene) => (
            <option key={scene.id} value={scene.id}>{scene.title || 'Untitled scene'}</option>
          ))}
        </select>
      </label>
      <button
        type="button"
        disabled={disabled || !selectedScene}
        onClick={() => selectedScene
          && void run(() => changeSelectedShotsScene(selectedScene.id, selectedScene.title))}
      >
        Change Scene
      </button>
      <button
        type="button"
        className="is-danger"
        disabled={disabled}
        onClick={() => {
          if (window.confirm(`Delete ${selectedShotIds.length} selected boards?`)) {
            void run(deleteSelectedShot)
          }
        }}
      >
        Delete
      </button>
      <button type="button" disabled={disabled} onClick={clearShotSelection}>
        Clear selection
      </button>
    </div>
  )
}
