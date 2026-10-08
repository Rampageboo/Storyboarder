import type { Shot } from '../types'

export function durationFrames(seconds: number, fps: number): number {
  return Math.max(1, Math.floor((Number.isFinite(seconds) && seconds > 0 ? seconds : 3) * fps + .5))
}
export function buildTimeline(shots: Shot[], fps: number) {
  let cursor = 0
  const entries = shots.map(shot => {
    const frames = durationFrames(shot.duration_seconds, fps), start = cursor
    cursor += frames
    return { shot, start, end: cursor, frames }
  })
  return { entries, frames: cursor }
}
export function timelineEntryAt<T extends { start: number; end: number }>(entries: T[], frame: number): T | undefined {
  return entries.find(entry => frame >= entry.start && frame < entry.end) ?? entries.at(-1)
}
export function frameTimecode(frame: number, fps: number): string {
  const seconds = Math.floor(Math.max(0, frame) / fps)
  return [Math.floor(seconds / 3600), Math.floor(seconds / 60) % 60, seconds % 60, Math.max(0, frame) % fps]
    .map(value => String(value).padStart(2, '0')).join(':')
}
