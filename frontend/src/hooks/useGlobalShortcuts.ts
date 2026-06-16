import { useEffect, useRef } from 'react'
import { addShot, createShotCanvas, deleteShot, openShotSource, syncShot } from '../api'
import { useProject } from '../state/ProjectContext'

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
 * - Delete : delete selected board (with confirm)
 * - R : sync selected board from Photoshop
 * - O : open selected board's source in Photoshop (creates a canvas first if needed)
 * - N : add a board after the selected one
 *
 * Single-key shortcuts are ignored while typing in a field; Ctrl/Cmd+S still works there.
 * Every state-changing shortcut flushes dirty drafts first and surfaces errors via the banner.
 */
export function useGlobalShortcuts() {
  const {
    project,
    selectedShotId,
    setSelectedShotId,
    setProject,
    saveProject,
    flushDirtyShots,
    reportError,
    projectActionBusy,
  } = useProject()

  const runningRef = useRef(false)
  // Mirror the latest values so the listener (attached once) always reads current state.
  const stateRef = useRef({ project, selectedShotId, projectActionBusy })
  stateRef.current = { project, selectedShotId, projectActionBusy }

  useEffect(() => {
    // Flush drafts, then run a state-changing action. Guards against overlapping runs.
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
      const { project } = stateRef.current
      const selectedShotId = stateRef.current.selectedShotId
      if (!project) return
      const mod = event.ctrlKey || event.metaKey

      // Save works even while editing a field (modifier combo, won't disrupt typing).
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
      if (mod || event.altKey) return // leave other modifier combos to the browser

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
          if (!selectedShotId) break
          event.preventDefault()
          if (!window.confirm('Delete the selected board?')) break
          void run(async () => {
            const payload = await deleteShot(selectedShotId)
            setProject(payload)
            const nextIndex = Math.min(idx, payload.shots.length - 1)
            setSelectedShotId(payload.shots[nextIndex]?.shot_id ?? null)
          })
          break
        case 'r':
        case 'R':
          if (!selectedShotId) break
          event.preventDefault()
          void run(async () => {
            setProject(await syncShot(selectedShotId))
          })
          break
        case 'o':
        case 'O': {
          if (!selectedShotId) break
          event.preventDefault()
          const shot = shots.find((s) => s.shot_id === selectedShotId)
          void run(async () => {
            if (shot && !shot.source_file_path) setProject(await createShotCanvas(selectedShotId, {}))
            await openShotSource(selectedShotId)
          })
          break
        }
        case 'n':
        case 'N':
          event.preventDefault()
          void run(async () => {
            const afterId = selectedShotId || undefined
            const payload = await addShot(afterId ? { after_shot_id: afterId } : {})
            setProject(payload)
            const newIndex = afterId
              ? Math.min(payload.shots.findIndex((s) => s.shot_id === afterId) + 1, payload.shots.length - 1)
              : payload.shots.length - 1
            const newId = payload.shots[newIndex]?.shot_id
            if (newId) setSelectedShotId(newId)
          })
          break
        default:
          break
      }
    }

    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [flushDirtyShots, saveProject, setProject, setSelectedShotId, reportError])
}
