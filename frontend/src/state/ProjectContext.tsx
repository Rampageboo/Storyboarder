import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type PropsWithChildren,
} from 'react'
import { createProject, getProject, openProject, saveProject } from '../api'
import { isNoProjectOpenError } from '../api'
import type { OpenProjectRequest, ProjectPathRequest, ProjectPayload } from '../types'

interface ProjectContextValue {
  project: ProjectPayload | null
  selectedShotId: string | null
  setSelectedShotId: (shotId: string | null) => void
  setProject: (project: ProjectPayload | null) => void
  reloadProject: () => Promise<void>
  newProject: (body?: ProjectPathRequest) => Promise<void>
  openProject: (body: OpenProjectRequest) => Promise<void>
  saveProject: () => Promise<void>
  lastError: string | null
  clearError: () => void
}

const ProjectContext = createContext<ProjectContextValue | null>(null)

export function ProjectProvider({ children }: PropsWithChildren) {
  const [project, setProject] = useState<ProjectPayload | null>(null)
  const [selectedShotId, setSelectedShotId] = useState<string | null>(null)
  const [lastError, setLastError] = useState<string | null>(null)

  const clearError = useCallback(() => setLastError(null), [])

  const reloadProject = useCallback(async () => {
    try {
      const payload = await getProject()
      setProject(payload)
      setLastError(null)
      if (payload.shots.length && !selectedShotId) {
        setSelectedShotId(payload.shots[0].shot_id)
      }
    } catch (error) {
      if (isNoProjectOpenError(error)) {
        setProject(null)
        setSelectedShotId(null)
        setLastError(null)
        return
      }
      setProject(null)
      setSelectedShotId(null)
      setLastError(error instanceof Error ? error.message : String(error))
    }
  }, [selectedShotId])

  const newProjectAction = useCallback(async (body: ProjectPathRequest = {}) => {
    try {
      const payload = await createProject(body)
      setProject(payload)
      setLastError(null)
      setSelectedShotId(payload.shots[0]?.shot_id ?? null)
    } catch (error) {
      setLastError(error instanceof Error ? error.message : String(error))
      throw error
    }
  }, [])

  const openProjectAction = useCallback(async (body: OpenProjectRequest) => {
    try {
      const payload = await openProject(body)
      setProject(payload)
      setLastError(null)
      setSelectedShotId(payload.shots[0]?.shot_id ?? null)
    } catch (error) {
      setLastError(error instanceof Error ? error.message : String(error))
      throw error
    }
  }, [])

  const saveProjectAction = useCallback(async () => {
    try {
      const payload = await saveProject()
      setProject(payload)
      setLastError(null)
    } catch (error) {
      setLastError(error instanceof Error ? error.message : String(error))
      throw error
    }
  }, [])

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

