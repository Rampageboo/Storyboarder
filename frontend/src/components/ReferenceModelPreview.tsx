import { forwardRef, useEffect, useImperativeHandle, useMemo, useRef, useState } from 'react'
import { projectFileUrl } from '../api'
import { ReferenceGlbRenderer, type GlbCaptureOptions } from '../scene3d/referenceGlbRenderer'
import type { Scene3dReferenceView } from '../utils/scene3dView'
import './ReferenceModelPreview.css'

export interface ReferenceModelCaptureOptions extends GlbCaptureOptions {}

export interface ReferenceModelPreviewHandle {
  captureFrame(options?: ReferenceModelCaptureOptions): Promise<string>
}

export const ReferenceModelPreview = forwardRef<ReferenceModelPreviewHandle, {
  path: string
  label: string
  compact?: boolean
  /** Optional Scene3D view to reproduce instead of the generic framed orbit preview. */
  view?: Scene3dReferenceView | null
}>(function ReferenceModelPreview({ path, label, compact = false, view = null }, ref) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const rendererRef = useRef<ReferenceGlbRenderer | null>(null)
  const [failed, setFailed] = useState(false)
  const previewUrl = useMemo(() => `${projectFileUrl(path)}&preview=model`, [path])
  const viewKey = useMemo(() => (view ? JSON.stringify(view) : ''), [view])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas || !path) return
    let disposed = false
    setFailed(false)
    const renderer = new ReferenceGlbRenderer(canvas, previewUrl)
    rendererRef.current = renderer
    void renderer.init(view).catch((error) => {
      console.warn('Reference model preview failed:', error)
      if (!disposed) setFailed(true)
    })
    return () => {
      disposed = true
      renderer.dispose()
      if (rendererRef.current === renderer) rendererRef.current = null
    }
  }, [path, previewUrl])

  useEffect(() => {
    rendererRef.current?.setView(view)
  }, [viewKey, view])

  useImperativeHandle(ref, () => ({
    async captureFrame(options: ReferenceModelCaptureOptions = {}) {
      const renderer = rendererRef.current
      if (!renderer) throw new Error('3D preview is not mounted yet.')
      return renderer.capture(options)
    },
  }), [])

  return (
    <div className={`ref-model-preview ${compact ? 'is-compact' : ''}`} title={label}>
      {failed ? (
        <div className="ref-model-preview-fallback" aria-hidden="true">
          3D
        </div>
      ) : (
        <canvas ref={canvasRef} aria-label={`3D preview: ${label}`} />
      )}
      <div className="ref-model-preview-badge">3D</div>
    </div>
  )
})
