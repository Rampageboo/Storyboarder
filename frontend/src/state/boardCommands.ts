import type { ProjectPayload } from '../types'
import type { ProjectHistory } from './projectHistory'

type BoardApi = Pick<typeof import('../api'), 'addShot' | 'deleteShot' | 'deleteShotsBatch' | 'restoreShotsBatch'
  | 'updateShotsBatch' | 'createQueueBatchRequests' | 'moveShotUp' | 'moveShotDown' | 'reorderShots'
  | 'syncShot' | 'createShotCanvas' | 'openShotSource'>
export interface BoardCommandOptions {
  api: BoardApi
  read: () => { project: ProjectPayload | null; selectedShotId: string | null; selectedShotIds: string[] }
  runExclusive: <T>(operation: () => Promise<T>) => Promise<T>
  accept: (payload: ProjectPayload, selected?: string | null) => boolean
  history: Pick<ProjectHistory, 'record'>
}

/** Board operations own their API sequence and inverse; all source reads follow the shared drain. */
export function createBoardCommands({ api, read, runExclusive, accept, history }: BoardCommandOptions) {
  const addShotAfterSelection = () => runExclusive(async () => {
    const { project, selectedShotId } = read()
    if (!project) return
    const afterId = selectedShotId ?? undefined
    const body = afterId ? { after_shot_id: afterId } : {}
    const createdFrom = (payload: ProjectPayload) => {
      const index = afterId ? Math.min(payload.shots.findIndex(shot => shot.shot_id === afterId) + 1, payload.shots.length - 1)
        : payload.shots.length - 1
      return payload.shots[index]?.shot_id ?? null
    }
    const payload = await api.addShot(body)
    let createdId = createdFrom(payload)
    if (!accept(payload, createdId) || !createdId) return
    history.record({
      label: 'Add board',
      undo: async () => ({ payload: await api.deleteShot(createdId as string), select: afterId ?? null }),
      redo: async () => {
        const payload = await api.addShot(body)
        createdId = createdFrom(payload) ?? createdId
        return { payload, select: createdId }
      },
    })
  })

  const insertShotAtIndex = (index: number) => runExclusive(async () => {
    const { project } = read()
    if (!project) return
    const previousShots = project.shots
    const target = Math.max(0, Math.min(index, previousShots.length))
    const afterId = target > 0 ? previousShots[target - 1]?.shot_id : undefined
    const body = afterId ? { after_shot_id: afterId } : {}
    const place = async (payload: ProjectPayload) => {
      const created = target === 0 ? payload.shots.at(-1)?.shot_id : payload.shots[target]?.shot_id
      if (created && target === 0 && previousShots.length) {
        payload = await api.reorderShots({ shot_ids: [created, ...previousShots.map(shot => shot.shot_id)] })
      }
      return { payload, id: created ?? null }
    }
    const initial = await place(await api.addShot(body))
    let createdId = initial.id
    if (!createdId || !accept(initial.payload, createdId)) return
    history.record({
      label: 'Insert board',
      undo: async () => ({ payload: await api.deleteShot(createdId as string), select: afterId ?? null }),
      redo: async () => {
        const next = await place(await api.addShot(body))
        createdId = next.id ?? createdId
        return { payload: next.payload, select: createdId }
      },
    })
  })

  const deleteSelectedShot = () => runExclusive(async () => {
    const { project, selectedShotIds } = read()
    if (!project || !selectedShotIds.length) return
    const selected = new Set(selectedShotIds)
    const removed = project.shots.map((shot, index) => ({ shot, index })).filter(({ shot }) => selected.has(shot.shot_id))
    if (!removed.length) return
    const ids = removed.map(({ shot }) => shot.shot_id)
    const nextSelection = (payload: ProjectPayload) => payload.shots[Math.min(removed[0].index, payload.shots.length - 1)]?.shot_id ?? null
    // Restore canonical memberships/layout only when actually stored; leave legacy projections legacy.
    const graph = project.settings.story_graph ? project.story_graph : undefined
    const payload = await api.deleteShotsBatch({ shot_ids: ids })
    if (!accept(payload, nextSelection(payload))) return
    history.record({
      label: removed.length === 1 ? 'Delete board' : `Delete ${removed.length} boards`,
      undo: async () => ({
        payload: await api.restoreShotsBatch({ items: removed,
          ...(graph ? { story_graph: { ...graph, revision: read().project?.story_graph?.revision ?? graph.revision } } : {}) }),
        select: removed[0].shot.shot_id,
      }),
      redo: async () => {
        const payload = await api.deleteShotsBatch({ shot_ids: ids })
        return { payload, select: nextSelection(payload) }
      },
    })
  })

  const changeSelectedShotsScene = (sceneId: string, sceneName: string) => runExclusive(async () => {
    const { project, selectedShotIds } = read()
    if (!project || !selectedShotIds.length) return
    const selected = new Set(selectedShotIds)
    const targets = project.shots.filter(shot => selected.has(shot.shot_id))
    if (!targets.length) return
    const next = targets.map(shot => ({ shot_id: shot.shot_id, changes: { scene_id: sceneId, scene: sceneName } }))
    const previous = targets.map(shot => ({ shot_id: shot.shot_id, changes: { scene_id: shot.scene_id, scene: shot.scene } }))
    if (!accept(await api.updateShotsBatch({ updates: next }))) return
    history.record({
      label: targets.length === 1 ? 'Change board scene' : `Change scene for ${targets.length} boards`,
      undo: async () => ({ payload: await api.updateShotsBatch({ updates: previous }) }),
      redo: async () => ({ payload: await api.updateShotsBatch({ updates: next }) }),
    })
  })

  const reorderBoards = (orderedIds: string[], selectId?: string | null) => runExclusive(async () => {
    const { project, selectedShotId } = read()
    if (!project) return
    const previous = project.shots.map(shot => shot.shot_id)
    if (previous.length === orderedIds.length && previous.every((id, index) => id === orderedIds[index])) return
    const select = selectId ?? selectedShotId
    if (!accept(await api.reorderShots({ shot_ids: orderedIds }), select)) return
    history.record({ label: 'Reorder boards',
      undo: async () => ({ payload: await api.reorderShots({ shot_ids: previous }), select }),
      redo: async () => ({ payload: await api.reorderShots({ shot_ids: orderedIds }), select }),
    })
  })

  const sendSelectedShotsToQueue = () => runExclusive(async () => {
    const { selectedShotIds } = read()
    if (selectedShotIds.length) accept((await api.createQueueBatchRequests(selectedShotIds)).project)
  })
  // Single-step nudges intentionally remain outside history, as in the board UI.
  const moveSelectedShot = (direction: 'up' | 'down') => runExclusive(async () => {
    const { selectedShotId } = read()
    if (selectedShotId) accept(await (direction === 'up' ? api.moveShotUp(selectedShotId) : api.moveShotDown(selectedShotId)), selectedShotId)
  })
  const syncSelectedShot = () => runExclusive(async () => {
    const { selectedShotId } = read()
    if (selectedShotId) accept(await api.syncShot(selectedShotId), selectedShotId)
  })
  const openSelectedShotSource = () => runExclusive(async () => {
    const { project, selectedShotId } = read()
    if (!project || !selectedShotId) return
    const shot = project.shots.find(item => item.shot_id === selectedShotId)
    if (shot && !shot.source_file_path) accept(await api.createShotCanvas(selectedShotId, {}), selectedShotId)
    await api.openShotSource(selectedShotId)
  })

  return { addShotAfterSelection, insertShotAtIndex, deleteSelectedShot, changeSelectedShotsScene, reorderBoards,
    sendSelectedShotsToQueue, moveSelectedShot, syncSelectedShot, openSelectedShotSource }
}
