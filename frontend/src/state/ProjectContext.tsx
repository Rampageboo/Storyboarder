import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
  type Dispatch,
  type PropsWithChildren,
  type SetStateAction,
} from 'react'
import { createProject, getProject, openProject, saveProject, updateShot } from '../api'
import { isNoProjectOpenError } from '../api'
import type { OpenProjectRequest, ProjectPathRequest, ProjectPayload, Shot, ShotUpdate } from '../types'

interface ProjectContextValue {
  project: ProjectPayload | null
  selectedShotId: string | null
  setSelectedShotId: (shotId: string | null) => void
  /** Accepts a value or a functional updater so stale-safe saves can merge into the latest state. */
  setProject: Dispatch<SetStateAction<ProjectPayload | null>>
  reloadProject: () => Promise<void>
  newProject: (body?: ProjectPathRequest) => Promise<void>
  openProject: (body: OpenProjectRequest) => Promise<void>
  saveProject: () => Promise<void>
  // Per-shot editing (centralized dirty/version tracking).
  getDraft: (shotId: string) => ShotUpdate | undefined
  editShotField: <K extends keyof ShotUpdate>(shotId: string, key: K, value: ShotUpdate[K]) => void
  isShotDirty: (shotId: string) => boolean
  dirtyShotIds: string[]
  savingShots: Record<string, boolean>
  saveShot: (shotId: string) => Promise<void>
  flushDirtyShots: () => Promise<void>
  lastError: string | null
  clearError: () => void
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

  // Per-shot edit state. `drafts` holds only changed fields per shot; presence ⇒ dirty.
  const [drafts, setDrafts] = useState<Record<string, ShotUpdate>>({})
  const [savingShots, setSavingShots] = useState<Record<string, boolean>>({})
  const versionsRef = useRef<Record<string, number>>({})

  // Refs mirror the latest committed values for synchronous reads inside async save/flush.
  const projectRef = useRef<ProjectPayload | null>(null)
  const draftsRef = useRef<Record<string, ShotUpdate>>({})
  projectRef.current = project
  draftsRef.current = drafts

  const clearError = useCallback(() => setLastError(null), [])

  const resetEditState = useCallback(() => {
    versionsRef.current = {}
    draftsRef.current = {}
    setDrafts({})
    setSavingShots({})
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
  const flushDirtyShots = useCallback(async (): Promise<void> => {
    const ids = Object.keys(draftsRef.current).filter((id) => draftIsDirty(draftsRef.current[id]))
    for (const id of ids) {
      await saveShot(id)
    }
  }, [saveShot])

  const reloadProject = useCallback(async () => {
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
    }
  }, [resetEditState])

  const newProjectAction = useCallback(
    async (body: ProjectPathRequest = {}) => {
      await flushDirtyShots()
      try {
        const payload = await createProject(body)
        resetEditState()
        setProject(payload)
        setLastError(null)
        setSelectedShotId(payload.shots[0]?.shot_id ?? null)
      } catch (error) {
        setLastError(error instanceof Error ? error.message : String(error))
        throw error
      }
    },
    [flushDirtyShots, resetEditState],
  )

  const openProjectAction = useCallback(
    async (body: OpenProjectRequest) => {
      await flushDirtyShots()
      try {
        const payload = await openProject(body)
        resetEditState()
        setProject(payload)
        setLastError(null)
        setSelectedShotId(payload.shots[0]?.shot_id ?? null)
      } catch (error) {
        setLastError(error instanceof Error ? error.message : String(error))
        throw error
      }
    },
    [flushDirtyShots, resetEditState],
  )

  const saveProjectAction = useCallback(async () => {
    await flushDirtyShots()
    try {
      const payload = await saveProject()
      setProject(payload)
      setLastError(null)
    } catch (error) {
      setLastError(error instanceof Error ? error.message : String(error))
      throw error
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
      openProject: openProjectAction,
      saveProject: saveProjectAction,
      getDraft,
      editShotField,
      isShotDirty,
      dirtyShotIds,
      savingShots,
      saveShot,
      flushDirtyShots,
      lastError,
      clearError,
    }),
    [
      project,
      selectedShotId,
      reloadProject,
      newProjectAction,
      openProjectAction,
      saveProjectAction,
      getDraft,
      editShotField,
      isShotDirty,
      dirtyShotIds,
      savingShots,
      saveShot,
      flushDirtyShots,
      lastError,
      clearError,
    ],
  )

  return <ProjectContext.Provider value={value}>{children}</ProjectContext.Provider>
}

export function useProject() {
  const ctx = useContext(ProjectContext)
  if (!ctx) throw new Error('useProject must be used within ProjectProvider')
  return ctx
}
