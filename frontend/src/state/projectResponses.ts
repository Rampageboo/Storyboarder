import type { ProjectPayload } from '../types'
import type { ComicDocument } from '../types/comic'
import type { DraftBuffer, ProjectLifecycle } from './projectLifecycle'

/** Full payloads may only replace the document lifetime and revision they belong to. */
export function acceptsProjectPayload(lifecycle: ProjectLifecycle, epoch: number,
  current: ProjectPayload | null, incoming: ProjectPayload): boolean {
  return lifecycle.accepts(epoch) && !!current && incoming.project_json_path === current.project_json_path
    && incoming.project_id === current.project_id
    && incoming.storage_revision >= current.storage_revision
}

/** Comic edits also invalidate generation freshness on affected boards on the server. */
export function mergeComicResponse(current: ProjectPayload, incoming: ProjectPayload): ProjectPayload {
  const freshShots = new Map(incoming.shots.map(shot => [shot.shot_id, shot]))
  return { ...current, comic_document: incoming.comic_document,
    settings: { ...current.settings, comic_document: incoming.comic_document },
    storage_revision: incoming.storage_revision, dirty: incoming.dirty,
    shots: current.shots.map(shot => {
      const fresh = freshShots.get(shot.shot_id)
      return fresh ? { ...shot, generation_state: { ...shot.generation_state,
        freshness_status: fresh.generation_state.freshness_status } } : shot
    }) }
}

/** Recovery discards a failed local Comic draft without trying to save it again. */
export async function reloadComicDraft(buffer: DraftBuffer<ComicDocument>, lifecycle: ProjectLifecycle,
  current: () => ProjectPayload | null, read: () => Promise<ProjectPayload>, accept: (payload: ProjectPayload) => void): Promise<boolean> {
  await buffer.settle()
  const ticket = lifecycle.captureRead()
  const payload = await read()
  if (!lifecycle.acceptsRead(ticket) || !acceptsProjectPayload(lifecycle, ticket.epoch, current(), payload)) return false
  buffer.reset()
  accept(payload)
  return true
}
