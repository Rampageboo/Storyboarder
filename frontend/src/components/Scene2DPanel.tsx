import { forwardRef, useCallback, useEffect, useImperativeHandle, useMemo, useRef, useState } from 'react'
import {
  addScene2DPerspectiveToReferences,
  createScene2D,
  createScene2DPerspective,
  deleteScene2D,
  deleteScene2DPerspective,
  importScene2DPerspective,
  listScene2D,
  listScene3D,
  openScene2DPerspective,
  refreshScene2DPerspectivePreview,
  scene2DPerspectivePreviewUrl,
  setPrimaryScene2DPerspective,
  updateScene2D,
  updateScene2DPerspective,
} from '../api'
import { useProject } from '../state/useProject'
import type { Scene2D, Scene2DPerspective, Scene3DRecord } from '../types'
import './Scene2DPanel.css'

function sceneLabel(scene: Scene2D | null) {
  return scene?.title || scene?.id || ''
}

function perspectiveLabel(perspective: Scene2DPerspective | null) {
  return perspective?.title || perspective?.id || ''
}

function replaceScene(scenes: Scene2D[], next: Scene2D): Scene2D[] {
  return scenes.map((scene) => (scene.id === next.id ? next : scene))
}

export interface Scene2DPanelHandle {
  openWorkspace: () => void
}

export const Scene2DPanel = forwardRef<Scene2DPanelHandle>(function Scene2DPanel(_, ref) {
  const { project, setProject, flushDirtyShots, projectActionBusy, reportError } = useProject()
  const [workspaceOpen, setWorkspaceOpen] = useState(false)
  const [scenes, setScenes] = useState<Scene2D[]>([])
  const [scene3ds, setScene3ds] = useState<Scene3DRecord[]>([])
  const [selectedSceneId, setSelectedSceneId] = useState('')
  const [selectedPerspectiveId, setSelectedPerspectiveId] = useState('')
  const [sceneTitle, setSceneTitle] = useState('')
  const [sceneDescription, setSceneDescription] = useState('')
  const [scene3dLink, setScene3dLink] = useState('')
  const [perspectiveTitle, setPerspectiveTitle] = useState('')
  const [perspective3dLink, setPerspective3dLink] = useState('')
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState('')
  const [previewFailedFor, setPreviewFailedFor] = useState('')
  const importRef = useRef<HTMLInputElement | null>(null)

  const selectedScene = useMemo(
    () => scenes.find((scene) => scene.id === selectedSceneId) ?? scenes[0] ?? null,
    [scenes, selectedSceneId],
  )
  const selectedPerspective = useMemo(() => {
    const perspectives = selectedScene?.perspectives ?? []
    return (
      perspectives.find((perspective) => perspective.id === selectedPerspectiveId) ??
      perspectives.find((perspective) => perspective.id === selectedScene?.primary_perspective_id) ??
      perspectives[0] ??
      null
    )
  }, [selectedPerspectiveId, selectedScene])
  const disabled = busy || projectActionBusy
  const previewKey = selectedScene && selectedPerspective ? `${selectedScene.id}:${selectedPerspective.id}` : ''
  const previewMissing = !selectedScene || !selectedPerspective || previewFailedFor === previewKey

  useImperativeHandle(ref, () => ({ openWorkspace: () => setWorkspaceOpen(true) }))

  const loadScenes = useCallback(async () => {
    if (!project) {
      setScenes([])
      setScene3ds([])
      setSelectedSceneId('')
      return
    }
    try {
      const [scene2dPayload, scene3dPayload] = await Promise.all([listScene2D(), listScene3D()])
      setScenes(scene2dPayload.scenes)
      setScene3ds(scene3dPayload.scenes)
      setSelectedSceneId((current) => {
        if (current && scene2dPayload.scenes.some((scene) => scene.id === current)) return current
        return scene2dPayload.scenes[0]?.id ?? ''
      })
    } catch (error) {
      reportError(error)
    }
  }, [project, reportError])

  useEffect(() => {
    void loadScenes()
  }, [loadScenes, project?.project_json_path])

  useEffect(() => {
    setSceneTitle(selectedScene?.title ?? '')
    setSceneDescription(selectedScene?.description ?? '')
    setScene3dLink(selectedScene?.linked_scene3d_id ?? '')
    setSelectedPerspectiveId((current) => {
      const perspectives = selectedScene?.perspectives ?? []
      if (current && perspectives.some((perspective) => perspective.id === current)) return current
      return selectedScene?.primary_perspective_id || perspectives[0]?.id || ''
    })
  }, [selectedScene?.id, selectedScene?.title, selectedScene?.description, selectedScene?.linked_scene3d_id, selectedScene?.primary_perspective_id])

  useEffect(() => {
    setPerspectiveTitle(selectedPerspective?.title ?? '')
    setPerspective3dLink(selectedPerspective?.linked_scene3d_id ?? '')
    setPreviewFailedFor('')
  }, [selectedPerspective?.id, selectedPerspective?.title, selectedPerspective?.linked_scene3d_id])

  const createScene = useCallback(async () => {
    setBusy(true)
    try {
      await flushDirtyShots()
      const payload = await createScene2D()
      setScenes(payload.scenes)
      setSelectedSceneId(payload.scene.id)
      setSelectedPerspectiveId(payload.scene.primary_perspective_id)
      setNote(`Created ${payload.scene.id}.`)
    } catch (error) {
      reportError(error)
    } finally {
      setBusy(false)
    }
  }, [flushDirtyShots, reportError])

  const saveSceneDetails = useCallback(async () => {
    if (!selectedScene) return
    setBusy(true)
    try {
      await flushDirtyShots()
      const payload = await updateScene2D(selectedScene.id, {
        title: sceneTitle,
        description: sceneDescription,
        linked_scene3d_id: scene3dLink,
      })
      setScenes(payload.scenes)
      setSelectedSceneId(payload.scene.id)
      setNote('Scene group saved.')
    } catch (error) {
      reportError(error)
    } finally {
      setBusy(false)
    }
  }, [flushDirtyShots, reportError, scene3dLink, sceneDescription, sceneTitle, selectedScene])

  const addPerspective = useCallback(async () => {
    if (!selectedScene) return
    setBusy(true)
    try {
      await flushDirtyShots()
      const payload = await createScene2DPerspective(selectedScene.id, {
        title: '',
        type: 'psd',
        linked_scene3d_id: scene3dLink,
      })
      setScenes(payload.scenes)
      setSelectedPerspectiveId(payload.perspective.id)
      setNote('Perspective added.')
    } catch (error) {
      reportError(error)
    } finally {
      setBusy(false)
    }
  }, [flushDirtyShots, reportError, scene3dLink, selectedScene])

  const importPerspective = useCallback(
    async (file: File | undefined) => {
      if (!selectedScene || !file) return
      setBusy(true)
      try {
        await flushDirtyShots()
        const payload = await importScene2DPerspective(selectedScene.id, file, {
          linked_scene3d_id: scene3dLink,
        })
        setScenes(payload.scenes)
        setSelectedPerspectiveId(payload.perspective.id)
        setNote(`Imported perspective: ${file.name}`)
      } catch (error) {
        reportError(error)
      } finally {
        setBusy(false)
        if (importRef.current) importRef.current.value = ''
      }
    },
    [flushDirtyShots, reportError, scene3dLink, selectedScene],
  )

  const savePerspectiveDetails = useCallback(async () => {
    if (!selectedScene || !selectedPerspective) return
    setBusy(true)
    try {
      await flushDirtyShots()
      const payload = await updateScene2DPerspective(selectedScene.id, selectedPerspective.id, {
        title: perspectiveTitle,
        linked_scene3d_id: perspective3dLink,
      })
      setScenes(payload.scenes)
      setSelectedPerspectiveId(payload.perspective.id)
      setNote('Perspective saved.')
    } catch (error) {
      reportError(error)
    } finally {
      setBusy(false)
    }
  }, [flushDirtyShots, perspective3dLink, perspectiveTitle, reportError, selectedPerspective, selectedScene])

  const openPerspective = useCallback(async () => {
    if (!selectedScene || !selectedPerspective) return
    setBusy(true)
    try {
      await flushDirtyShots()
      await openScene2DPerspective(selectedScene.id, selectedPerspective.id)
      setNote('Opened perspective.')
    } catch (error) {
      reportError(error)
    } finally {
      setBusy(false)
    }
  }, [flushDirtyShots, reportError, selectedPerspective, selectedScene])

  const refreshPreview = useCallback(async () => {
    if (!selectedScene || !selectedPerspective) return
    setBusy(true)
    try {
      await flushDirtyShots()
      const payload = await refreshScene2DPerspectivePreview(selectedScene.id, selectedPerspective.id)
      setScenes((current) => replaceScene(current, payload.scene))
      setPreviewFailedFor(payload.preview_exists ? '' : `${selectedScene.id}:${selectedPerspective.id}`)
      setNote(payload.message)
    } catch (error) {
      reportError(error)
    } finally {
      setBusy(false)
    }
  }, [flushDirtyShots, reportError, selectedPerspective, selectedScene])

  const setPrimary = useCallback(async () => {
    if (!selectedScene || !selectedPerspective) return
    setBusy(true)
    try {
      await flushDirtyShots()
      const payload = await setPrimaryScene2DPerspective(selectedScene.id, selectedPerspective.id)
      setScenes(payload.scenes)
      setNote('Primary perspective updated.')
    } catch (error) {
      reportError(error)
    } finally {
      setBusy(false)
    }
  }, [flushDirtyShots, reportError, selectedPerspective, selectedScene])

  const addToReferences = useCallback(async () => {
    if (!selectedScene || !selectedPerspective) return
    setBusy(true)
    try {
      await flushDirtyShots()
      const payload = await addScene2DPerspectiveToReferences(selectedScene.id, selectedPerspective.id)
      setProject(payload.project)
      setNote('Added perspective to references.')
    } catch (error) {
      reportError(error)
    } finally {
      setBusy(false)
    }
  }, [flushDirtyShots, reportError, selectedPerspective, selectedScene, setProject])

  const removePerspective = useCallback(async () => {
    if (!selectedScene || !selectedPerspective) return
    if (!window.confirm(`Delete perspective "${perspectiveLabel(selectedPerspective)}"?`)) return
    setBusy(true)
    try {
      await flushDirtyShots()
      const payload = await deleteScene2DPerspective(selectedScene.id, selectedPerspective.id)
      setScenes(payload.scenes)
      setSelectedPerspectiveId(payload.scene.primary_perspective_id)
      setNote('Perspective deleted.')
    } catch (error) {
      reportError(error)
    } finally {
      setBusy(false)
    }
  }, [flushDirtyShots, reportError, selectedPerspective, selectedScene])

  const removeScene = useCallback(async () => {
    if (!selectedScene) return
    if (!window.confirm(`Delete Scene 2D "${sceneLabel(selectedScene)}"?`)) return
    setBusy(true)
    try {
      await flushDirtyShots()
      const payload = await deleteScene2D(selectedScene.id)
      setScenes(payload.scenes)
      setSelectedSceneId(payload.scenes[0]?.id ?? '')
      setNote('Scene 2D deleted.')
    } catch (error) {
      reportError(error)
    } finally {
      setBusy(false)
    }
  }, [flushDirtyShots, reportError, selectedScene])

  if (!project) return null

  return (
    <>
      <div className="scene2d-workspace-overlay" hidden={!workspaceOpen} role="dialog" aria-modal="true" aria-label="Scene 2D workspace">
        <div className="scene2d-workspace-card">
          <div className="scene2d-workspace-header">
            <div>
              <div className="scene2d-workspace-title">Scene 2D Workspace</div>
              <div className="scene2d-workspace-subtitle">
                {selectedScene ? `${sceneLabel(selectedScene)} · ${selectedScene.perspectives.length} perspective${selectedScene.perspectives.length === 1 ? '' : 's'}` : 'Create a scene group to begin'}
              </div>
            </div>
            <div className="scene2d-workspace-actions">
              {note ? <span className="scene2d-note">{note}</span> : null}
              <button type="button" onClick={() => void createScene()} disabled={disabled}>
                Add Scene
              </button>
              <button type="button" className="scene2d-workspace-close" onClick={() => setWorkspaceOpen(false)} title="Close Scene 2D" aria-label="Close Scene 2D">
                ×
              </button>
            </div>
          </div>

          <div className="scene2d-workspace-layout">
            <aside className="scene2d-workspace-list">
              <div className="scene2d-workspace-section-title">Scene groups</div>
              {scenes.map((scene) => (
                <button
                  key={scene.id}
                  type="button"
                  className={scene.id === selectedScene?.id ? 'is-selected' : ''}
                  onClick={() => setSelectedSceneId(scene.id)}
                >
                  <span>{sceneLabel(scene)}</span>
                  <small>{scene.perspectives.length} perspective{scene.perspectives.length === 1 ? '' : 's'}</small>
                </button>
              ))}
              {scenes.length === 0 ? <div className="scene2d-empty">No Scene 2D boards yet.</div> : null}
            </aside>

            <main className="scene2d-workspace-main">
              {selectedScene ? (
                <>
                  <div className="scene2d-workspace-fields">
                    <label className="scene2d-field">
                      <span>Scene title</span>
                      <input value={sceneTitle} onChange={(event) => setSceneTitle(event.target.value)} disabled={disabled} />
                    </label>
                    <label className="scene2d-field">
                      <span>Linked Scene 3D</span>
                      <select value={scene3dLink} onChange={(event) => setScene3dLink(event.target.value)} disabled={disabled}>
                        <option value="">No linked Scene 3D</option>
                        {scene3ds.map((scene) => (
                          <option key={scene.id} value={scene.id}>
                            {scene.title || scene.id}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className="scene2d-field scene2d-field-wide">
                      <span>Description</span>
                      <textarea value={sceneDescription} onChange={(event) => setSceneDescription(event.target.value)} disabled={disabled} rows={2} />
                    </label>
                    <button type="button" className="primary" onClick={() => void saveSceneDetails()} disabled={disabled}>
                      Save scene
                    </button>
                    <button type="button" className="danger" onClick={() => void removeScene()} disabled={disabled}>
                      Delete Scene 2D
                    </button>
                  </div>

                  <div className="scene2d-workspace-section-row">
                    <div className="scene2d-workspace-section-title">Perspectives</div>
                    <div className="scene2d-workspace-actions">
                      <button type="button" onClick={() => void addPerspective()} disabled={disabled}>
                        Add Perspective
                      </button>
                      <button type="button" onClick={() => importRef.current?.click()} disabled={disabled}>
                        Import image/PSD
                      </button>
                    </div>
                  </div>
                  <input
                    ref={importRef}
                    type="file"
                    accept=".psd,image/png,image/jpeg,image/webp"
                    hidden
                    onChange={(event) => {
                      void importPerspective(event.target.files?.[0] ?? undefined)
                    }}
                  />

                  <div className="scene2d-perspective-grid">
                    {selectedScene.perspectives.map((perspective) => (
                      <button
                        type="button"
                        key={perspective.id}
                        className={perspective.id === selectedPerspective?.id ? 'is-selected' : ''}
                        onClick={() => setSelectedPerspectiveId(perspective.id)}
                      >
                        <span>{perspectiveLabel(perspective)}</span>
                        <small>
                          {perspective.type}
                          {perspective.id === selectedScene.primary_perspective_id ? ' · primary' : ''}
                        </small>
                      </button>
                    ))}
                  </div>
                </>
              ) : (
                <div className="scene2d-empty">Create a Scene 2D group to add perspectives.</div>
              )}
            </main>

            <aside className="scene2d-workspace-detail">
              {selectedScene && selectedPerspective ? (
                <>
                  <div className="scene2d-workspace-preview">
                    {previewMissing ? (
                      <div className="scene2d-preview-placeholder">
                        No Scene 2D preview yet.
                        <br />
                        Open the canvas in Photoshop and export or replace the preview PNG, then refresh preview.
                      </div>
                    ) : (
                      <img
                        src={scene2DPerspectivePreviewUrl(selectedScene, selectedPerspective)}
                        alt={`${perspectiveLabel(selectedPerspective)} preview`}
                        onError={() => setPreviewFailedFor(previewKey)}
                      />
                    )}
                  </div>

                  <label className="scene2d-field">
                    <span>Perspective title</span>
                    <input value={perspectiveTitle} onChange={(event) => setPerspectiveTitle(event.target.value)} disabled={disabled} />
                  </label>
                  <label className="scene2d-field">
                    <span>Perspective linked Scene 3D</span>
                    <select value={perspective3dLink} onChange={(event) => setPerspective3dLink(event.target.value)} disabled={disabled}>
                      <option value="">Use scene group link</option>
                      {scene3ds.map((scene) => (
                        <option key={scene.id} value={scene.id}>
                          {scene.title || scene.id}
                        </option>
                      ))}
                    </select>
                  </label>

                  <div className="scene2d-actions">
                    <button type="button" className="primary" onClick={() => void savePerspectiveDetails()} disabled={disabled}>
                      Save perspective
                    </button>
                    <button type="button" onClick={() => void openPerspective()} disabled={disabled}>
                      Open in Photoshop
                    </button>
                    <button type="button" onClick={() => void refreshPreview()} disabled={disabled}>
                      Refresh preview
                    </button>
                    <button type="button" onClick={() => void setPrimary()} disabled={disabled || selectedPerspective.id === selectedScene.primary_perspective_id}>
                      Set as primary
                    </button>
                    <button type="button" onClick={() => void addToReferences()} disabled={disabled || previewMissing}>
                      Add to References
                    </button>
                    <button type="button" className="danger" onClick={() => void removePerspective()} disabled={disabled}>
                      Delete perspective
                    </button>
                  </div>
                </>
              ) : (
                <div className="scene2d-empty">Select a perspective to preview and edit.</div>
              )}
            </aside>
          </div>
        </div>
      </div>
    </>
  )
})
