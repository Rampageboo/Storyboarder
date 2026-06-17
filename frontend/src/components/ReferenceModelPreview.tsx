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
let assignmentPreviewObserver: MutationObserver | null = null

function loadReferenceModelPreviewModule() {
  if (!referenceModelPreviewModule) {
    referenceModelPreviewModule = import(/* @vite-ignore */ '/static/reference_model_preview.js')
  }
  return referenceModelPreviewModule
}

function selectedAssignmentModelPath(): string {
  const selected = document.querySelector<HTMLElement>('.ref-assign-ref-item.is-selected[title]')
  return selected?.getAttribute('title') || ''
}

function hydrateAssignmentModelPlaceholder() {
  const root = document.querySelector<HTMLElement>('.ref-assign-player-model-safe')
  if (!root || root.dataset.modelPreviewHydrated === 'true') return
  const path = selectedAssignmentModelPath()
  if (!path) return
  root.dataset.modelPreviewHydrated = 'true'
  root.classList.add('is-hydrated')
  root.textContent = ''
  const canvas = document.createElement('canvas')
  canvas.dataset.refModelPreview = `${projectFileUrl(path)}&preview=model`
  canvas.setAttribute('aria-label', `3D preview: ${path.split(/[/\\]/).pop() || path}`)
  root.appendChild(canvas)
  const badge = document.createElement('div')
  badge.className = 'ref-model-preview-badge'
  badge.textContent = '3D'
  root.appendChild(badge)
  void loadReferenceModelPreviewModule().then(() => window.hydrateReferenceModelPreviews?.(root))
}

function ensureAssignmentPreviewObserver() {
  if (assignmentPreviewObserver || typeof document === 'undefined') return
  assignmentPreviewObserver = new MutationObserver(() => hydrateAssignmentModelPlaceholder())
  assignmentPreviewObserver.observe(document.body, { childList: true, subtree: true })
  hydrateAssignmentModelPlaceholder()
}

if (typeof window !== 'undefined') {
  queueMicrotask(ensureAssignmentPreviewObserver)
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
