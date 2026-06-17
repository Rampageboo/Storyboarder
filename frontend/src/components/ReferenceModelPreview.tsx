import { useEffect, useMemo, useRef } from 'react'
import { projectFileUrl } from '../api'
import './ReferenceModelPreview.css'

declare global {
  interface Window {
    hydrateReferenceModelPreviews?: (root?: ParentNode) => void
    disposeReferenceModelPreviews?: (root?: ParentNode) => void
  }
}

let referenceModelPreviewModule: Promise<unknown> | null = null

function loadReferenceModelPreviewModule() {
  if (!referenceModelPreviewModule) {
    referenceModelPreviewModule = import(/* @vite-ignore */ '/static/reference_model_preview.js')
  }
  return referenceModelPreviewModule
}

export function ReferenceModelPreview({
  path,
  label,
  compact = false,
}: {
  path: string
  label: string
  compact?: boolean
}) {
  const rootRef = useRef<HTMLDivElement | null>(null)
  const previewUrl = useMemo(() => `${projectFileUrl(path)}&preview=model`, [path])

  useEffect(() => {
    const root = rootRef.current
    if (!root || !path) return
    let disposed = false

    void loadReferenceModelPreviewModule()
      .then(() => {
        if (disposed) return
        window.hydrateReferenceModelPreviews?.(root)
      })
      .catch((error) => {
        console.warn('Reference model preview module failed:', error)
      })

    return () => {
      disposed = true
      window.disposeReferenceModelPreviews?.(root)
    }
  }, [path, previewUrl])

  return (
    <div className={`ref-model-preview ${compact ? 'is-compact' : ''}`} ref={rootRef} title={label}>
      <canvas data-ref-model-preview={previewUrl} aria-label={`3D preview: ${label}`} />
      <div className="ref-model-preview-badge">3D</div>
    </div>
  )
}
