import { useCallback, useEffect, useState } from 'react'
import { FilmSlate, Trash } from '@phosphor-icons/react'
import {
  createVideoTake,
  deleteVideoTake,
  getVideoPromptDraft,
  listVideoTakes,
  videoTakeUrl,
  VIDEO_TAKE_ACTIVE,
  type VideoTake,
} from '../api'
import { useProject } from '../state/useProject'
import type { Shot } from '../types'
import { shotDisplayLabel } from '../utils/shotDisplay'

const STATUS_LABEL: Record<string, string> = {
  queued: 'Queued',
  uploading: 'Uploading the board frame…',
  running: 'Generating on Comfy Cloud…',
  downloading: 'Downloading the video…',
  succeeded: 'Ready',
  failed: 'Failed',
}

function elapsed(take: VideoTake): string {
  const start = Date.parse(take.created_at)
  const end = Date.parse(take.updated_at || take.created_at)
  if (!Number.isFinite(start) || !Number.isFinite(end)) return ''
  const seconds = Math.max(0, Math.round((end - start) / 1000))
  return seconds >= 60 ? `${Math.floor(seconds / 60)}m ${seconds % 60}s` : `${seconds}s`
}

/** Board → short video on Comfy Cloud. Takes are listed newest first; the board itself is never changed. */
export function VideoTakes({ shot, onError }: { shot: Shot; onError: (error: unknown) => void }) {
  const [prompt, setPrompt] = useState('')
  const [negative, setNegative] = useState('')
  const [seconds, setSeconds] = useState(3)
  const [takes, setTakes] = useState<VideoTake[]>([])
  const [configured, setConfigured] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [message, setMessage] = useState('')
  const [endShotId, setEndShotId] = useState('')
  const { activeRouteShots, project } = useProject()
  const route = activeRouteShots.length ? activeRouteShots : project?.shots ?? []
  const routeIndex = route.findIndex((item) => item.shot_id === shot.shot_id)
  const nextShot = routeIndex >= 0 ? route[routeIndex + 1] : undefined
  const hasImage = (item: Shot) => Boolean(item.preview_image_path || item.image_path)
  const endChoices = route.filter((item) => item.shot_id !== shot.shot_id && hasImage(item))
  const endShot = endChoices.find((item) => item.shot_id === endShotId)
  const boardLabel = (item: Shot) => `${String(route.indexOf(item) + 1).padStart(2, '0')} · ${shotDisplayLabel(item)}`
  const labelFor = (id: string) => {
    const item = route.find((candidate) => candidate.shot_id === id) ?? project?.shots.find((candidate) => candidate.shot_id === id)
    return item ? boardLabel(item) : 'another board'
  }

  const refresh = useCallback(async () => {
    const result = await listVideoTakes(shot.shot_id)
    setTakes(result.takes)
    setConfigured(result.configured)
  }, [shot.shot_id])

  useEffect(() => {
    let cancelled = false
    getVideoPromptDraft(shot.shot_id)
      .then((draft) => {
        if (cancelled) return
        setPrompt(draft.prompt)
        setNegative(draft.negative_prompt)
        setSeconds(draft.seconds)
      })
      .catch(onError)
    listVideoTakes(shot.shot_id)
      .then((result) => {
        if (cancelled) return
        setTakes(result.takes)
        setConfigured(result.configured)
      })
      .catch(onError)
    return () => { cancelled = true }
  }, [shot.shot_id, onError])

  const active = takes.some((take) => VIDEO_TAKE_ACTIVE.has(take.status))
  useEffect(() => {
    if (!active) return
    const timer = window.setInterval(() => { refresh().catch(() => {}) }, 3000)
    return () => window.clearInterval(timer)
  }, [active, refresh])

  const generate = async () => {
    setSubmitting(true)
    setMessage('')
    try {
      await createVideoTake(shot.shot_id, { prompt, negative_prompt: negative, seconds, end_shot_id: endShot?.shot_id ?? '' })
      await refresh()
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error))
    } finally {
      setSubmitting(false)
    }
  }

  const remove = async (take: VideoTake) => {
    if (!window.confirm('Delete this video take?')) return
    try {
      await deleteVideoTake(take.take_id)
      await refresh()
    } catch (error) {
      onError(error)
    }
  }

  return (
    <div className="inspector-body video-takes">
      {!configured ? (
        <div className="notice is-warn">Add your Comfy Cloud API key in Settings (gear icon, top right) to generate video.</div>
      ) : null}
      <label className="field">
        <span className="field-label-row"><span className="field-label">Motion prompt</span><span className="field-flag">Wan 2.2 · image to video</span></span>
        <textarea rows={5} value={prompt} onChange={(event) => setPrompt(event.target.value)}
          placeholder="What moves in this shot: action, camera movement, timing." />
      </label>
      <details className="video-takes-negative">
        <summary>Negative prompt</summary>
        <textarea rows={2} value={negative} onChange={(event) => setNegative(event.target.value)} aria-label="Negative prompt" />
      </details>
      <div className="field">
        <span className="field-label">End frame</span>
        <div className="video-end-row">
          <select value={endShot ? endShot.shot_id : ''} onChange={(event) => setEndShotId(event.target.value)} aria-label="End frame">
            <option value="">None — free motion from this board</option>
            {endChoices.map((item) => (
              <option key={item.shot_id} value={item.shot_id}>
                {boardLabel(item)}{item === nextShot ? '  (next board)' : ''}
              </option>
            ))}
          </select>
          {endShot ? (
            <img className="video-end-thumb" alt="" src={`/api/shots/${encodeURIComponent(endShot.shot_id)}/image?t=${encodeURIComponent(String(endShot.preview_disk_mtime ?? ''))}`} />
          ) : null}
        </div>
        <span className="inspector-intro">
          {endShot
            ? 'The video starts on this board and arrives exactly on the chosen board. Use it for continuous moves, not for cuts.'
            : nextShot && !hasImage(nextShot) ? 'The next board has no image yet, so it cannot be an end frame.' : 'Optional: end on another board to connect a continuous move.'}
        </span>
      </div>
      <div className="video-takes-row">
        <label className="field">
          <span className="field-label">Length</span>
          <span className="input-suffix">
            <input type="number" min={1} max={5} step={0.5} value={seconds}
              onChange={(event) => setSeconds(Number(event.target.value))} />
            <span>sec</span>
          </span>
        </label>
        <button type="button" className="primary" onClick={() => void generate()}
          disabled={submitting || !configured || !prompt.trim()}>
          <FilmSlate size={16} />{submitting ? 'Submitting…' : 'Generate video'}
        </button>
      </div>
      <p className="inspector-intro">Uses this board as the first frame. 1–5 s at 16 fps, 832 px on the long edge. Billed to your Comfy Cloud credits.</p>
      {message ? <div className="notice is-danger" role="alert">{message}</div> : null}

      {takes.length ? <span className="section-label">Takes</span> : null}
      <ul className="video-take-list">
        {takes.map((take) => (
          <li key={take.take_id} className={'video-take is-' + take.status}>
            {take.status === 'succeeded' ? (
              <video className="video-take-player" src={videoTakeUrl(take)} controls loop playsInline preload="metadata" />
            ) : (
              <div className="video-take-pending">
                {VIDEO_TAKE_ACTIVE.has(take.status) ? <span className="video-take-spinner" aria-hidden="true" /> : null}
                <span>{STATUS_LABEL[take.status] ?? take.status}</span>
              </div>
            )}
            <div className="video-take-meta">
              <span>{take.seconds}s · {take.width}×{take.height}{take.end_shot_id ? ` · → ${labelFor(take.end_shot_id)}` : ''}{elapsed(take) ? ` · ${elapsed(take)}` : ''}</span>
              {!VIDEO_TAKE_ACTIVE.has(take.status) ? (
                <button type="button" className="ghost icon-btn" aria-label="Delete take" title="Delete take" onClick={() => void remove(take)}>
                  <Trash size={14} />
                </button>
              ) : null}
            </div>
            {take.status === 'failed' && take.error ? <p className="video-take-error">{take.error}</p> : null}
            <p className="video-take-prompt" title={take.prompt}>{take.prompt}</p>
          </li>
        ))}
      </ul>
    </div>
  )
}
