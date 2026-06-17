import { useEffect, useMemo, useRef, useState } from 'react'
import { projectFileUrl } from '../api'
import './ReferenceModelPreview.css'

declare global {
  interface Window {
    hydrateReferenceModelPreviews?: (root?: ParentNode) => void
    disposeReferenceModelPreviews?: (root?: ParentNode) => void
  }
}

let referenceModelPreviewModule: Promise<unknown> | null = null

function importRuntimeModule<T = unknown>(url: string): Promise<T> {
  return import(/* @vite-ignore */ url) as Promise<T>
}

function loadReferenceModelPreviewModule() {
  if (!referenceModelPreviewModule) {
    referenceModelPreviewModule = importRuntimeModule('/static/runtime/reference_model_preview.js').catch((error) => {
      referenceModelPreviewModule = null
      throw error
    })
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
  const [moduleFailed, setModuleFailed] = useState(false)
  const previewUrl = useMemo(() => `${projectFileUrl(path)}&preview=model`, [path])

  useEffect(() => {
    const root = rootRef.current
    if (!root || !path) return
    let disposed = false
    setModuleFailed(false)

    const hydrate = () => {
      if (disposed) return
      window.hydrateReferenceModelPreviews?.(root)
    }

    void loadReferenceModelPreviewModule()
      .then(() => {
        requestAnimationFrame(hydrate)
      })
      .catch((error) => {
        console.warn('Reference model preview module failed:', error)
        if (!disposed) setModuleFailed(true)
      })

    const onReady = () => hydrate()
    window.addEventListener('reference-model-preview-ready', onReady)

    return () => {
      disposed = true
      window.removeEventListener('reference-model-preview-ready', onReady)
      window.disposeReferenceModelPreviews?.(root)
    }
  }, [path, previewUrl])

  return (
    <div className={`ref-model-preview ${compact ? 'is-compact' : ''}`} ref={rootRef} title={label}>
      {moduleFailed ? (
        <div className="ref-model-preview-fallback" aria-hidden="true">
          3D
        </div>
      ) : (
        <canvas key={previewUrl} data-ref-model-preview={previewUrl} aria-label={`3D preview: ${label}`} />
      )}
      <div className="ref-model-preview-badge">3D</div>
    </div>
  )
}
