import { forwardRef, useEffect, useImperativeHandle, useMemo, useRef, useState } from 'react'
import { projectFileUrl } from '../api'
import type { Scene3dReferenceView } from '../utils/scene3dView'
import './ReferenceModelPreview.css'

declare global {
  interface Window {
    hydrateReferenceModelPreviews?: (root?: ParentNode) => void
    disposeReferenceModelPreviews?: (root?: ParentNode) => void
    applyReferenceModelView?: (root?: ParentNode) => void
    captureReferenceModelFrame?: (
      root: ParentNode,
      options: { time?: number; view?: Scene3dReferenceView | null; width?: number; height?: number },
    ) => Promise<string>
  }
}

export type ReferenceModelPreviewHandle = {
  /** Render one GLB frame at the given animation time/view and return a PNG data URL. */
  captureFrame: (options: {
    time: number
    view: Scene3dReferenceView | null
    width?: number
    height?: number
  }) => Promise<string>
}

type ReferenceModelPreviewProps = {
  path: string
  label: string
  compact?: boolean
  /** Optional Scene3D view to reproduce instead of the generic framed orbit preview. */
  view?: Scene3dReferenceView | null
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

export const ReferenceModelPreview = forwardRef<ReferenceModelPreviewHandle, ReferenceModelPreviewProps>(
  function ReferenceModelPreview({ path, label, compact = false, view = null }, ref) {
    const rootRef = useRef<HTMLDivElement | null>(null)
    const [moduleFailed, setModuleFailed] = useState(false)
    const previewUrl = useMemo(() => `${projectFileUrl(path)}&preview=model`, [path])
    // Empty string (not undefined) so the canvas attribute clears cleanly when there is no view.
    const viewJson = useMemo(() => (view ? JSON.stringify(view) : ''), [view])

    // Let a parent (the reference-assignment apply flow) render board frames from this GLB preview.
    useImperativeHandle(
      ref,
      () => ({
        captureFrame: async (options) => {
          const root = rootRef.current
          if (!root) throw new Error('3D preview is not mounted')
          if (typeof window.captureReferenceModelFrame !== 'function') {
            // Make sure the runtime module (which registers the global) is loaded, then retry.
            await loadReferenceModelPreviewModule()
          }
          const capture = window.captureReferenceModelFrame
          if (typeof capture !== 'function') throw new Error('3D capture unavailable (runtime not loaded)')
          return capture(root, options)
        },
      }),
      [],
    )

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

    // Re-apply the camera/view when it changes for an already-mounted preview (no remount, so the
    // WebGL context is reused). Runs for both directions — setting a view AND clearing it back to ''
    // (the runtime then falls back to frameObject + resumes auto-rotate). On first mount the runtime
    // reads the view attribute itself.
    useEffect(() => {
      const root = rootRef.current
      if (!root) return
      let cancelled = false
      void loadReferenceModelPreviewModule()
        .then(() => {
          if (cancelled) return
          requestAnimationFrame(() => {
            if (!cancelled) window.applyReferenceModelView?.(root)
          })
        })
        .catch(() => {})
      return () => {
        cancelled = true
      }
    }, [viewJson])

    return (
      <div className={`ref-model-preview ${compact ? 'is-compact' : ''}`} ref={rootRef} title={label}>
        {moduleFailed ? (
          <div className="ref-model-preview-fallback" aria-hidden="true">
            3D
          </div>
        ) : (
          <canvas
            key={previewUrl}
            data-ref-model-preview={previewUrl}
            data-ref-model-view={viewJson}
            aria-label={`3D preview: ${label}`}
          />
        )}
        <div className="ref-model-preview-badge">3D</div>
      </div>
    )
  },
)
