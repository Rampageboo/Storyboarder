import { useEffect, useMemo, useRef, useState } from 'react'
import {
  applyRefSegment,
  applyRefSegment3d,
  applyRefSegmentImage,
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
import { findRefSegment, refSegmentsWithoutOverlap } from '../utils/refSegmentDisplay'
import { describeScene3dView, resolveScene3dReferenceView } from '../utils/scene3dView'
import { ReferenceModelPreview, type ReferenceModelPreviewHandle } from './ReferenceModelPreview'
import './ReferenceAssignmentPopover.css'

type Segment = {
  id?: string
  anchor_shot_id?: string
  end_shot_id?: string
  source_type?: string
  reference_id?: string
  reference_path?: string
  video_start?: number
  fit_mode?: string
  [key: string]: unknown
}

type FitMode = 'fit' | 'fill' | 'stretch'
const FIT_MODES: FitMode[] = ['fit', 'fill', 'stretch']

function newSegmentId(): string {
  const c = globalThis.crypto as Crypto | undefined
  if (c && typeof c.randomUUID === 'function') return c.randomUUID().replace(/-/g, '')
  return `seg_${Date.now().toString(36)}${Math.floor(Math.random() * 1e6).toString(36)}`
}

function fileName(path: string) {
  return path.split(/[/\\]/).pop() || path
}

function formatClock(seconds: number) {
  const ms = Math.max(0, Math.round((Number(seconds) || 0) * 1000))
  const m = Math.floor(ms / 60000)
  const s = Math.floor((ms % 60000) / 1000)
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}.${String(ms % 1000).padStart(3, '0')}`
}

function segmentDurationSeconds(shots: { duration_seconds?: number }[], lo: number, hi: number) {
  let total = 0
  for (let i = lo; i <= hi; i += 1) total += Math.max(0.1, Number(shots[i]?.duration_seconds) || 3)
  return total
}

function normalizeFitMode(value: unknown): FitMode {
  const mode = String(value || 'fit').trim().toLowerCase()
  return FIT_MODES.includes(mode as FitMode) ? (mode as FitMode) : 'fit'
}

function fitModeToObjectFit(mode: FitMode): 'contain' | 'cover' | 'fill' {
  if (mode === 'fill') return 'cover'
  if (mode === 'stretch') return 'fill'
  return 'contain'
}

function clampStart(start: number, mediaDuration: number, boardDuration: number, mode: string) {
  if (mode === 'image') return 0
  if (!mediaDuration || boardDuration >= mediaDuration) return Math.max(0, Number(start) || 0)
  return Math.min(Math.max(0, Number(start) || 0), Math.max(0, mediaDuration - Math.max(0.001, boardDuration)))
}

function RefThumb({ link, selected }: { link: ReferenceLink; selected: boolean }) {
  const [failed, setFailed] = useState(false)
  const url = projectFileUrl(link.path)
  useEffect(() => setFailed(false), [link.id, link.path])
  return (
    <div className={`ref-assign-ref-thumb ${selected ? 'is-selected' : ''}`}>
      {link.type === 'model' ? (
        <ReferenceModelPreview path={link.path} label={link.title || fileName(link.path)} compact />
      ) : failed ? (
        <div className="ref-assign-ref-fallback">{link.type}</div>
      ) : link.type === 'video' ? (
        <video src={url} muted preload="metadata" playsInline onError={() => setFailed(true)} />
      ) : (
        <img src={url} alt="" loading="lazy" onError={() => setFailed(true)} />
      )}
    </div>
  )
}

export function ReferenceAssignmentPopover() {
  const {
    project,
    flushDirtyShots,
    setProject,
    projectActionBusy,
    reportError,
    segmentRange,
    setSegmentAnchor,
    setSegmentEnd,
    activeAppliedSegmentId,
    dismissRefSegmentUi,
    refSegmentInspectOpen,
    closeRefSegmentInspect,
    refApplyUndoToken,
    setRefApplyUndoToken,
  } = useProject()
  const [busy, setBusy] = useState(false)
  const [refId, setRefId] = useState('')
  const [formAnchorShotId, setFormAnchorShotId] = useState('')
  const [formEndShotId, setFormEndShotId] = useState('')
  const [fitMode, setFitMode] = useState<FitMode>('fit')
  const [segmentStart, setSegmentStart] = useState(0)
  const [mediaDuration, setMediaDuration] = useState(0)
  const [playheadTime, setPlayheadTime] = useState(0)
  const [toast, setToast] = useState('')
  const [previewFailed, setPreviewFailed] = useState(false)
  const [progress, setProgress] = useState('')
  const importRef = useRef<HTMLInputElement | null>(null)
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const modelRef = useRef<ReferenceModelPreviewHandle | null>(null)

  const links = useMemo(() => project?.settings?.reference_links ?? [], [project?.settings?.reference_links])
  const segments = useMemo(() => (project?.settings?.ref_segments ?? []) as unknown as Segment[], [project?.settings?.ref_segments])
  const shots = project?.shots ?? []
  const draftComplete = !!(segmentRange.anchorShotId && segmentRange.endShotId)
  const isInspectMode = refSegmentInspectOpen && !!activeAppliedSegmentId && !draftComplete
  const open = draftComplete || isInspectMode
  const inspectSegment = useMemo(() => findRefSegment(segments, activeAppliedSegmentId), [segments, activeAppliedSegmentId])
  const startShot = isInspectMode ? formAnchorShotId : (segmentRange.anchorShotId ?? '')
  const endShot = isInspectMode ? formEndShotId : (segmentRange.endShotId ?? '')
  const anchorIdx = startShot ? shots.findIndex((s) => s.shot_id === startShot) : -1
  const endIdx = endShot ? shots.findIndex((s) => s.shot_id === endShot) : -1
  const lo = anchorIdx >= 0 && endIdx >= 0 ? Math.min(anchorIdx, endIdx) : -1
  const hi = anchorIdx >= 0 && endIdx >= 0 ? Math.max(anchorIdx, endIdx) : -1
  const boardCount = lo >= 0 && hi >= 0 ? hi - lo + 1 : 0
  const durationSec = lo >= 0 && hi >= 0 ? segmentDurationSeconds(shots, lo, hi) : 0
  const selectedRef = useMemo(() => links.find((l) => l.id === refId) ?? null, [links, refId])
  const refMode = selectedRef?.type ?? 'none'
  const anchorShot = useMemo(() => shots.find((s) => s.shot_id === startShot) ?? null, [shots, startShot])
  const scene3dView = useMemo(
    () => (refMode === 'model' ? resolveScene3dReferenceView({ shot: anchorShot, settings: project?.settings ?? null }) : null),
    [refMode, anchorShot, project?.settings],
  )

  useEffect(() => {
    if (!isInspectMode || !inspectSegment) return
    const ref = inspectSegment.reference_id ? String(inspectSegment.reference_id) : links.find((l) => l.path === inspectSegment.reference_path)?.id ?? ''
    if (ref) setRefId(ref)
    setFormAnchorShotId(String(inspectSegment.anchor_shot_id || ''))
    setFormEndShotId(String(inspectSegment.end_shot_id || ''))
    setFitMode(normalizeFitMode(inspectSegment.fit_mode))
    const start = Number(inspectSegment.video_start)
    setSegmentStart(Number.isFinite(start) && start > 0 ? start : 0)
    setPreviewFailed(false)
    setPlayheadTime(0)
    setMediaDuration(0)
  }, [isInspectMode, inspectSegment, links])

  useEffect(() => {
    if (isInspectMode) return
    setRefId((cur) => (cur && links.some((l) => l.id === cur) ? cur : links[0]?.id ?? ''))
  }, [links, isInspectMode])

  useEffect(() => {
    setPreviewFailed(false)
    if (!isInspectMode) {
      setFitMode('fit')
      setSegmentStart(0)
      setMediaDuration(0)
      setPlayheadTime(0)
    }
  }, [refId, isInspectMode])

  useEffect(() => {
    if (!toast) return
    const t = window.setTimeout(() => setToast(''), 3200)
    return () => window.clearTimeout(t)
  }, [toast])

  if (!project || !open) return toast ? <div className="ref-assign-toast">{toast}</div> : null

  const disabled = busy || projectActionBusy
  const previewUrl = selectedRef ? projectFileUrl(selectedRef.path) : ''
  const previewLabel = selectedRef ? selectedRef.title || fileName(selectedRef.path) : 'No reference selected'
  const boardLabel = lo === hi ? `#${lo + 1}` : `#${lo + 1}–#${hi + 1}`
  const objectFit = fitModeToObjectFit(fitMode)

  const close = () => {
    if (isInspectMode) closeRefSegmentInspect()
    else dismissRefSegmentUi()
  }
  const setStart = (id: string | null) => (isInspectMode ? setFormAnchorShotId(id ?? '') : setSegmentAnchor(id))
  const setEnd = (id: string | null) => (isInspectMode ? setFormEndShotId(id ?? '') : setSegmentEnd(id))
  const shotLabel = (id: string) => shotDisplayLabel(shots.find((s) => s.shot_id === id) ?? ({ shot_id: id } as never))

  const importReference = (file: File | undefined) => {
    if (!file) return
    setBusy(true)
    void (async () => {
      try {
        await flushDirtyShots()
        const payload = await uploadProjectReference(file)
        setProject(payload)
        const imported = payload.settings?.reference_links?.find((l) => l.path.includes(file.name))
        if (imported) setRefId(imported.id)
      } catch (error) {
        reportError(error)
      } finally {
        setBusy(false)
      }
    })()
  }

  async function applyModel(body: ApplyRefSegmentRequest): Promise<ProjectPayload> {
    if (!project) throw new Error('No project loaded.')
    if (!modelRef.current) throw new Error('3D preview is not ready yet.')
    if (lo < 0 || hi < 0) throw new Error('Select a valid board range first.')
    const width = Math.max(1, Math.floor(Number(project.settings?.canvas_width) || 1920))
    const height = Math.max(1, Math.floor(Number(project.settings?.canvas_height) || 1080))
    const animStart = clampStart(segmentStart, mediaDuration, durationSec, refMode)
    const animSpan = Math.max(0.001, durationSec)
    let offset = 0
    const captures: NonNullable<ApplyRefSegmentRequest['captures']> = []
    for (let index = lo; index <= hi; index += 1) {
      const shot = shots[index]
      const animationTime = Math.max(0, animStart + (durationSec > 0 ? offset / durationSec : 0) * animSpan)
      setProgress(`Rendering 3D board ${index - lo + 1} / ${boardCount}`)
      const dataUrl = await modelRef.current.captureFrame({ time: animationTime, view: scene3dView, width, height })
      captures.push({ shot_id: shot.shot_id, data_url: dataUrl, animation_time: animationTime })
      offset += Math.max(0.1, Number(shot.duration_seconds) || 3)
    }
    setProgress('Finalizing 3D apply…')
    return applyRefSegment3d({
      ...body,
      camera_name: scene3dView?.mode === 'scene_camera' ? scene3dView.camera_name || '' : '',
      captures,
    })
  }

  const apply = () => {
    if (!selectedRef) return window.alert('Choose a source reference first.')
    if (!startShot || !endShot) return
    const segId = isInspectMode && activeAppliedSegmentId ? activeAppliedSegmentId : newSegmentId()
    const seg: Segment = {
      id: segId,
      anchor_shot_id: startShot,
      end_shot_id: endShot,
      source_type: selectedRef.type,
      reference_id: selectedRef.id,
      reference_path: selectedRef.path,
      video_start: clampStart(segmentStart, mediaDuration, durationSec, refMode),
      fit_mode: fitMode,
    }
    setBusy(true)
    setProgress('')
    void (async () => {
      try {
        await flushDirtyShots()
        const existing = refSegmentsWithoutOverlap(segments, seg, shots)
        await updateSettings({ ref_segments: [...existing, seg], active_ref_segment_id: segId })
        const body: ApplyRefSegmentRequest = { anchor_shot_id: startShot, end_shot_id: endShot, segment_id: segId }
        const payload = selectedRef.type === 'image' ? await applyRefSegmentImage(body) : selectedRef.type === 'model' ? await applyModel(body) : await applyRefSegment(body)
        setProject(payload)
        const result = payload as unknown as { board_count?: number; undo_token?: string }
        const count = result.board_count ?? boardCount
        setRefApplyUndoToken(typeof result.undo_token === 'string' ? result.undo_token : null)
        close()
        setToast(`${isInspectMode ? 'Reapplied' : 'Applied'} to ${count} board${count === 1 ? '' : 's'}`)
      } catch (error) {
        reportError(error)
      } finally {
        setProgress('')
        setBusy(false)
      }
    })()
  }

  const deleteSegment = () => {
    if (!activeAppliedSegmentId) return
    if (!window.confirm('Delete this applied reference segment and clear its generated board backgrounds/previews?')) return
    const id = activeAppliedSegmentId
    dismissRefSegmentUi()
    setBusy(true)
    void (async () => {
      try {
        await flushDirtyShots()
        setProject(await deleteRefSegment(id))
        setToast('Reference segment deleted.')
      } catch (error) {
        reportError(error)
      } finally {
        setBusy(false)
      }
    })()
  }

  const undo = () => {
    if (!refApplyUndoToken) return
    setBusy(true)
    void (async () => {
      try {
        await flushDirtyShots()
        setProject(await restoreRefApply(refApplyUndoToken))
        setRefApplyUndoToken(null)
        setToast('Reference apply undone.')
      } catch (error) {
        reportError(error)
      } finally {
        setBusy(false)
      }
    })()
  }

  return (
    <>
      <div className="ref-assign-backdrop" onClick={close} aria-hidden="true" />
      <div className={`ref-assign-modal ref-assign-modal--${refMode}`} role="dialog" aria-modal="true" aria-label="Assign reference to board range">
        <div className="ref-assign-modal-header">
          <h3>{isInspectMode ? 'Inspect reference segment' : 'Reference segment'}</h3>
          <button type="button" className="ref-assign-close" onClick={close} aria-label="Cancel">×</button>
        </div>
        <div className="ref-assign-layout">
          <aside className="ref-assign-refs" aria-label="References">
            <div className="ref-assign-refs-head"><span>References</span><button type="button" onClick={() => importRef.current?.click()} disabled={disabled}>Import</button></div>
            <input ref={importRef} type="file" accept="image/*,video/*,.glb,.gltf" hidden onChange={(e) => { importReference(e.target.files?.[0] ?? undefined); e.target.value = '' }} />
            <div className="ref-assign-ref-list">
              {links.map((link) => <button key={link.id} type="button" className={`ref-assign-ref-item ${refId === link.id ? 'is-selected' : ''}`} onClick={() => setRefId(link.id)} title={link.path}><RefThumb link={link} selected={refId === link.id} /><span className="ref-assign-ref-name">{link.title || fileName(link.path)}</span><span className="ref-assign-ref-type">{link.type}</span></button>)}
              {links.length === 0 ? <div className="ref-assign-refs-empty">Import images, video, or GLB models.</div> : null}
            </div>
          </aside>
          <main className="ref-assign-main">
            <div className="ref-assign-preview-head"><span className="ref-assign-section-label">{refMode === 'model' ? '3D' : refMode === 'video' ? 'Video' : refMode === 'image' ? 'Image' : 'Reference'} segment</span><span className="ref-assign-preview-meta">{previewLabel}</span></div>
            {refMode === 'model' ? <div className="ref-assign-3d-info"><span className={`ref-assign-3d-view ${scene3dView ? '' : 'is-generic'}`}>3D view: {describeScene3dView(scene3dView)}</span><span className="ref-assign-3d-note">Apply renders every board from the GLB, then the backend stamps metadata/provenance and creates an undo snapshot.</span></div> : null}
            <div className="ref-assign-player" style={{ position: 'relative' }}>
              {!selectedRef ? <div className="ref-assign-player-empty">Select a reference on the left</div> : selectedRef.type === 'model' ? <ReferenceModelPreview ref={modelRef} path={selectedRef.path} label={previewLabel} view={scene3dView} /> : previewFailed ? <div className="ref-assign-player-empty">Preview unavailable</div> : selectedRef.type === 'video' ? <video ref={videoRef} key={selectedRef.id} src={previewUrl} controls preload="metadata" playsInline style={{ objectFit }} onLoadedMetadata={(event) => { const duration = event.currentTarget.duration; if (Number.isFinite(duration) && duration > 0) setMediaDuration(duration) }} onTimeUpdate={(event) => setPlayheadTime(event.currentTarget.currentTime || 0)} onError={() => setPreviewFailed(true)} /> : <img key={selectedRef.id} src={previewUrl} alt={previewLabel} style={{ objectFit }} onError={() => setPreviewFailed(true)} />}
              {progress ? <div className="ref-assign-player-empty" style={{ position: 'absolute', inset: 0, background: 'rgba(0,0,0,0.72)' }}>{progress}</div> : null}
            </div>
            <div className="ref-assign-fit-mode" role="group" aria-label="Reference fit"><span className="ref-assign-fit-label">Fit</span>{FIT_MODES.map((mode) => <button key={mode} type="button" className={`ref-assign-fit-btn ${fitMode === mode ? 'is-active' : ''}`} onClick={() => setFitMode(mode)} disabled={disabled}>{mode === 'fit' ? 'Fit' : mode === 'fill' ? 'Fill' : 'Stretch'}</button>)}</div>
            <section className="ref-assign-segment-box">
              <div className="ref-assign-segment-toolbar"><span className="ref-assign-section-label">Board segment</span><div className="ref-assign-board-picks"><select value={startShot} onChange={(e) => setStart(e.target.value || null)} disabled={disabled}>{shots.map((s) => <option key={s.shot_id} value={s.shot_id}>{shotLabel(s.shot_id)}</option>)}</select><span>→</span><select value={endShot} onChange={(e) => setEnd(e.target.value || null)} disabled={disabled}>{shots.map((s) => <option key={s.shot_id} value={s.shot_id}>{shotLabel(s.shot_id)}</option>)}</select></div><button type="button" className="ref-assign-reset-start" onClick={() => setSegmentStart(0)} disabled={disabled || refMode === 'image' || segmentStart <= 0}>Reset start</button><button type="button" className="ref-assign-apply" onClick={apply} disabled={disabled || !links.length || shots.length === 0}>{isInspectMode ? 'Reapply to boards' : 'Apply to boards'}</button>{isInspectMode ? <button type="button" className="ref-assign-delete" onClick={deleteSegment} disabled={disabled}>Delete segment</button> : null}</div>
              <div className="ref-assign-segment-summary"><span>{refMode === 'model' ? `3D segment: ${formatClock(durationSec)} · anim ${formatClock(segmentStart)} · boards ${boardLabel}` : `Reference segment: ${durationSec.toFixed(1)}s · boards ${boardLabel}`}</span><span>{refMode === 'video' ? `Playhead: ${formatClock(playheadTime)}` : `Fit: ${fitMode}`}</span></div>
            </section>
            <div className="ref-assign-footer"><button type="button" onClick={close} disabled={disabled}>{isInspectMode ? 'Close' : 'Cancel / clear range'}</button>{isInspectMode ? <button type="button" className="primary" onClick={apply} disabled={disabled || !links.length}>Reapply</button> : null}{refApplyUndoToken ? <button type="button" onClick={undo} disabled={disabled}>Undo last apply</button> : null}</div>
          </main>
        </div>
      </div>
      {toast ? <div className="ref-assign-toast">{toast}</div> : null}
    </>
  )
}
