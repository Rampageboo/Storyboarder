import { useCallback, useLayoutEffect, useMemo, useRef } from 'react'
import type { RefObject } from 'react'
import { addShot, deleteShot, deleteShotsBatch, restoreShotsBatch, updateShotsBatch, createQueueBatchRequests,
  moveShotUp, moveShotDown, reorderShots, syncShot, createShotCanvas, openShotSource } from '../api'
import type { ProjectPayload } from '../types'
import type { ProjectHistory } from './projectHistory'
import { createBoardCommands } from './boardCommands'

interface Options {
  projectRef: RefObject<ProjectPayload | null>
  selectedShotId: string | null
  selectedShotIds: string[]
  runExclusive: <T>(operation: () => Promise<T>) => Promise<T>
  accept: (payload: ProjectPayload, selected?: string | null) => boolean
  history: ProjectHistory
}
const api = { addShot, deleteShot, deleteShotsBatch, restoreShotsBatch, updateShotsBatch, createQueueBatchRequests,
  moveShotUp, moveShotDown, reorderShots, syncShot, createShotCanvas, openShotSource }

export function useBoardCommands(options: Options) {
  const latest = useRef(options)
  useLayoutEffect(() => { latest.current = options })
  const commands = useCallback(() => createBoardCommands({ api,
    read: () => ({ project: latest.current.projectRef.current, selectedShotId: latest.current.selectedShotId,
      selectedShotIds: latest.current.selectedShotIds }),
    runExclusive: operation => latest.current.runExclusive(operation),
    accept: (payload, selected) => latest.current.accept(payload, selected),
    history: latest.current.history,
  }), [])
  return useMemo(() => ({
    addShotAfterSelection: () => commands().addShotAfterSelection(),
    insertShotAtIndex: (index: number) => commands().insertShotAtIndex(index),
    deleteSelectedShot: () => commands().deleteSelectedShot(),
    changeSelectedShotsScene: (id: string, name: string) => commands().changeSelectedShotsScene(id, name),
    reorderBoards: (ids: string[], select?: string | null) => commands().reorderBoards(ids, select),
    sendSelectedShotsToQueue: () => commands().sendSelectedShotsToQueue(),
    moveSelectedShot: (direction: 'up' | 'down') => commands().moveSelectedShot(direction),
    syncSelectedShot: () => commands().syncSelectedShot(),
    openSelectedShotSource: () => commands().openSelectedShotSource(),
  }), [commands])
}
