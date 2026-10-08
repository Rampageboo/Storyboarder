import { useCallback, useRef, useState } from 'react'
import type { Dispatch, SetStateAction } from 'react'
import type { ProjectPayload } from '../types'
import { ProjectLifecycle } from './projectLifecycle'
import { acceptsProjectPayload } from './projectResponses'

export function useProjectLifecycle() {
  const [lifecycle] = useState(() => new ProjectLifecycle())
  const [project, renderProject] = useState<ProjectPayload | null>(null)
  const projectRef = useRef<ProjectPayload | null>(null)
  const [projectActionBusy, setBusy] = useState(false)
  const [drawingActive, setDrawingActiveState] = useState(false)
  const drawingActiveRef = useRef(false)
  const [lastError, setLastError] = useState<string | null>(null)
  const reportError = useCallback((error: unknown) => setLastError(error instanceof Error ? error.message : String(error)), [])
  const clearError = useCallback(() => setLastError(null), [])
  const setDrawingActive = useCallback((active: boolean) => {
    drawingActiveRef.current = active
    setDrawingActiveState(active)
  }, [])
  const commitProject = useCallback<Dispatch<SetStateAction<ProjectPayload | null>>>((update) => {
    const next = typeof update === 'function' ? update(projectRef.current) : update
    if (next !== projectRef.current) lifecycle.changed()
    projectRef.current = next
    renderProject(next)
  }, [lifecycle])
  const beginProject = useCallback((payload: ProjectPayload | null) => {
    lifecycle.advance()
    commitProject(payload)
  }, [commitProject, lifecycle])
  // Each rendered facade belongs to a document lifetime, even when a path is reopened.
  const epoch = lifecycle.capture()
  const setProject = useCallback<Dispatch<SetStateAction<ProjectPayload | null>>>((update) => {
    if (!lifecycle.accepts(epoch)) return
    commitProject(current => {
      const next = typeof update === 'function' ? update(current) : update
      if (!next || !acceptsProjectPayload(lifecycle, epoch, current, next)) return current
      return next
    })
  }, [commitProject, epoch, lifecycle])
  const runProjectTransition = useCallback(async <T,>(operation: () => Promise<T>): Promise<T> => {
    try { return await lifecycle.run(operation, drawingActiveRef.current, setBusy) }
    catch (error) { reportError(error); throw error }
  }, [lifecycle, reportError])
  return { lifecycle, project, projectRef, setProject, commitProject, beginProject,
    drawingActive, drawingActiveRef, setDrawingActive, projectActionBusy, runProjectTransition,
    lastError, setLastError, reportError, clearError }
}
