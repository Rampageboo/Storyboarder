import { forwardRef, useEffect, useImperativeHandle, useMemo, useRef, useState } from 'react'

import { projectFileUrl } from '../api'

import { loadPreviewStyle } from '../scene3d/previewStyleBridge'

import { ReferenceGlbRenderer } from '../scene3d/referenceGlbRenderer'

import {

  defaultPreviewSettings,

  resolveScene3dPreviewSettingsSync,

  type Scene3dPreviewSettings,

} from '../scene3d/scenePreviewSettings'

import type { Scene3dCaptureRequest, Scene3dReferenceView } from '../scene3d/scene3dTypes'

import { useProject } from '../state/ProjectContext'

import './ReferenceModelPreview.css'



export interface ReferenceModelCaptureOptions extends Scene3dCaptureRequest {}



export interface ReferenceModelPreviewHandle {

  captureFrame(options?: ReferenceModelCaptureOptions): Promise<string>

}



export const ReferenceModelPreview = forwardRef<ReferenceModelPreviewHandle, {

  path: string

  label: string

  compact?: boolean

  view?: Scene3dReferenceView | null

}>(function ReferenceModelPreview({ path, label, compact = false, view = null }, ref) {

  const { project } = useProject()

  const canvasRef = useRef<HTMLCanvasElement | null>(null)

  const rendererRef = useRef<ReferenceGlbRenderer | null>(null)

  const [failed, setFailed] = useState(false)

  const [previewSettings, setPreviewSettings] = useState<Scene3dPreviewSettings>(() => defaultPreviewSettings())

  const previewUrl = useMemo(() => `${projectFileUrl(path)}&preview=model`, [path])

  const viewKey = useMemo(() => (view ? JSON.stringify(view) : ''), [view])

  const previewSettingsKey = useMemo(() => JSON.stringify(previewSettings), [previewSettings])



  useEffect(() => {

    let cancelled = false

    void loadPreviewStyle().then((style) => {

      if (cancelled) return

      setPreviewSettings(resolveScene3dPreviewSettingsSync(project?.settings ?? null, style))

    })

    return () => {

      cancelled = true

    }

  }, [project?.settings?.scene3d?.wireframe_mode, project?.settings?.scene3d?.object_color_preview, project?.settings])



  if (compact) {

    return (

      <div className="ref-model-preview is-compact" title={label}>

        <div className="ref-model-preview-fallback" aria-hidden="true">3D</div>

        <div className="ref-model-preview-badge">3D</div>

      </div>

    )

  }



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

})


