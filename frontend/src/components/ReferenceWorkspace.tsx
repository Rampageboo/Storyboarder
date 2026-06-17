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
import { refSegmentsWithoutOverlap } from '../utils/refSegmentDisplay'
import './ReferenceWorkspace.css'

// A persisted reference segment (loose shape — the backend normalizes it on save/load).
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

export function ReferenceWorkspace() {
  const { project, selectedShotId, setProject, flushDirtyShots, projectActionBusy, reportError } = useProject()
  const [open, setOpen] = useState(true)
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState('')
  const [lightbox, setLightbox] = useState<ReferenceLink | null>(null)
  const importRef = useRef<HTMLInputElement | null>(null)

  // Segment form state.
  const [refId, setRefId] = useState('')
  const [startShot, setStartShot] = useState('')
  const [endShot, setEndShot] = useState('')
  const [startTime, setStartTime] = useState('0')
  // Undo token returned by the most recent apply (video/image applies provide one; 3D does not).
  const [undoToken, setUndoToken] = useState('')

  const links = useMemo(() => project?.settings?.reference_links ?? [], [project?.settings?.reference_links])
  const segments = useMemo(
    () => (project?.settings?.ref_segments ?? []) as unknown as Segment[],
    [project?.settings?.ref_segments],
  )
  const shots = project?.shots ?? []

  // Default the reference select to the first available asset.
  useEffect(() => {
    setRefId((cur) => (cur && links.some((l) => l.id === cur) ? cur : links[0]?.id ?? ''))
  }, [links])

  // Default the segment range to the selected shot.
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
        setNote(`Imported reference: ${file.name}`)
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

  // Define the segment (persist via settings) then apply it to the board range by reference type.
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
        const existing = refSegmentsWithoutOverlap(segments, seg, shots)
        await updateSettings({ ref_segments: [...existing, seg], active_ref_segment_id: segId })
        const body: ApplyRefSegmentRequest = { anchor_shot_id: startShot, end_shot_id: endShot, segment_id: segId }
        let payload: ProjectPayload
        if (selectedRef.type === 'image') payload = await applyRefSegmentImage(body)
        else if (selectedRef.type === 'model') payload = await applyRefSegment3d({ ...body, camera_name: '' })
        else payload = await applyRefSegment(body)
        setProject(payload)
        const result = payload as unknown as { board_count?: number; undo_token?: string }
        setUndoToken(typeof result.undo_token === 'string' ? result.undo_token : '')
        setNote(`Applied ${selectedRef.type} reference to ${result.board_count ?? '?'} board(s).`)
      } catch (error) {
        reportError(error)
      } finally {
        setBusy(false)
      }
    })()
  }

  // Undo the last reference apply (reverts the affected boards' previews).
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
    <section className={`refws ${open ? 'is-open' : ''}`}>
      <button type="button" className="refws-toggle" onClick={() => setOpen((v) => !v)}>
        <span>Reference library &amp; segments</span>
        <span className="refws-toggle-icon">{open ? '▾' : '▸'}</span>
      </button>

      {open ? (
        <div className="refws-body">
          <div className="refws-section">
            <div className="refws-section-head">
              <span className="refws-section-title">Reference library ({links.length})</span>
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
              <div className="refws-empty">No project references yet. Import an image, video, or GLB model.</div>
            ) : (
              <ul className="refws-list">
                {links.map((link) => (
                  <li className="refws-item" key={link.id}>
                    <span className={`refws-type refws-type-${link.type}`}>{link.type}</span>
                    <button
                      type="button"
                      className="refws-name"
                      title={link.path}
                      onClick={() => (link.type === 'model' ? undefined : setLightbox(link))}
                      disabled={link.type === 'model'}
                    >
                      {link.title || fileName(link.path)}
                    </button>
                    <button
                      type="button"
                      className="refws-remove"
                      onClick={() => removeLink(link.id, link.title || fileName(link.path))}
                      disabled={disabled}
                      aria-label="Remove reference"
                    >
                      ×
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div className="refws-section">
            <div className="refws-section-title">Reference segment</div>
            <div className="refws-fields">
              <label className="refws-field">
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
              <label className="refws-field">
                <span>Start shot</span>
                <select value={startShot} onChange={(e) => setStartShot(e.target.value)}>
                  {shots.map((s) => (
                    <option key={s.shot_id} value={s.shot_id}>
                      {shotLabel(s.shot_id)}
                    </option>
                  ))}
                </select>
              </label>
              <label className="refws-field">
                <span>End shot</span>
                <select value={endShot} onChange={(e) => setEndShot(e.target.value)}>
                  {shots.map((s) => (
                    <option key={s.shot_id} value={s.shot_id}>
                      {shotLabel(s.shot_id)}
                    </option>
                  ))}
                </select>
              </label>
              <label className="refws-field">
                <span>Start time (s)</span>
                <input
                  type="number"
                  min="0"
                  step="0.1"
                  value={startTime}
                  onChange={(e) => setStartTime(e.target.value)}
                  disabled={selectedRef?.type !== 'video'}
                  title={selectedRef?.type === 'video' ? 'Offset into the reference video' : 'Only used for video references'}
                />
              </label>
            </div>
            <div className="refws-actions">
              <button
                type="button"
                className="primary"
                onClick={() => applySegment()}
                disabled={disabled || !links.length || shots.length === 0}
              >
                Apply to shot range
              </button>
              {undoToken ? (
                <button
                  type="button"
                  onClick={() => undoLastApply()}
                  disabled={disabled}
                  title="Revert the boards changed by the last reference apply"
                >
                  Undo last reference apply
                </button>
              ) : null}
            </div>
            <div className="refws-hint">End is derived from the selected shot range duration.</div>

            {segments.length > 0 ? (
              <ul className="refws-list">
                {segments.map((s, i) => (
                  <li className="refws-item" key={s.id || `${s.anchor_shot_id}-${s.end_shot_id}-${i}`}>
                    <span className={`refws-type refws-type-${s.source_type}`}>{s.source_type || '—'}</span>
                    <span className="refws-seg-range">
                      {shotLabel(s.anchor_shot_id || '')} → {shotLabel(s.end_shot_id || '')}
                    </span>
                    {s.id ? (
                      <button
                        type="button"
                        className="refws-remove"
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
          </div>

          {note ? <div className="refws-note">{note}</div> : null}
        </div>
      ) : null}

      {lightbox ? (
        <div className="refws-lightbox" role="dialog" aria-modal="true" onClick={() => setLightbox(null)}>
          {lightbox.type === 'video' ? (
            <video src={projectFileUrl(lightbox.path)} controls onClick={(e) => e.stopPropagation()} />
          ) : (
            <img
              src={projectFileUrl(lightbox.path)}
              alt={lightbox.title || fileName(lightbox.path)}
              onClick={(e) => e.stopPropagation()}
            />
          )}
          <div className="refws-lightbox-path">{lightbox.path}</div>
          <button type="button" className="refws-lightbox-close" onClick={() => setLightbox(null)} aria-label="Close preview">
            ×
          </button>
        </div>
      ) : null}
    </section>
  )
}
