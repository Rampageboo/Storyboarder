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
 * - Ctrl/Cmd+N / Ctrl/Cmd+O : new / open project (also from Home)
 */
export function useGlobalShortcuts() {
  const {
    project,
    activeRouteShots,
    selectedShotId,
    selectedShotIds,
    setSelectedShotId,
    saveProject,
    flushDirtyShots,
    reportError,
    projectActionBusy,
    activeAppliedSegmentId,
    addShotAfterSelection,
    deleteSelectedShot,
    deleteActiveRefSegment,
    syncSelectedShot,
    openSelectedShotSource,
    undo,
    redo,
    newProject,
    openProjectFromDialog,
  } = useProject()

  const runningRef = useRef(false)
  const stateRef = useRef({ project, activeRouteShots, selectedShotId, selectedShotIds, projectActionBusy, activeAppliedSegmentId })
  useLayoutEffect(() => {
    stateRef.current = { project, activeRouteShots, selectedShotId, selectedShotIds, projectActionBusy, activeAppliedSegmentId }
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
      // The Fabric editor owns save/undo/delete while open; never also mutate boards.
      if (document.body.classList.contains('storyboard-drawing-active')) return
      const { project, activeAppliedSegmentId } = stateRef.current
      const selectedShotId = stateRef.current.selectedShotId
      const mod = event.ctrlKey || event.metaKey

      if (mod && !event.shiftKey && !event.altKey && (event.key === 'n' || event.key === 'N' || event.key === 'o' || event.key === 'O')) {
        if (document.querySelector('dialog[open]')) return
        event.preventDefault()
        if (stateRef.current.projectActionBusy) return
        const action = event.key.toLowerCase() === 'n'
          ? () => newProject({ path: null, canvas_width: 1920, canvas_height: 1080 })
          : openProjectFromDialog
        void action().catch((error) => reportError(error))
        return
      }

      if (!project) return

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
      if (document.querySelector('[data-comic-active="true"]')) return

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

      const allBoards = document.querySelector('[data-story-view="all"]')
      const shots = allBoards ? project.shots : stateRef.current.activeRouteShots
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
            void run(deleteActiveRefSegment)
            break
          }
          if (!selectedShotId) break
          if (!window.confirm(
            stateRef.current.selectedShotIds.length > 1
              ? `Delete ${stateRef.current.selectedShotIds.length} selected boards?`
              : 'Delete the selected board?',
          )) break
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
    addShotAfterSelection,
    deleteSelectedShot,
    deleteActiveRefSegment,
    syncSelectedShot,
    openSelectedShotSource,
    undo,
    redo,
    newProject,
    openProjectFromDialog,
  ])
}
