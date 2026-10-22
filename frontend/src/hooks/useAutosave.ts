import { useEffect, useRef } from 'react'
import { useProject } from '../state/useProject'

const IDLE_MS = 1500

/**
 * Board text edits are held as drafts while the user types. Flush them shortly
 * after typing stops: every flushed edit is written to the project folder by
 * the backend, so there is no separate document save.
 */
export function useAutosave(): void {
  const { dirtyShotIds, flushDirtyShots, drawingActive, projectActionBusy } = useProject()
  const flushing = useRef(false)
  const pending = dirtyShotIds.join('|')

  useEffect(() => {
    if (!pending || drawingActive || projectActionBusy) return
    const id = window.setTimeout(() => {
      if (flushing.current) return
      flushing.current = true
      void flushDirtyShots()
        .catch(() => {
          // Errors are surfaced through the project context's error banner.
        })
        .finally(() => {
          flushing.current = false
        })
    }, IDLE_MS)
    return () => window.clearTimeout(id)
  }, [pending, drawingActive, projectActionBusy, flushDirtyShots])
}
