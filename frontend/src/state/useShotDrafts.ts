import { useCallback, useLayoutEffect, useMemo, useState } from 'react'
import type { Dispatch, RefObject, SetStateAction } from 'react'
import { updateShot } from '../api'
import type { ProjectPayload, ShotUpdate } from '../types'
import { shotToUpdate } from '../utils/shotUpdate'
import { DraftBuffer, ProjectLifecycle } from './projectLifecycle'
import { acceptsProjectPayload } from './projectResponses'

export function useShotDrafts(lifecycle: ProjectLifecycle, projectRef: RefObject<ProjectPayload | null>,
  commit: Dispatch<SetStateAction<ProjectPayload | null>>, reportError: (error: unknown) => void) {
  const [drafts, setDrafts] = useState<Record<string, ShotUpdate>>({})
  const [savingShots, setSavingShots] = useState<Record<string, boolean>>({})
  const [buffers] = useState(() => new Map<string, DraftBuffer<ShotUpdate>>())
  const buffer = useCallback((id: string) => {
    let item = buffers.get(id)
    if (!item) {
      item = new DraftBuffer<ShotUpdate>(async snapshot => {
        const epoch = lifecycle.capture()
        return lifecycle.write(async () => {
          const base = projectRef.current?.shots.find(shot => shot.shot_id === id)
          if (!base) throw new Error('The edited board no longer exists. Reload before continuing.')
          const payload = await updateShot(id, { ...shotToUpdate(base), ...snapshot })
          if (lifecycle.accepts(epoch)) commit(current => {
            if (!current || !acceptsProjectPayload(lifecycle, epoch, current, payload)) return current
            const saved = payload.shots.find(shot => shot.shot_id === id)
            return { ...current, shots: current.shots.map(shot => shot.shot_id === id && saved ? saved : shot),
              dirty: payload.dirty, storage_revision: payload.storage_revision }
          })
          return snapshot
        })
      }, (draft, busy) => {
        setDrafts(previous => { const next = { ...previous }; if (draft) next[id] = draft; else delete next[id]; return next })
        setSavingShots(previous => { const next = { ...previous }; if (busy) next[id] = true; else delete next[id]; return next })
      })
      buffers.set(id, item)
    }
    return item
  }, [buffers, lifecycle, projectRef, commit])
  const saveShot = useCallback(async (id: string) => {
    try { await buffers.get(id)?.flush() } catch (error) { reportError(error); throw error }
  }, [buffers, reportError])
  const flush = useCallback(async () => { for (const id of buffers.keys()) await saveShot(id) }, [buffers, saveShot])
  useLayoutEffect(() => lifecycle.register(flush), [lifecycle, flush])
  const resetDrafts = useCallback(() => { for (const item of buffers.values()) item.reset(); buffers.clear() }, [buffers])
  const editShotField = useCallback(<K extends keyof ShotUpdate>(id: string, key: K, value: ShotUpdate[K]) => {
    if (!lifecycle.editable) { reportError(new Error('Wait for the current project action before editing.')); return }
    lifecycle.edited()
    const item = buffer(id)
    item.edit({ ...item.current, [key]: value })
  }, [lifecycle, buffer, reportError])
  const getDraft = useCallback((id: string) => drafts[id], [drafts])
  const isShotDirty = useCallback((id: string) => !!drafts[id], [drafts])
  const dirtyShotIds = useMemo(() => Object.keys(drafts), [drafts])
  return { resetDrafts, getDraft, isShotDirty, dirtyShotIds, savingShots, editShotField, saveShot }
}
