import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  createScene3D,
  getProject,
  importScene3DToScene,
  listScene3D,
  openBlenderScene,
  setActiveScene3D,
  updateScene3D,
  updateSettings,
  updateShot,
  uploadShotImage,
} from '../api'
import { useProject } from '../state/useProject'
import type { ProjectPayload, Scene3DRecord, Shot } from '../types'
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

function parseKeywords(value: string) {
  const seen = new Set<string>()
  return value
    .split(',')
    .map((item) => item.trim())
    .filter((item) => {
      const key = item.toLocaleLowerCase()
      if (!item || seen.has(key)) return false
      seen.add(key)
      return true
    })
}

function Scene3DKeywordEditor({
  scene,
  disabled,
  onSave,
}: {
  scene: Scene3DRecord
  disabled: boolean
  onSave: (keywords: string[]) => Promise<void>
}) {
  const initialValue = (scene.keywords || []).join(', ')
  const [value, setValue] = useState(initialValue)
  const [saving, setSaving] = useState(false)

  const save = async () => {
    const keywords = parseKeywords(value)
    const normalized = keywords.join(', ')
    if (normalized === initialValue) return
    setSaving(true)
    try {
      await onSave(keywords)
      setValue(normalized)
    } finally {
      setSaving(false)
    }
  }

  return (
    <input
      className="scene3d-keywords-input"
      value={value}
      onChange={(event) => setValue(event.target.value)}
      onBlur={() => void save().catch(() => {})}
      onKeyDown={(event) => {
        if (event.key === 'Enter') event.currentTarget.blur()
      }}
      placeholder="Keywords: school, classroom"
      aria-label="Scene 3D keywords"
      title="Comma-separated words that link shot details to this 3D asset"
      disabled={disabled || saving}
    />
  )
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

export function Scene3DPanel({ active }: { active: boolean }) {
  const { project, selectedShotId, setProject, flushDirtyShots, projectActionBusy, reportError } = useProject()
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState('')
  const [editorReady, setEditorReady] = useState(false)
  const [scene3ds, setScene3ds] = useState<Scene3DRecord[]>([])
  const [activeScene3dId, setActiveScene3dId] = useState('')
  const inputRef = useRef<HTMLInputElement | null>(null)
  const blendInputRef = useRef<HTMLInputElement | null>(null)
  const editorRootRef = useRef<HTMLDivElement | null>(null)
  const editorRef = useRef<Scene3DEditorInstance | null>(null)
  const loadedSceneKeyRef = useRef('')
  const persistTimerRef = useRef<number | null>(null)
  const refViewTimerRef = useRef<number | null>(null)
  const projectRef = useRef<ProjectPayload | null>(null)
  const selectedShotIdRef = useRef<string | null>(null)
  const activeScene3dIdRef = useRef('')
  const wasActiveRef = useRef(false)

  useEffect(() => {
    projectRef.current = project
  }, [project])

  useEffect(() => {
    selectedShotIdRef.current = selectedShotId
  }, [selectedShotId])

  useEffect(() => {
    activeScene3dIdRef.current = activeScene3dId
  }, [activeScene3dId])

  const scene = useMemo(() => sceneSettings(project), [project])
  const activeScene3d = useMemo(
    () => scene3ds.find((item) => item.id === activeScene3dId) ?? scene3ds[0] ?? null,
    [activeScene3dId, scene3ds],
  )
  const scenePath = typeof scene.file_path === 'string' ? scene.file_path : ''
  const sceneName = activeScene3d?.title || (typeof scene.file_name === 'string' && scene.file_name) || (scenePath ? fileName(scenePath) : '')
  const hasLinkedGlb = !!scenePath
  const disabled = busy || projectActionBusy
  const currentSceneKey = useMemo(() => sceneKey(project), [project])

  const loadScene3DList = useCallback(async () => {
    if (!project) {
      setScene3ds([])
      setActiveScene3dId('')
      return
    }
    try {
      const payload = await listScene3D()
      setScene3ds(payload.scenes)
      setActiveScene3dId(payload.active_scene3d_id)
    } catch (error) {
      reportError(error)
    }
  }, [project, reportError])

  // Lazy-load: defer until the panel is first made active.
  useEffect(() => {
    if (!active) return
    wasActiveRef.current = true
  }, [active])

  useEffect(() => {
    if (!wasActiveRef.current) return
    void loadScene3DList()
  }, [loadScene3DList, project?.project_json_path, active])

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
      const activeId = activeScene3dIdRef.current
      if (activeId) {
        await updateScene3D(activeId, {
          display_settings: merged,
          reference_view: typeof merged.reference_view === 'object' && merged.reference_view ? (merged.reference_view as Record<string, unknown>) : null,
        })
      } else {
        await updateSettings({ scene3d: merged })
      }
      const payload = await getProject()
      setProject(payload)
      void loadScene3DList()
      setNote('3D scene settings saved.')
    },
    [flushDirtyShots, loadScene3DList, setProject],
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
          const activeId = activeScene3dIdRef.current
          if (activeId) {
            await updateScene3D(activeId, { reference_view: view as Record<string, unknown> })
            setProject(await getProject())
            void loadScene3DList()
          } else {
            const merged: Scene3DSettings = { ...sceneSettings(projectRef.current), reference_view: view }
            setProject(await updateSettings({ scene3d: merged }))
          }
        } catch (error) {
          reportError(error)
        }
      })()
    }, 400)
  }, [flushDirtyShots, loadScene3DList, reportError, setProject])

  const create3dScene = useCallback(async () => {
    setBusy(true)
    try {
      await flushDirtyShots()
      const payload = await createScene3D()
      setScene3ds(payload.scenes)
      setActiveScene3dId(payload.active_scene3d_id)
      setProject(await getProject())
      setNote(`Created ${payload.scene.title || payload.scene.id}.`)
      return payload.scene.id
    } catch (error) {
      reportError(error)
      return ''
    } finally {
      setBusy(false)
    }
  }, [flushDirtyShots, reportError, setProject])

  const activate3dScene = useCallback(
    async (sceneId: string) => {
      if (!sceneId || sceneId === activeScene3dIdRef.current) return
      setBusy(true)
      try {
        await flushDirtyShots()
        const payload = await setActiveScene3D(sceneId)
        setScene3ds(payload.scenes)
        setActiveScene3dId(payload.active_scene3d_id)
        const nextProject = await getProject()
        setProject(nextProject)
        setNote(`Active Scene 3D: ${payload.scene.title || payload.scene.id}`)
        if (editorRef.current) {
          await editorRef.current.loadSceneData(sceneSettings(nextProject))
          loadedSceneKeyRef.current = sceneKey(nextProject)
          requestAnimationFrame(() => editorRef.current?._resize?.())
        }
      } catch (error) {
        reportError(error)
      } finally {
        setBusy(false)
      }
    },
    [flushDirtyShots, reportError, setProject],
  )

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

  const importSceneAsset = useCallback(
    async (file: File | undefined) => {
      if (!file) return
      setBusy(true)
      try {
        await flushDirtyShots()
        let targetId = activeScene3dIdRef.current
        if (!targetId) {
          const created = await createScene3D({ title: file.name.replace(/\.[^.]+$/, '') })
          targetId = created.scene.id
        }
        const scenePayload = await importScene3DToScene(targetId, file)
        setScene3ds(scenePayload.scenes)
        setActiveScene3dId(scenePayload.active_scene3d_id)
        const payload = await getProject()
        setProject(payload)
        const editor = editorRef.current
        if (editor) {
          await editor.loadSceneData(sceneSettings(payload))
          editor.setFollowCamera?.(true, { persist: false })
          loadedSceneKeyRef.current = sceneKey(payload)
          requestAnimationFrame(() => editor._resize?.())
        }
        setNote(file.name.toLocaleLowerCase().endsWith('.blend') ? `Attached Blender file: ${file.name}` : `Imported 3D preview: ${file.name}`)
      } catch (error) {
        reportError(error)
      } finally {
        setBusy(false)
        if (inputRef.current) inputRef.current.value = ''
        if (blendInputRef.current) blendInputRef.current.value = ''
      }
    },
    [flushDirtyShots, reportError, setProject],
  )

  const saveSceneKeywords = useCallback(async (sceneId: string, keywords: string[]) => {
    setBusy(true)
    try {
      await flushDirtyShots()
      const payload = await updateScene3D(sceneId, { keywords })
      setScene3ds(payload.scenes)
      setActiveScene3dId(payload.active_scene3d_id)
      setProject(await getProject())
      setNote(keywords.length ? `Keywords saved: ${keywords.join(', ')}` : 'Scene keywords cleared.')
    } catch (error) {
      reportError(error)
      throw error
    } finally {
      setBusy(false)
    }
  }, [flushDirtyShots, reportError, setProject])

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
    const shotTime = getShotScene3dTime()
    if (shotTime != null && Number.isFinite(shotTime)) editor.setAnimationTime?.(shotTime)
    editor.refreshBoardPreview?.()
    requestAnimationFrame(() => editor._resize?.())
  }, [ensureEditorLoaded, getShotScene3dTime])

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
    if (active) {
      wasActiveRef.current = true
      void loadEditorScene()
        .then(() => {
          requestAnimationFrame(() => requestAnimationFrame(() => editorRef.current?._resize?.()))
        })
        .catch(reportError)
      return
    }
    if (!wasActiveRef.current) return
    persistReferenceView()
    editorRef.current?.pauseAnimation?.()
    wasActiveRef.current = false
  }, [active, currentSceneKey, selectedShotId, loadEditorScene, persistReferenceView, reportError])

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
    <>
      <input
        ref={inputRef}
        type="file"
        accept=".glb,.gltf"
        hidden
        onChange={(event) => {
          void importSceneAsset(event.target.files?.[0] ?? undefined)
        }}
      />
      <input
        ref={blendInputRef}
        type="file"
        accept=".blend"
        hidden
        onChange={(event) => {
          void importSceneAsset(event.target.files?.[0] ?? undefined)
        }}
      />

      <section className="scene3d-workspace-page" aria-label="Scene 3D workspace">
          <div className="scene3d-workspace-header">
            <div>
              <div className="scene3d-workspace-title">Scene 3D Workspace</div>
              <div className="scene3d-workspace-subtitle">
                {sceneName || activeScene3d?.id || 'Built-in scene'} - selected board drives preview/capture
              </div>
            </div>
            <div className="scene3d-workspace-actions">
              {note ? <span className="scene3d-note">{note}</span> : null}
              <select
                className="scene3d-workspace-select"
                value={activeScene3dId}
                onChange={(event) => void activate3dScene(event.target.value)}
                disabled={disabled || scene3ds.length === 0}
                aria-label="Active Scene 3D"
              >
                {scene3ds.length ? (
                  scene3ds.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.title || item.id}
                    </option>
                  ))
                ) : (
                  <option value="">No Scene 3D records</option>
                )}
              </select>
              {activeScene3d ? (
                <Scene3DKeywordEditor
                  key={`${activeScene3d.id}:${activeScene3d.updated_at}`}
                  scene={activeScene3d}
                  disabled={disabled}
                  onSave={(keywords) => saveSceneKeywords(activeScene3d.id, keywords)}
                />
              ) : null}
              <button type="button" onClick={() => void create3dScene()} disabled={disabled}>
                Add 3D Scene
              </button>
              <button type="button" onClick={() => inputRef.current?.click()} disabled={disabled}>
                Import GLB
              </button>
              <button type="button" onClick={() => blendInputRef.current?.click()} disabled={disabled}>
                Attach .blend
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
            </div>
          </div>
          <div className="scene3d-editor-root" ref={editorRootRef} />
      </section>
    </>
  )
}
