import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import {
  applyRefSegment,
  applyRefSegmentImage,
  applyRefSegmentModelCaptures,
  projectFileUrl,
  restoreRefApply,
  updateSettings,
  uploadProjectReference,
  type ApplyRefSegmentRequest,
} from '../api'
import type { ProjectPayload, ReferenceLink } from '../types'
import { useProject } from '../state/useProject'
import { shotDisplayLabel } from '../utils/shotDisplay'
import { findRefSegment, refSegmentsWithoutOverlap } from '../utils/refSegmentDisplay'
import { describeScene3dView, resolveScene3dReferenceView } from '../utils/scene3dView'
import { applyModelCaptures } from '../scene3d/applyModelCaptures'
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

function nextFrame(): Promise<void> {
  return new Promise((resolve) => requestAnimationFrame(() => resolve()))
}

async function waitFrames(count = 2): Promise<void> {
  for (let i = 0; i < count; i += 1) await nextFrame()
}

function renderBodyPortal(node: ReactNode) {
  return createPortal(node, document.body)
}

function RefThumb({ link, selected }: { link: ReferenceLink; selected: boolean }) {
  const linkKey = `${link.id}:${link.path}`
  const [prevLinkKey, setPrevLinkKey] = useState(linkKey)
  const [failed, setFailed] = useState(false)
  const url = projectFileUrl(link.path)
  if (linkKey !== prevLinkKey) {
    setPrevLinkKey(linkKey)
    setFailed(false)
  }
  return (
    <div className={`ref-assign-ref-thumb ${selected ? 'is-selected' : ''}`}>
      {link.type === 'model' ? (
        <ReferenceModelPreview path={link.path} label={link.title || fileName(link.path)} />
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
    recordRefApply,
    deleteRefSegmentUndoable,
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
  const shots = useMemo(() => project?.shots ?? [], [project?.shots])
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

  // Seed form state when entering inspect mode for a segment.
  const inspectKey = isInspectMode ? (inspectSegment?.id ?? '') : ''
  const [prevInspectKey, setPrevInspectKey] = useState(inspectKey)
  if (inspectKey !== prevInspectKey) {
    setPrevInspectKey(inspectKey)
    if (isInspectMode && inspectSegment) {
      const ref = inspectSegment.reference_id
        ? String(inspectSegment.reference_id)
        : links.find((l) => l.path === inspectSegment.reference_path)?.id ?? ''
      if (ref) setRefId(ref)
      setFormAnchorShotId(String(inspectSegment.anchor_shot_id || ''))
      setFormEndShotId(String(inspectSegment.end_shot_id || ''))
      setFitMode(normalizeFitMode(inspectSegment.fit_mode))
      const start = Number(inspectSegment.video_start)
      setSegmentStart(Number.isFinite(start) && start > 0 ? start : 0)
      setPreviewFailed(false)
      setPlayheadTime(0)
      setMediaDuration(0)
    }
  }

  // Normalize refId to a valid link when the library or mode changes.
  const linksKey = links.map((l) => l.id).join(',')
  const [prevLinksKey, setPrevLinksKey] = useState(linksKey)
  const [prevIsInspectMode, setPrevIsInspectMode] = useState(isInspectMode)
  if (linksKey !== prevLinksKey || isInspectMode !== prevIsInspectMode) {
    setPrevLinksKey(linksKey)
    setPrevIsInspectMode(isInspectMode)
    if (!isInspectMode) {
      setRefId((cur) => (cur && links.some((l) => l.id === cur) ? cur : links[0]?.id ?? ''))
    }
  }

  // Reset preview state when the selected reference or mode changes.
  const refModeKey = `${refId}:${isInspectMode ? '1' : '0'}`
  const [prevRefModeKey, setPrevRefModeKey] = useState(refModeKey)
  if (refModeKey !== prevRefModeKey) {
    setPrevRefModeKey(refModeKey)
    setPreviewFailed(false)
    if (!isInspectMode) {
      setFitMode('fit')
      setSegmentStart(0)
      setMediaDuration(0)
      setPlayheadTime(0)
    }
  }

  useEffect(() => {
    if (!toast) return
    const t = window.setTimeout(() => setToast(''), 3200)
    return () => window.clearTimeout(t)
  }, [toast])

  if (!project) {
    return toast ? renderBodyPortal(<div className="ref-assign-toast" role="status">{toast}</div>) : null
  }

  const disabled = busy || projectActionBusy
  const previewUrl = selectedRef ? projectFileUrl(selectedRef.path) : ''
  const previewLabel = selectedRef ? selectedRef.title || fileName(selectedRef.path) : 'No reference selected'
  const boardLabel = lo === hi ? `#${lo + 1}` : `#${lo + 1}–#${hi + 1}`
  const objectFit = fitModeToObjectFit(fitMode)

  // Practical max for the source-time slider.
  // For video: use loaded duration when available, fall back to 60 s.
  // For model: use loaded duration when available, fall back to 10 s (typical animation).
  const sliderMax =
    refMode === 'video' ? (mediaDuration > 0 ? mediaDuration : 60) :
    refMode === 'model' ? (mediaDuration > 0 ? mediaDuration : 10) :
    0

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

  async function buildModelRequest(body: ApplyRefSegmentRequest): Promise<ApplyRefSegmentRequest> {
    if (!project) throw new Error('No project loaded.')
    if (!modelRef.current) throw new Error('3D preview is not ready yet.')
    if (lo < 0 || hi < 0) throw new Error('Select a valid board range first.')
    const width = Math.max(1, Math.floor(Number(project.settings?.canvas_width) || 1920))
    const height = Math.max(1, Math.floor(Number(project.settings?.canvas_height) || 1080))
    const animStart = clampStart(segmentStart, mediaDuration, durationSec, refMode)
    const animSpan = Math.max(0.001, durationSec)
    const captures = await applyModelCaptures({
      shots,
      lo,
      hi,
      boardCount,
      durationSec,
      animStart,
      animSpan,
      view: scene3dView,
      width,
      height,
      captureFrame: (options) => modelRef.current!.captureFrame(options),
      onProgress: setProgress,
    })
    setProgress('Finalizing 3D apply…')
    await nextFrame()
    return {
      ...body,
      camera_name: scene3dView?.mode === 'scene_camera' ? scene3dView.camera_name || '' : '',
      captures,
    }
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
    const refType = selectedRef.type
    const wasInspect = isInspectMode
    setBusy(true)
    setProgress('')
    void (async () => {
      try {
        await flushDirtyShots()
        const existing = refSegmentsWithoutOverlap(segments, seg, shots)
        const body: ApplyRefSegmentRequest = { anchor_shot_id: startShot, end_shot_id: endShot, segment_id: segId }
        // Render model captures once so redo can re-send them without the 3D preview.
        const bakeRequest: ApplyRefSegmentRequest = refType === 'model' ? await buildModelRequest(body) : body
        const runBake = async (): Promise<ProjectPayload> => {
          await updateSettings({ ref_segments: [...existing, seg], active_ref_segment_id: segId })
          if (refType === 'image') return applyRefSegmentImage(bakeRequest)
          if (refType === 'model') return applyRefSegmentModelCaptures(bakeRequest)
          return applyRefSegment(bakeRequest)
        }
        const payload = await runBake()
        const result = payload as unknown as { board_count?: number; undo_token?: string }
        const count = result.board_count ?? boardCount
        const token = typeof result.undo_token === 'string' ? result.undo_token : ''
        setRefApplyUndoToken(token || null)
        recordRefApply({ label: wasInspect ? 'Replace reference' : 'Apply reference', undoToken: token, redo: runBake })
        setProgress('Refreshing boards…')
        setProject(payload)
        await waitFrames(2)
        close()
        setToast(`${wasInspect ? 'Reapplied' : 'Applied'} to ${count} board${count === 1 ? '' : 's'}`)
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
        await deleteRefSegmentUndoable(id)
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

  const toastNode = toast ? <div className="ref-assign-toast" role="status">{toast}</div> : null

  if (!open) {
    return toastNode ? renderBodyPortal(toastNode) : null
  }

  return renderBodyPortal(
    <>
      <div className="ref-assign-backdrop" onClick={busy ? undefined : close} aria-hidden="true" />
      <div className={`ref-assign-modal ref-assign-modal--${refMode}`} role="dialog" aria-modal="true" aria-label="Assign reference to board range">
        {progress ? (
          <div className="ref-assign-modal-overlay" aria-live="polite">
            {progress}
          </div>
        ) : null}
        <div className="ref-assign-modal-header">
          <h3>{isInspectMode ? 'Inspect reference segment' : 'Reference segment'}</h3>
          <button type="button" className="ref-assign-close" onClick={close} disabled={busy} aria-label="Cancel">×</button>
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
            </div>
            <div className="ref-assign-fit-mode" role="group" aria-label="Reference fit"><span className="ref-assign-fit-label">Fit</span>{FIT_MODES.map((mode) => <button key={mode} type="button" className={`ref-assign-fit-btn ${fitMode === mode ? 'is-active' : ''}`} onClick={() => setFitMode(mode)} disabled={disabled}>{mode === 'fit' ? 'Fit' : mode === 'fill' ? 'Fill' : 'Stretch'}</button>)}</div>
            <section className="ref-assign-segment-box">
              <div className="ref-assign-segment-toolbar"><span className="ref-assign-section-label">Board segment</span><div className="ref-assign-board-picks"><select value={startShot} onChange={(e) => setStart(e.target.value || null)} disabled={disabled}>{shots.map((s) => <option key={s.shot_id} value={s.shot_id}>{shotLabel(s.shot_id)}</option>)}</select><span>→</span><select value={endShot} onChange={(e) => setEnd(e.target.value || null)} disabled={disabled}>{shots.map((s) => <option key={s.shot_id} value={s.shot_id}>{shotLabel(s.shot_id)}</option>)}</select></div><button type="button" className="ref-assign-reset-start" onClick={() => setSegmentStart(0)} disabled={disabled || refMode === 'image' || segmentStart <= 0}>Reset start</button><button type="button" className="ref-assign-apply" onClick={apply} disabled={disabled || !links.length || shots.length === 0}>{isInspectMode ? 'Reapply to boards' : 'Apply to boards'}</button>{isInspectMode ? <button type="button" className="ref-assign-delete" onClick={deleteSegment} disabled={disabled}>Delete segment</button> : null}</div>
              {(refMode === 'video' || refMode === 'model') ? (
                <div className="ref-assign-source-time">
                  <label className="ref-assign-source-time-label">
                    <span>{refMode === 'model' ? 'Animation start' : 'Source start'}</span>
                    <span className="ref-assign-source-time-value">{segmentStart.toFixed(1)} s</span>
                  </label>
                  <input
                    type="range"
                    className="ref-assign-source-time-slider"
                    min={0}
                    max={sliderMax}
                    step={0.1}
                    value={segmentStart}
                    onChange={(e) => {
                      const val = Number(e.target.value)
                      setSegmentStart(val)
                      // Seek the video preview so the user can see that frame; no reapply.
                      if (videoRef.current && refMode === 'video') {
                        videoRef.current.currentTime = val
                      }
                    }}
                    disabled={disabled}
                    aria-label={refMode === 'model' ? 'Animation start time in seconds' : 'Source start time in seconds'}
                  />
                </div>
              ) : refMode === 'image' ? (
                <p className="ref-assign-source-time-note">Image references do not use source time.</p>
              ) : null}
              <div className="ref-assign-segment-summary"><span>{refMode === 'model' ? `3D segment: ${formatClock(durationSec)} · anim ${formatClock(segmentStart)} · boards ${boardLabel}` : `Reference segment: ${durationSec.toFixed(1)}s · boards ${boardLabel}`}</span><span>{refMode === 'video' ? `Playhead: ${formatClock(playheadTime)}` : `Fit: ${fitMode}`}</span></div>
            </section>
            <div className="ref-assign-footer"><button type="button" onClick={close} disabled={disabled}>{isInspectMode ? 'Close' : 'Cancel / clear range'}</button>{isInspectMode ? <button type="button" className="primary" onClick={apply} disabled={disabled || !links.length}>Reapply</button> : null}{refApplyUndoToken ? <button type="button" onClick={undo} disabled={disabled}>Undo last apply</button> : null}</div>
          </main>
        </div>
      </div>
      {toastNode}
    </>,
  )
}
