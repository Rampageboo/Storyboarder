/**
 * Shared canvas capture helpers for Scene3D workspace and reference GLB renderer.
 * No board writes — callers upload captures to the backend apply endpoint.
 */

export type Scene3dCaptureOptions = {
  width?: number
  height?: number
  /** Defaults to `image/png`. */
  mimeType?: string
  /** When true, throw if the canvas appears blank or nearly uniform. */
  rejectBlank?: boolean
}

export type Scene3dCaptureResult = {
  dataUrl: string
  width: number
  height: number
}

export function isBlankCanvas(canvas: HTMLCanvasElement): boolean {
  if (canvas.width <= 1 || canvas.height <= 1) return true
  const probe = document.createElement('canvas')
  probe.width = 32
  probe.height = 32
  const ctx = probe.getContext('2d', { willReadFrequently: true })
  if (!ctx) return false
  ctx.drawImage(canvas, 0, 0, probe.width, probe.height)
  const pixels = ctx.getImageData(0, 0, probe.width, probe.height).data
  let min = 255
  let max = 0
  let transparent = 0
  let brightness = 0
  const count = probe.width * probe.height
  for (let i = 0; i < pixels.length; i += 4) {
    const r = pixels[i]
    const g = pixels[i + 1]
    const b = pixels[i + 2]
    const a = pixels[i + 3]
    if (a < 8) transparent += 1
    min = Math.min(min, r, g, b)
    max = Math.max(max, r, g, b)
    brightness += (r + g + b) / 3
  }
  const avg = brightness / count
  if (transparent / count > 0.8) return true
  return max - min < 3 && (avg < 8 || avg > 247)
}

export type CaptureCanvasPngOptions = Scene3dCaptureOptions & {
  /** Optional render callback invoked before readback. */
  render?: () => void
}

/**
 * Read a PNG data URL from a canvas.
 * Caller should set renderer size before calling render when exporting at custom dimensions.
 */
export function captureCanvasPng(
  canvas: HTMLCanvasElement,
  options: CaptureCanvasPngOptions = {},
): Scene3dCaptureResult {
  const width = Math.max(1, Math.floor(options.width ?? canvas.width ?? 1))
  const height = Math.max(1, Math.floor(options.height ?? canvas.height ?? 1))
  const mimeType = options.mimeType ?? 'image/png'

  options.render?.()

  if (options.rejectBlank && isBlankCanvas(canvas)) {
    throw new Error('3D capture produced a blank frame; refusing to export.')
  }

  const dataUrl = canvas.toDataURL(mimeType)
  return { dataUrl, width, height }
}
