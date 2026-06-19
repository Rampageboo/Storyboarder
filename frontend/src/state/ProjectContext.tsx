import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type Dispatch,
  type PropsWithChildren,
  type SetStateAction,
} from 'react'
import {
  addShot,
  createProject,
  createShotCanvas,
  deleteRefSegment,
  deleteShot,
  getProject,
  moveShotDown,
  moveShotUp,
  openProject,
  openShotSource,
  reorderShots,
  restoreShot,
  saveProject,
  syncShot,
  updateShot,
} from '../api'
import { browseFolder, getAppSession, isNoProjectOpenError, updateAppSession, type AppSession } from '../api'
import type { ProjectPathRequest, ProjectPayload, Shot, ShotUpdate } from '../types'
import { ProjectContext } from './useProject'

export interface ProjectContextValue {
  project: ProjectPayload | null
  selectedShotId: string | null
  setSelectedShotId: (shotId: string | null) => void
  replaceProject: (payload: ProjectPayload, preferredShotId?: string | null) => void
  refreshProjectFromBridge: (pluginSelectedShotId?: string | null) => Promise<void>
  setProject: Dispatch<SetStateAction<ProjectPayload | null>>
  reloadProject: () => Promise<void>
  newProject: (body?: ProjectPathRequest) => Promise<void>
  openProjectFromDialog: () => Promise<void>
  saveProject: () => Promise<void>
  addShotAfterSelection: () => Promise<void>
  deleteSelectedShot: () => Promise<void>
  moveSelectedShot: (direction: 'up' | 'down') => Promise<void>
  reorderBoards: (orderedIds: string[], selectId?: string | null) => Promise<void>
  deleteActiveRefSegment: () => Promise<void>
  undo: () => Promise<void>
  redo: () => Promise<void>
  canUndo: boolean
  canRedo: boolean
  undoLabel: string | null
  redoLabel: string | null
  syncSelectedShot: () => Promise<void>
  openSelectedShotSource: () => Promise<void>
  initialLoading: boolean
  projectActionBusy: boolean
  getDraft: (shotId: string) => ShotUpdate | undefined
  editShotField: <K extends keyof ShotUpdate>(shotId: string, key: K, value: ShotUpdate[K]) => void
  isShotDirty: (shotId: string) => boolean
  dirtyShotIds: string[]
  savingShots: Record<string, boolean>
  saveShot: (shotId: string) => Promise<void>
  flushDirtyShots: () => Promise<void>
  visualEpoch: number
  segmentRange: { anchorShotId: string | null; endShotId: string | null }
  setSegmentAnchor: (shotId: string | null) => void
  setSegmentEnd: (shotId: string | null) => void
  pickSegmentShot: (shotId: string) => void
  clearSegmentRange: () => void
  /** Selected persisted segment for inspect/edit (not the temporary dot draft). */
  activeAppliedSegmentId: string | null
  setActiveAppliedSegmentId: (segmentId: string | null) => void
  clearActiveAppliedSegment: () => void
  /** True when the assignment popover is open for inspect/edit of a persisted segment. */
  refSegmentInspectOpen: boolean
  openRefSegmentInspect: (segmentId: string) => void
  closeRefSegmentInspect: () => void
  dismissRefSegmentUi: () => void
  refApplyUndoToken: string | null
  setRefApplyUndoToken: (token: string | null) => void
  lastError: string | null
  clearError: () => void
  reportError: (error: unknown) => void
}

function projectJsonInFolder(folderPath: string): string {
  const trimmed = folderPath.replace(/[\\/]+$/, '')
  return `${trimmed}/project.json`
}

function shotToUpdate(shot: Shot): ShotUpdate {
  return {
    title: shot.title,
    scene: shot.scene,
    sequence: shot.sequence,
    description: shot.description,
    action_note: shot.action_note,
    camera_note: shot.camera_note,
    character_note: shot.character_note,
    dialogue: shot.dialogue,
    lighting_note: shot.lighting_note,
    transition_note: shot.transition_note,
    duration_seconds: shot.duration_seconds,
    camera_data: shot.camera_data,
    tags: shot.tags,
    status: shot.status,
  }
}

function draftIsDirty(draft: ShotUpdate | undefined): boolean {
  return !!draft && Object.keys(draft).length > 0
}

function preferredShotId(payload: ProjectPayload, wanted?: string | null): string | null {
  if (wanted && payload.shots.some((shot) => shot.shot_id === wanted)) return wanted
  return payload.shots[0]?.shot_id ?? null
}

function projectVisualEpoch(payload: ProjectPayload | null): number {
  if (!payload) return 0
  let hash = payload.dirty ? 17 : 0
  hash = (hash * 31 + payload.shots.length) >>> 0
  for (const shot of payload.shots) {
    hash = (hash * 31 + shot.shot_id.length) >>> 0
    hash = (hash * 31 + String(shot.preview_disk_mtime ?? '').length) >>> 0
    hash = (hash * 31 + String(shot.thumbnail_disk_mtime ?? '').length) >>> 0
    hash = (hash * 31 + String(shot.board_background_disk_mtime ?? '').length) >>> 0
    hash = (hash * 31 + String(shot.image_path ?? '').length) >>> 0
    hash = (hash * 31 + String(shot.preview_image_path ?? '').length) >>> 0
    hash = (hash * 31 + String(shot.source_file_path ?? '').length) >>> 0
    hash = (hash * 31 + (shot.has_board_background ? 1 : 0)) >>> 0
  }
  hash = (hash * 31 + JSON.stringify(payload.settings?.ref_segments ?? []).length) >>> 0
  return hash
}

/** One reversible board operation. undo/redo each perform a server mutation and
 *  return the fresh project payload plus the shot id to select afterwards. */
interface HistoryEntry {
  label: string
  undo: () => Promise<{ payload: ProjectPayload; select?: string | null }>
  redo: () => Promise<{ payload: ProjectPayload; select?: string | null }>
}

const HISTORY_LIMIT = 50

export function ProjectProvider({ children }: PropsWithChildren) {
  const [project, setProject] = useState<ProjectPayload | null>(null)
  const [selectedShotId, setSelectedShotId] = useState<string | null>(null)
  const [lastError, setLastError] = useState<string | null>(null)
  const [initialLoading, setInitialLoading] = useState(true)
  const [projectActionBusy, setProjectActionBusy] = useState(false)
  const [drafts, setDrafts] = useState<Record<string, ShotUpdate>>({})
  const [savingShots, setSavingShots] = useState<Record<string, boolean>>({})
  const [segmentRange, setSegmentRange] = useState<{ anchorShotId: string | null; endShotId: string | null }>({
    anchorShotId: null,
    endShotId: null,
  })
  const [refApplyUndoToken, setRefApplyUndoToken] = useState<string | null>(null)
  const [activeAppliedSegmentId, setActiveAppliedSegmentId] = useState<string | null>(null)
  const [refSegmentInspectOpen, setRefSegmentInspectOpen] = useState(false)
  const [undoStack, setUndoStack] = useState<HistoryEntry[]>([])
  const [redoStack, setRedoStack] = useState<HistoryEntry[]>([])
  const versionsRef = useRef<Record<string, number>>({})
  const projectRef = useRef<ProjectPayload | null>(null)
  const draftsRef = useRef<Record<string, ShotUpdate>>({})
  const undoStackRef = useRef<HistoryEntry[]>([])
  const redoStackRef = useRef<HistoryEntry[]>([])
  const historyBusyRef = useRef(false)

  // Keep refs current after every render so stable callbacks always read latest values.
  useLayoutEffect(() => {
    projectRef.current = project
    draftsRef.current = drafts
    undoStackRef.current = undoStack
    redoStackRef.current = redoStack
  })

  const visualEpoch = useMemo(() => projectVisualEpoch(project), [project])

  useEffect(() => {
    if (!project?.project_json_path || !selectedShotId) return
    void updateAppSession({
      last_project_json_path: project.project_json_path,
      selected_shot_id: selectedShotId,
      recent_projects: [project.project_path, ...(project.settings.recent_projects ?? [])],
    }).catch(() => {})
  }, [project?.project_json_path, project?.project_path, project?.settings.recent_projects, selectedShotId])

  const clearError = useCallback(() => setLastError(null), [])
  const reportError = useCallback((error: unknown) => {
    setLastError(error instanceof Error ? error.message : String(error))
  }, [])

  // Push a reversible board operation onto the undo stack. Recording a new
  // operation discards any pending redo branch, matching standard editor semantics.
  const pushHistory = useCallback((entry: HistoryEntry) => {
    setUndoStack((prev) => [...prev, entry].slice(-HISTORY_LIMIT))
    setRedoStack([])
  }, [])

  const resetEditState = useCallback(() => {
    versionsRef.current = {}
    draftsRef.current = {}
    setDrafts({})
    setSavingShots({})
    setSegmentRange({ anchorShotId: null, endShotId: null })
    setRefApplyUndoToken(null)
    setActiveAppliedSegmentId(null)
    setRefSegmentInspectOpen(false)
    setUndoStack([])
    setRedoStack([])
  }, [])

  const setSegmentAnchor = useCallback((shotId: string | null) => {
    setSegmentRange((range) => ({ ...range, anchorShotId: shotId }))
  }, [])
  const setSegmentEnd = useCallback((shotId: string | null) => {
    setSegmentRange((range) => ({ ...range, endShotId: shotId }))
  }, [])
  const clearSegmentRange = useCallback(() => setSegmentRange({ anchorShotId: null, endShotId: null }), [])
  const clearActiveAppliedSegment = useCallback(() => {
    setActiveAppliedSegmentId(null)
    setRefSegmentInspectOpen(false)
  }, [])
  const closeRefSegmentInspect = useCallback(() => setRefSegmentInspectOpen(false), [])
  const openRefSegmentInspect = useCallback((segmentId: string) => {
    setActiveAppliedSegmentId(segmentId)
    setRefSegmentInspectOpen(true)
  }, [])
  const dismissRefSegmentUi = useCallback(() => {
    setSegmentRange({ anchorShotId: null, endShotId: null })
    setActiveAppliedSegmentId(null)
    setRefSegmentInspectOpen(false)
  }, [])
  const pickSegmentShot = useCallback((shotId: string) => {
    setActiveAppliedSegmentId(null)
    setRefSegmentInspectOpen(false)
    setSegmentRange((range) => {
      if (!range.anchorShotId) return { anchorShotId: shotId, endShotId: null }
      if (!range.endShotId) return { anchorShotId: range.anchorShotId, endShotId: shotId }
      return { anchorShotId: shotId, endShotId: null }
    })
  }, [])

  const openPayload = useCallback(
    (payload: ProjectPayload, selected?: string | null) => {
      resetEditState()
      setProject(payload)
      setLastError(null)
      setSelectedShotId(preferredShotId(payload, selected))
    },
    [resetEditState],
  )

  const replaceProject = useCallback((payload: ProjectPayload, selected?: string | null) => {
    setProject(payload)
    setLastError(null)
    setSelectedShotId((current) => preferredShotId(payload, selected === undefined ? current : selected))
  }, [])

  const refreshProjectFromBridge = useCallback(
    async (pluginSelectedShotId?: string | null) => {
      const payload = await getProject()
      const pluginSelectionValid = !!pluginSelectedShotId && payload.shots.some((shot) => shot.shot_id === pluginSelectedShotId)
      // A plugin-driven refresh means boards/metadata changed outside our control;
      // discard history so undo/redo can never replay against a stale world.
      setUndoStack([])
      setRedoStack([])
      replaceProject(payload, pluginSelectionValid ? pluginSelectedShotId : undefined)
    },
    [replaceProject],
  )

  const editShotField = useCallback(<K extends keyof ShotUpdate>(shotId: string, key: K, value: ShotUpdate[K]) => {
    versionsRef.current[shotId] = (versionsRef.current[shotId] ?? 0) + 1
    setDrafts((prev) => ({ ...prev, [shotId]: { ...(prev[shotId] ?? {}), [key]: value } }))
  }, [])

  const getDraft = useCallback((shotId: string): ShotUpdate | undefined => drafts[shotId], [drafts])
  const isShotDirty = useCallback((shotId: string) => draftIsDirty(drafts[shotId]), [drafts])
  const dirtyShotIds = useMemo(() => Object.keys(drafts).filter((id) => draftIsDirty(drafts[id])), [drafts])

  const saveShot = useCallback(async (shotId: string): Promise<void> => {
    const draft = draftsRef.current[shotId]
    if (!draftIsDirty(draft)) return
    const baseShot = projectRef.current?.shots.find((shot) => shot.shot_id === shotId)
    if (!baseShot) return
    const startVersion = versionsRef.current[shotId] ?? 0
    const fullUpdate: ShotUpdate = { ...shotToUpdate(baseShot), ...draft }

    setSavingShots((prev) => ({ ...prev, [shotId]: true }))
    try {
      const payload = await updateShot(shotId, fullUpdate)
      if ((versionsRef.current[shotId] ?? 0) !== startVersion) return
      const serverShot = payload.shots.find((shot) => shot.shot_id === shotId)
      setProject((prev) => {
        if (!prev) return payload
        return {
          ...prev,
          shots: serverShot ? prev.shots.map((shot) => (shot.shot_id === shotId ? serverShot : shot)) : prev.shots,
          dirty: payload.dirty,
          name: payload.name,
          settings: payload.settings,
          statuses: payload.statuses,
          project_path: payload.project_path,
          project_json_path: payload.project_json_path,
        }
      })
      setDrafts((prev) => {
        if (!(shotId in prev)) return prev
        const next = { ...prev }
        delete next[shotId]
        return next
      })
      setLastError(null)
    } catch (error) {
      setLastError(error instanceof Error ? error.message : String(error))
      throw error
    } finally {
      setSavingShots((prev) => {
        const next = { ...prev }
        delete next[shotId]
        return next
      })
    }
  }, [])

  const flushDirtyShots = useCallback(async (): Promise<void> => {
    for (let attempt = 0; attempt < 5; attempt += 1) {
      const ids = Object.keys(draftsRef.current).filter((id) => draftIsDirty(draftsRef.current[id]))
      if (ids.length === 0) return
      for (const id of ids) await saveShot(id)
    }
    const remaining = Object.keys(draftsRef.current).filter((id) => draftIsDirty(draftsRef.current[id]))
    if (remaining.length > 0) {
      const message = 'Unsaved edits changed while saving. Try again before continuing.'
      setLastError(message)
      throw new Error(message)
    }
  }, [saveShot])

  const undo = useCallback(async () => {
    if (historyBusyRef.current) return
    const entry = undoStackRef.current[undoStackRef.current.length - 1]
    if (!entry) return
    historyBusyRef.current = true
    try {
      await flushDirtyShots()
      const { payload, select } = await entry.undo()
      replaceProject(payload, select)
      setUndoStack((prev) => prev.slice(0, -1))
      setRedoStack((prev) => [...prev, entry])
    } catch (error) {
      setLastError(error instanceof Error ? error.message : String(error))
    } finally {
      historyBusyRef.current = false
    }
  }, [flushDirtyShots, replaceProject])

  const redo = useCallback(async () => {
    if (historyBusyRef.current) return
    const entry = redoStackRef.current[redoStackRef.current.length - 1]
    if (!entry) return
    historyBusyRef.current = true
    try {
      await flushDirtyShots()
      const { payload, select } = await entry.redo()
      replaceProject(payload, select)
      setRedoStack((prev) => prev.slice(0, -1))
      setUndoStack((prev) => [...prev, entry])
    } catch (error) {
      setLastError(error instanceof Error ? error.message : String(error))
    } finally {
      historyBusyRef.current = false
    }
  }, [flushDirtyShots, replaceProject])

  const reloadProject = useCallback(async () => {
    setInitialLoading(true)
    try {
      const session: AppSession = await getAppSession().catch((): AppSession => ({}))
      try {
        const payload = await getProject()
        openPayload(payload, typeof session.selected_shot_id === 'string' ? session.selected_shot_id : null)
      } catch (error) {
        if (!isNoProjectOpenError(error)) throw error
        const lastPath = typeof session.last_project_json_path === 'string' ? session.last_project_json_path : ''
        if (!lastPath) {
          resetEditState()
          setProject(null)
          setSelectedShotId(null)
          setLastError(null)
          return
        }
        const payload = await openProject({ project_json_path: lastPath })
        openPayload(payload, typeof session.selected_shot_id === 'string' ? session.selected_shot_id : null)
      }
    } catch (error) {
      resetEditState()
      setProject(null)
      setSelectedShotId(null)
      setLastError(error instanceof Error ? error.message : String(error))
    } finally {
      setInitialLoading(false)
    }
  }, [openPayload, resetEditState])

  const newProjectAction = useCallback(
    async (body: ProjectPathRequest = {}) => {
      setProjectActionBusy(true)
      try {
        await flushDirtyShots()
        let nextBody = body
        if (!nextBody.path) {
          const result = await browseFolder()
          if (result.cancelled || !result.path) return
          nextBody = { ...nextBody, path: result.path }
        }
        const payload = await createProject(nextBody)
        openPayload(payload, payload.shots[0]?.shot_id ?? null)
      } catch (error) {
        setLastError(error instanceof Error ? error.message : String(error))
        throw error
      } finally {
        setProjectActionBusy(false)
      }
    },
    [flushDirtyShots, openPayload],
  )

  const openProjectFromDialog = useCallback(async () => {
    setProjectActionBusy(true)
    try {
      await flushDirtyShots()
      const result = await browseFolder()
      if (result.cancelled || !result.path) return
      const payload = await openProject({ project_json_path: projectJsonInFolder(result.path) })
      openPayload(payload, payload.shots[0]?.shot_id ?? null)
    } catch (error) {
      setLastError(error instanceof Error ? error.message : String(error))
      throw error
    } finally {
      setProjectActionBusy(false)
    }
  }, [flushDirtyShots, openPayload])

  const saveProjectAction = useCallback(async () => {
    setProjectActionBusy(true)
    try {
      await flushDirtyShots()
      const payload = await saveProject()
      setProject(payload)
      setLastError(null)
    } catch (error) {
      setLastError(error instanceof Error ? error.message : String(error))
      throw error
    } finally {
      setProjectActionBusy(false)
    }
  }, [flushDirtyShots])

  const addShotAfterSelection = useCallback(async () => {
    const current = projectRef.current
    const afterId = current && selectedShotId ? selectedShotId : undefined
    const addBody = afterId ? { after_shot_id: afterId } : {}
    const indexAfter = (payload: ProjectPayload): number =>
      afterId
        ? Math.min(payload.shots.findIndex((shot) => shot.shot_id === afterId) + 1, payload.shots.length - 1)
        : payload.shots.length - 1
    const payload = await addShot(addBody)
    let createdId = payload.shots[indexAfter(payload)]?.shot_id ?? null
    replaceProject(payload, createdId)
    if (!createdId) return
    pushHistory({
      label: 'Add board',
      undo: async () => ({ payload: await deleteShot(createdId as string), select: afterId ?? null }),
      redo: async () => {
        const p = await addShot(addBody)
        createdId = p.shots[indexAfter(p)]?.shot_id ?? createdId
        return { payload: p, select: createdId }
      },
    })
  }, [replaceProject, selectedShotId, pushHistory])

  const deleteSelectedShot = useCallback(async () => {
    const current = projectRef.current
    if (!current || !selectedShotId) return
    const selectedIndex = current.shots.findIndex((shot) => shot.shot_id === selectedShotId)
    const removedShot = current.shots[selectedIndex]
    if (!removedShot) return
    const payload = await deleteShot(selectedShotId)
    const nextIndex = Math.min(Math.max(selectedIndex, 0), payload.shots.length - 1)
    replaceProject(payload, payload.shots[nextIndex]?.shot_id ?? null)
    pushHistory({
      label: 'Delete board',
      undo: async () => ({
        payload: await restoreShot({ shot: removedShot, index: selectedIndex }),
        select: removedShot.shot_id,
      }),
      redo: async () => {
        const p = await deleteShot(removedShot.shot_id)
        const ni = Math.min(Math.max(selectedIndex, 0), p.shots.length - 1)
        return { payload: p, select: p.shots[ni]?.shot_id ?? null }
      },
    })
  }, [replaceProject, selectedShotId, pushHistory])

  // Single-step nudge via the ← / → buttons. Trivially reversible by pressing the
  // other arrow, so this intentionally does NOT record an undo entry. Drag-to-reorder
  // (reorderBoards) is the multi-position move that records history.
  const moveSelectedShot = useCallback(async (direction: 'up' | 'down') => {
    if (!selectedShotId) return
    const payload = direction === 'up' ? await moveShotUp(selectedShotId) : await moveShotDown(selectedShotId)
    replaceProject(payload, selectedShotId)
  }, [replaceProject, selectedShotId])

  // Drag-to-reorder: persist an explicit board order and record it as one undoable step.
  const reorderBoards = useCallback(async (orderedIds: string[], selectId?: string | null) => {
    const current = projectRef.current
    if (!current) return
    const prevOrder = current.shots.map((shot) => shot.shot_id)
    const unchanged = prevOrder.length === orderedIds.length && prevOrder.every((id, i) => id === orderedIds[i])
    if (unchanged) return
    const select = selectId ?? selectedShotId
    replaceProject(await reorderShots({ shot_ids: orderedIds }), select)
    pushHistory({
      label: 'Reorder boards',
      undo: async () => ({ payload: await reorderShots({ shot_ids: prevOrder }), select }),
      redo: async () => ({ payload: await reorderShots({ shot_ids: orderedIds }), select }),
    })
  }, [replaceProject, selectedShotId, pushHistory])

  const deleteActiveRefSegment = useCallback(async () => {
    if (!activeAppliedSegmentId) return
    const segmentId = activeAppliedSegmentId
    dismissRefSegmentUi()
    replaceProject(await deleteRefSegment(segmentId))
  }, [activeAppliedSegmentId, dismissRefSegmentUi, replaceProject])

  const syncSelectedShot = useCallback(async () => {
    if (!selectedShotId) return
    replaceProject(await syncShot(selectedShotId), selectedShotId)
  }, [replaceProject, selectedShotId])

  const openSelectedShotSource = useCallback(async () => {
    const current = projectRef.current
    if (!current || !selectedShotId) return
    const shot = current.shots.find((item) => item.shot_id === selectedShotId)
    if (shot && !shot.source_file_path) {
      replaceProject(await createShotCanvas(selectedShotId, {}), selectedShotId)
    }
    await openShotSource(selectedShotId)
  }, [replaceProject, selectedShotId])

  const value = useMemo<ProjectContextValue>(
    () => ({
      project,
      selectedShotId,
      setSelectedShotId,
      replaceProject,
      refreshProjectFromBridge,
      setProject,
      reloadProject,
      newProject: newProjectAction,
      openProjectFromDialog,
      saveProject: saveProjectAction,
      addShotAfterSelection,
      deleteSelectedShot,
      moveSelectedShot,
      reorderBoards,
      deleteActiveRefSegment,
      undo,
      redo,
      canUndo: undoStack.length > 0,
      canRedo: redoStack.length > 0,
      undoLabel: undoStack[undoStack.length - 1]?.label ?? null,
      redoLabel: redoStack[redoStack.length - 1]?.label ?? null,
      syncSelectedShot,
      openSelectedShotSource,
      initialLoading,
      projectActionBusy,
      getDraft,
      editShotField,
      isShotDirty,
      dirtyShotIds,
      savingShots,
      saveShot,
      flushDirtyShots,
      visualEpoch,
      segmentRange,
      setSegmentAnchor,
      setSegmentEnd,
      pickSegmentShot,
      clearSegmentRange,
      activeAppliedSegmentId,
      setActiveAppliedSegmentId,
      clearActiveAppliedSegment,
      refSegmentInspectOpen,
      openRefSegmentInspect,
      closeRefSegmentInspect,
      dismissRefSegmentUi,
      refApplyUndoToken,
      setRefApplyUndoToken,
      lastError,
      clearError,
      reportError,
    }),
    [project, selectedShotId, replaceProject, refreshProjectFromBridge, reloadProject, newProjectAction, openProjectFromDialog, saveProjectAction, addShotAfterSelection, deleteSelectedShot, moveSelectedShot, reorderBoards, deleteActiveRefSegment, undo, redo, undoStack, redoStack, syncSelectedShot, openSelectedShotSource, initialLoading, projectActionBusy, getDraft, editShotField, isShotDirty, dirtyShotIds, savingShots, saveShot, flushDirtyShots, visualEpoch, segmentRange, setSegmentAnchor, setSegmentEnd, pickSegmentShot, clearSegmentRange, activeAppliedSegmentId, setActiveAppliedSegmentId, clearActiveAppliedSegment, refSegmentInspectOpen, openRefSegmentInspect, closeRefSegmentInspect, dismissRefSegmentUi, refApplyUndoToken, lastError, clearError, reportError],
  )

  return <ProjectContext.Provider value={value}>{children}</ProjectContext.Provider>
}

