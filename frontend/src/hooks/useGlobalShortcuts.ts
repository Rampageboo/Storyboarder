import { useEffect, useLayoutEffect, useRef } from 'react'
import { useProject } from '../state/useProject'

function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  const tag = target.tagName
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return true
  return target.isContentEditable
}

/**
 * Global drawing-workflow keyboard shortcuts. Mounted once near the app root.
 * - ←/→ : select previous / next board
 * - Ctrl/Cmd+S : save (flushes dirty shot drafts, then saves the project)
 * - Delete : delete selected reference segment when a marker is selected, else delete selected board
 * - R : sync selected board from Photoshop
 * - O : open selected board's source in Photoshop (creates a canvas first if needed)
 * - N : add a board after the selected one
 */
export function useGlobalShortcuts() {
  const {
    project,
    selectedShotId,
    setSelectedShotId,
    saveProject,
    flushDirtyShots,
    reportError,
    projectActionBusy,
    activeAppliedSegmentId,
    dismissRefSegmentUi,
    addShotAfterSelection,
    deleteSelectedShot,
    deleteActiveRefSegment,
    syncSelectedShot,
    openSelectedShotSource,
    undo,
    redo,
  } = useProject()

  const runningRef = useRef(false)
  const stateRef = useRef({ project, selectedShotId, projectActionBusy, activeAppliedSegmentId })
  useLayoutEffect(() => {
    stateRef.current = { project, selectedShotId, projectActionBusy, activeAppliedSegmentId }
  })

  useEffect(() => {
    const run = async (fn: () => Promise<void>) => {
      if (runningRef.current || stateRef.current.projectActionBusy) return
      runningRef.current = true
      try {
        await flushDirtyShots()
        await fn()
      } catch (error) {
        reportError(error)
      } finally {
        runningRef.current = false
      }
    }

    const onKeyDown = (event: KeyboardEvent) => {
      const { project, activeAppliedSegmentId } = stateRef.current
      const selectedShotId = stateRef.current.selectedShotId
      if (!project) return
      const mod = event.ctrlKey || event.metaKey

      if (mod && (event.key === 's' || event.key === 'S')) {
        event.preventDefault()
        if (runningRef.current) return
        runningRef.current = true
        void saveProject()
          .catch((error) => reportError(error))
          .finally(() => {
            runningRef.current = false
          })
        return
      }

      if (isTypingTarget(event.target)) return

      // Undo / redo of board operations. Skipped above when focus is in a text field
      // so the browser's native text undo still works while editing metadata.
      if (mod && (event.key === 'z' || event.key === 'Z')) {
        event.preventDefault()
        void (event.shiftKey ? redo() : undo()).catch((error) => reportError(error))
        return
      }
      if (mod && (event.key === 'y' || event.key === 'Y')) {
        event.preventDefault()
        void redo().catch((error) => reportError(error))
        return
      }

      if (mod || event.altKey) return

      const shots = project.shots
      const idx = shots.findIndex((s) => s.shot_id === selectedShotId)

      switch (event.key) {
        case 'ArrowLeft':
          if (idx > 0) {
            event.preventDefault()
            setSelectedShotId(shots[idx - 1].shot_id)
          }
          break
        case 'ArrowRight':
          if (idx >= 0 && idx < shots.length - 1) {
            event.preventDefault()
            setSelectedShotId(shots[idx + 1].shot_id)
          }
          break
        case 'Delete':
          event.preventDefault()
          if (activeAppliedSegmentId) {
            if (!window.confirm('Delete this applied reference segment and clear its generated board backgrounds/previews?')) break
            dismissRefSegmentUi()
            void run(deleteActiveRefSegment)
            break
          }
          if (!selectedShotId) break
          if (!window.confirm('Delete the selected board?')) break
          void run(deleteSelectedShot)
          break
        case 'r':
        case 'R':
          if (!selectedShotId) break
          event.preventDefault()
          void run(syncSelectedShot)
          break
        case 'o':
        case 'O': {
          if (!selectedShotId) break
          event.preventDefault()
          void run(openSelectedShotSource)
          break
        }
        case 'n':
        case 'N':
          event.preventDefault()
          void run(addShotAfterSelection)
          break
        default:
          break
      }
    }

    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [
    flushDirtyShots,
    saveProject,
    setSelectedShotId,
    reportError,
    dismissRefSegmentUi,
    addShotAfterSelection,
    deleteSelectedShot,
    deleteActiveRefSegment,
    syncSelectedShot,
    openSelectedShotSource,
    undo,
    redo,
  ])
}
