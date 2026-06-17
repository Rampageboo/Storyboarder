import type { RefSegmentModelCapture, Scene3dCaptureRequest, Scene3dReferenceView } from './scene3dTypes'

export type ModelCaptureFrameFn = (options: Scene3dCaptureRequest) => Promise<string>

export type ApplyModelCapturesOptions = {
  shots: { shot_id: string; duration_seconds?: number }[]
  lo: number
  hi: number
  boardCount: number
  durationSec: number
  animStart: number
  animSpan: number
  view: Scene3dReferenceView | null
  width: number
  height: number
  captureFrame: ModelCaptureFrameFn
  onProgress?: (message: string) => void
}

function nextFrame(): Promise<void> {
  return new Promise((resolve) => requestAnimationFrame(() => resolve()))
}

/** Render one GLB frame per board in range; does not mutate project state. */
export async function applyModelCaptures(options: ApplyModelCapturesOptions): Promise<RefSegmentModelCapture[]> {
  const {
    shots,
    lo,
    hi,
    boardCount,
    durationSec,
    animStart,
    animSpan,
    view,
    width,
    height,
    captureFrame,
    onProgress,
  } = options

  const captures: RefSegmentModelCapture[] = []
  let offset = 0
  for (let index = lo; index <= hi; index += 1) {
    const shot = shots[index]
    const animationTime = Math.max(0, animStart + (durationSec > 0 ? offset / durationSec : 0) * animSpan)
    onProgress?.(`Rendering 3D board ${index - lo + 1} / ${boardCount}`)
    await nextFrame()
    const dataUrl = await captureFrame({ time: animationTime, view, width, height })
    captures.push({ shot_id: shot.shot_id, data_url: dataUrl, animation_time: animationTime })
    offset += Math.max(0.1, Number(shot.duration_seconds) || 3)
    await nextFrame()
  }
  return captures
}
