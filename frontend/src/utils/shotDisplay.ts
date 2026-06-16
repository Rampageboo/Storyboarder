import type { Shot } from '../types'

export function shortShotId(shotId: string, length = 8): string {
  const id = shotId.trim()
  if (id.length <= length) return id
  return `${id.slice(0, length)}…`
}

/** One-line label for filmstrip cards and headers. */
export function shotDisplayLabel(shot: Pick<Shot, 'shot_id' | 'title' | 'scene' | 'sequence'>): string {
  const title = shot.title?.trim()
  if (title) return title
  const scene = shot.scene?.trim()
  if (scene) return scene
  const sequence = shot.sequence?.trim()
  if (sequence) return sequence
  return shortShotId(shot.shot_id)
}
