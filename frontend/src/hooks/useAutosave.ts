import { useEffect, useRef } from 'react'
import { useProject } from '../state/useProject'

const DEFAULT_INTERVAL_MINUTES = 5
const MINUTE_MS = 60_000

/**
 * Periodic autosave. Interactive edits no longer write the document on every
 * change (that re-zips the whole .sbd); instead the document is flushed on this
 * interval, on manual Save (Ctrl+S), and on close. Fires only when there are
 * unsaved changes and never overlaps its own save.
 */
export function useAutosave(): void {
  const { project, saveProject, dirtyShotIds } = useProject()
  const hasProject = !!project
  const rawInterval = Number(project?.settings?.autosave_interval_minutes ?? DEFAULT_INTERVAL_MINUTES)
  const intervalMinutes = Number.isFinite(rawInterval) && rawInterval > 0 ? rawInterval : DEFAULT_INTERVAL_MINUTES

  const savingRef = useRef(false)
  const latest = useRef({ project, saveProject, dirtyShotIds })
  useEffect(() => {
    latest.current = { project, saveProject, dirtyShotIds }
  })

  useEffect(() => {
    if (!hasProject) return
    const id = window.setInterval(() => {
      const { project: current, saveProject: save, dirtyShotIds: dirty } = latest.current
      if (!current || savingRef.current) return
      if (!current.dirty && dirty.length === 0) return
      savingRef.current = true
      void save()
        .catch(() => {
          // Errors are surfaced through the project context's error banner.
        })
        .finally(() => {
          savingRef.current = false
        })
    }, intervalMinutes * MINUTE_MS)
    return () => window.clearInterval(id)
  }, [hasProject, intervalMinutes])
}
