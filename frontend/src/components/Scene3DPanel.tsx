import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { importScene3d, openBlenderScene, updateSettings, updateShot, uploadShotImage } from '../api'
import { useProject } from '../state/useProject'
import type { ProjectPayload, Shot } from '../types'
import { shotDisplayLabel } from '../utils/shotDisplay'
import { shotToUpdate } from '../utils/shotUpdate'
import {
  loadScene3DEditorClass,
  type Scene3DEditorInstance,
} from '../scene3d/workspace/loadScene3DEditor'
import './Scene3DPanel.css'
import './Scene3DPanel.tune.css'

type Scene3DSettings = Record<string, unknown>

type CameraState = {
  position?: unknown
  target?: unknown
  rotation?: unknown
  fov?: unknown
  focal_length?: unknown
}

function fileName(path: string) {
  return path.split(/[/\\]/).pop() || path
}

function sceneSettings(project: ProjectPayload | null): Scene3DSettings {
  const value = project?.settings?.scene3d
  return value && typeof value === 'object' ? (value as Scene3DSettings) : {}
}

function sceneKey(project: ProjectPayload | null): string {
  const scene = sceneSettings(project)
  return [project?.project_json_path || '', scene.source || 'builtin', scene.file_path || '', scene.file_name || ''].join(':')
}

function numericTriple(value: unknown): [number, number, number] | null {
  if (Array.isArray(value) && value.length >= 3) {
    return [Number(value[0]) || 0, Number(value[1]) || 0, Number(value[2]) || 0]
  }
  if (typeof value === 'string') {
    const values = value
      .split(/[\s,]+/)
      .map((item) => Number(item))
      .filter((item) => Number.isFinite(item))
    if (values.length >= 3) return [values[0], values[1], values[2]]
  }
  return null
}

function formatTriple(value: unknown): string {
  const parsed = numericTriple(value)
  return parsed ? parsed.map((item) => Number(item).toFixed(2)).join(', ') : ''
}

function getShotCamera(shot: Shot | null): Record<string, unknown> | null {
  if (!shot) return null
  const data: Record<string, unknown> = { ...(shot.camera_data || {}) }
  const position = numericTriple(data.position) || numericTriple(data.location)
  const rotation = numericTriple(data.rotation) || numericTriple(data.rotation_text)
  if (position) data.position = position
  if (rotation) data.rotation = rotation
  if (!data.fov && data.focal_length) {
    const focal = Number(data.focal_length)
    if (Number.isFinite(focal) && focal > 0) data.fov = (2 * Math.atan(36 / (2 * focal)) * 180) / Math.PI
  }
  return position ? data : null
}

async function dataUrlToFile(dataUrl: string, name: string): Promise<File> {
  const blob = await (await fetch(dataUrl)).blob()
  return new File([blob], name, { type: blob.type || 'image/png' })
}

export function Scene3DPanel() {
  const { project, selectedShotId, setProject, flushDirtyShots, projectActionBusy, reportError } = useProject()
  const [panelOpen, setPanelOpen] = useState(true)
  const [workspaceOpen, setWorkspaceOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState('')
  const [editorReady, setEditorReady] = useState(false)
  const inputRef = useRef<HTMLInputElement | null>(null)
  const editorRootRef = useRef<HTMLDivElement | null>(null)
  const editorRef = useRef<Scene3DEditorInstance | null>(null)
  const loadedSceneKeyRef = useRef('')
  const persistTimerRef = useRef<number | null>(null)
  const refViewTimerRef = useRef<number | null>(null)
  const projectRef = useRef<ProjectPayload | null>(null)
  const selectedShotIdRef = useRef<string | null>(null)

  useEffect(() => {
    projectRef.current = project
  }, [project])

  useEffect(() => {
    selectedShotIdRef.current = selectedShotId
  }, [selectedShotId])

  const scene = useMemo(() => sceneSettings(project), [project])
  const scenePath = typeof scene.file_path === 'string' ? scene.file_path : ''
  const sceneName = (typeof scene.file_name === 'string' && scene.file_name) || (scenePath ? fileName(scenePath) : '')
  const hasScene = !!scenePath || Array.isArray(scene.objects)
  const hasLinkedGlb = !!scenePath
  const disabled = busy || projectActionBusy
  const currentSceneKey = useMemo(() => sceneKey(project), [project])

  const currentShot = useCallback((): Shot | null => {
    const shotId = selectedShotIdRef.current
    return projectRef.current?.shots.find((shot) => shot.shot_id === shotId) ?? null
  }, [])

  const getBoardPreviewUrl = useCallback(() => {
    const shot = currentShot()
    if (!shot || (!shot.preview_image_path && !shot.image_path)) return ''
    return `/api/shots/${encodeURIComponent(shot.shot_id)}/image?t=${Date.now()}`
  }, [currentShot])

  const getBoardLabel = useCallback(() => {
    const shot = currentShot()
    if (!shot) return 'No board selected'
    const shots = projectRef.current?.shots ?? []
    const index = shots.findIndex((item) => item.shot_id === shot.shot_id)
    return `${shotDisplayLabel(shot)} · Board ${index >= 0 ? index + 1 : '?'}`
  }, [currentShot])

  const getShotScene3dTime = useCallback(() => {
    const shot = currentShot()
    const value = shot?.camera_data?.scene3d_time
    return value != null && value !== '' ? Number(value) : null
  }, [currentShot])

  const persistSceneSettings = useCallback(
    async (nextScene: Scene3DSettings) => {
      await flushDirtyShots()
      // exportSceneData() doesn't carry the React-managed reference view; preserve any existing one
      // so saving the scene (or an object edit) never wipes settings.scene3d.reference_view.
      const prev = sceneSettings(projectRef.current)
      const merged: Scene3DSettings = { ...nextScene }
      if (merged.reference_view == null && prev.reference_view != null) merged.reference_view = prev.reference_view
      const payload = await updateSettings({ scene3d: merged })
      setProject(payload)
      setNote('3D scene settings saved.')
    },
    [flushDirtyShots, setProject],
  )

  // Persist the current workspace view to settings.scene3d.reference_view so the GLB reference
  // assignment preview/apply can reuse it. Silent + debounced so camera tweaks don't spam saves.
  const persistReferenceView = useCallback(() => {
    const view = editorRef.current?.getViewState?.()
    if (!view) return
    if (refViewTimerRef.current) window.clearTimeout(refViewTimerRef.current)
    refViewTimerRef.current = window.setTimeout(() => {
      void (async () => {
        try {
          await flushDirtyShots()
          const merged: Scene3DSettings = { ...sceneSettings(projectRef.current), reference_view: view }
          setProject(await updateSettings({ scene3d: merged }))
        } catch (error) {
          reportError(error)
        }
      })()
    }, 400)
  }, [flushDirtyShots, reportError, setProject])

  const schedulePersistSceneSettings = useCallback(
    (nextScene: Scene3DSettings) => {
      if (persistTimerRef.current) window.clearTimeout(persistTimerRef.current)
      persistTimerRef.current = window.setTimeout(() => {
        void persistSceneSettings(nextScene).catch(reportError)
      }, 350)
    },
    [persistSceneSettings, reportError],
  )

  const openBlender = useCallback(async () => {
    setBusy(true)
    try {
      await flushDirtyShots()
      setProject(await openBlenderScene())
      setNote('Opened project scene in Blender.')
    } catch (error) {
      reportError(error)
    } finally {
      setBusy(false)
    }
  }, [flushDirtyShots, reportError, setProject])

  const importGlb = useCallback(
    async (file: File | undefined) => {
      if (!file) return
      setBusy(true)
      try {
        await flushDirtyShots()
        const payload = await importScene3d(file)
        setProject(payload)
        const editor = editorRef.current
        if (editor) {
          await editor.loadSceneData(sceneSettings(payload))
          editor.setFollowCamera?.(true, { persist: false })
          loadedSceneKeyRef.current = sceneKey(payload)
          requestAnimationFrame(() => editor._resize?.())
        }
        setWorkspaceOpen(true)
        setPanelOpen(true)
        setNote(`Imported GLB: ${file.name}`)
      } catch (error) {
        reportError(error)
      } finally {
        setBusy(false)
        if (inputRef.current) inputRef.current.value = ''
      }
    },
    [flushDirtyShots, reportError, setProject],
  )

  const applyCameraFromEditor = useCallback(
    async (cameraState: CameraState) => {
      const baseShot = currentShot()
      if (!baseShot) {
        setNote('Select a board before saving the 3D camera.')
        return
      }
      setBusy(true)
      try {
        await flushDirtyShots()
        const latestShot = currentShot() ?? baseShot
        const cameraData = {
          ...(latestShot.camera_data || {}),
          position: cameraState.position,
          target: cameraState.target,
          rotation: cameraState.rotation,
          rotation_text: formatTriple(cameraState.rotation),
          fov: cameraState.fov,
          focal_length: String(cameraState.focal_length ?? ''),
          location: formatTriple(cameraState.position),
          angle: formatTriple(cameraState.target),
        }
        setProject(await updateShot(latestShot.shot_id, { ...shotToUpdate(latestShot), camera_data: cameraData }))
        setNote('Saved 3D camera to selected board.')
      } catch (error) {
        reportError(error)
      } finally {
        setBusy(false)
      }
    },
    [currentShot, flushDirtyShots, reportError, setProject],
  )

  const captureToBoard = useCallback(async () => {
    const editor = editorRef.current
    const shot = currentShot()
    if (!editor || !shot) {
      setNote('Open Scene 3D and select a board before capture.')
      return
    }
    if (!editor.captureFrameDataUrl) {
      setNote('3D capture is unavailable in the loaded editor.')
      return
    }
    setBusy(true)
    try {
      await flushDirtyShots()
      const dataUrl = editor.captureFrameDataUrl()
      const file = await dataUrlToFile(dataUrl, `${shot.shot_id}_3d_frame.png`)
      const imagePayload = await uploadShotImage(shot.shot_id, file)
      const savedShot = imagePayload.shots.find((item) => item.shot_id === shot.shot_id) ?? shot
      const anim = editor.getAnimationState?.() ?? {}
      const view = editor.getViewState?.() ?? null
      const cameraData = {
        ...(savedShot.camera_data || {}),
        scene3d_time: Number(anim.time ?? 0),
        scene3d_camera: String(anim.camera_name ?? ''),
        // Full reproducible view so the GLB reference preview can match this captured board exactly.
        ...(view ? { scene3d_view: view } : {}),
      }
      const payload = await updateShot(savedShot.shot_id, { ...shotToUpdate(savedShot), camera_data: cameraData })
      setProject(payload)
      editor.refreshBoardPreview?.()
      setNote(`Captured 3D view to ${shotDisplayLabel(savedShot)}.`)
    } catch (error) {
      reportError(error)
    } finally {
      setBusy(false)
    }
  }, [currentShot, flushDirtyShots, reportError, setProject])

  const ensureEditorLoaded = useCallback(async () => {
    if (editorRef.current) return editorRef.current
    if (!editorRootRef.current) throw new Error('3D editor root is not mounted.')
    const Scene3DEditor = await loadScene3DEditorClass()
    const root = editorRootRef.current
    const editor = new Scene3DEditor(root, {
      getShotCamera: () => getShotCamera(currentShot()),
      getShotScene3dTime,
      getBoardPreviewUrl,
      getBoardLabel,
      onApplyShotCamera: (cameraState: CameraState) => void applyCameraFromEditor(cameraState),
      onImportBlender: () => inputRef.current?.click(),
      onOpenBlender: () => void openBlender(),
      onCaptureToBoard: () => void captureToBoard(),
      onMessage: (message: string) => setNote(message),
      onSceneSettingsChange: (nextScene: Scene3DSettings) => schedulePersistSceneSettings(nextScene),
      onViewChange: () => persistReferenceView(),
    })
    const cameraSelect = root.querySelector<HTMLSelectElement>('[data-camera-select]')
    cameraSelect?.addEventListener('change', () => {
      const cameraId = cameraSelect.value
      if (!cameraId) return
      editor.setFollowCamera?.(true, { persist: false })
      editor.setActiveCamera?.(cameraId, true)
      setNote(`Camera view: ${cameraSelect.selectedOptions[0]?.textContent || cameraId}`)
      // Let the editor settle on the new camera, then snapshot it as the reference view.
      requestAnimationFrame(() => persistReferenceView())
    })
    editorRef.current = editor
    setEditorReady(true)
    return editor
  }, [applyCameraFromEditor, captureToBoard, currentShot, getBoardLabel, getBoardPreviewUrl, getShotScene3dTime, openBlender, persistReferenceView, schedulePersistSceneSettings])

  const loadEditorScene = useCallback(async () => {
    if (!projectRef.current) return
    const editor = await ensureEditorLoaded()
    const nextScene = sceneSettings(projectRef.current)
    const nextKey = sceneKey(projectRef.current)
    if (loadedSceneKeyRef.current !== nextKey) {
      await editor.loadSceneData(Object.keys(nextScene).length ? nextScene : null)
      loadedSceneKeyRef.current = nextKey
    } else {
      editor.applyDisplaySettings?.(nextScene)
    }
    editor.setBlendFilePath?.(nextScene.blend_file_path)
    editor.setFollowCamera?.(true, { persist: false })
    const shotTime = getShotScene3dTime()
    if (shotTime != null && Number.isFinite(shotTime)) editor.setAnimationTime?.(shotTime)
    editor.refreshBoardPreview?.()
    requestAnimationFrame(() => editor._resize?.())
  }, [ensureEditorLoaded, getShotScene3dTime])

  const openWorkspace = useCallback(() => {
    setWorkspaceOpen(true)
    setPanelOpen(true)
    void loadEditorScene().catch(reportError)
  }, [loadEditorScene, reportError])

  const closeWorkspace = useCallback(() => {
    // Capture whatever view (incl. free-orbit) the user left the workspace at.
    persistReferenceView()
    editorRef.current?.pauseAnimation?.()
    setWorkspaceOpen(false)
  }, [persistReferenceView])

  const reloadGlb = useCallback(async () => {
    if (!editorRef.current?.reloadBlenderScene) {
      setNote('Open the Scene 3D workspace before reloading GLB.')
      return
    }
    await editorRef.current.reloadBlenderScene()
  }, [])

  const saveScene = useCallback(async () => {
    const sceneData = editorRef.current?.exportSceneData?.()
    if (!sceneData) {
      setNote('Open the Scene 3D workspace before saving scene data.')
      return
    }
    setBusy(true)
    try {
      await persistSceneSettings(sceneData)
    } catch (error) {
      reportError(error)
    } finally {
      setBusy(false)
    }
  }, [persistSceneSettings, reportError])

  useEffect(() => {
    if (!workspaceOpen) return
    void loadEditorScene().catch(reportError)
  }, [workspaceOpen, currentSceneKey, selectedShotId, loadEditorScene, reportError])

  useEffect(
    () => () => {
      if (persistTimerRef.current) window.clearTimeout(persistTimerRef.current)
      if (refViewTimerRef.current) window.clearTimeout(refViewTimerRef.current)
      editorRef.current?.dispose?.()
      editorRef.current = null
    },
    [],
  )

  if (!project) return null

  return (
    <section className={`scene3d ${panelOpen ? 'is-open' : ''}`}>
      <button type="button" className="scene3d-toggle" onClick={() => setPanelOpen((value) => !value)}>
        <span>Scene 3D</span>
        <span className="scene3d-toggle-icon">{panelOpen ? '▾' : '▸'}</span>
      </button>

      {panelOpen ? (
        <div className="scene3d-body">
          <div className="scene3d-status">
            {hasScene ? (
              <>
                <span className={`scene3d-chip ${hasLinkedGlb ? 'ok' : 'off'}`}>{hasLinkedGlb ? 'Linked GLB' : 'Built-in'}</span>
                <span className="scene3d-path" title={scenePath || 'Built-in scene'}>
                  {sceneName || 'Built-in scene'}
                </span>
              </>
            ) : (
              <span className="scene3d-chip off">No 3D scene linked</span>
            )}
          </div>
          <div className="scene3d-actions">
            <button type="button" className="primary" onClick={() => openWorkspace()} disabled={disabled}>
              Open workspace
            </button>
            <button type="button" onClick={() => inputRef.current?.click()} disabled={disabled}>
              Import GLB
            </button>
            <button type="button" onClick={() => void openBlender()} disabled={disabled} title="Open the project's Blender scene">
              Open Blender
            </button>
          </div>
          <div className="scene3d-help">Open workspace for viewport, camera switching, reload, and capture-to-board.</div>
          {note ? <div className="scene3d-note">{note}</div> : null}
        </div>
      ) : null}

      <input
        ref={inputRef}
        type="file"
        accept=".glb,.gltf"
        hidden
        onChange={(event) => {
          void importGlb(event.target.files?.[0] ?? undefined)
        }}
      />

      <div className="scene3d-workspace-overlay" hidden={!workspaceOpen} role="dialog" aria-modal="true" aria-label="Scene 3D workspace">
        <div className="scene3d-workspace-card">
          <div className="scene3d-workspace-header">
            <div>
              <div className="scene3d-workspace-title">Scene 3D Workspace</div>
              <div className="scene3d-workspace-subtitle">{sceneName || 'Built-in scene'} · selected board drives preview/capture</div>
            </div>
            <div className="scene3d-workspace-actions">
              <button type="button" onClick={() => inputRef.current?.click()} disabled={disabled}>
                Import GLB
              </button>
              <button type="button" onClick={() => void openBlender()} disabled={disabled}>
                Open Blender
              </button>
              <button type="button" onClick={() => void reloadGlb()} disabled={!editorReady || !hasLinkedGlb}>
                Reload GLB
              </button>
              <button type="button" onClick={() => void captureToBoard()} disabled={!editorReady || !selectedShotId || disabled}>
                Capture to board
              </button>
              <button type="button" onClick={() => void saveScene()} disabled={!editorReady || disabled}>
                Save scene
              </button>
              <button type="button" className="scene3d-workspace-close" onClick={closeWorkspace} title="Close Scene 3D">
                ×
              </button>
            </div>
          </div>
          <div className="scene3d-editor-root" ref={editorRootRef} />
        </div>
      </div>
    </section>
  )
}
