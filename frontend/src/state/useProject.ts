import { createContext, useContext } from 'react'
import type { ProjectContextValue } from './ProjectContext'

export const ProjectContext = createContext<ProjectContextValue | null>(null)

export function useProject() {
  const ctx = useContext(ProjectContext)
  if (!ctx) throw new Error('useProject must be used within ProjectProvider')
  return ctx
}
