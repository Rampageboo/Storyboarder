/**
 * Canvas capture helpers for the Scene3D workspace.
 * No board writes — callers upload captures to the backend apply endpoint.
 */

import type { WorkspaceCaptureOptions, WorkspaceCaptureResult } from './workspaceTypes'

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

export type CaptureCanvasPngOptions = WorkspaceCaptureOptions & {
  /** Optional render callback invoked after resize, before readback. */
  render?: () => void
}

/**
 * Read a PNG data URL from a canvas. Optionally resizes via width/height on the source canvas
 * dimensions used for export (caller should set renderer size before calling render).
 */
export function captureCanvasPng(
  canvas: HTMLCanvasElement,
  options: CaptureCanvasPngOptions = {},
): WorkspaceCaptureResult {
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

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type ThreeModule = Record<string, any>
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type ThreeObject = any

export type CaptureRendererPngOptions = {
  width?: number
  height?: number
  getProjectCanvasSize?: () => { width: number; height: number }
  /** Invoked before export resize and again after resize (matches scene3d.js follow-camera timing). */
  prepareExport?: () => void
  /** Invoked after restoring display size — typically re-apply follow camera + display render. */
  finishDisplay?: () => void
}

/** Export a PNG data URL from a WebGLRenderer at project canvas dimensions. */
export function captureRendererPng(
  THREE: ThreeModule,
  renderer: ThreeObject,
  camera: ThreeObject,
  scene: ThreeObject,
  options: CaptureRendererPngOptions = {},
): string {
  const displaySize = new THREE.Vector2()
  renderer.getSize(displaySize)
  const displayPixelRatio = renderer.getPixelRatio()
  const displayAspect = camera.aspect
  const projectSize = options.getProjectCanvasSize?.() ?? { width: 1920, height: 1080 }
  const exportWidth = Math.max(1, Math.floor(options.width ?? projectSize.width))
  const exportHeight = Math.max(1, Math.floor(options.height ?? projectSize.height))

  options.prepareExport?.()

  renderer.setPixelRatio(1)
  renderer.setSize(exportWidth, exportHeight, false)
  camera.aspect = exportWidth / exportHeight
  camera.updateProjectionMatrix()

  options.prepareExport?.()
  renderer.render(scene, camera)
  const url = renderer.domElement.toDataURL('image/png')

  renderer.setPixelRatio(displayPixelRatio)
  renderer.setSize(displaySize.x, displaySize.y, false)
  camera.aspect = displayAspect
  camera.updateProjectionMatrix()

  options.finishDisplay?.()

  return url
}
