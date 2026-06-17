import { useEffect, useMemo, useRef, useState } from 'react'
import {
  deleteProjectReference,
  deleteRefSegment,
  projectFileUrl,
  restoreRefApply,
  uploadProjectReference,
} from '../api'
import type { ReferenceLink } from '../types'
import { useProject } from '../state/ProjectContext'
import { shotDisplayLabel } from '../utils/shotDisplay'
import './ReferenceSidebar.css'

type Segment = {
  id?: string
  anchor_shot_id?: string
  end_shot_id?: string
  source_type?: string
  [key: string]: unknown
}

function fileName(path: string) {
  return path.split(/[/\\]/).pop() || path
}

function RefPreview({ link }: { link: ReferenceLink }) {
  const [failed, setFailed] = useState(false)
  const url = projectFileUrl(link.path)

  useEffect(() => {
    setFailed(false)
  }, [link.id, link.path])

  if (link.type === 'model') {
    return <div className="reflib-thumb-model">3D</div>
  }

  if (failed) {
    return <div className="reflib-thumb-fallback">{link.type}</div>
  }

  if (link.type === 'video') {
    return <video src={url} muted preload="metadata" playsInline onError={() => setFailed(true)} />
  }

  return <img src={url} alt="" loading="lazy" onError={() => setFailed(true)} />
}

export function ReferenceSidebar() {
  const {
    project,
    setProject,
    flushDirtyShots,
    projectActionBusy,
    reportError,
    refApplyUndoToken,
    setRefApplyUndoToken,
    activeAppliedSegmentId,
    dismissRefSegmentUi,
  } = useProject()
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [segmentsOpen, setSegmentsOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState('')
  const [lightbox, setLightbox] = useState<ReferenceLink | null>(null)
  const importRef = useRef<HTMLInputElement | null>(null)

  const links = useMemo(() => project?.settings?.reference_links ?? [], [project?.settings?.reference_links])
  const segments = useMemo(
    () => (project?.settings?.ref_segments ?? []) as unknown as Segment[],
    [project?.settings?.ref_segments],
  )
  const shots = project?.shots ?? []
  const recentSegments = useMemo(() => segments.slice(-5).reverse(), [segments])

  useEffect(() => {
    if (!note) return
    const t = window.setTimeout(() => setNote(''), 3200)
    return () => window.clearTimeout(t)
  }, [note])

  if (!project) return null

  const disabled = busy || projectActionBusy

  const shotLabel = (id: string) => {
    const s = shots.find((sh) => sh.shot_id === id)
    return s ? shotDisplayLabel(s) : id
  }

  const importReference = (file: File | undefined) => {
    if (!file) return
    setBusy(true)
    void (async () => {
      try {
        await flushDirtyShots()
        setProject(await uploadProjectReference(file))
        setNote(`Imported: ${file.name}`)
      } catch (error) {
        reportError(error)
      } finally {
        setBusy(false)
      }
    })()
  }

  const removeLink = (id: string, title: string) => {
    if (!window.confirm(`Remove reference "${title}" from the library?`)) return
    setBusy(true)
    void (async () => {
      try {
        await flushDirtyShots()
        setProject(await deleteProjectReference(id))
        setLightbox((cur) => (cur?.id === id ? null : cur))
      } catch (error) {
        reportError(error)
      } finally {
        setBusy(false)
      }
    })()
  }

  const undoLastApply = () => {
    if (!refApplyUndoToken) return
    setBusy(true)
    void (async () => {
      try {
        await flushDirtyShots()
        setProject(await restoreRefApply(refApplyUndoToken))
        setRefApplyUndoToken(null)
        setNote('Reference apply undone.')
      } catch (error) {
        reportError(error)
      } finally {
        setBusy(false)
      }
    })()
  }

  const removeSegment = (id: string) => {
    setBusy(true)
    void (async () => {
      try {
        await flushDirtyShots()
        setProject(await deleteRefSegment(id))
        if (activeAppliedSegmentId === id) dismissRefSegmentUi()
      } catch (error) {
        reportError(error)
      } finally {
        setBusy(false)
      }
    })()
  }

  return (
    <>
      <button
        type="button"
        className={`ref-rail-btn ${drawerOpen ? 'is-active' : ''}`}
        onClick={() => setDrawerOpen((v) => !v)}
        title="Reference library"
        aria-expanded={drawerOpen}
        aria-controls="ref-drawer-panel"
      >
        <span className="ref-rail-icon" aria-hidden="true">
          ◫
        </span>
        <span className="ref-rail-label">Refs</span>
        {links.length > 0 ? <span className="ref-rail-count">{links.length}</span> : null}
      </button>

      {drawerOpen ? <div className="ref-drawer-backdrop" onClick={() => setDrawerOpen(false)} aria-hidden="true" /> : null}

      <aside
        id="ref-drawer-panel"
        className={`ref-sidebar ${drawerOpen ? 'is-open' : ''}`}
        aria-label="Project references"
        aria-hidden={!drawerOpen}
      >
        <div className="ref-sidebar-scroll">
          <div className="ref-sidebar-head">
            <span className="ref-sidebar-title">References ({links.length})</span>
            <div className="ref-sidebar-head-actions">
              <button type="button" onClick={() => importRef.current?.click()} disabled={disabled}>
                Import
              </button>
              <button type="button" className="ref-drawer-close" onClick={() => setDrawerOpen(false)} aria-label="Close">
                ×
              </button>
            </div>
          </div>
          <input
            ref={importRef}
            type="file"
            accept="image/*,video/*,.glb,.gltf"
            hidden
            onChange={(e) => {
              importReference(e.target.files?.[0] ?? undefined)
              e.target.value = ''
            }}
          />

          <p className="ref-sidebar-hint">Pick a dot range on the filmstrip to assign a reference to boards.</p>

          {links.length === 0 ? (
            <div className="ref-sidebar-empty">Import images, video, or GLB models for reference segments.</div>
          ) : (
            <div className="reflib-grid">
              {links.map((link) => {
                const label = link.title || fileName(link.path)
                return (
                  <div key={link.id} className="reflib-card">
                    <button
                      type="button"
                      className="reflib-card-main"
                      onDoubleClick={() => (link.type !== 'model' ? setLightbox(link) : undefined)}
                      title={link.path}
                    >
                      <div className="reflib-thumb">
                        <RefPreview link={link} />
                      </div>
                      <div className="reflib-meta">
                        <span className="reflib-type">{link.type}</span>
                        <span className="reflib-name">{label}</span>
                      </div>
                    </button>
                    <button
                      type="button"
                      className="reflib-remove"
                      onClick={() => removeLink(link.id, label)}
                      disabled={disabled}
                      aria-label={`Remove ${label}`}
                    >
                      ×
                    </button>
                  </div>
                )
              })}
            </div>
          )}

          {segments.length > 0 ? (
            <section className="ref-segments-disclosure">
              <button
                type="button"
                className="ref-segments-toggle"
                onClick={() => setSegmentsOpen((v) => !v)}
                aria-expanded={segmentsOpen}
              >
                <span>Applied segments ({segments.length})</span>
                <span className="ref-segments-chevron">{segmentsOpen ? '▾' : '▸'}</span>
              </button>
              {segmentsOpen ? (
                <ul className="ref-segment-list">
                  {recentSegments.map((s, i) => (
                    <li className="ref-segment-item" key={s.id || `${s.anchor_shot_id}-${s.end_shot_id}-${i}`}>
                      <span className="ref-segment-type">{s.source_type || '—'}</span>
                      <span className="ref-segment-range">
                        {shotLabel(s.anchor_shot_id || '')} → {shotLabel(s.end_shot_id || '')}
                      </span>
                      {s.id ? (
                        <button
                          type="button"
                          className="ref-segment-remove"
                          onClick={() => removeSegment(s.id as string)}
                          disabled={disabled}
                          aria-label="Delete segment"
                        >
                          ×
                        </button>
                      ) : null}
                    </li>
                  ))}
                  {segments.length > 5 ? (
                    <li className="ref-segment-more">+ {segments.length - 5} older segment(s)</li>
                  ) : null}
                </ul>
              ) : null}
            </section>
          ) : null}

          {refApplyUndoToken ? (
            <button type="button" className="ref-sidebar-undo" onClick={() => undoLastApply()} disabled={disabled}>
              Undo last apply
            </button>
          ) : null}

          {note ? <div className="ref-sidebar-note">{note}</div> : null}
        </div>
      </aside>

      {lightbox ? (
        <div className="ref-sidebar-lightbox" role="dialog" aria-modal="true" onClick={() => setLightbox(null)}>
          {lightbox.type === 'video' ? (
            <video src={projectFileUrl(lightbox.path)} controls onClick={(e) => e.stopPropagation()} />
          ) : (
            <img
              src={projectFileUrl(lightbox.path)}
              alt={lightbox.title || fileName(lightbox.path)}
              onClick={(e) => e.stopPropagation()}
            />
          )}
          <div className="ref-sidebar-lightbox-path">{lightbox.path}</div>
          <button
            type="button"
            className="ref-sidebar-lightbox-close"
            onClick={() => setLightbox(null)}
            aria-label="Close preview"
          >
            ×
          </button>
        </div>
      ) : null}
    </>
  )
}
