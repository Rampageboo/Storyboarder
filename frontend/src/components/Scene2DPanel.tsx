import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type DragEvent } from 'react'
import {
  addScene2DPerspectiveToReferences,
  createScene2D,
  createScene2DPerspective,
  deleteScene2D,
  deleteScene2DPerspective,
  importScene2DPerspective,
  listScene2D,
  listScene3D,
  moveScene2DPerspective,
  openScene2DPerspective,
  refreshScene2DPerspectivePreview,
  reorderScene2DPerspectives,
  scene2DPerspectivePreviewUrl,
  setPrimaryScene2DPerspective,
  updateScene2D,
  updateScene2DPerspective,
} from '../api'
import { useProject } from '../state/useProject'
import { useBridgeStatus } from '../state/liveBridgeUtils'
import type { Scene2D, Scene2DPerspective, Scene3DRecord } from '../types'
import { ContextMenu, type ContextMenuItem, type ContextMenuState } from './ContextMenu'
import './Scene2DPanel.css'

// TODO(Part 4): Perspective ordering — backend does not yet persist order, so
// drag-and-drop is intentionally omitted. Add when a stable ordering field is
// available so UUIDs are never used to derive display order.

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

function dropIsAfter(event: DragEvent<HTMLElement>): boolean {
  const rect = event.currentTarget.getBoundingClientRect()
  return event.clientX > rect.left + rect.width / 2
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
  const bridgeStatus = useBridgeStatus()
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
  const [inspectorCollapsed, setInspectorCollapsed] = useState(false)
  const [descriptionOpen, setDescriptionOpen] = useState(false)
  const [contextMenu, setContextMenu] = useState<(ContextMenuState & { perspectiveId: string }) | null>(null)
  const [dragPerspectiveId, setDragPerspectiveId] = useState<string | null>(null)
  const [dropPerspectiveTarget, setDropPerspectiveTarget] = useState<{ id: string; after: boolean } | null>(null)
  const importRef = useRef<HTMLInputElement | null>(null)
  const canvasAreaRef = useRef<HTMLDivElement | null>(null)
  const lastPluginChangeRevisionRef = useRef<number | null>(null)
  const sceneSavingRef = useRef(false)
  const perspectiveSavingRef = useRef(false)
  // Tracks whether the canvas currently has something to zoom — avoids stale closure in wheel handler
  const canWheelZoomRef = useRef(false)

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

  // Dirty detection — Save button is only emphasized when there are unsaved edits
  const sceneDirty =
    sceneTitle !== (selectedScene?.title ?? '') ||
    sceneDescription !== (selectedScene?.description ?? '') ||
    scene3dLink !== (selectedScene?.linked_scene3d_id ?? '')

  const perspectiveDirty =
    perspectiveTitle !== (selectedPerspective?.title ?? '') ||
    perspective3dLink !== (selectedPerspective?.linked_scene3d_id ?? '')

  // Position label for canvas overlay
  const perspectiveIndex = selectedScene
    ? selectedScene.perspectives.findIndex((p) => p.id === selectedPerspective?.id) + 1
    : 0
  const perspectiveTotal = selectedScene?.perspectives.length ?? 0

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

  // Auto-dismiss action feedback toast
  useEffect(() => {
    if (!note) return
    const timer = setTimeout(() => setNote(''), 3000)
    return () => clearTimeout(timer)
  }, [note])

  // Keep the wheel-zoom guard in sync with whether there's a perspective to zoom
  useEffect(() => {
    canWheelZoomRef.current = !!selectedPerspective && (selectedScene?.perspectives.length ?? 0) > 0
  }, [selectedPerspective, selectedScene?.perspectives.length])

  // Wheel-to-zoom on the canvas area (passive:false so we can preventDefault)
  useEffect(() => {
    const area = canvasAreaRef.current
    if (!area) return
    const onWheel = (e: WheelEvent) => {
      if (!canWheelZoomRef.current) return
      e.preventDefault()
      const step = e.deltaY > 0 ? -ZOOM_STEP : ZOOM_STEP
      setFitPreview(false)
      setPreviewZoom((prev) => clampPreviewZoom(prev + step))
    }
    area.addEventListener('wheel', onWheel, { passive: false })
    return () => area.removeEventListener('wheel', onWheel)
  }, [])

  // Reload when plugin exports a Scene 2D preview
  useEffect(() => {
    const change = bridgeStatus?.plugin_change
    if (!change || change.kind !== 'scene2d') return
    const revision = Number(change.revision ?? 0)
    if (revision <= 0 || revision === lastPluginChangeRevisionRef.current) return
    lastPluginChangeRevisionRef.current = revision
    if (hasBeenActivatedRef.current) {
      void loadScenes()
    }
  }, [bridgeStatus?.plugin_change, loadScenes])

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
    if (sceneSavingRef.current) return
    sceneSavingRef.current = true
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
      sceneSavingRef.current = false
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
    if (perspectiveSavingRef.current) return
    perspectiveSavingRef.current = true
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
      perspectiveSavingRef.current = false
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

  const movePerspectiveToScene = useCallback(
    async (perspectiveId: string, targetSceneId: string) => {
      if (!selectedScene || targetSceneId === selectedScene.id) return
      setBusy(true)
      try {
        await flushDirtyShots()
        const payload = await moveScene2DPerspective(selectedScene.id, perspectiveId, {
          target_scene_id: targetSceneId,
        })
        setScenes(payload.scenes)
        setSelectedSceneId(payload.target_scene.id)
        setSelectedPerspectiveId(payload.perspective.id)
        setNote(`Moved to ${sceneLabel(payload.target_scene)}.`)
      } catch (error) {
        reportError(error)
      } finally {
        setBusy(false)
      }
    },
    [flushDirtyShots, reportError, selectedScene],
  )

  const handlePerspectiveDragStart = useCallback(
    (event: DragEvent<HTMLButtonElement>, perspectiveId: string) => {
      if (disabled) {
        event.preventDefault()
        return
      }
      setContextMenu(null)
      setDragPerspectiveId(perspectiveId)
      event.dataTransfer.effectAllowed = 'move'
      try {
        event.dataTransfer.setData('text/plain', perspectiveId)
      } catch {
        // Some embedded browsers reject setData; component state still tracks the drag.
      }
    },
    [disabled],
  )

  const handlePerspectiveDragOver = useCallback(
    (event: DragEvent<HTMLButtonElement>, perspectiveId: string) => {
      if (!dragPerspectiveId || dragPerspectiveId === perspectiveId) return
      event.preventDefault()
      event.dataTransfer.dropEffect = 'move'
      const after = dropIsAfter(event)
      setDropPerspectiveTarget((prev) =>
        prev && prev.id === perspectiveId && prev.after === after ? prev : { id: perspectiveId, after },
      )
    },
    [dragPerspectiveId],
  )

  const handlePerspectiveDragEnd = useCallback(() => {
    setDragPerspectiveId(null)
    setDropPerspectiveTarget(null)
  }, [])

  const handlePerspectiveDrop = useCallback(
    async (event: DragEvent<HTMLButtonElement>, perspectiveId: string) => {
      event.preventDefault()
      if (!selectedScene) return
      const dragId = dragPerspectiveId
      const after = dropIsAfter(event)
      setDragPerspectiveId(null)
      setDropPerspectiveTarget(null)
      if (!dragId || dragId === perspectiveId) return

      const ids = selectedScene.perspectives.map((item) => item.id).filter((id) => id !== dragId)
      const targetIndex = ids.indexOf(perspectiveId)
      if (targetIndex < 0) return
      ids.splice(after ? targetIndex + 1 : targetIndex, 0, dragId)
      const currentIds = selectedScene.perspectives.map((item) => item.id)
      if (ids.length === currentIds.length && ids.every((id, index) => id === currentIds[index])) return

      setBusy(true)
      try {
        await flushDirtyShots()
        const payload = await reorderScene2DPerspectives(selectedScene.id, { perspective_ids: ids })
        setScenes(payload.scenes)
        setSelectedPerspectiveId(dragId)
        setNote('Perspective order updated.')
      } catch (error) {
        reportError(error)
      } finally {
        setBusy(false)
      }
    },
    [dragPerspectiveId, flushDirtyShots, reportError, selectedScene],
  )

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

  const perspectiveContextMenuItems = useMemo<ContextMenuItem[]>(() => {
    if (!selectedScene || !contextMenu) return []
    const perspective = selectedScene.perspectives.find((item) => item.id === contextMenu.perspectiveId)
    if (!perspective) return []
    const moveItems = scenes.map((scene) => ({
      label: scene.id === selectedScene.id ? `${sceneLabel(scene)} (current)` : sceneLabel(scene),
      disabled: disabled || scene.id === selectedScene.id,
      onSelect: () => void movePerspectiveToScene(perspective.id, scene.id),
    }))
    return [
      { kind: 'label', label: perspectiveLabel(perspective) },
      { kind: 'separator' },
      { kind: 'label', label: 'Move to scene' },
      ...moveItems,
    ]
  }, [contextMenu, disabled, movePerspectiveToScene, scenes, selectedScene])

  if (!project) return null

  // Plugin status badge for inspector
  let pluginStatusLabel = ''
  let pluginStatusClass = 'scene2d-plugin-status'
  if (selectedScene && selectedPerspective && bridgeStatus?.plugin_linked) {
    const workKey = `scene2d:${selectedScene.id}:${selectedPerspective.id}`
    const isActive = bridgeStatus.plugin_active_work_key === workKey
    const isOpen = (bridgeStatus.plugin_open_work_keys ?? []).includes(workKey)
    const change = bridgeStatus.plugin_change
    const recentlyExported =
      change?.kind === 'scene2d' &&
      change.scene_id === selectedScene.id &&
      change.perspective_id === selectedPerspective.id
    if (isActive) {
      pluginStatusLabel = recentlyExported ? 'Preview updated' : 'Photoshop linked'
      pluginStatusClass += ' linked'
    } else if (isOpen) {
      pluginStatusLabel = 'Open in Photoshop'
      pluginStatusClass += ' open'
    }
  }

  return (
    <section className="scene2d-workspace-page" aria-label="Scene 2D workspace">
      <div className="scene2d-workspace">

        {/* ── LEFT: Scene list ─────────────────────────────────────────── */}
        <aside className="scene2d-scene-list">
          <div className="scene2d-scene-list-header">
            <span className="scene2d-workspace-section-title">Scene groups</span>
          </div>

          {scenes.map((scene) => (
            <button
              key={scene.id}
              type="button"
              className={scene.id === selectedScene?.id ? 'is-selected' : ''}
              onClick={() => setSelectedSceneId(scene.id)}
            >
              <span>{sceneLabel(scene)}</span>
              <small>
                {scene.perspectives.length} perspective{scene.perspectives.length === 1 ? '' : 's'}
              </small>
            </button>
          ))}

          {scenes.length === 0 && (
            <div className="scene2d-empty">No Scene 2D boards yet.</div>
          )}

          <button
            type="button"
            className="scene2d-scene-add-tile"
            onClick={() => void createScene()}
            disabled={disabled}
            aria-label="Add scene"
          >
            <span className="scene2d-scene-add-tile-icon" aria-hidden="true" />
            Add Scene
          </button>
        </aside>

        {/* ── RIGHT: perspective strip + canvas ───────────────────────── */}
        <div className="scene2d-main-col">

          {/* Horizontal perspective strip */}
          {selectedScene && (
            <div className="scene2d-perspective-strip">
              {selectedScene.perspectives.map((perspective) => (
                <button
                  type="button"
                  key={perspective.id}
                  draggable={!disabled}
                  className={[
                    perspective.id === selectedPerspective?.id ? 'is-selected' : '',
                    dragPerspectiveId === perspective.id ? 'is-dragging' : '',
                    dropPerspectiveTarget?.id === perspective.id
                      ? dropPerspectiveTarget.after
                        ? 'drop-after'
                        : 'drop-before'
                      : '',
                  ]
                    .filter(Boolean)
                    .join(' ')}
                  onClick={() => setSelectedPerspectiveId(perspective.id)}
                  onContextMenu={(event) => {
                    event.preventDefault()
                    setSelectedPerspectiveId(perspective.id)
                    setContextMenu({
                      x: event.clientX,
                      y: event.clientY,
                      perspectiveId: perspective.id,
                    })
                  }}
                  onDragStart={(event) => handlePerspectiveDragStart(event, perspective.id)}
                  onDragOver={(event) => handlePerspectiveDragOver(event, perspective.id)}
                  onDrop={(event) => void handlePerspectiveDrop(event, perspective.id)}
                  onDragEnd={handlePerspectiveDragEnd}
                >
                  <div className="scene2d-perspective-thumb">
                    <PerspectiveCardPreview scene={selectedScene} perspective={perspective} />
                  </div>
                  <span>{perspectiveLabel(perspective)}</span>
                  <small>
                    <span className="scene2d-perspective-badge">{perspective.type}</span>
                    {perspective.id === selectedScene.primary_perspective_id && (
                      <span className="scene2d-perspective-badge primary">Primary</span>
                    )}
                  </small>
                </button>
              ))}

              <button
                type="button"
                className="scene2d-perspective-add-card"
                onClick={() => void addPerspective()}
                disabled={disabled}
                aria-label="Add perspective"
              >
                <span className="scene2d-perspective-add-mark" aria-hidden="true" />
                <span>Add Perspective</span>
              </button>

              <button
                type="button"
                className="scene2d-perspective-import-card"
                onClick={() => importRef.current?.click()}
                disabled={disabled}
              >
                Import image/PSD
              </button>
            </div>
          )}

          {/* ── Canvas area ──────────────────────────────────────────── */}
          <div className="scene2d-canvas-area" ref={canvasAreaRef}>

            {/* Canvas title overlay (top-left, non-blocking) */}
            {selectedScene && selectedPerspective && (
              <div className="scene2d-canvas-title" aria-hidden="true">
                <div className="scene2d-canvas-title-scene">{sceneLabel(selectedScene)}</div>
                <div className="scene2d-canvas-title-perspective">
                  {perspectiveLabel(selectedPerspective)}
                  {perspectiveTotal > 1 && (
                    <span className="scene2d-canvas-title-index">
                      {' '}· {perspectiveIndex} of {perspectiveTotal}
                    </span>
                  )}
                </div>
              </div>
            )}

            {/* Toast (top-center, auto-dismissed) */}
            {note && (
              <div className="scene2d-toast" role="status" aria-live="polite">
                {note}
              </div>
            )}

            {/* ── Floating Inspector island (top-right) ─────────────── */}
            <div
              className={`scene2d-inspector${inspectorCollapsed ? ' is-collapsed' : ''}`}
              aria-label="Inspector"
            >
              {inspectorCollapsed ? (
                <button
                  type="button"
                  className="scene2d-inspector-pill"
                  onClick={() => setInspectorCollapsed(false)}
                  aria-label="Expand inspector"
                  title="Expand inspector"
                >
                  <span className="scene2d-inspector-pill-label">
                    {selectedScene ? sceneLabel(selectedScene) : 'Inspector'}
                    {selectedPerspective ? ` / ${perspectiveLabel(selectedPerspective)}` : ''}
                  </span>
                  <span className="scene2d-inspector-pill-icon" aria-hidden="true">⊞</span>
                </button>
              ) : (
                <>
                  <div className="scene2d-inspector-header">
                    <span className="scene2d-inspector-heading">Inspector</span>
                    <button
                      type="button"
                      className="scene2d-inspector-close"
                      onClick={() => setInspectorCollapsed(true)}
                      aria-label="Collapse inspector"
                      title="Collapse inspector"
                    >
                      ×
                    </button>
                  </div>

                  <div className="scene2d-inspector-body">
                    {selectedScene ? (
                      <>
                        {/* ── SCENE section ── */}
                        <div className="scene2d-insp-section">
                          <div className="scene2d-insp-section-label">SCENE</div>

                          <label className="scene2d-insp-field">
                            <span>Title</span>
                            <input
                              value={sceneTitle}
                              onChange={(e) => setSceneTitle(e.target.value)}
                              onBlur={() => {
                                if (sceneDirty) void saveSceneDetails()
                              }}
                              onKeyDown={(e) => {
                                if (e.key === 'Enter') e.currentTarget.blur()
                              }}
                              disabled={disabled}
                              placeholder="Scene title"
                            />
                          </label>

                          <label className="scene2d-insp-field">
                            <span>Linked Scene 3D</span>
                            <select
                              value={scene3dLink}
                              onChange={(e) => setScene3dLink(e.target.value)}
                              disabled={disabled}
                            >
                              <option value="">No linked Scene 3D</option>
                              {scene3ds.map((s) => (
                                <option key={s.id} value={s.id}>
                                  {s.title || 'Untitled Scene 3D'}
                                </option>
                              ))}
                            </select>
                          </label>

                          <details
                            className="scene2d-insp-desc-group"
                            open={descriptionOpen}
                            onToggle={(e) => setDescriptionOpen((e.target as HTMLDetailsElement).open)}
                          >
                            <summary className="scene2d-insp-desc-summary">
                              Description{sceneDescription ? ' ·' : ''}
                            </summary>
                            <textarea
                              className="scene2d-insp-desc-area"
                              value={sceneDescription}
                              onChange={(e) => setSceneDescription(e.target.value)}
                              disabled={disabled}
                              rows={3}
                              placeholder="Scene description…"
                            />
                          </details>

                          <div className="scene2d-insp-row">
                            <button
                              type="button"
                              className={`scene2d-insp-save${sceneDirty ? ' is-dirty' : ''}`}
                              onClick={() => void saveSceneDetails()}
                              disabled={disabled}
                            >
                              Save scene
                            </button>
                          </div>
                          <div className="scene2d-insp-danger-row">
                            <button
                              type="button"
                              className="scene2d-insp-danger-btn"
                              onClick={() => void removeScene()}
                              disabled={disabled}
                            >
                              Delete scene
                            </button>
                          </div>
                        </div>

                        {/* ── PERSPECTIVE section ── */}
                        {selectedPerspective ? (
                          <div className="scene2d-insp-section">
                            <div className="scene2d-insp-section-label">PERSPECTIVE</div>

                            {pluginStatusLabel && (
                              <div className={pluginStatusClass}>{pluginStatusLabel}</div>
                            )}

                            <label className="scene2d-insp-field">
                              <span>Title</span>
                              <input
                                value={perspectiveTitle}
                                onChange={(e) => setPerspectiveTitle(e.target.value)}
                                onBlur={() => {
                                  if (perspectiveDirty) void savePerspectiveDetails()
                                }}
                                onKeyDown={(e) => {
                                  if (e.key === 'Enter') e.currentTarget.blur()
                                }}
                                disabled={disabled}
                                placeholder="Perspective title"
                              />
                            </label>

                            <div className="scene2d-insp-meta-row">
                              <span className="scene2d-perspective-badge">
                                {selectedPerspective.type}
                              </span>
                              {selectedPerspective.id === selectedScene.primary_perspective_id && (
                                <span className="scene2d-perspective-badge primary">Primary</span>
                              )}
                            </div>

                            <label className="scene2d-insp-field">
                              <span>Linked Scene 3D (override)</span>
                              <select
                                value={perspective3dLink}
                                onChange={(e) => setPerspective3dLink(e.target.value)}
                                disabled={disabled}
                              >
                                <option value="">Use scene group link</option>
                                {scene3ds.map((s) => (
                                  <option key={s.id} value={s.id}>
                                    {s.title || 'Untitled Scene 3D'}
                                  </option>
                                ))}
                              </select>
                            </label>

                            <div className="scene2d-insp-row">
                              <button
                                type="button"
                                className={`scene2d-insp-save${perspectiveDirty ? ' is-dirty' : ''}`}
                                onClick={() => void savePerspectiveDetails()}
                                disabled={disabled}
                              >
                                Save perspective
                              </button>
                            </div>

                            <div className="scene2d-insp-primary-actions">
                              <button
                                type="button"
                                className="scene2d-insp-open-ps"
                                onClick={() => void openPerspective()}
                                disabled={disabled}
                              >
                                Open in Photoshop
                              </button>
                              <button
                                type="button"
                                className="scene2d-insp-secondary-btn"
                                onClick={() => void refreshPreview()}
                                disabled={disabled}
                              >
                                Refresh preview
                              </button>
                            </div>

                            <div className="scene2d-insp-secondary-actions">
                              <button
                                type="button"
                                className={`scene2d-insp-secondary-btn${selectedPerspective.id === selectedScene.primary_perspective_id ? ' is-state-active' : ''}`}
                                onClick={() => void setPrimary()}
                                disabled={disabled || selectedPerspective.id === selectedScene.primary_perspective_id}
                              >
                                {selectedPerspective.id === selectedScene.primary_perspective_id
                                  ? 'Is primary'
                                  : 'Set primary'}
                              </button>
                              <button
                                type="button"
                                className="scene2d-insp-secondary-btn"
                                onClick={() => void addToReferences()}
                                disabled={disabled || previewMissing}
                              >
                                Add to References
                              </button>
                            </div>

                            <div className="scene2d-insp-danger-row">
                              <button
                                type="button"
                                className="scene2d-insp-danger-btn"
                                onClick={() => void removePerspective()}
                                disabled={disabled}
                              >
                                Delete perspective
                              </button>
                            </div>
                          </div>
                        ) : (
                          <div className="scene2d-insp-section">
                            <div className="scene2d-insp-section-label">PERSPECTIVE</div>
                            <div className="scene2d-insp-empty">No perspective selected</div>
                          </div>
                        )}
                      </>
                    ) : (
                      <div className="scene2d-insp-empty scene2d-insp-empty-pad">
                        No scene selected
                      </div>
                    )}
                  </div>
                </>
              )}
            </div>

            {/* Preview / empty states */}
            {!selectedScene ? (
              <div className="scene2d-canvas-empty">
                <strong>No Scene 2D groups yet</strong>
                <span>Create a Scene to begin organizing Perspectives.</span>
                <button
                  type="button"
                  className="scene2d-canvas-empty-btn"
                  onClick={() => void createScene()}
                  disabled={disabled}
                >
                  Create Scene
                </button>
              </div>
            ) : selectedScene.perspectives.length === 0 ? (
              <div className="scene2d-canvas-empty">
                <strong>No Perspectives in this Scene</strong>
                <div className="scene2d-canvas-empty-actions">
                  <button type="button" onClick={() => void addPerspective()} disabled={disabled}>
                    Create PSD Perspective
                  </button>
                  <button type="button" onClick={() => importRef.current?.click()} disabled={disabled}>
                    Import image/PSD
                  </button>
                </div>
              </div>
            ) : (
              <div className="scene2d-preview-viewport">
                {selectedPerspective && !previewMissing ? (
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
                ) : (
                  <div className="scene2d-preview-placeholder">
                    <strong>No preview available</strong>
                    <span>Open the PSD in Photoshop, export the preview, then refresh.</span>
                    <div className="scene2d-preview-placeholder-actions">
                      <button type="button" onClick={() => void openPerspective()} disabled={disabled}>
                        Open in Photoshop
                      </button>
                      <button type="button" onClick={() => void refreshPreview()} disabled={disabled}>
                        Refresh Preview
                      </button>
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* Floating zoom island (bottom-center) */}
            {selectedScene && selectedScene.perspectives.length > 0 && (
              <div className="scene2d-zoom-island" aria-label="Preview zoom controls">
                <button
                  type="button"
                  className={fitPreview ? 'is-active' : ''}
                  onClick={() => setFitPreview(true)}
                  disabled={!selectedPerspective}
                  aria-label="Fit preview to screen"
                  title="Fit"
                >
                  Fit
                </button>
                <button
                  type="button"
                  onClick={() => setManualPreviewZoom(previewZoom - 10)}
                  disabled={!selectedPerspective || previewZoom <= MIN_PREVIEW_ZOOM}
                  aria-label="Zoom out"
                  title="Zoom out"
                >
                  −
                </button>
                <input
                  type="range"
                  min={MIN_PREVIEW_ZOOM}
                  max={MAX_PREVIEW_ZOOM}
                  step={ZOOM_STEP}
                  value={previewZoom}
                  onChange={(e) => setManualPreviewZoom(Number(e.target.value))}
                  disabled={!selectedPerspective}
                  aria-label="Zoom level"
                  className="scene2d-zoom-slider"
                />
                <button
                  type="button"
                  onClick={() => setManualPreviewZoom(previewZoom + 10)}
                  disabled={!selectedPerspective || previewZoom >= MAX_PREVIEW_ZOOM}
                  aria-label="Zoom in"
                  title="Zoom in"
                >
                  +
                </button>
                <output
                  className="scene2d-zoom-output"
                  onClick={() => setManualPreviewZoom(100)}
                  title="Click to reset to 100%"
                >
                  {fitPreview ? 'Fit' : `${previewZoom}%`}
                </output>
              </div>
            )}
          </div>{/* /.scene2d-canvas-area */}
        </div>{/* /.scene2d-main-col */}
      </div>{/* /.scene2d-workspace */}

      <ContextMenu
        menu={contextMenu}
        items={perspectiveContextMenuItems}
        onClose={() => setContextMenu(null)}
        ariaLabel="Perspective actions"
      />

      <input
        ref={importRef}
        type="file"
        accept=".psd,image/png,image/jpeg,image/webp"
        hidden
        onChange={(e) => void importPerspective(e.target.files?.[0] ?? undefined)}
      />
    </section>
  )
}
