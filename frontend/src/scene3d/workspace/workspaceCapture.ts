/**
 * Canvas capture helpers for the Scene3D workspace static bundle.
 * Core implementation lives in ../capture.ts (shared with reference GLB renderer).
 */

export {
  captureCanvasPng,
  isBlankCanvas,
  type CaptureCanvasPngOptions,
  type Scene3dCaptureOptions,
  type Scene3dCaptureResult,
} from '../capture'

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
