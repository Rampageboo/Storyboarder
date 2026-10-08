import type { ProjectPayload } from '../types'
import type { ProjectLifecycle } from './projectLifecycle'

export interface HistoryResult {
  payload: ProjectPayload
  select?: string | null
  /** Domain-local state changes run only after an accepted replay. */
  commit?: () => void
}
export interface HistoryEntry {
  label: string
  undo: () => Promise<HistoryResult>
  redo: () => Promise<HistoryResult>
}
export interface HistorySnapshot {
  canUndo: boolean
  canRedo: boolean
  undoLabel: string | null
  redoLabel: string | null
}

/** The board and reference domains share ordering, not the construction of their inverses. */
export class ProjectHistory {
  private undoStack: HistoryEntry[] = []
  private redoStack: HistoryEntry[] = []
  private revision = 0
  private listeners = new Set<() => void>()
  private snapshot: HistorySnapshot = { canUndo: false, canRedo: false, undoLabel: null, redoLabel: null }

  getSnapshot = () => this.snapshot
  subscribe = (listener: () => void) => {
    this.listeners.add(listener)
    return () => { this.listeners.delete(listener) }
  }
  private publish() {
    this.snapshot = {
      canUndo: this.undoStack.length > 0, canRedo: this.redoStack.length > 0,
      undoLabel: this.undoStack.at(-1)?.label ?? null, redoLabel: this.redoStack.at(-1)?.label ?? null,
    }
    for (const listener of this.listeners) listener()
  }
  record = (entry: HistoryEntry) => {
    this.revision += 1
    this.undoStack = [...this.undoStack, entry].slice(-50)
    this.redoStack = []
    this.publish()
  }
  clear = () => {
    this.revision += 1
    this.undoStack = []
    this.redoStack = []
    this.publish()
  }

  /** The existing project lifecycle gate owns serialization and draft draining. */
  replay = async (direction: 'undo' | 'redo', accept: (result: HistoryResult) => boolean): Promise<'applied' | 'unchanged' | 'invalidated'> => {
    const source = direction === 'undo' ? this.undoStack : this.redoStack
    const entry = source.at(-1)
    if (!entry) return 'unchanged'
    const revision = this.revision
    const result = await entry[direction]()
    // A bridge refresh, route change or newly recorded operation invalidates this replay.
    if (revision !== this.revision) return 'invalidated'
    if (!accept(result)) return 'unchanged'
    result.commit?.()
    if (direction === 'undo') {
      this.undoStack = this.undoStack.slice(0, -1)
      this.redoStack = [...this.redoStack, entry]
    } else {
      this.redoStack = this.redoStack.slice(0, -1)
      this.undoStack = [...this.undoStack, entry].slice(-50)
    }
    this.revision += 1
    this.publish()
    return 'applied'
  }
}

/** Recover canonical data after a replay invalidation, without resurrecting its history or tokens. */
export async function replayProjectHistory(history: ProjectHistory, lifecycle: ProjectLifecycle, direction: 'undo' | 'redo',
  ports: { read: () => Promise<ProjectPayload>; accept: (payload: ProjectPayload, selected?: string | null) => boolean;
    reportError: (error: unknown) => void }): Promise<void> {
  const epoch = lifecycle.capture()
  try {
    const outcome = await history.replay(direction, result => lifecycle.accepts(epoch) && ports.accept(result.payload, result.select))
    if (outcome !== 'invalidated' || !lifecycle.accepts(epoch)) return
    // A successful server mutation may have outlived a bridge-driven history clear.
    // Re-read instead of applying the old reply, including legacy revision-zero payloads.
    const ticket = lifecycle.captureRead()
    const payload = await ports.read()
    if (lifecycle.acceptsRead(ticket)) ports.accept(payload)
  } catch (error) { ports.reportError(error) }
}
