import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from 'react'
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

const MIN_PREVIEW_ZOOM = 25
const MAX_PREVIEW_ZOOM = 200
const ZOOM_STEP = 5

function sceneLabel(scene: Scene2D | null) {
  return scene?.title || 'Untitled Scene'
}

function perspectiveLabel(perspective: Scene2DPerspective | null) {
  return perspective?.title || 'Untitled Perspective'
}

function clampPreviewZoom(value: number) {
  return Math.min(MAX_PREVIEW_ZOOM, Math.max(MIN_PREVIEW_ZOOM, value))
}

function replaceScene(scenes: Scene2D[], next: Scene2D): Scene2D[] {
  return scenes.map((scene) => (scene.id === next.id ? next : scene))
}

function PerspectiveCardPreview({ scene, perspective }: { scene: Scene2D; perspective: Scene2DPerspective }) {
  const previewKey = `${scene.id}:${perspective.id}:${perspective.updated_at}`
  const [failedKey, setFailedKey] = useState('')

  if (failedKey === previewKey) {
    return (
      <div className="scene2d-perspective-thumb-fallback">
        <span>{perspective.type === 'psd' ? 'PSD' : 'Image'}</span>
      </div>
    )
  }

  return (
    <img
      src={scene2DPerspectivePreviewUrl(scene, perspective)}
      alt=""
      loading="lazy"
      onError={() => setFailedKey(previewKey)}
    />
  )
}

export function Scene2DPanel({ active = false }: { active?: boolean }) {
  const { project, setProject, flushDirtyShots, projectActionBusy, reportError } = useProject()
  const hasBeenActivatedRef = useRef(false)
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
  const [previewZoom, setPreviewZoom] = useState(100)
  const [fitPreview, setFitPreview] = useState(true)
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

  // Lazy-load: only fetch scenes when the panel is first activated.
  useEffect(() => {
    if (!active) return
    hasBeenActivatedRef.current = true
  }, [active])

  useEffect(() => {
    if (!hasBeenActivatedRef.current) return
    void loadScenes()
  }, [loadScenes, project?.project_json_path, active])

  useEffect(() => {
    setSceneTitle(selectedScene?.title ?? '')
    setSceneDescription(selectedScene?.description ?? '')
    setScene3dLink(selectedScene?.linked_scene3d_id ?? '')
    setSelectedPerspectiveId((current) => {
      const perspectives = selectedScene?.perspectives ?? []
      if (current && perspectives.some((perspective) => perspective.id === current)) return current
      return selectedScene?.primary_perspective_id || perspectives[0]?.id || ''
    })
  }, [
    selectedScene?.id,
    selectedScene?.title,
    selectedScene?.description,
    selectedScene?.linked_scene3d_id,
    selectedScene?.primary_perspective_id,
  ])

  useEffect(() => {
    setPerspectiveTitle(selectedPerspective?.title ?? '')
    setPerspective3dLink(selectedPerspective?.linked_scene3d_id ?? '')
    setPreviewFailedFor('')
    setPreviewZoom(100)
    setFitPreview(true)
  }, [selectedPerspective?.id, selectedPerspective?.title, selectedPerspective?.linked_scene3d_id])

  const setManualPreviewZoom = useCallback((value: number) => {
    setFitPreview(false)
    setPreviewZoom(clampPreviewZoom(value))
  }, [])

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
    <section className="scene2d-workspace-page" aria-label="Scene 2D workspace">
          <div className="scene2d-workspace-header">
            <div>
              <div className="scene2d-workspace-title">Scene 2D Workspace</div>
              <div className="scene2d-workspace-subtitle">
                {selectedScene
                  ? `${sceneLabel(selectedScene)} · ${selectedScene.perspectives.length} perspective${selectedScene.perspectives.length === 1 ? '' : 's'}`
                  : 'Create a scene group to begin'}
              </div>
            </div>
            <div className="scene2d-workspace-actions">
              {note ? <span className="scene2d-note">{note}</span> : null}
              <button type="button" onClick={() => void createScene()} disabled={disabled}>
                Add Scene
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
                  <section className="scene2d-workspace-fields" aria-label="Scene metadata">
                    <label className="scene2d-field scene2d-field-title">
                      <span>Scene title</span>
                      <input value={sceneTitle} onChange={(event) => setSceneTitle(event.target.value)} disabled={disabled} />
                    </label>
                    <label className="scene2d-field scene2d-field-link">
                      <span>Linked Scene 3D</span>
                      <select value={scene3dLink} onChange={(event) => setScene3dLink(event.target.value)} disabled={disabled}>
                        <option value="">No linked Scene 3D</option>
                        {scene3ds.map((scene) => (
                          <option key={scene.id} value={scene.id}>
                            {scene.title || 'Untitled Scene 3D'}
                          </option>
                        ))}
                      </select>
                    </label>
                    <div className="scene2d-workspace-field-actions">
                      <button type="button" className="primary" onClick={() => void saveSceneDetails()} disabled={disabled}>
                        Save scene
                      </button>
                      <button type="button" className="danger subtle" onClick={() => void removeScene()} disabled={disabled}>
                        Delete
                      </button>
                    </div>
                    <label className="scene2d-field scene2d-field-wide">
                      <span>Description</span>
                      <textarea value={sceneDescription} onChange={(event) => setSceneDescription(event.target.value)} disabled={disabled} rows={2} />
                    </label>
                  </section>

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
                        <div className="scene2d-perspective-thumb">
                          <PerspectiveCardPreview scene={selectedScene} perspective={perspective} />
                        </div>
                        <span>{perspectiveLabel(perspective)}</span>
                        <small>
                          <span className="scene2d-perspective-badge">{perspective.type}</span>
                          {perspective.id === selectedScene.primary_perspective_id ? <span className="scene2d-perspective-badge primary">Primary</span> : null}
                        </small>
                      </button>
                    ))}
                    <button type="button" className="scene2d-perspective-add-card" onClick={() => void addPerspective()} disabled={disabled}>
                      <span className="scene2d-perspective-add-mark">+</span>
                      <span>Add Perspective</span>
                    </button>
                  </div>

                  <section className="scene2d-preview-area" aria-label="Selected perspective preview">
                    <div className="scene2d-preview-stage">
                      {selectedPerspective ? (
                        previewMissing ? (
                          <div className="scene2d-preview-placeholder">
                            <strong>No preview available</strong>
                            <span>Open the PSD in Photoshop, export or replace the preview PNG, then refresh the preview.</span>
                            <div className="scene2d-preview-placeholder-actions">
                              <button type="button" onClick={() => void openPerspective()} disabled={disabled}>
                                Open in Photoshop
                              </button>
                              <button type="button" onClick={() => void refreshPreview()} disabled={disabled}>
                                Refresh Preview
                              </button>
                            </div>
                          </div>
                        ) : (
                          <div
                            className={`scene2d-preview-canvas ${fitPreview ? 'is-fit' : 'is-zoomed'}`}
                            style={{ '--scene2d-preview-width': `${previewZoom}%` } as CSSProperties}
                          >
                            <img
                              src={scene2DPerspectivePreviewUrl(selectedScene, selectedPerspective)}
                              alt={`${perspectiveLabel(selectedPerspective)} preview`}
                              onError={() => setPreviewFailedFor(previewKey)}
                            />
                          </div>
                        )
                      ) : (
                        <div className="scene2d-preview-placeholder">Select a perspective to preview and edit.</div>
                      )}
                    </div>

                    <div className="scene2d-zoom-toolbar" aria-label="Preview zoom controls">
                      <button type="button" className={fitPreview ? 'is-active' : ''} onClick={() => setFitPreview(true)} disabled={!selectedPerspective}>
                        Fit
                      </button>
                      <button type="button" onClick={() => setManualPreviewZoom(previewZoom - 10)} disabled={!selectedPerspective || previewZoom <= MIN_PREVIEW_ZOOM}>
                        -
                      </button>
                      <span>{MIN_PREVIEW_ZOOM}%</span>
                      <input
                        type="range"
                        min={MIN_PREVIEW_ZOOM}
                        max={MAX_PREVIEW_ZOOM}
                        step={ZOOM_STEP}
                        value={previewZoom}
                        onChange={(event) => setManualPreviewZoom(Number(event.target.value))}
                        disabled={!selectedPerspective}
                      />
                      <span>{MAX_PREVIEW_ZOOM}%</span>
                      <button type="button" onClick={() => setManualPreviewZoom(previewZoom + 10)} disabled={!selectedPerspective || previewZoom >= MAX_PREVIEW_ZOOM}>
                        +
                      </button>
                      <button type="button" onClick={() => setManualPreviewZoom(100)} disabled={!selectedPerspective}>
                        100%
                      </button>
                      <output>{fitPreview ? 'Fit' : `${previewZoom}%`}</output>
                    </div>
                  </section>

                  {selectedPerspective ? (
                    <section className="scene2d-perspective-editor" aria-label="Selected perspective controls">
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
                              {scene.title || 'Untitled Scene 3D'}
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
                          Set primary
                        </button>
                        <button type="button" onClick={() => void addToReferences()} disabled={disabled || previewMissing}>
                          Add to References
                        </button>
                        <button type="button" className="danger" onClick={() => void removePerspective()} disabled={disabled}>
                          Delete perspective
                        </button>
                      </div>
                    </section>
                  ) : null}
                </>
              ) : (
                <div className="scene2d-empty">Create a Scene 2D group to add perspectives.</div>
              )}
            </main>
          </div>
    </section>
  )
}
