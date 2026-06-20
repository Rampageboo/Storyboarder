import { useMemo, useRef, useState } from 'react'
import { projectFileUrl, removeShotReference, uploadShotReference } from '../api'
import { useProject } from '../state/useProject'
import './ReferencePanel.css'

function fileName(path: string) {
  return path.split(/[/\\]/).pop() || path
}

function RefThumb({ url, name }: { url: string; name: string }) {
  const [prevUrl, setPrevUrl] = useState(url)
  const [failed, setFailed] = useState(false)
  if (url !== prevUrl) {
    setPrevUrl(url)
    setFailed(false)
  }
  if (failed) {
    return <div className="refs-thumb-missing">missing</div>
  }
  return <img src={url} alt={name} loading="lazy" onError={() => setFailed(true)} />
}

export function ReferencePanel() {
  const { project, selectedShotId, setProject, flushDirtyShots, projectActionBusy, reportError } = useProject()
  const [busy, setBusy] = useState(false)
  const [bust, setBust] = useState(0)
  const [lightbox, setLightbox] = useState<string | null>(null)
  const [lightboxFailed, setLightboxFailed] = useState(false)
  const inputRef = useRef<HTMLInputElement | null>(null)

  const shot = useMemo(() => {
    if (!project || !selectedShotId) return null
    return project.shots.find((s) => s.shot_id === selectedShotId) || null
  }, [project, selectedShotId])

  const [prevShotIdForLightbox, setPrevShotIdForLightbox] = useState(selectedShotId)
  if (selectedShotId !== prevShotIdForLightbox) {
    setPrevShotIdForLightbox(selectedShotId)
    setLightbox(null)
  }

  const [prevLightbox, setPrevLightbox] = useState(lightbox)
  if (lightbox !== prevLightbox) {
    setPrevLightbox(lightbox)
    setLightboxFailed(false)
  }

  if (!project || !shot) {
    return (
      <section className="refs refs-idle">
        <div className="refs-header">
          <span className="refs-title">Shot references</span>
        </div>
        <div className="refs-empty">Select a board to manage per-shot reference images.</div>
      </section>
    )
  }

  const refs = shot.reference_image_paths || []
  const shotId = shot.shot_id
  const disabled = busy || projectActionBusy
  const refUrl = (path: string) => `${projectFileUrl(path)}&v=${bust}`

  const addReference = (file: File | undefined) => {
    if (!file) return
    setBusy(true)
    void (async () => {
      try {
        await flushDirtyShots()
        setProject(await uploadShotReference(shotId, file))
        setBust((x) => x + 1)
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
        setBust((x) => x + 1)
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
                <RefThumb url={refUrl(path)} name={fileName(path)} />
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
                  &times;
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {lightbox ? (
        <div className="refs-lightbox" role="dialog" aria-modal="true" onClick={() => setLightbox(null)}>
          {lightboxFailed ? (
            <div className="refs-lightbox-missing" onClick={(e) => e.stopPropagation()}>
              Image missing or unreadable
            </div>
          ) : (
            <img
              src={refUrl(lightbox)}
              alt={fileName(lightbox)}
              onClick={(e) => e.stopPropagation()}
              onError={() => setLightboxFailed(true)}
            />
          )}
          <div className="refs-lightbox-path">{lightbox}</div>
          <button type="button" className="refs-lightbox-close" onClick={() => setLightbox(null)} aria-label="Close preview">
            &times;
          </button>
        </div>
      ) : null}
    </section>
  )
}
