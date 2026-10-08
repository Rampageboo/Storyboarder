/**
 * GLB animation clip / timeline helpers for the Scene3D workspace.
 */

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type AnimationClip = any
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type MixerAction = any

export function trackNodeName(trackName: string): string {
  const dot = String(trackName || '').lastIndexOf('.')
  return dot > 0 ? trackName.slice(0, dot) : trackName
}

export function collectAnimatedNodeNames(animations: AnimationClip[] | null | undefined): Set<string> {
  const names = new Set<string>()
  for (const clip of animations || []) {
    for (const track of clip.tracks || []) {
      const nodeName = trackNodeName(track.name)
      if (nodeName) names.add(nodeName)
    }
  }
  return names
}

export function computeClipDuration(clips: AnimationClip[] | null | undefined): number {
  let duration = 0
  for (const clip of clips || []) {
    duration = Math.max(duration, Number(clip.duration) || 0)
    for (const track of clip.tracks || []) {
      const times = track.times
      if (times?.length) duration = Math.max(duration, times[times.length - 1])
    }
  }
  return duration
}

export function selectAnimationClips(animations: AnimationClip[] | null | undefined): AnimationClip[] {
  return animations || []
}

export function clampAnimationTime(seconds: number, duration: number): number {
  if (duration > 0) return Math.min(Math.max(0, seconds), duration)
  return Math.max(0, seconds)
}

export function syncMixerActionsTime(
  mixerActions: MixerAction[],
  mixer: { update(delta: number): void } | null | undefined,
  seconds: number,
): number {
  if (!mixer || !mixerActions.length) return Math.max(0, Number(seconds) || 0)
  const time = Math.max(0, Number(seconds) || 0)
  for (const action of mixerActions) {
    action.enabled = true
    action.paused = false
    action.time = time
  }
  mixer.update(0)
  return time
}

export type TimelineUiState = {
  max: string
  value: string
  disabled: boolean
  displayText: string
}

export function buildTimelineUiState(
  animationTime: number,
  animationDuration: number,
  formatTime: (seconds: number) => string,
): TimelineUiState {
  const duration = animationDuration || 0
  return {
    max: duration.toFixed(2),
    value: animationTime.toFixed(2),
    disabled: duration <= 0,
    displayText: `${formatTime(animationTime)} / ${formatTime(duration)}`,
  }
}

export type AnimationHintInput = {
  animationDuration: number
  activeCameraName: string
  cameraMoves: boolean
  formatTime: (seconds: number) => string
}

export function buildAnimationHint(input: AnimationHintInput): string {
  const duration = input.animationDuration || 0
  if (!duration) {
    return (
      'No animation in this preview. Add keyframes in Blender and save to animate cameras.'
    )
  }
  if (!input.activeCameraName) {
    return `Animation ${input.formatTime(duration)} · choose a camera in the Cameras list`
  }
  if (!input.cameraMoves) {
    return (
      `Animation ${input.formatTime(duration)} · camera "${input.activeCameraName}" does not move. ` +
      'Pick another camera, or keyframe this camera (or its parent) in Blender and save.'
    )
  }
  return 'Scrub or play · camera view follows the active camera · Capture saves this frame to the selected board'
}

export function advancePlaybackTime(
  animationTime: number,
  delta: number,
  duration: number,
): { nextTime: number; reachedEnd: boolean } {
  const total = duration || 0
  const nextTime = animationTime + delta
  if (total > 0 && nextTime >= total) {
    return { nextTime: total, reachedEnd: true }
  }
  return { nextTime, reachedEnd: false }
}
