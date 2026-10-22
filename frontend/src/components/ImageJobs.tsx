import { useCallback, useEffect, useState } from 'react'
import { Check, Sparkle, Trash } from '@phosphor-icons/react'
import {
  applyImageJob,
  createImageJob,
  deleteImageJob,
  IMAGE_JOB_ACTIVE,
  IMAGE_JOB_MAX_REFERENCES,
  IMAGE_MODEL_LABEL,
  imageJobOutputUrl,
  listImageJobs,
  previewShotPrompt,
  shotThumbnailUrl,
  type ImageJob,
} from '../api'
import { useProject } from '../state/useProject'
import type { Shot } from '../types'
import { shotDisplayLabel } from '../utils/shotDisplay'

const STATUS_LABEL: Record<string, string> = {
  queued: 'Queued',
  uploading: 'Uploading references…',
  running: 'Generating on Comfy Cloud…',
  downloading: 'Downloading the image…',
  succeeded: 'Ready',
  failed: 'Failed',
}

const hasImage = (item: Shot) => Boolean(item.preview_image_path || item.image_path)

/** Board image on Comfy Cloud: text → image, or other boards as references → image. Outputs are candidates until applied. */
export function ImageJobs({ shot, onError }: { shot: Shot; onError: (error: unknown) => void }) {
  const [prompt, setPrompt] = useState('')
  const [negative, setNegative] = useState('')
  const [seed, setSeed] = useState('')
  const [references, setReferences] = useState<string[]>([])
  const [jobs, setJobs] = useState<ImageJob[]>([])
  const [configured, setConfigured] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [applying, setApplying] = useState('')
  const [message, setMessage] = useState('')
  const { activeRouteShots, project, setProject, flushDirtyShots } = useProject()
  const route = activeRouteShots.length ? activeRouteShots : project?.shots ?? []
  const allShots = project?.shots ?? route
  const boardNumber = (item: Shot) => String(route.indexOf(item) + 1).padStart(2, '0')
  const labelFor = (id: string) => {
    const item = allShots.find((candidate) => candidate.shot_id === id)
    if (!item) return 'a removed board'
    return route.includes(item) ? `${boardNumber(item)} · ${shotDisplayLabel(item)}` : shotDisplayLabel(item)
  }
  const referenceChoices = route.filter((item) => item.shot_id !== shot.shot_id && hasImage(item))
  const chosen = references.filter((id) => referenceChoices.some((item) => item.shot_id === id))
  const mode = chosen.length ? 'ref' : 't2i'

  const refresh = useCallback(async () => {
    const result = await listImageJobs(shot.shot_id)
    setJobs(newestFirst(result.jobs))
    setConfigured(result.configured)
  }, [shot.shot_id])

  useEffect(() => {
    let cancelled = false
    listImageJobs(shot.shot_id)
      .then(async (result) => {
        if (cancelled) return
        const sorted = newestFirst(result.jobs)
        setJobs(sorted)
        setConfigured(result.configured)
        // Start from the last prompt used on this board, else the board's compiled prompt.
        if (sorted[0]) {
          setPrompt(sorted[0].prompt)
          setNegative(sorted[0].negative_prompt)
          return
        }
        const preview = await previewShotPrompt(shot.shot_id)
        if (cancelled) return
        setPrompt(preview.prompt.compiled_prompt)
        setNegative(preview.prompt.negative_prompt)
      })
      .catch(onError)
    return () => { cancelled = true }
  }, [shot.shot_id, onError])

  const active = jobs.some((job) => IMAGE_JOB_ACTIVE.has(job.status))
  useEffect(() => {
    if (!active) return
    const timer = window.setInterval(() => { refresh().catch(() => {}) }, 3000)
    return () => window.clearInterval(timer)
  }, [active, refresh])

  const toggleReference = (id: string) => {
    setReferences((current) => {
      const live = current.filter((item) => referenceChoices.some((choice) => choice.shot_id === item))
      if (live.includes(id)) return live.filter((item) => item !== id)
      return live.length >= IMAGE_JOB_MAX_REFERENCES ? live : [...live, id]
    })
  }

  const seedValue = seed.trim() === '' ? undefined : Number(seed)
  const seedValid = seedValue === undefined || (Number.isInteger(seedValue) && seedValue >= 0)

  const generate = async () => {
    setSubmitting(true)
    setMessage('')
    try {
      await createImageJob(shot.shot_id, {
        prompt,
        negative_prompt: negative,
        references: chosen,
        ...(seedValue !== undefined ? { seed: seedValue } : {}),
      })
      await refresh()
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error))
    } finally {
      setSubmitting(false)
    }
  }

  const apply = async (job: ImageJob, index: number) => {
    if (hasImage(shot) && !window.confirm('Replace this board’s image with the generated one?')) return
    setApplying(`${job.job_id}:${index}`)
    try {
      await flushDirtyShots()
      setProject(await applyImageJob(job.job_id, index))
      await refresh()
    } catch (error) {
      onError(error)
    } finally {
      setApplying('')
    }
  }

  const remove = async (job: ImageJob) => {
    if (!window.confirm('Delete this image job and its outputs?')) return
    try {
      await deleteImageJob(job.job_id)
      await refresh()
    } catch (error) {
      onError(error)
    }
  }

  return (
    <div className="inspector-body image-jobs">
      {!configured ? (
        <div className="notice is-warn">Add your Comfy Cloud API key in Settings (gear icon, top right) to generate images.</div>
      ) : null}
      <label className="field">
        <span className="field-label-row"><span className="field-label">Image prompt</span><span className="field-flag">{IMAGE_MODEL_LABEL[mode]}</span></span>
        <textarea rows={5} value={prompt} onChange={(event) => setPrompt(event.target.value)}
          placeholder={mode === 'ref' ? 'What to make from the references: “this character, sitting at the window, night”.' : 'Subject, setting, framing, light, style.'} />
      </label>
      <details className="video-takes-negative">
        <summary>Negative prompt</summary>
        <textarea rows={2} value={negative} onChange={(event) => setNegative(event.target.value)} aria-label="Negative prompt" />
      </details>
      <div className="field">
        <span className="field-label-row">
          <span className="field-label">References</span>
          <span className="field-flag">{chosen.length}/{IMAGE_JOB_MAX_REFERENCES}</span>
        </span>
        {referenceChoices.length ? (
          <div className="image-ref-grid" role="group" aria-label="Reference boards">
            {referenceChoices.map((item) => {
              const on = chosen.includes(item.shot_id)
              const full = !on && chosen.length >= IMAGE_JOB_MAX_REFERENCES
              return (
                <button key={item.shot_id} type="button" className="image-ref" aria-pressed={on} disabled={full}
                  title={`${boardNumber(item)} · ${shotDisplayLabel(item)}`} onClick={() => toggleReference(item.shot_id)}>
                  <img alt="" loading="lazy" draggable={false}
                    src={`${shotThumbnailUrl(item.shot_id)}?v=${encodeURIComponent(String(item.preview_disk_mtime ?? ''))}`} />
                  <span className="image-ref-number">{boardNumber(item)}</span>
                </button>
              )
            })}
          </div>
        ) : null}
        <span className="inspector-intro">
          {chosen.length
            ? 'The selected boards’ images guide characters, places and style. Describe the new shot in the prompt.'
            : referenceChoices.length
              ? `Optional: pick up to ${IMAGE_JOB_MAX_REFERENCES} boards to keep characters and places consistent.`
              : 'No other board has an image yet, so this is text to image.'}
        </span>
      </div>
      <div className="video-takes-row">
        <label className="field">
          <span className="field-label">Seed</span>
          <input type="number" min={0} step={1} value={seed} placeholder="Random"
            onChange={(event) => setSeed(event.target.value)} aria-invalid={!seedValid} />
        </label>
        <button type="button" className="primary" onClick={() => void generate()}
          disabled={submitting || !configured || !prompt.trim() || !seedValid}>
          <Sparkle size={16} />{submitting ? 'Submitting…' : 'Generate image'}
        </button>
      </div>
      <p className="inspector-intro">Results are candidates: the board keeps its image until you choose “Use this image”. Billed to your Comfy Cloud credits.</p>
      {message ? <div className="notice is-danger" role="alert">{message}</div> : null}

      {jobs.length ? <span className="section-label">Results</span> : null}
      <ul className="video-take-list">
        {jobs.map((job) => (
          <li key={job.job_id} className={'video-take is-' + job.status}>
            {job.status === 'succeeded' && job.outputs > 0 ? (
              <div className="image-job-outputs">
                {Array.from({ length: job.outputs }, (_, index) => {
                  const applied = job.applied_index === index
                  const busy = applying === `${job.job_id}:${index}`
                  return (
                    <figure key={index} className={'image-job-output' + (applied ? ' is-applied' : '')}>
                      <a href={imageJobOutputUrl(job, index)} target="_blank" rel="noreferrer">
                        <img alt={`Result ${index + 1}`} src={imageJobOutputUrl(job, index)} loading="lazy" draggable={false} />
                      </a>
                      <button type="button" className={applied ? 'ghost' : undefined} disabled={busy || Boolean(applying)}
                        onClick={() => void apply(job, index)}>
                        {applied ? <><Check size={14} />On the board</> : busy ? 'Applying…' : 'Use this image'}
                      </button>
                    </figure>
                  )
                })}
              </div>
            ) : (
              <div className="video-take-pending" style={job.width && job.height ? { aspectRatio: `${job.width} / ${job.height}` } : undefined}>
                {IMAGE_JOB_ACTIVE.has(job.status) ? <span className="video-take-spinner" aria-hidden="true" /> : null}
                <span>{job.status === 'succeeded' ? 'No output' : STATUS_LABEL[job.status] ?? job.status}</span>
              </div>
            )}
            <div className="video-take-meta">
              <span>
                {job.mode === 'ref' ? 'Ref' : 'Text'} · {job.width}×{job.height}{job.seed != null ? ` · seed ${job.seed}` : ''}
                {job.references.length ? ` · from ${job.references.map(labelFor).join(', ')}` : ''}
              </span>
              {!IMAGE_JOB_ACTIVE.has(job.status) ? (
                <button type="button" className="ghost icon-btn" aria-label="Delete image job" title="Delete image job" onClick={() => void remove(job)}>
                  <Trash size={14} />
                </button>
              ) : null}
            </div>
            {job.status === 'failed' && job.error ? <p className="video-take-error">{job.error}</p> : null}
            <p className="video-take-prompt" title={job.prompt}>{job.prompt}</p>
          </li>
        ))}
      </ul>
    </div>
  )
}

function newestFirst(jobs: ImageJob[]): ImageJob[] {
  return [...jobs].sort((a, b) => (Date.parse(b.created_at) || 0) - (Date.parse(a.created_at) || 0))
}
