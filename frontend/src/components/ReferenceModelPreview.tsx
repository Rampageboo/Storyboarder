import { forwardRef, useEffect, useImperativeHandle, useMemo, useRef, useState } from 'react'

import { projectFileUrl } from '../api'

import { ReferenceGlbRenderer } from '../scene3d/referenceGlbRenderer'

import { resolveScene3dPreviewSettings } from '../scene3d/scenePreviewSettings'

import type { Scene3dCaptureRequest, Scene3dReferenceView } from '../scene3d/scene3dTypes'

import { useProject } from '../state/useProject'

import './ReferenceModelPreview.css'

export type ReferenceModelCaptureOptions = Scene3dCaptureRequest

export interface ReferenceModelPreviewHandle {
  captureFrame(options?: ReferenceModelCaptureOptions): Promise<string>
}

type ReferenceModelPreviewProps = {
  path: string
  label: string
  compact?: boolean
  view?: Scene3dReferenceView | null
}

function ReferenceModelPreviewCompact({ label }: { label: string }) {
  // Strip directory and extension for a compact display name.
  const shortName = (label.split(/[/\\]/).pop() ?? label).replace(/\.[^.]+$/, '') || label
  return (
    <div className="ref-model-preview is-compact" title={label}>
      <div className="ref-model-preview-compact-body">
        <span className="ref-model-preview-cube-icon" aria-hidden="true">⬡</span>
        <span className="ref-model-preview-filename">{shortName}</span>
        <span className="ref-model-preview-type-tag">3D / GLB</span>
      </div>
      <div className="ref-model-preview-badge">3D</div>
    </div>
  )
}

const ReferenceModelPreviewCanvas = forwardRef<ReferenceModelPreviewHandle, Omit<ReferenceModelPreviewProps, 'compact'>>(
  function ReferenceModelPreviewCanvas({ path, label, view = null }, ref) {
    const { project } = useProject()
    const canvasRef = useRef<HTMLCanvasElement | null>(null)
    const rendererRef = useRef<ReferenceGlbRenderer | null>(null)
    const [failed, setFailed] = useState(false)
    // Derived from project settings — no state needed; useMemo recalculates when scene3d sub-fields change.
    const previewSettings = useMemo(
      () => resolveScene3dPreviewSettings(project?.settings ?? null),
      // eslint-disable-next-line react-hooks/exhaustive-deps -- intentionally tracks scene3d sub-fields plus the settings ref
      [project?.settings?.scene3d?.wireframe_mode, project?.settings?.scene3d?.object_color_preview, project?.settings],
    )
    const previewUrl = useMemo(() => `${projectFileUrl(path)}&preview=model`, [path])
    const viewKey = useMemo(() => (view ? JSON.stringify(view) : ''), [view])
    const previewSettingsKey = useMemo(() => JSON.stringify(previewSettings), [previewSettings])

    useEffect(() => {
      const canvas = canvasRef.current
      if (!canvas || !path) return
      let disposed = false
      setFailed(false)
      const renderer = new ReferenceGlbRenderer(canvas, previewUrl, previewSettings)
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
      // eslint-disable-next-line react-hooks/exhaustive-deps -- settings/view sync in dedicated effects below
    }, [path, previewUrl])

    useEffect(() => {
      rendererRef.current?.updatePreviewSettings(previewSettings)
    }, [previewSettingsKey, previewSettings])

    useEffect(() => {
      rendererRef.current?.setView(view)
    }, [viewKey, view])

    useImperativeHandle(ref, () => ({
      async captureFrame(options: ReferenceModelCaptureOptions = {}) {
        const renderer = rendererRef.current
        if (!renderer) throw new Error('3D preview is not mounted yet.')
        return renderer.captureFrame(options)
      },
    }), [])

    return (
      <div className="ref-model-preview" title={label}>
        {failed ? (
          <div className="ref-model-preview-fallback" aria-hidden="true">3D preview unavailable</div>
        ) : (
          <canvas ref={canvasRef} aria-label={`3D preview: ${label}`} />
        )}
        <div className="ref-model-preview-badge">3D</div>
      </div>
    )
  },
)

export const ReferenceModelPreview = forwardRef<ReferenceModelPreviewHandle, ReferenceModelPreviewProps>(
  function ReferenceModelPreview({ path, label, compact = false, view = null }, ref) {
    if (compact) return <ReferenceModelPreviewCompact label={label} />
    return <ReferenceModelPreviewCanvas ref={ref} path={path} label={label} view={view} />
  },
)
