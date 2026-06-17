import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type Dispatch,
  type PropsWithChildren,
  type SetStateAction,
} from 'react'
import { createProject, getProject, openProject, saveProject, updateShot } from '../api'
import { browseProjectJson } from '../api'
import { isNoProjectOpenError } from '../api'
import type { ProjectPathRequest, ProjectPayload, Shot, ShotUpdate } from '../types'

interface ProjectContextValue {
  project: ProjectPayload | null
  selectedShotId: string | null
  setSelectedShotId: (shotId: string | null) => void
  /** Accepts a value or a functional updater so stale-safe saves can merge into the latest state. */
  setProject: Dispatch<SetStateAction<ProjectPayload | null>>
  reloadProject: () => Promise<void>
  newProject: (body?: ProjectPathRequest) => Promise<void>
  openProjectFromDialog: () => Promise<void>
  saveProject: () => Promise<void>
  initialLoading: boolean
  projectActionBusy: boolean
  // Per-shot editing (centralized dirty/version tracking).
  getDraft: (shotId: string) => ShotUpdate | undefined
  editShotField: <K extends keyof ShotUpdate>(shotId: string, key: K, value: ShotUpdate[K]) => void
  isShotDirty: (shotId: string) => boolean
  dirtyShotIds: string[]
  savingShots: Record<string, boolean>
  saveShot: (shotId: string) => Promise<void>
  flushDirtyShots: () => Promise<void>
  visualEpoch: number
  // Reference-segment range draft, shared by the filmstrip dots and the ReferenceSidebar form.
  // Local-only until the user applies — selecting dots never writes to disk.
  segmentRange: { anchorShotId: string | null; endShotId: string | null }
  setSegmentAnchor: (shotId: string | null) => void
  setSegmentEnd: (shotId: string | null) => void
  pickSegmentShot: (shotId: string) => void
  clearSegmentRange: () => void
  lastError: string | null
  clearError: () => void
  reportError: (error: unknown) => void
}

const ProjectContext = createContext<ProjectContextValue | null>(null)

/** The editable subset sent on every PATCH. Backend resets omitted fields to defaults, so this must be complete. */
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

export function ProjectProvider({ children }: PropsWithChildren) {
  const [project, setProject] = useState<ProjectPayload | null>(null)
  const [selectedShotId, setSelectedShotId] = useState<string | null>(null)
  const [lastError, setLastError] = useState<string | null>(null)
  const [initialLoading, setInitialLoading] = useState(true)
  const [projectActionBusy, setProjectActionBusy] = useState(false)

  // Per-shot edit state. `drafts` holds only changed fields per shot; presence ⇒ dirty.
  const [drafts, setDrafts] = useState<Record<string, ShotUpdate>>({})
  const [savingShots, setSavingShots] = useState<Record<string, boolean>>({})
  const [visualEpoch, setVisualEpoch] = useState(0)
  const [segmentRange, setSegmentRange] = useState<{ anchorShotId: string | null; endShotId: string | null }>({
    anchorShotId: null,
    endShotId: null,
  })
  const versionsRef = useRef<Record<string, number>>({})

  // Refs mirror the latest committed values for synchronous reads inside async save/flush.
  const projectRef = useRef<ProjectPayload | null>(null)
  const draftsRef = useRef<Record<string, ShotUpdate>>({})
  projectRef.current = project
  draftsRef.current = drafts

  // Bump thumbnail cache keys whenever committed project data changes (reference apply, sync, etc.).
  useEffect(() => {
    if (project) setVisualEpoch((v) => v + 1)
  }, [project])

  const clearError = useCallback(() => setLastError(null), [])

  const reportError = useCallback((error: unknown) => {
    setLastError(error instanceof Error ? error.message : String(error))
  }, [])

  const resetEditState = useCallback(() => {
    versionsRef.current = {}
    draftsRef.current = {}
    setDrafts({})
    setSavingShots({})
    setSegmentRange({ anchorShotId: null, endShotId: null })
  }, [])

  const setSegmentAnchor = useCallback((shotId: string | null) => {
    setSegmentRange((r) => ({ ...r, anchorShotId: shotId }))
  }, [])

  const setSegmentEnd = useCallback((shotId: string | null) => {
    setSegmentRange((r) => ({ ...r, endShotId: shotId }))
  }, [])

  const clearSegmentRange = useCallback(() => {
    setSegmentRange({ anchorShotId: null, endShotId: null })
  }, [])

  // Filmstrip dot interaction: first pick sets the start, second sets the end, a third starts over.
  const pickSegmentShot = useCallback((shotId: string) => {
    setSegmentRange((r) => {
      if (!r.anchorShotId) return { anchorShotId: shotId, endShotId: null }
      if (!r.endShotId) return { anchorShotId: r.anchorShotId, endShotId: shotId }
      return { anchorShotId: shotId, endShotId: null }
    })
  }, [])

  const editShotField = useCallback(
    <K extends keyof ShotUpdate>(shotId: string, key: K, value: ShotUpdate[K]) => {
      versionsRef.current[shotId] = (versionsRef.current[shotId] ?? 0) + 1
      setDrafts((prev) => ({
        ...prev,
        [shotId]: { ...(prev[shotId] ?? {}), [key]: value },
      }))
    },
    [],
  )

  const getDraft = useCallback((shotId: string): ShotUpdate | undefined => drafts[shotId], [drafts])

  const isShotDirty = useCallback((shotId: string) => draftIsDirty(drafts[shotId]), [drafts])

  const dirtyShotIds = useMemo(
    () => Object.keys(drafts).filter((id) => draftIsDirty(drafts[id])),
    [drafts],
  )

  // Save one shot, guarding against stale responses. Tied to the passed shotId, never selectedShotId.
  const saveShot = useCallback(async (shotId: string): Promise<void> => {
    const draft = draftsRef.current[shotId]
    if (!draftIsDirty(draft)) return
    const baseShot = projectRef.current?.shots.find((s) => s.shot_id === shotId)
    if (!baseShot) return

    const startVersion = versionsRef.current[shotId] ?? 0
    const fullUpdate: ShotUpdate = { ...shotToUpdate(baseShot), ...draft }

    setSavingShots((prev) => ({ ...prev, [shotId]: true }))
    try {
      const payload = await updateShot(shotId, fullUpdate)

      // If the user kept editing this shot while the request was in flight, the response is stale:
      // ignore the returned payload entirely and keep the draft. Never overwrite newer local edits.
      if ((versionsRef.current[shotId] ?? 0) !== startVersion) return

      // Safe: merge only this shot's server data into the latest project state.
      const serverShot = payload.shots.find((s) => s.shot_id === shotId)
      setProject((prev) => {
        if (!prev) return payload
        const shots = serverShot
          ? prev.shots.map((s) => (s.shot_id === shotId ? serverShot : s))
          : prev.shots
        return {
          ...prev,
          shots,
          dirty: payload.dirty,
          name: payload.name,
          settings: payload.settings,
          statuses: payload.statuses,
          project_path: payload.project_path,
          project_json_path: payload.project_json_path,
        }
      })
      // Shot is no longer dirty.
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

  // Save every dirty shot before destructive/structural actions. Sequential to avoid interleaved
  // server-side mutation of the shared project. Re-throws so callers abort their action.
  //
  // A stale in-flight save keeps its draft (saveShot ignores stale responses), so one pass may not
  // reach clean. Retry a bounded number of times until no dirty drafts remain; if edits keep
  // changing past the limit, fail loudly so the caller aborts instead of discarding the draft.
  const flushDirtyShots = useCallback(async (): Promise<void> => {
    for (let attempt = 0; attempt < 5; attempt += 1) {
      const ids = Object.keys(draftsRef.current).filter((id) => draftIsDirty(draftsRef.current[id]))
      if (ids.length === 0) return
      for (const id of ids) {
        await saveShot(id)
      }
    }

    const remaining = Object.keys(draftsRef.current).filter((id) => draftIsDirty(draftsRef.current[id]))
    if (remaining.length > 0) {
      const message = 'Unsaved edits changed while saving. Try again before continuing.'
      setLastError(message)
      throw new Error(message)
    }
  }, [saveShot])

  const reloadProject = useCallback(async () => {
    setInitialLoading(true)
    try {
      const payload = await getProject()
      resetEditState()
      setProject(payload)
      setLastError(null)
      setSelectedShotId((prev) => prev ?? payload.shots[0]?.shot_id ?? null)
    } catch (error) {
      resetEditState()
      setProject(null)
      setSelectedShotId(null)
      if (isNoProjectOpenError(error)) {
        setLastError(null)
        return
      }
      setLastError(error instanceof Error ? error.message : String(error))
    } finally {
      setInitialLoading(false)
    }
  }, [resetEditState])

  const newProjectAction = useCallback(
    async (body: ProjectPathRequest = {}) => {
      setProjectActionBusy(true)
      try {
        await flushDirtyShots()
        const payload = await createProject(body)
        resetEditState()
        setProject(payload)
        setLastError(null)
        setSelectedShotId(payload.shots[0]?.shot_id ?? null)
      } catch (error) {
        setLastError(error instanceof Error ? error.message : String(error))
        throw error
      } finally {
        setProjectActionBusy(false)
      }
    },
    [flushDirtyShots, resetEditState],
  )

  const openProjectFromDialog = useCallback(async () => {
    setProjectActionBusy(true)
    try {
      await flushDirtyShots()
      const result = await browseProjectJson()
      if (result.cancelled || !result.path) return
      const payload = await openProject({ project_json_path: result.path })
      resetEditState()
      setProject(payload)
      setLastError(null)
      setSelectedShotId(payload.shots[0]?.shot_id ?? null)
    } catch (error) {
      setLastError(error instanceof Error ? error.message : String(error))
      throw error
    } finally {
      setProjectActionBusy(false)
    }
  }, [flushDirtyShots, resetEditState])

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

  const value = useMemo<ProjectContextValue>(
    () => ({
      project,
      selectedShotId,
      setSelectedShotId,
      setProject,
      reloadProject,
      newProject: newProjectAction,
      openProjectFromDialog,
      saveProject: saveProjectAction,
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
      lastError,
      clearError,
      reportError,
    }),
    [
      project,
      selectedShotId,
      reloadProject,
      newProjectAction,
      openProjectFromDialog,
      saveProjectAction,
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
      lastError,
      clearError,
      reportError,
    ],
  )

  return <ProjectContext.Provider value={value}>{children}</ProjectContext.Provider>
}

export function useProject() {
  const ctx = useContext(ProjectContext)
  if (!ctx) throw new Error('useProject must be used within ProjectProvider')
  return ctx
}
