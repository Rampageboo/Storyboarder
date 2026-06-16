import { useEffect, useMemo, useRef, useState } from 'react'
import { projectFileUrl, removeShotReference, uploadShotReference } from '../api'
import { useProject } from '../state/ProjectContext'
import './ReferencePanel.css'

function fileName(path: string) {
  return path.split(/[/\\]/).pop() || path
}

export function ReferencePanel() {
  const { project, selectedShotId, setProject, flushDirtyShots, projectActionBusy, reportError } = useProject()
  const [busy, setBusy] = useState(false)
  const [lightbox, setLightbox] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement | null>(null)

  const shot = useMemo(() => {
    if (!project || !selectedShotId) return null
    return project.shots.find((s) => s.shot_id === selectedShotId) || null
  }, [project, selectedShotId])

  // Close the lightbox when switching shots.
  useEffect(() => {
    setLightbox(null)
  }, [selectedShotId])

  if (!project || !shot) return null

  const refs = shot.reference_image_paths || []
  const shotId = shot.shot_id
  const disabled = busy || projectActionBusy

  const addReference = (file: File | undefined) => {
    if (!file) return
    setBusy(true)
    void (async () => {
      try {
        await flushDirtyShots()
        setProject(await uploadShotReference(shotId, file))
      } catch (error) {
        reportError(error)
      } finally {
        setBusy(false)
      }
    })()
  }

  const removeReference = (path: string) => {
    if (!window.confirm(`Remove reference "${fileName(path)}"?`)) return
    setBusy(true)
    void (async () => {
      try {
        await flushDirtyShots()
        setProject(await removeShotReference(shotId, { path }))
        setLightbox((cur) => (cur === path ? null : cur))
      } catch (error) {
        reportError(error)
      } finally {
        setBusy(false)
      }
    })()
  }

  return (
    <section className="refs">
      <div className="refs-header">
        <span className="refs-title">References ({refs.length})</span>
        <button type="button" onClick={() => inputRef.current?.click()} disabled={disabled}>
          Add reference
        </button>
      </div>
      <input
        ref={inputRef}
        type="file"
        accept="image/*"
        hidden
        onChange={(e) => {
          addReference(e.target.files?.[0] ?? undefined)
          e.target.value = ''
        }}
      />

      {refs.length === 0 ? (
        <div className="refs-empty">No reference images yet.</div>
      ) : (
        <div className="refs-grid">
          {refs.map((path) => (
            <div className="refs-item" key={path}>
              <button type="button" className="refs-thumb" onClick={() => setLightbox(path)} title={`Preview ${path}`}>
                <img src={projectFileUrl(path)} alt={fileName(path)} loading="lazy" />
              </button>
              <div className="refs-meta">
                <span className="refs-name" title={path}>
                  {fileName(path)}
                </span>
                <button
                  type="button"
                  className="refs-remove"
                  onClick={() => removeReference(path)}
                  disabled={disabled}
                  aria-label={`Remove ${fileName(path)}`}
                >
                  ×
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {lightbox ? (
        <div className="refs-lightbox" role="dialog" aria-modal="true" onClick={() => setLightbox(null)}>
          <img src={projectFileUrl(lightbox)} alt={fileName(lightbox)} onClick={(e) => e.stopPropagation()} />
          <div className="refs-lightbox-path">{lightbox}</div>
          <button type="button" className="refs-lightbox-close" onClick={() => setLightbox(null)} aria-label="Close preview">
            ×
          </button>
        </div>
      ) : null}
    </section>
  )
}
