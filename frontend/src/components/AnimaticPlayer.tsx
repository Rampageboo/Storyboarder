import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties } from 'react'
import type { Shot } from '../types'
import { useProject } from '../state/useProject'
import { exportAnimatic, openExport } from '../api/export'
import { buildTimeline, frameTimecode, timelineEntryAt } from '../utils/animaticTimeline'
import { shotDisplayLabel } from '../utils/shotDisplay'
import { shotDisplayVersion, shotHasBoardBackground, shotHasCodexLayer, shotShouldOverlayPreview } from '../utils/shotPreview'
import { ShotThumb } from './ShotThumb'
import './AnimaticPlayer.css'

export function AnimaticPlayer({ shots, routeId, selectedId, active, onSelect }: {
  shots: Shot[]; routeId: string; selectedId: string | null; active: boolean; onSelect: (id: string, draw?: boolean) => void
}) {
  const { project, getDraft, editShotField, flushDirtyShots, runProjectMutation, projectActionBusy, drawingActive, lastError, reportError, visualEpoch } = useProject()
  const [fps, setFps] = useState(24)
  const [speed, setSpeed] = useState(1)
  const [loop, setLoop] = useState(false)
  const [captions, setCaptions] = useState(true)
  const [safeGuide, setSafeGuide] = useState(false)
  const [frame, setFrame] = useState(() => buildTimeline(shots.map(shot => ({ ...shot,
    duration_seconds: getDraft(shot.shot_id)?.duration_seconds ?? shot.duration_seconds })), 24)
    .entries.find(item => item.shot.shot_id === selectedId)?.start ?? 0)
  const [playing, setPlaying] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [exported, setExported] = useState<{ route_id: string; path: string } | null>(null)
  const [framesText, setFramesText] = useState<string | null>(null)
  const [lastSelection, setLastSelection] = useState(selectedId)
  const effectiveShots = shots.map(shot => ({ ...shot, duration_seconds: getDraft(shot.shot_id)?.duration_seconds ?? shot.duration_seconds }))
  const timeline = buildTimeline(effectiveShots, fps)
  const currentFrame = Math.max(0, Math.min(frame, timeline.frames - 1))
  const entry = timelineEntryAt(timeline.entries, currentFrame)
  const shot = entry?.shot
  const disabled = projectActionBusy || drawingActive || exporting
  if (playing && (!active || disabled || lastError)) setPlaying(false)
  if (lastSelection !== selectedId) {
    setLastSelection(selectedId)
    if (selectedId !== shot?.shot_id) {
      setPlaying(false); setFrame(timeline.entries.find(item => item.shot.shot_id === selectedId)?.start ?? 0); setFramesText(null)
    }
  }
  const frameRef = useRef(currentFrame)
  useLayoutEffect(() => { frameRef.current = currentFrame })
  useEffect(() => {
    if (!playing || timeline.frames === 0) return
    let request = 0
    const origin = performance.now(), start = frameRef.current
    const tick = (now: number) => {
      const next = start + Math.floor((now - origin) * fps * speed / 1000)
      if (!loop && next >= timeline.frames) { setFrame(timeline.frames - 1); setPlaying(false); return }
      setFrame(loop ? next % timeline.frames : next)
      request = requestAnimationFrame(tick)
    }
    request = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(request)
  }, [playing, fps, speed, loop, timeline.frames])
  const seek = (next: number) => { setPlaying(false); setFrame(Math.max(0, Math.min(timeline.frames - 1, next))); setFramesText(null) }
  const togglePlayback = () => {
    if (disabled || !timeline.frames || !active) return
    if (!playing && currentFrame >= timeline.frames - 1) setFrame(0)
    setPlaying(value => !value)
  }
  useEffect(() => {
    if (!active) return
    const onKey = (event: KeyboardEvent) => {
      if (event.defaultPrevented || disabled || event.ctrlKey || event.metaKey || event.altKey || (event.target instanceof HTMLElement &&
          (event.target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(event.target.tagName)))) return
      if (event.code === 'Space') { event.preventDefault(); togglePlayback() }
      else if (event.key === ',' || event.key === '.') { event.preventDefault(); seek(currentFrame + (event.key === ',' ? -1 : 1)) }
      else if (event.key === 'Home') { event.preventDefault(); seek(0) }
      else if (event.key === 'End') { event.preventDefault(); seek(timeline.frames - 1) }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })
  const saveFrames = (value: number) => {
    setFramesText(null)
    if (shot && entry && value !== entry.frames && Number.isInteger(value) && value >= 1 && value <= fps * 3600) {
      seek(entry.start); editShotField(shot.shot_id, 'duration_seconds', value / fps)
      // Let React commit the new draft before the existing flusher reads its refs.
      requestAnimationFrame(() => { void flushDirtyShots().catch(reportError) })
    }
  }
  const exportRoute = async () => {
    setPlaying(false); setExporting(true)
    try {
      await runProjectMutation(async () => {
        await flushDirtyShots()
        const result = await exportAnimatic({ fps, captions, route_id: routeId })
        setExported({ route_id: routeId, path: result.path })
      })
    } catch (error) { reportError(error) } finally { setExporting(false) }
  }
  const aspect = `${project?.settings.canvas_width ?? 1920} / ${project?.settings.canvas_height ?? 1080}`
  return <section className="animatic-player" aria-label="Animatic timeline">
    <div className="animatic-options">
      <label>FPS<select aria-label="Animatic FPS" value={fps} disabled={disabled || playing} onChange={event => {
        const next = Number(event.target.value); setFrame(Math.round(currentFrame * next / fps)); setFps(next); setFramesText(null)
      }}>{[12, 15, 24, 25, 30, 48, 60].map(value => <option key={value}>{value}</option>)}</select></label>
      <label>Speed<select aria-label="Playback speed" value={speed} disabled={disabled} onChange={event => setSpeed(Number(event.target.value))}>
        {[.25, .5, 1, 1.5, 2].map(value => <option key={value} value={value}>{value}×</option>)}</select></label>
      <button type="button" aria-pressed={loop} disabled={disabled} onClick={() => setLoop(value => !value)}>Loop</button>
      <button type="button" aria-pressed={captions} onClick={() => setCaptions(value => !value)}>Dialogue</button>
      <button type="button" aria-pressed={safeGuide} onClick={() => setSafeGuide(value => !value)}>Safe area</button>
      <button type="button" disabled={disabled || !shots.length} onClick={() => { void exportRoute() }}>{exporting ? 'Exporting…' : 'Export route MP4'}</button>
    </div>
    <div className="animatic-screen"><div className="animatic-picture" style={{ aspectRatio: aspect,
      '--animatic-ratio': Number(project?.settings.canvas_width ?? 1920) / Number(project?.settings.canvas_height ?? 1080) } as CSSProperties}>
      {shot ? <ShotThumb shotId={shot.shot_id} version={shotDisplayVersion(shot, visualEpoch, 0)} fullResolution
        hasImage={shotShouldOverlayPreview(shot)} hasBg={shotHasBoardBackground(shot)} hasCodex={shotHasCodexLayer(shot)} /> : <span>No boards in this route</span>}
      {safeGuide ? <div className="animatic-safe-guide" aria-hidden="true" /> : null}
    </div></div>
    <div className="animatic-current"><strong>{shot ? shotDisplayLabel(shot) : 'No board'}</strong>
      <span>{entry ? `${entry.frames} frames · ${(entry.frames / fps).toFixed(3)}s` : ''}</span></div>
    {captions && shot?.dialogue ? <p className="animatic-dialogue">{shot.dialogue}</p> : null}
    {shot?.action_note || shot?.camera_note ? <details className="animatic-shot-notes"><summary>Action & camera notes</summary>
      {shot.action_note ? <p>{shot.action_note}</p> : null}{shot.camera_note ? <p>{shot.camera_note}</p> : null}</details> : null}
    <div className="animatic-transport">
      <button type="button" aria-label="First frame" disabled={disabled || !timeline.frames} onClick={() => seek(0)}>⏮</button>
      <button type="button" aria-label="Previous frame" disabled={disabled || currentFrame <= 0} onClick={() => seek(currentFrame - 1)}>−1f</button>
      <button type="button" aria-label={playing ? 'Pause animatic' : 'Play animatic'} disabled={disabled || !timeline.frames} onClick={togglePlayback}>{playing ? 'Pause' : 'Play'}</button>
      <button type="button" aria-label="Next frame" disabled={disabled || currentFrame >= timeline.frames - 1} onClick={() => seek(currentFrame + 1)}>+1f</button>
      <output aria-label="Animatic timecode">{frameTimecode(currentFrame, fps)} / {frameTimecode(timeline.frames, fps)}</output>
      <button type="button" disabled={disabled || !shot} onClick={() => { if (shot) { setPlaying(false); onSelect(shot.shot_id, true) } }}>Edit board</button>
    </div>
    <input className="animatic-scrubber" type="range" aria-label="Animatic playhead" min={0} max={Math.max(0, timeline.frames - 1)} step={1}
      value={currentFrame} disabled={disabled || !timeline.frames} onChange={event => seek(Number(event.target.value))} />
    <div className="animatic-track-scroll"><div className="animatic-track" style={{ minWidth: `${Math.max(100, timeline.frames / fps * 28)}px` }}>
      {timeline.entries.map(item => <button type="button" key={item.shot.shot_id} className={entry === item ? 'is-current' : ''}
        aria-label={`Timeline ${shotDisplayLabel(item.shot)}: ${item.frames} frames`} disabled={disabled} title={`${shotDisplayLabel(item.shot)} · ${item.frames}f`}
        style={{ flexGrow: item.frames }} onClick={() => seek(item.start)}>
        <span>{shotDisplayLabel(item.shot)}</span><small>{item.frames}f</small></button>)}
      {timeline.frames ? <i className="animatic-playhead" style={{ left: `${currentFrame / timeline.frames * 100}%` }} /> : null}
    </div></div>
    <div className="animatic-timing-edit"><label>Current board frames<input aria-label="Current board frames" type="number" min={1} max={fps * 3600}
      value={framesText ?? entry?.frames ?? 1} disabled={disabled || !shot || playing} onFocus={() => setFramesText(String(entry?.frames ?? 1))}
      onChange={event => setFramesText(event.target.value)} onBlur={event => saveFrames(event.currentTarget.valueAsNumber)} onKeyDown={event => {
        if (event.key === 'Enter') event.currentTarget.blur()
        if (event.key === 'Escape') { setFramesText(null); event.currentTarget.value = String(entry?.frames ?? 1); event.currentTarget.blur() }
      }} /></label><span>Space: play / pause · , / .: frame step · Time changes are shared by every route using this board.</span></div>
    {exported ? <div className="animatic-export-result" role="status">Saved: {exported.path}
      <button type="button" disabled={disabled} onClick={() => { void openExport('animatic', { route_id: exported.route_id }).catch(reportError) }}>Open MP4</button></div> : null}
  </section>
}
