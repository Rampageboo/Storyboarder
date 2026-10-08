import type { ProjectPayload, SettingsUpdate } from '../types'
import type { ProjectHistory } from './projectHistory'

type ReferenceApi = Pick<typeof import('../api'), 'restoreRefApply' | 'getProject' | 'snapshotRefBoards' | 'deleteRefSegment' | 'updateSettings'>
export interface ReferenceCommandOptions {
  api: ReferenceApi
  readProject: () => ProjectPayload | null
  readActiveSegment: () => string | null
  dismiss: () => void
  setUndoToken: (token: string | null) => void
  runExclusive: <T>(operation: () => Promise<T>) => Promise<T>
  accept: (payload: ProjectPayload, selected?: string | null) => boolean
  history: Pick<ProjectHistory, 'record'>
}
export interface ReferenceApplyRecord {
  label: string
  undoToken: string
  redo: () => Promise<ProjectPayload>
}

/** Reference inverses own snapshot tokens and metadata restoration, never history stacks. */
export function createReferenceCommands({ api, readProject, readActiveSegment, dismiss, setUndoToken,
  runExclusive, accept, history }: ReferenceCommandOptions) {
  // External bake callers record an already-completed operation. Do not enter a nested gate here.
  const recordRefApply = (options: ReferenceApplyRecord) => {
    let token = options.undoToken
    history.record({
      label: options.label,
      undo: async () => {
        let payload: ProjectPayload | null = null
        if (token) {
          try { payload = await api.restoreRefApply(token) } catch { payload = null }
        }
        if (!payload) payload = await api.getProject()
        return { payload, commit: () => setUndoToken(null) }
      },
      redo: async () => {
        const payload = await options.redo()
        const next = (payload as { undo_token?: unknown }).undo_token
        token = typeof next === 'string' ? next : ''
        return { payload, commit: () => setUndoToken(token || null) }
      },
    })
  }

  const deleteSegment = async (segmentId: string) => {
    const project = readProject()
    if (!project) return
    const records = (project.settings.ref_segments ?? []) as Array<{ id?: string; anchor_shot_id?: string; end_shot_id?: string }>
    const record = records.find(segment => segment?.id === segmentId)
    const anchor = record?.anchor_shot_id ?? '', end = record?.end_shot_id ?? ''
    let token: string | null = null
    if (anchor && end) {
      try { token = (await api.snapshotRefBoards({ anchor_shot_id: anchor, end_shot_id: end })).undo_token }
      catch { token = null }
    }
    if (!accept(await api.deleteRefSegment(segmentId)) || !record || !token) return
    let currentToken = token
    history.record({
      label: 'Delete reference',
      undo: async () => {
        const restored = await api.restoreRefApply(currentToken)
        const merged = [...((restored.settings.ref_segments as unknown[]) ?? []), record]
        return { payload: await api.updateSettings({ ref_segments: merged } as SettingsUpdate) }
      },
      redo: async () => {
        if (anchor && end) {
          try { currentToken = (await api.snapshotRefBoards({ anchor_shot_id: anchor, end_shot_id: end })).undo_token }
          catch { /* Preserve the previous snapshot token as a fallback. */ }
        }
        return { payload: await api.deleteRefSegment(segmentId) }
      },
    })
  }
  const deleteRefSegmentUndoable = (segmentId: string) => runExclusive(() => deleteSegment(segmentId))
  const deleteActiveRefSegment = () => runExclusive(async () => {
    const segmentId = readActiveSegment()
    if (!segmentId) return
    dismiss()
    await deleteSegment(segmentId)
  })
  return { recordRefApply, deleteRefSegmentUndoable, deleteActiveRefSegment }
}
