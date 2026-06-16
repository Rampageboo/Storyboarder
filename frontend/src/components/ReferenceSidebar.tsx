import { useEffect, useMemo, useRef, useState } from 'react'
import {
  applyRefSegment,
  applyRefSegment3d,
  applyRefSegmentImage,
  deleteProjectReference,
  deleteRefSegment,
  projectFileUrl,
  restoreRefApply,
  updateSettings,
  uploadProjectReference,
  type ApplyRefSegmentRequest,
} from '../api'
import type { ProjectPayload, ReferenceLink } from '../types'
import { useProject } from '../state/ProjectContext'
import { shotDisplayLabel } from '../utils/shotDisplay'
import './ReferenceSidebar.css'

type Segment = {
  id?: string
  anchor_shot_id?: string
  end_shot_id?: string
  source_type?: string
  reference_id?: string
  reference_path?: string
  video_start?: number
  [key: string]: unknown
}

function newSegmentId(): string {
  const c = globalThis.crypto as Crypto | undefined
  if (c && typeof c.randomUUID === 'function') return c.randomUUID().replace(/-/g, '')
  return `seg_${Date.now().toString(36)}${Math.floor(Math.random() * 1e6).toString(36)}`
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
  const { project, selectedShotId, setProject, flushDirtyShots, projectActionBusy, reportError } = useProject()
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState('')
  const [lightbox, setLightbox] = useState<ReferenceLink | null>(null)
  const importRef = useRef<HTMLInputElement | null>(null)

  const [refId, setRefId] = useState('')
  const [startShot, setStartShot] = useState('')
  const [endShot, setEndShot] = useState('')
  const [startTime, setStartTime] = useState('0')
  const [undoToken, setUndoToken] = useState('')

  const links = useMemo(() => project?.settings?.reference_links ?? [], [project?.settings?.reference_links])
  const segments = useMemo(
    () => (project?.settings?.ref_segments ?? []) as unknown as Segment[],
    [project?.settings?.ref_segments],
  )
  const shots = project?.shots ?? []

  useEffect(() => {
    setRefId((cur) => (cur && links.some((l) => l.id === cur) ? cur : links[0]?.id ?? ''))
  }, [links])

  useEffect(() => {
    if (selectedShotId) {
      setStartShot(selectedShotId)
      setEndShot(selectedShotId)
    }
  }, [selectedShotId])

  if (!project) return null

  const disabled = busy || projectActionBusy
  const selectedRef = links.find((l) => l.id === refId) || null

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

  const applySegment = () => {
    if (!selectedRef) {
      window.alert('Choose a source reference first.')
      return
    }
    if (!startShot || !endShot) {
      window.alert('Choose a start shot and an end shot.')
      return
    }
    const start = Number(startTime)
    const videoStart = Number.isFinite(start) && start > 0 ? start : 0
    const segId = newSegmentId()
    const seg: Segment = {
      id: segId,
      anchor_shot_id: startShot,
      end_shot_id: endShot,
      source_type: selectedRef.type,
      reference_id: selectedRef.id,
      reference_path: selectedRef.path,
      video_start: videoStart,
    }
    setBusy(true)
    void (async () => {
      try {
        await flushDirtyShots()
        const existing = segments.filter((s) => s.id && s.id !== segId)
        await updateSettings({ ref_segments: [...existing, seg], active_ref_segment_id: segId })
        const body: ApplyRefSegmentRequest = { anchor_shot_id: startShot, end_shot_id: endShot, segment_id: segId }
        let payload: ProjectPayload
        if (selectedRef.type === 'image') payload = await applyRefSegmentImage(body)
        else if (selectedRef.type === 'model') payload = await applyRefSegment3d({ ...body, camera_name: '' })
        else payload = await applyRefSegment(body)
        setProject(payload)
        const result = payload as unknown as { board_count?: number; undo_token?: string }
        setUndoToken(typeof result.undo_token === 'string' ? result.undo_token : '')
        setNote(`Applied to ${result.board_count ?? '?'} board(s).`)
      } catch (error) {
        reportError(error)
      } finally {
        setBusy(false)
      }
    })()
  }

  const undoLastApply = () => {
    if (!undoToken) return
    setBusy(true)
    void (async () => {
      try {
        await flushDirtyShots()
        setProject(await restoreRefApply(undoToken))
        setUndoToken('')
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
      } catch (error) {
        reportError(error)
      } finally {
        setBusy(false)
      }
    })()
  }

  return (
    <aside className="ref-sidebar" aria-label="Project references">
      <div className="ref-sidebar-scroll">
        <div className="ref-sidebar-head">
          <span className="ref-sidebar-title">References ({links.length})</span>
          <button type="button" onClick={() => importRef.current?.click()} disabled={disabled}>
            Import
          </button>
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

        {links.length === 0 ? (
          <div className="ref-sidebar-empty">Import images, video, or GLB models for reference segments.</div>
        ) : (
          <div className="reflib-grid">
            {links.map((link) => {
              const label = link.title || fileName(link.path)
              const isSelected = refId === link.id
              return (
                <button
                  key={link.id}
                  type="button"
                  className={`reflib-card ${isSelected ? 'is-selected' : ''}`}
                  onClick={() => setRefId(link.id)}
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
                  <button
                    type="button"
                    className="reflib-remove"
                    onClick={(e) => {
                      e.stopPropagation()
                      removeLink(link.id, label)
                    }}
                    disabled={disabled}
                    aria-label={`Remove ${label}`}
                  >
                    ×
                  </button>
                </button>
              )
            })}
          </div>
        )}

        <section className="ref-segment">
          <div className="ref-segment-title">Reference segment</div>
          <label className="ref-segment-field">
            <span>Source</span>
            <select value={refId} onChange={(e) => setRefId(e.target.value)} disabled={!links.length}>
              {links.length === 0 ? <option value="">No references</option> : null}
              {links.map((l) => (
                <option key={l.id} value={l.id}>
                  {l.title || fileName(l.path)} · {l.type}
                </option>
              ))}
            </select>
          </label>
          <label className="ref-segment-field">
            <span>Start board</span>
            <select value={startShot} onChange={(e) => setStartShot(e.target.value)}>
              {shots.map((s) => (
                <option key={s.shot_id} value={s.shot_id}>
                  {shotLabel(s.shot_id)}
                </option>
              ))}
            </select>
          </label>
          <label className="ref-segment-field">
            <span>End board</span>
            <select value={endShot} onChange={(e) => setEndShot(e.target.value)}>
              {shots.map((s) => (
                <option key={s.shot_id} value={s.shot_id}>
                  {shotLabel(s.shot_id)}
                </option>
              ))}
            </select>
          </label>
          <label className="ref-segment-field">
            <span>Start time (s)</span>
            <input
              type="number"
              min="0"
              step="0.1"
              value={startTime}
              onChange={(e) => setStartTime(e.target.value)}
              disabled={selectedRef?.type !== 'video'}
            />
          </label>
          <div className="ref-segment-actions">
            <button
              type="button"
              className="primary"
              onClick={() => applySegment()}
              disabled={disabled || !links.length || shots.length === 0}
            >
              Apply to board range
            </button>
            {undoToken ? (
              <button type="button" onClick={() => undoLastApply()} disabled={disabled}>
                Undo last apply
              </button>
            ) : null}
          </div>
          <div className="ref-segment-hint">Select a reference above, choose a board range, then apply.</div>

          {segments.length > 0 ? (
            <ul className="ref-segment-list">
              {segments.map((s, i) => (
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
            </ul>
          ) : null}
        </section>

        {note ? <div className="ref-sidebar-note">{note}</div> : null}
      </div>

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
    </aside>
  )
}
