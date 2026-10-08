import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Aperture, Cube, LinkSimple, Plus, VideoCamera } from '@phosphor-icons/react'
import {
  createScene3D,
  getProject,
  getScene3DManifest,
  getScene3DSession,
  resolveScene3DSession,
  type Scene3DCamera,
  type Scene3DManifest,
  type Scene3DSession,
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
import { statusStyle } from '../utils/status'
import './Scene3DPanel.css'

type Scene3DSettings = Record<string, unknown>
type InspectorTab = 'camera' | 'display' | 'scene'

const SESSION_LABELS: Record<string, { label: string; tone: string }> = {
  offline: { label: 'Blender offline', tone: 'Draft' },
  launching: { label: 'Opening Blender…', tone: 'In Progress' },
  connected: { label: 'Blender connected', tone: 'Approved' },
  closed: { label: 'Syncing last save…', tone: 'In Progress' },
  conflict: { label: 'Save conflict', tone: 'Review' },
}

function formatVector(value: number[] | undefined, digits = 2): string {
  return Array.isArray(value) ? value.map((item) => Number(item).toFixed(digits)).join(', ') : '—'
}

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
  const [session, setSession] = useState<Scene3DSession | null>(null)
  const [manifest, setManifest] = useState<Scene3DManifest | null>(null)
  const [cameraName, setCameraName] = useState('')
  const [inspectorTab, setInspectorTab] = useState<InspectorTab>('camera')
  const externalBlenderOwned = Boolean(session?.external_blender_owned)
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
  const previewRevisionRef = useRef(0)
  const manifestRevisionRef = useRef(-1)
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
  const hasBlenderPreview = activeScene3d?.source_type === 'blender' || scene.source === 'blender'
  const disabled = busy || projectActionBusy
  const sceneMutationDisabled = disabled || externalBlenderOwned
  const currentSceneKey = useMemo(() => sceneKey(project), [project])
  const projectJsonPath = project?.project_json_path || ''

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
      setNote('Blender opened. Save there to update this read-only preview automatically.')
    } catch (error) {
      reportError(error)
    } finally {
      setBusy(false)
    }
  }, [flushDirtyShots, reportError, setProject])

  useEffect(() => {
    previewRevisionRef.current = 0
    manifestRevisionRef.current = -1
  }, [activeScene3dId, projectJsonPath])

  useEffect(() => {
    if (!active || !projectJsonPath) return
    let cancelled = false
    let timer = 0

    const poll = async () => {
      try {
        const status = await getScene3DSession()
        if (cancelled) return
        setSession(status)
        const revision = Number(status.preview_revision || 0)
        if (status.preview_error) setNote(`Blender preview export failed: ${status.preview_error}`)
        else if (status.preview_exporting) setNote('Blender is updating the preview…')
        if (revision && revision !== previewRevisionRef.current) {
          previewRevisionRef.current = revision
          if (editorRef.current?.reloadBlenderScene) {
            await editorRef.current.reloadBlenderScene()
            if (!cancelled) setNote('Preview updated from Blender.')
          }
        }
        const sceneId = activeScene3dIdRef.current
        const manifestRevision = Number(status.manifest_revision || 0)
        if (sceneId && manifestRevision !== manifestRevisionRef.current) {
          manifestRevisionRef.current = manifestRevision
          const next = await getScene3DManifest(sceneId)
          if (!cancelled) setManifest(next)
        }
      } catch {
        // Keep the last usable preview during a transient status failure.
      } finally {
        if (!cancelled) timer = window.setTimeout(() => void poll(), 1200)
      }
    }

    void poll()
    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [active, projectJsonPath])

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
      try {
        await editor.loadSceneData(Object.keys(nextScene).length ? nextScene : null)
        loadedSceneKeyRef.current = nextKey
      } catch (error) {
        if (nextScene.source === 'blender') {
          setNote('Waiting for Blender to create the first preview...')
          return
        }
        throw error
      }
    } else {
      editor.applyDisplaySettings?.(nextScene)
    }
    editor.setBlendFilePath?.(nextScene.blend_file_path)
    const shotTime = getShotScene3dTime()
    if (shotTime != null && Number.isFinite(shotTime)) editor.setAnimationTime?.(shotTime)
    editor.refreshBoardPreview?.()
    requestAnimationFrame(() => editor._resize?.())
  }, [ensureEditorLoaded, getShotScene3dTime])

  useEffect(() => {
    if (active) {
      wasActiveRef.current = true
      // Without a Blender preview the editor root is not rendered; the empty state explains why.
      if (!hasBlenderPreview) return
      const request = window.requestAnimationFrame(() => {
        void loadEditorScene()
          .then(() => {
            requestAnimationFrame(() => requestAnimationFrame(() => editorRef.current?._resize?.()))
          })
          .catch(reportError)
      })
      return () => window.cancelAnimationFrame(request)
    }
    if (!wasActiveRef.current) return
    persistReferenceView()
    editorRef.current?.pauseAnimation?.()
    wasActiveRef.current = false
  }, [active, hasBlenderPreview, currentSceneKey, selectedShotId, loadEditorScene, persistReferenceView, reportError])

  useEffect(
    () => () => {
      if (persistTimerRef.current) window.clearTimeout(persistTimerRef.current)
      if (refViewTimerRef.current) window.clearTimeout(refViewTimerRef.current)
      editorRef.current?.dispose?.()
      editorRef.current = null
    },
    [],
  )

  const selectCamera = useCallback((name: string) => {
    setCameraName(name)
    setInspectorTab('camera')
    const editor = editorRef.current
    if (editor?.setActiveCameraByName && !editor.setActiveCameraByName(name)) {
      setNote(`Camera "${name}" is not in the current preview yet. Save in Blender to refresh it.`)
    }
  }, [])

  const linkCameraToBoard = useCallback(async (name: string) => {
    const shot = currentShot()
    if (!shot) {
      setNote('Select a board to link this camera to.')
      return
    }
    setBusy(true)
    try {
      await flushDirtyShots()
      const latest = currentShot() ?? shot
      const linked = String(latest.camera_data?.scene3d_camera || '') === name
      const cameraData = { ...(latest.camera_data || {}), scene3d_camera: linked ? '' : name }
      setProject(await updateShot(latest.shot_id, { ...shotToUpdate(latest), camera_data: cameraData }))
      setNote(linked ? `Unlinked ${name} from ${shotDisplayLabel(latest)}.` : `Linked ${name} to ${shotDisplayLabel(latest)}.`)
    } catch (error) {
      reportError(error)
    } finally {
      setBusy(false)
    }
  }, [currentShot, flushDirtyShots, reportError, setProject])

  const resolveConflict = useCallback(async (action: 'use_blender' | 'discard') => {
    if (action === 'discard' && !window.confirm('Discard the Blender save that conflicts with the project file?')) return
    setBusy(true)
    try {
      setSession(await resolveScene3DSession(action))
      setProject(await getProject())
      setNote(action === 'use_blender' ? 'Blender save copied into the project.' : 'Blender session discarded.')
    } catch (error) {
      reportError(error)
    } finally {
      setBusy(false)
    }
  }, [reportError, setProject])

  if (!project) return null

  const sessionState = session?.state ?? 'offline'
  const sessionBadge = SESSION_LABELS[sessionState] ?? SESSION_LABELS.offline
  const sceneManifest = manifest && manifest.scene3d_id === activeScene3d?.id ? manifest : null
  const cameras: Scene3DCamera[] = sceneManifest?.cameras ?? []
  const selectedCamera = cameras.find((camera) => camera.name === cameraName)
    ?? cameras.find((camera) => camera.name === session?.external_blender_camera)
    ?? cameras.find((camera) => camera.is_active)
    ?? cameras[0]
  const selectedShot = project.shots.find((shot) => shot.shot_id === selectedShotId) ?? null
  const boardsByCamera = new Map<string, { id: string; label: string; index: number }[]>()
  project.shots.forEach((shot, index) => {
    const name = String(shot.camera_data?.scene3d_camera || '')
    if (!name) return
    const list = boardsByCamera.get(name) ?? []
    list.push({ id: shot.shot_id, label: shotDisplayLabel(shot), index: index + 1 })
    boardsByCamera.set(name, list)
  })
  const selectedShotCamera = String(selectedShot?.camera_data?.scene3d_camera || '')
  const display = sceneSettings(project)
  const captures = project.shots
    .map((shot, index) => ({ shot, index }))
    .filter(({ shot }) => shot.camera_data?.scene3d_camera || shot.camera_data?.scene3d_view)

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
        <aside className="scene3d-nav" aria-label="3D scenes and cameras">
          <div className="scene3d-nav-heading">
            <span className="section-label">3D scenes</span>
            <button type="button" className="ghost icon-btn" aria-label="Add 3D scene" title="Add 3D scene"
              onClick={() => void create3dScene()} disabled={sceneMutationDisabled}><Plus size={15} /></button>
          </div>
          <div className="scene3d-nav-list">
            {scene3ds.map((item) => (
              <button key={item.id} type="button"
                className={'scene3d-nav-row' + (item.id === activeScene3d?.id ? ' is-active' : '')}
                aria-current={item.id === activeScene3d?.id ? 'true' : undefined}
                disabled={sceneMutationDisabled && item.id !== activeScene3d?.id}
                title={externalBlenderOwned && item.id !== activeScene3d?.id ? 'Close Blender before switching scenes' : item.title}
                onClick={() => void activate3dScene(item.id)}>
                <Cube size={15} className="scene3d-nav-icon" />
                <span className="scene3d-nav-label">{item.title || item.id}</span>
                <span className="scene3d-nav-meta">{item.source_type === 'blender' ? '.blend' : item.source_type || ''}</span>
              </button>
            ))}
            {!scene3ds.length ? <p className="scene3d-nav-empty">No 3D scenes yet.</p> : null}
          </div>

          <div className="scene3d-nav-heading">
            <span className="section-label">Cameras → boards</span>
          </div>
          <div className="scene3d-nav-list is-grow">
            {cameras.map((camera) => {
              const boards = boardsByCamera.get(camera.name) ?? []
              return (
                <button key={camera.name} type="button"
                  className={'scene3d-nav-row is-camera' + (camera.name === selectedCamera?.name ? ' is-active' : '')}
                  onClick={() => selectCamera(camera.name)} title={camera.name}>
                  <VideoCamera size={15} className="scene3d-nav-icon" />
                  <span className="scene3d-nav-label">
                    <span className="scene3d-camera-name">{camera.name}</span>
                    <small>{boards.length ? boards.map((board) => String(board.index).padStart(2, '0')).join(', ') : 'Not linked'}</small>
                  </span>
                  {camera.is_active ? <span className="scene3d-nav-meta">active</span> : null}
                </button>
              )
            })}
            {!cameras.length ? (
              <p className="scene3d-nav-empty">
                {hasBlenderPreview ? 'Cameras appear here after the next save in Blender.' : 'Open Blender to list this scene’s cameras.'}
              </p>
            ) : null}
          </div>
        </aside>

        <main className="scene3d-stage">
          <div className="scene3d-workspace-header stage-toolbar">
            <div className="stage-title">
              <strong>{sceneName || activeScene3d?.title || 'Scene 3D'}</strong>
              <span className="status-chip" style={statusStyle(sessionBadge.tone)}><span className="status-dot" />{sessionBadge.label}</span>
            </div>
            {note ? <span className="scene3d-note" role="status" title={note}>{note}</span> : null}
            <button type="button" onClick={() => blendInputRef.current?.click()} disabled={sceneMutationDisabled}>
              Attach .blend
            </button>
            <button type="button" onClick={() => void captureToBoard()} disabled={!editorReady || !selectedShotId || disabled}
              title="Save the current 3D frame to the selected board">
              <Aperture size={16} />Capture to board
            </button>
            <button type="button" className="primary" onClick={() => void openBlender()} disabled={disabled || externalBlenderOwned}>
              {externalBlenderOwned ? 'Blender is open' : 'Open Blender'}
            </button>
          </div>
          {sessionState === 'conflict' ? (
            <div className="notice is-warn scene3d-conflict" role="alert">
              <span>{session?.sync_error || 'The project’s .blend changed while Blender had it open.'}</span>
              <button type="button" onClick={() => void resolveConflict('use_blender')} disabled={busy}>Use Blender’s version</button>
              <button type="button" className="ghost" onClick={() => void resolveConflict('discard')} disabled={busy}>Discard</button>
            </div>
          ) : session?.sync_error ? (
            <div className="notice is-danger scene3d-conflict" role="alert">{session.sync_error}</div>
          ) : null}
          {hasBlenderPreview ? (
            <div className="scene3d-editor-root" ref={editorRootRef} />
          ) : (
            <div className="scene3d-preview-empty">
              <div className="scene3d-empty-card">
                <div className="scene3d-empty-head">
                  <span className="scene3d-empty-icon" aria-hidden="true"><Cube size={20} /></span>
                  <div>
                    <strong>No Blender preview yet</strong>
                    <p>The viewport shows a read-only preview of the scene Blender saves.</p>
                  </div>
                </div>
                <ol className="scene3d-empty-steps">
                  <li><span>1</span>Open Blender from here, or attach an existing .blend</li>
                  <li><span>2</span>Build or adjust the set, then save in Blender</li>
                  <li><span>3</span>The preview and its cameras appear here; capture them to boards</li>
                </ol>
                <div className="scene3d-empty-actions">
                  <button type="button" className="primary" onClick={() => void openBlender()} disabled={disabled || externalBlenderOwned}>
                    {externalBlenderOwned ? 'Blender is open' : 'Open Blender'}
                  </button>
                  <button type="button" onClick={() => blendInputRef.current?.click()} disabled={sceneMutationDisabled}>Attach .blend</button>
                </div>
              </div>
            </div>
          )}
        </main>

        <aside className="scene3d-inspector" aria-label="3D inspector">
          <div className="tab-row" role="tablist" aria-label="3D details">
            {(['camera', 'display', 'scene'] as const).map((tab) => (
              <button key={tab} type="button" role="tab" aria-selected={inspectorTab === tab} onClick={() => setInspectorTab(tab)}>
                {tab === 'camera' ? 'Camera' : tab === 'display' ? 'Display' : 'Scene'}
              </button>
            ))}
          </div>
          <div className="scene3d-inspector-body">
            {inspectorTab === 'camera' ? (
              selectedCamera ? (
                <>
                  <div className="scene3d-camera-card">
                    <VideoCamera size={18} />
                    <div>
                      <strong>{selectedCamera.name}</strong>
                      <span>{selectedCamera.projection === 'ORTHO' ? 'Orthographic' : 'Perspective'}{selectedCamera.animated ? ' · animated' : ''}{selectedCamera.is_active ? ' · scene camera' : ''}</span>
                    </div>
                  </div>
                  <dl className="scene3d-facts">
                    <dt>Focal length</dt><dd>{selectedCamera.lens_mm} mm</dd>
                    <dt>Sensor</dt><dd>{selectedCamera.sensor_width_mm} mm</dd>
                    <dt>Location</dt><dd>{formatVector(selectedCamera.location)}</dd>
                    <dt>Rotation</dt><dd>{formatVector(selectedCamera.rotation_deg, 1)}°</dd>
                  </dl>
                  <div className="scene3d-link-box">
                    <span className="field-label">Selected board</span>
                    {selectedShot ? (
                      <>
                        <p>{shotDisplayLabel(selectedShot)}{selectedShotCamera ? ` · uses ${selectedShotCamera}` : ' · no camera linked'}</p>
                        <button type="button" onClick={() => void linkCameraToBoard(selectedCamera.name)} disabled={disabled}>
                          <LinkSimple size={15} />{selectedShotCamera === selectedCamera.name ? 'Unlink from this board' : 'Link to this board'}
                        </button>
                      </>
                    ) : <p>Select a board in the Story workspace to link this camera.</p>}
                  </div>
                  {(boardsByCamera.get(selectedCamera.name) ?? []).length ? (
                    <div>
                      <span className="field-label">Boards using this camera</span>
                      <ul className="scene3d-board-list">
                        {(boardsByCamera.get(selectedCamera.name) ?? []).map((board) => (
                          <li key={board.id}><b>{String(board.index).padStart(2, '0')}</b>{board.label}</li>
                        ))}
                      </ul>
                    </div>
                  ) : null}
                </>
              ) : (
                <p className="scene3d-inspector-empty">No camera selected. Cameras come from the Blender scene after a save.</p>
              )
            ) : null}

            {inspectorTab === 'display' ? (
              editorReady ? (
                <div className="scene3d-display">
                  <label className="check-field">
                    <input type="checkbox" checked={display.follow_camera !== false}
                      onChange={(event) => editorRef.current?.setFollowCamera?.(event.target.checked)} />
                    Look through the selected camera
                  </label>
                  <label className="check-field">
                    <input type="checkbox" checked={display.object_color_preview !== false}
                      onChange={(event) => editorRef.current?.setObjectColorPreview?.(event.target.checked, { persist: true, notify: true })} />
                    Colour objects to tell them apart
                  </label>
                  <label className="field">
                    <span className="field-label">Wireframe</span>
                    <select value={String(display.wireframe_mode || 'off')}
                      onChange={(event) => editorRef.current?.setWireframeMode?.(event.target.value, { persist: true, notify: true })}>
                      <option value="off">Off</option>
                      <option value="on">Edges</option>
                      <option value="strong">Strong</option>
                    </select>
                  </label>
                  <label className="field">
                    <span className="field-label">Fill light</span>
                    <select value={String(display.program_lighting || 'auto')}
                      onChange={(event) => editorRef.current?.setProgramLightingMode?.(event.target.value, { persist: true, notify: true })}>
                      <option value="auto">Auto (use Blender lights when present)</option>
                      <option value="on">Always on</option>
                      <option value="off">Off (Blender lights only)</option>
                    </select>
                  </label>
                  <p className="scene3d-inspector-empty">Display settings change only this preview, never the .blend.</p>
                </div>
              ) : <p className="scene3d-inspector-empty">Display options appear once a Blender preview is loaded.</p>
            ) : null}

            {inspectorTab === 'scene' ? (
              <div className="scene3d-display">
                {activeScene3d ? (
                  <label className="field">
                    <span className="field-label">Keywords</span>
                    <Scene3DKeywordEditor
                      key={`${activeScene3d.id}:${activeScene3d.updated_at}`}
                      scene={activeScene3d}
                      disabled={sceneMutationDisabled}
                      onSave={(keywords) => saveSceneKeywords(activeScene3d.id, keywords)}
                    />
                    <small className="scene3d-hint-text">Words in a board’s story or camera notes that link it to this set.</small>
                  </label>
                ) : null}
                <dl className="scene3d-facts">
                  <dt>Blender file</dt><dd className="mono">{activeScene3d?.blend_file_path || '—'}</dd>
                  <dt>Frames</dt><dd>{sceneManifest?.frame_start != null ? `${sceneManifest.frame_start}–${sceneManifest.frame_end}` : '—'}{sceneManifest?.fps ? ` @ ${sceneManifest.fps} fps` : ''}</dd>
                  <dt>Objects</dt><dd>{sceneManifest?.object_count ?? '—'}</dd>
                  <dt>Last sync</dt><dd>{session?.last_synced_at ? new Date(session.last_synced_at * 1000).toLocaleTimeString() : '—'}</dd>
                </dl>
                {captures.length ? (
                  <div>
                    <span className="field-label">Boards captured from 3D</span>
                    <ul className="scene3d-board-list">
                      {captures.map(({ shot, index }) => (
                        <li key={shot.shot_id}><b>{String(index + 1).padStart(2, '0')}</b>{shotDisplayLabel(shot)}
                          <i>{String(shot.camera_data?.scene3d_camera || '')}</i></li>
                      ))}
                    </ul>
                  </div>
                ) : null}
              </div>
            ) : null}
          </div>
        </aside>
      </section>
    </>
  )
}
