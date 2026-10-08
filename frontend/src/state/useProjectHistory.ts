import { useCallback, useMemo, useState, useSyncExternalStore } from 'react'
import type { ProjectPayload } from '../types'
import type { ProjectLifecycle } from './projectLifecycle'
import { ProjectHistory, replayProjectHistory } from './projectHistory'
import { getProject } from '../api'

export function useProjectHistory(lifecycle: ProjectLifecycle,
  runExclusive: <T>(operation: () => Promise<T>) => Promise<T>,
  accept: (payload: ProjectPayload, selected?: string | null) => boolean,
  reportError: (error: unknown) => void) {
  const [history] = useState(() => new ProjectHistory())
  const snapshot = useSyncExternalStore(history.subscribe, history.getSnapshot, history.getSnapshot)
  const replay = useCallback((direction: 'undo' | 'redo') => runExclusive(() =>
    replayProjectHistory(history, lifecycle, direction, { read: getProject, accept, reportError })),
  [runExclusive, lifecycle, history, accept, reportError])
  const undo = useCallback(() => replay('undo'), [replay])
  const redo = useCallback(() => replay('redo'), [replay])
  const historyState = useMemo(() => ({ ...snapshot, undo, redo }), [snapshot, undo, redo])
  return { history, clearHistory: history.clear, historyState }
}
