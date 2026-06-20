import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  addScene2DToReferences,
  createScene2D,
  deleteScene2D,
  listScene2D,
  openScene2D,
  refreshScene2DPreview,
  scene2DPreviewUrl,
  updateScene2D,
} from '../api'
import { useProject } from '../state/useProject'
import type { Scene2D } from '../types'
import './Scene2DPanel.css'

function sceneLabel(scene: Scene2D) {
  return scene.title || scene.id
}

export function Scene2DPanel() {
  const { project, setProject, flushDirtyShots, projectActionBusy, reportError } = useProject()
  const [panelOpen, setPanelOpen] = useState(true)
  const [scenes, setScenes] = useState<Scene2D[]>([])
  const [selectedId, setSelectedId] = useState('')
  const [draftTitle, setDraftTitle] = useState('')
  const [draftDescription, setDraftDescription] = useState('')
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState('')
  const [previewFailedFor, setPreviewFailedFor] = useState('')

  const selected = useMemo(
    () => scenes.find((scene) => scene.id === selectedId) ?? scenes[0] ?? null,
    [scenes, selectedId],
  )
  const disabled = busy || projectActionBusy

  const loadScenes = useCallback(async () => {
    if (!project) {
      setScenes([])
      setSelectedId('')
      return
    }
    try {
      const payload = await listScene2D()
      setScenes(payload.scenes)
      setSelectedId((current) => {
        if (current && payload.scenes.some((scene) => scene.id === current)) return current
        return payload.scenes[0]?.id ?? ''
      })
    } catch (error) {
      reportError(error)
    }
  }, [project, reportError])

  useEffect(() => {
    void loadScenes()
  }, [loadScenes, project?.project_json_path])

  useEffect(() => {
    setDraftTitle(selected?.title ?? '')
    setDraftDescription(selected?.description ?? '')
    setPreviewFailedFor('')
  }, [selected?.id, selected?.title, selected?.description])

  const createScene = useCallback(async () => {
    setBusy(true)
    try {
      await flushDirtyShots()
      const payload = await createScene2D()
      setScenes(payload.scenes)
      setSelectedId(payload.scene.id)
      setNote(`Created ${payload.scene.id}.`)
    } catch (error) {
      reportError(error)
    } finally {
      setBusy(false)
    }
  }, [flushDirtyShots, reportError])

  const saveDetails = useCallback(async () => {
    if (!selected) return
    setBusy(true)
    try {
      await flushDirtyShots()
      const payload = await updateScene2D(selected.id, {
        title: draftTitle,
        description: draftDescription,
      })
      setScenes(payload.scenes)
      setSelectedId(payload.scene.id)
      setNote('Scene 2D details saved.')
    } catch (error) {
      reportError(error)
    } finally {
      setBusy(false)
    }
  }, [draftDescription, draftTitle, flushDirtyShots, reportError, selected])

  const openScene = useCallback(async () => {
    if (!selected) return
    setBusy(true)
    try {
      await flushDirtyShots()
      await openScene2D(selected.id)
      setNote('Opened Scene 2D in Photoshop.')
    } catch (error) {
      reportError(error)
    } finally {
      setBusy(false)
    }
  }, [flushDirtyShots, reportError, selected])

  const refreshPreview = useCallback(async () => {
    if (!selected) return
    setBusy(true)
    try {
      const payload = await refreshScene2DPreview(selected.id)
      setScenes((current) => current.map((scene) => (scene.id === payload.scene.id ? payload.scene : scene)))
      setPreviewFailedFor(payload.preview_exists ? '' : payload.scene.id)
      setNote(payload.message)
    } catch (error) {
      reportError(error)
    } finally {
      setBusy(false)
    }
  }, [reportError, selected])

  const addToReferences = useCallback(async () => {
    if (!selected) return
    setBusy(true)
    try {
      await flushDirtyShots()
      const payload = await addScene2DToReferences(selected.id)
      setProject(payload.project)
      setNote('Added Scene 2D preview to project references.')
    } catch (error) {
      reportError(error)
    } finally {
      setBusy(false)
    }
  }, [flushDirtyShots, reportError, selected, setProject])

  const deleteScene = useCallback(async () => {
    if (!selected) return
    if (!window.confirm(`Delete Scene 2D "${sceneLabel(selected)}"?`)) return
    setBusy(true)
    try {
      await flushDirtyShots()
      const payload = await deleteScene2D(selected.id)
      setScenes(payload.scenes)
      setSelectedId(payload.scenes[0]?.id ?? '')
      setNote('Scene 2D deleted.')
    } catch (error) {
      reportError(error)
    } finally {
      setBusy(false)
    }
  }, [flushDirtyShots, reportError, selected])

  if (!project) return null

  const previewMissing = !selected || previewFailedFor === selected.id

  return (
    <section className={`scene2d ${panelOpen ? 'is-open' : ''}`}>
      <button type="button" className="scene2d-toggle" onClick={() => setPanelOpen((value) => !value)}>
        <span>Scene 2D</span>
        <span className="scene2d-toggle-icon">{panelOpen ? 'v' : '>'}</span>
      </button>

      {panelOpen ? (
        <div className="scene2d-body">
          {scenes.length === 0 ? (
            <div className="scene2d-empty">
              Scene 2D is a project-level scene board for layouts, maps, blocking, or environment sketches.
            </div>
          ) : (
            <div className="scene2d-list" aria-label="Scene 2D scenes">
              {scenes.map((scene) => (
                <button
                  key={scene.id}
                  type="button"
                  className={scene.id === selected?.id ? 'is-selected' : ''}
                  onClick={() => setSelectedId(scene.id)}
                  title={scene.description || scene.id}
                >
                  <span>{sceneLabel(scene)}</span>
                  <small>{scene.id}</small>
                </button>
              ))}
            </div>
          )}

          <button type="button" className="primary scene2d-create" onClick={() => void createScene()} disabled={disabled}>
            Create Scene 2D
          </button>

          {selected ? (
            <div className="scene2d-details">
              <div className="scene2d-preview">
                {previewMissing ? (
                  <div className="scene2d-preview-placeholder">No Scene 2D preview exists yet.</div>
                ) : (
                  <img
                    src={scene2DPreviewUrl(selected)}
                    alt={`${sceneLabel(selected)} preview`}
                    onError={() => setPreviewFailedFor(selected.id)}
                  />
                )}
              </div>

              <label className="scene2d-field">
                <span>Title</span>
                <input value={draftTitle} onChange={(event) => setDraftTitle(event.target.value)} disabled={disabled} />
              </label>
              <label className="scene2d-field">
                <span>Description</span>
                <textarea
                  value={draftDescription}
                  onChange={(event) => setDraftDescription(event.target.value)}
                  disabled={disabled}
                  rows={3}
                />
              </label>

              <div className="scene2d-actions">
                <button type="button" className="primary" onClick={() => void saveDetails()} disabled={disabled}>
                  Save details
                </button>
                <button type="button" onClick={() => void openScene()} disabled={disabled}>
                  Open in Photoshop
                </button>
                <button type="button" onClick={() => void refreshPreview()} disabled={disabled}>
                  Refresh preview
                </button>
                <button type="button" onClick={() => void addToReferences()} disabled={disabled || previewMissing}>
                  Add to References
                </button>
                <button type="button" className="danger" onClick={() => void deleteScene()} disabled={disabled}>
                  Delete Scene 2D
                </button>
              </div>
            </div>
          ) : null}

          {note ? <div className="scene2d-note">{note}</div> : null}
        </div>
      ) : null}
    </section>
  )
}
