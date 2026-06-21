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
  getMissingFiles,
  getProject,
  moveShotDown,
  moveShotUp,
  openProject,
  openShotSource,
  reorderShots,
  restoreRefApply,
  restoreShot,
  saveProject,
  snapshotRefBoards,
  syncShot,
  updateSettings,
  updateShot,
} from '../api'
import { bootstrapApp, browseFolder, refreshPreviewAnalysis, updateAppSession } from '../api'
import type { MissingFileRow, ProjectPathRequest, ProjectPayload, SettingsUpdate, ShotUpdate } from '../types'
import { shotToUpdate } from '../utils/shotUpdate'
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
  insertShotAtIndex: (index: number) => Promise<void>
  deleteSelectedShot: () => Promise<void>
  moveSelectedShot: (direction: 'up' | 'down') => Promise<void>
  reorderBoards: (orderedIds: string[], selectId?: string | null) => Promise<void>
  deleteActiveRefSegment: () => Promise<void>
  deleteRefSegmentUndoable: (segmentId: string) => Promise<void>
  recordRefApply: (opts: { label: string; undoToken: string; redo: () => Promise<ProjectPayload> }) => void
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
  missingFiles: MissingFileRow[] | null
  missingFilesLoading: boolean
  refreshMissingFiles: () => void
  refreshPreviewFields: () => Promise<void>
}

function projectJsonInFolder(folderPath: string): string {
  const trimmed = folderPath.replace(/[\\/]+$/, '')
  return `${trimmed}/project.json`
}

function draftIsDirty(draft: ShotUpdate | undefined): boolean {
  return !!draft && Object.keys(draft).length > 0
}

function preferredShotId(payload: ProjectPayload, wanted?: string | null): string | null {
  if (wanted && payload.shots.some((shot) => shot.shot_id === wanted)) return wanted
  return payload.shots[0]?.shot_id ?? null
}

function hashString(value: string): number {
  let hash = 2166136261
  for (let i = 0; i < value.length; i += 1) {
    hash ^= value.charCodeAt(i)
    hash = Math.imul(hash, 16777619)
  }
  return hash >>> 0
}

function mixHash(hash: number, value: unknown): number {
  return Math.imul(hash ^ hashString(String(value ?? '')), 16777619) >>> 0
}

function projectVisualEpoch(payload: ProjectPayload | null): number {
  if (!payload) return 0
  let hash = payload.dirty ? 17 : 0
  hash = (hash * 31 + payload.shots.length) >>> 0
  for (const shot of payload.shots) {
    hash = mixHash(hash, shot.shot_id)
    hash = mixHash(hash, shot.preview_disk_mtime)
    hash = mixHash(hash, shot.thumbnail_disk_mtime)
    hash = mixHash(hash, shot.board_background_disk_mtime)
    hash = mixHash(hash, shot.image_path)
    hash = mixHash(hash, shot.preview_image_path)
    hash = mixHash(hash, shot.source_file_path)
    hash = mixHash(hash, shot.has_board_background ? '1' : '0')
  }
  hash = mixHash(hash, JSON.stringify(payload.settings?.ref_segments ?? []))
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
  const [missingFiles, setMissingFiles] = useState<MissingFileRow[] | null>(null)
  const [missingFilesLoading, setMissingFilesLoading] = useState(false)
  const versionsRef = useRef<Record<string, number>>({})
  const projectRef = useRef<ProjectPayload | null>(null)
  const draftsRef = useRef<Record<string, ShotUpdate>>({})
  const undoStackRef = useRef<HistoryEntry[]>([])
  const redoStackRef = useRef<HistoryEntry[]>([])
  const historyBusyRef = useRef(false)
  const missingFilesInFlightRef = useRef(false)

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
    setMissingFiles(null)
  }, [])

  const refreshMissingFiles = useCallback(() => {
    if (missingFilesInFlightRef.current) return
    if (!projectRef.current) return
    missingFilesInFlightRef.current = true
    setMissingFilesLoading(true)
    getMissingFiles()
      .then((payload) => {
        setMissingFiles(payload.missing_files ?? [])
      })
      .catch(() => {
        // Silently ignore: missing-file errors must never break the UI
      })
      .finally(() => {
        missingFilesInFlightRef.current = false
        setMissingFilesLoading(false)
      })
  }, [])

  // Defer missing-files scan until after first paint so it never blocks initial loading.
  useEffect(() => {
    if (!project) return
    const hasIdleCallback = typeof window !== 'undefined' && 'requestIdleCallback' in window
    let id: number
    if (hasIdleCallback) {
      id = (window as Window & typeof globalThis).requestIdleCallback(refreshMissingFiles)
    } else {
      id = window.setTimeout(refreshMissingFiles, 500)
    }
    return () => {
      if (hasIdleCallback) {
        (window as Window & typeof globalThis).cancelIdleCallback(id)
      } else {
        clearTimeout(id)
      }
    }
  }, [project?.project_json_path, refreshMissingFiles])

  // Narrow project refresh: merge only preview-analysis fields from the server
  // without touching undo/redo history, selected shot, or unsaved drafts.
  const refreshPreviewFields = useCallback(async () => {
    if (!projectRef.current) return
    const payload = await getProject()
    const shotMap = new Map(payload.shots.map((s) => [s.shot_id, s]))
    setProject((prev) => {
      if (!prev) return payload
      return {
        ...prev,
        shots: prev.shots.map((s) => {
          const fresh = shotMap.get(s.shot_id)
          if (!fresh) return s
          return {
            ...s,
            has_artwork_preview: fresh.has_artwork_preview,
            preview_has_transparency: fresh.preview_has_transparency,
            preview_analysis_state: fresh.preview_analysis_state,
            preview_disk_mtime: fresh.preview_disk_mtime,
          }
        }),
      }
    })
  }, [])

  // Trigger preview analysis once per project path, after initial loading clears.
  // Fires for both the first project load and subsequent project switches.
  const lastAnalysisProjectRef = useRef<string | null>(null)
  useEffect(() => {
    if (initialLoading) return
    if (!project) { lastAnalysisProjectRef.current = null; return }
    if (project.project_path === lastAnalysisProjectRef.current) return
    lastAnalysisProjectRef.current = project.project_path
    const doAnalysis = () => { void refreshPreviewAnalysis().catch(() => {}) }
    const hasIdleCallback = typeof window !== 'undefined' && 'requestIdleCallback' in window
    if (hasIdleCallback) {
      const id = (window as Window & typeof globalThis).requestIdleCallback(doAnalysis)
      return () => (window as Window & typeof globalThis).cancelIdleCallback(id)
    }
    const id = window.setTimeout(doAnalysis, 500)
    return () => clearTimeout(id)
  }, [initialLoading, project?.project_path])

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
      const bootstrap = await bootstrapApp()
      const session = bootstrap.session
      const selectedShotIdFromSession = typeof session.selected_shot_id === 'string' ? session.selected_shot_id : null
      if (bootstrap.project) {
        openPayload(bootstrap.project, selectedShotIdFromSession)
      } else {
        // No project from bootstrap (none open, no last path, or invalid last path)
        resetEditState()
        setProject(null)
        setSelectedShotId(null)
        setLastError(null)
      }
      if (bootstrap.warning) {
        // Non-fatal: stale last-project path etc.
        console.warn('[bootstrap]', bootstrap.warning)
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

  const insertShotAtIndex = useCallback(async (index: number) => {
    const current = projectRef.current
    if (!current) return
    const previousShots = current.shots
    const targetIndex = Math.max(0, Math.min(index, previousShots.length))
    const afterId = targetIndex > 0 ? previousShots[targetIndex - 1]?.shot_id : undefined
    const addBody = afterId ? { after_shot_id: afterId } : {}
    const placeCreated = async (payload: ProjectPayload, createdId: string): Promise<ProjectPayload> => {
      if (targetIndex !== 0 || previousShots.length === 0) return payload
      const previousOrder = previousShots.map((shot) => shot.shot_id)
      return reorderShots({ shot_ids: [createdId, ...previousOrder] })
    }
    const createdIdFrom = (payload: ProjectPayload): string | null => {
      if (targetIndex === 0) return payload.shots[0]?.shot_id ?? null
      return payload.shots[targetIndex]?.shot_id ?? null
    }

    let payload = await addShot(addBody)
    let createdId =
      targetIndex === 0
        ? payload.shots[payload.shots.length - 1]?.shot_id ?? null
        : payload.shots[targetIndex]?.shot_id ?? null
    if (!createdId) return
    payload = await placeCreated(payload, createdId)
    createdId = createdIdFrom(payload) ?? createdId
    replaceProject(payload, createdId)
    pushHistory({
      label: 'Insert board',
      undo: async () => ({ payload: await deleteShot(createdId as string), select: afterId ?? null }),
      redo: async () => {
        let p = await addShot(addBody)
        const nextCreatedId =
          targetIndex === 0 ? p.shots[p.shots.length - 1]?.shot_id ?? null : p.shots[targetIndex]?.shot_id ?? null
        if (nextCreatedId) {
          p = await placeCreated(p, nextCreatedId)
          createdId = createdIdFrom(p) ?? nextCreatedId
        }
        return { payload: p, select: createdId }
      },
    })
  }, [replaceProject, pushHistory])

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

  // Record a reference apply/replace into the global undo stack. Undo restores the
  // pre-apply boards via the apply's undo token (same as the footer button); redo re-runs
  // the bake. The footer "Undo last apply" buttons remain as a resilient fallback.
  const recordRefApply = useCallback(
    (opts: { label: string; undoToken: string; redo: () => Promise<ProjectPayload> }) => {
      let token = opts.undoToken
      pushHistory({
        label: opts.label,
        undo: async () => {
          let payload: ProjectPayload | null = null
          if (token) {
            try {
              payload = await restoreRefApply(token)
            } catch {
              payload = null
            }
          }
          if (!payload) payload = await getProject()
          setRefApplyUndoToken(null)
          return { payload }
        },
        redo: async () => {
          const payload = await opts.redo()
          const next = (payload as { undo_token?: unknown }).undo_token
          token = typeof next === 'string' ? next : ''
          setRefApplyUndoToken(token || null)
          return { payload }
        },
      })
    },
    [pushHistory],
  )

  // Delete a reference segment as one undoable step: snapshot affected boards first, delete,
  // then on undo restore those boards and re-insert the segment record into settings.
  const deleteRefSegmentUndoable = useCallback(
    async (segmentId: string) => {
      const current = projectRef.current
      if (!current) return
      const records = (current.settings?.ref_segments ?? []) as Array<{
        id?: string
        anchor_shot_id?: string
        end_shot_id?: string
      }>
      const record = records.find((seg) => seg?.id === segmentId)
      const anchor = record?.anchor_shot_id ?? ''
      const end = record?.end_shot_id ?? ''
      let token: string | null = null
      if (anchor && end) {
        try {
          token = (await snapshotRefBoards({ anchor_shot_id: anchor, end_shot_id: end })).undo_token
        } catch {
          token = null
        }
      }
      replaceProject(await deleteRefSegment(segmentId))
      if (!record || !token) return
      let currentToken = token
      pushHistory({
        label: 'Delete reference',
        undo: async () => {
          const restored = await restoreRefApply(currentToken)
          const merged = [...((restored.settings?.ref_segments as unknown[]) ?? []), record]
          const payload = await updateSettings({ ref_segments: merged } as unknown as SettingsUpdate)
          return { payload }
        },
        redo: async () => {
          if (anchor && end) {
            try {
              currentToken = (await snapshotRefBoards({ anchor_shot_id: anchor, end_shot_id: end })).undo_token
            } catch {
              // keep the prior token; a later undo simply re-restores from it
            }
          }
          const payload = await deleteRefSegment(segmentId)
          return { payload }
        },
      })
    },
    [replaceProject, pushHistory],
  )

  const deleteActiveRefSegment = useCallback(async () => {
    if (!activeAppliedSegmentId) return
    const segmentId = activeAppliedSegmentId
    dismissRefSegmentUi()
    await deleteRefSegmentUndoable(segmentId)
  }, [activeAppliedSegmentId, dismissRefSegmentUi, deleteRefSegmentUndoable])

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
      insertShotAtIndex,
      deleteSelectedShot,
      moveSelectedShot,
      reorderBoards,
      deleteActiveRefSegment,
      deleteRefSegmentUndoable,
      recordRefApply,
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
      missingFiles,
      missingFilesLoading,
      refreshMissingFiles,
      refreshPreviewFields,
    }),
    [project, selectedShotId, replaceProject, refreshProjectFromBridge, reloadProject, newProjectAction, openProjectFromDialog, saveProjectAction, addShotAfterSelection, insertShotAtIndex, deleteSelectedShot, moveSelectedShot, reorderBoards, deleteActiveRefSegment, deleteRefSegmentUndoable, recordRefApply, undo, redo, undoStack, redoStack, syncSelectedShot, openSelectedShotSource, initialLoading, projectActionBusy, getDraft, editShotField, isShotDirty, dirtyShotIds, savingShots, saveShot, flushDirtyShots, visualEpoch, segmentRange, setSegmentAnchor, setSegmentEnd, pickSegmentShot, clearSegmentRange, activeAppliedSegmentId, setActiveAppliedSegmentId, clearActiveAppliedSegment, refSegmentInspectOpen, openRefSegmentInspect, closeRefSegmentInspect, dismissRefSegmentUi, refApplyUndoToken, lastError, clearError, reportError, missingFiles, missingFilesLoading, refreshMissingFiles, refreshPreviewFields],
  )

  return <ProjectContext.Provider value={value}>{children}</ProjectContext.Provider>
}

