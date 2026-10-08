import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { ArrowClockwise, ChatCircle, Check } from '@phosphor-icons/react'
import {
  addComment,
  createScene2D,
  listScene2D,
  listScene3D,
  previewShotPrompt,
  resolveComment,
  type ShotPromptPreview,
} from '../api'
import { useProject } from '../state/useProject'
import type { ProjectPayload, Scene2D, Scene3DRecord, Shot, ShotComment, ShotContinuity, ShotDesign } from '../types'
import { statusStyle } from '../utils/status'
import { KeywordTextarea, type KeywordAssetHint } from './KeywordTextarea'
import './ShotInspector.css'

const CONTINUITY_MODES: { value: ShotContinuity['mode']; label: string }[] = [
  { value: 'continuous', label: 'Continuous' },
  { value: 'insert', label: 'Insert' },
  { value: 'montage', label: 'Montage' },
  { value: 'parallel', label: 'Parallel action' },
  { value: 'time-jump', label: 'Time jump' },
  { value: 'reset', label: 'Continuity reset' },
]

// Suggestions only: the fields stay free text because the prompt compiler reads them verbatim.
const SHOT_SIZES = ['Extreme wide', 'Wide', 'Full', 'Medium wide', 'Medium', 'Medium close-up', 'Close-up', 'Extreme close-up', 'Insert']
const CAMERA_ANGLES = ['Eye level', 'High angle', 'Low angle', 'Bird’s-eye', 'Worm’s-eye', 'Dutch angle', 'Over the shoulder', 'POV']
const CAMERA_HEIGHTS = ['Ground', 'Knee', 'Waist', 'Shoulder', 'Eye', 'Overhead']
const CAMERA_MOVES = ['Static', 'Pan', 'Tilt', 'Push in', 'Pull out', 'Dolly', 'Truck', 'Crane', 'Handheld', 'Zoom']
const LENSES = ['Wide 18–24mm', 'Normal 35mm', 'Normal 50mm', 'Portrait 85mm', 'Telephoto 135mm+']

type InspectorTab = 'shot' | 'camera' | 'continuity' | 'prompt' | 'notes' | 'advanced'

function toCommaList(values: string[] | undefined) {
  return (values || []).join(', ')
}

function fromCommaList(value: string) {
  return value
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)
}

function toLineList(values: string[] | undefined) {
  return (values || []).join('\n')
}

function fromLineList(value: string) {
  return value
    .split(/\r?\n/)
    .map((item) => item.trim())
    .filter(Boolean)
}

function pathStem(value: string) {
  const name = value.split(/[/\\]/).pop() || ''
  return name.replace(/\.[^.]+$/, '')
}

function keywordAssetHints(scenes: Scene3DRecord[]): KeywordAssetHint[] {
  return scenes.flatMap((scene) => {
    const path = scene.blend_file_path || scene.file_path
    if (!path) return []
    const terms = [
      ...(scene.keywords || []),
      scene.title,
      pathStem(scene.file_path),
      pathStem(scene.blend_file_path),
    ]
    const seen = new Set<string>()
    const keywords = terms.filter((term) => {
      const cleaned = String(term || '').trim()
      const key = cleaned.toLocaleLowerCase()
      if (!cleaned || seen.has(key)) return false
      seen.add(key)
      return true
    })
    return [{ id: scene.id, title: scene.title || pathStem(path) || scene.id, keywords, path }]
  })
}

function Datalist({ id, options }: { id: string; options: string[] }) {
  return <datalist id={id}>{options.map((option) => <option key={option} value={option} />)}</datalist>
}

export function ShotInspector({ advanced }: { advanced?: ReactNode }) {
  const { project, selectedShotId } = useProject()
  const [tab, setTab] = useState<InspectorTab>('shot')

  const shot = useMemo(() => {
    if (!project || !selectedShotId) return null
    return project.shots.find((candidate) => candidate.shot_id === selectedShotId) || null
  }, [project, selectedShotId])

  if (!project) return null

  const openNotes = (shot?.comments ?? []).filter((comment) => !comment.resolved).length
  const tabs: { id: InspectorTab; label: string }[] = [
    { id: 'shot', label: 'Shot' },
    { id: 'camera', label: 'Camera' },
    { id: 'continuity', label: 'Continuity' },
    { id: 'prompt', label: 'Prompt' },
    { id: 'notes', label: openNotes ? `Notes · ${openNotes}` : 'Notes' },
  ]

  return (
    <section className="inspector">
      <div className="tab-row inspector-tabs" role="tablist" aria-label="Board details">
        {tabs.map((item) => (
          <button key={item.id} type="button" role="tab" aria-selected={tab === item.id} onClick={() => setTab(item.id)}>
            {item.label}
          </button>
        ))}
      </div>
      {tab === 'advanced' ? (
        <div className="inspector-body inspector-advanced">
          <div className="inspector-section-title">
            <span className="section-label">Advanced</span>
            <button type="button" className="ghost" onClick={() => setTab('shot')}>Back</button>
          </div>
          {advanced}
        </div>
      ) : shot ? (
        <ShotInspectorEditor key={shot.shot_id} shot={shot} statuses={project.statuses || []} tab={tab} />
      ) : (
        <div className="inspector-empty">
          <p>Select or add a board</p>
          <p className="inspector-empty-hint">Story, camera and continuity details appear here.</p>
        </div>
      )}
      {shot ? (
        <InspectorFooter shot={shot} advancedOpen={tab === 'advanced'} hasAdvanced={!!advanced}
          onToggleAdvanced={() => setTab((current) => current === 'advanced' ? 'shot' : 'advanced')} />
      ) : null}
    </section>
  )
}

function InspectorFooter({ shot, advancedOpen, hasAdvanced, onToggleAdvanced }: {
  shot: Shot
  advancedOpen: boolean
  hasAdvanced: boolean
  onToggleAdvanced: () => void
}) {
  const { isShotDirty, savingShots, saveShot } = useProject()
  const dirty = isShotDirty(shot.shot_id)
  const saving = !!savingShots[shot.shot_id]
  return (
    <footer className="inspector-footer">
      <span className="inspector-footer-id" title={shot.shot_id}>{shot.shot_id.slice(0, 8)}</span>
      <span className={'inspector-footer-state' + (dirty || saving ? ' is-dirty' : '')}>{saving ? 'Saving…' : dirty ? 'Unsaved' : 'Saved'}</span>
      {dirty ? (
        <button type="button" className="ghost" onClick={() => void saveShot(shot.shot_id)} disabled={saving}>Save now</button>
      ) : null}
      {hasAdvanced ? (
        <button type="button" className="ghost" aria-pressed={advancedOpen} onClick={onToggleAdvanced}>Advanced</button>
      ) : null}
    </footer>
  )
}

function ShotInspectorEditor({
  shot,
  statuses,
  tab,
}: {
  shot: Shot
  statuses: string[]
  tab: InspectorTab
}) {
  const { project, getDraft, editShotField, reportError } = useProject()
  const [tagsText, setTagsText] = useState(() => toCommaList(shot.tags))
  const [dependencyText, setDependencyText] = useState(() => toCommaList(shot.continuity.depends_on_shot_ids))
  const [preserveText, setPreserveText] = useState(() => toLineList(shot.continuity.preserve))
  const [intentionalChangesText, setIntentionalChangesText] = useState(() => toLineList(shot.continuity.intentional_changes))
  const [scenes, setScenes] = useState<Scene2D[]>([])
  const [scene3dAssets, setScene3dAssets] = useState<Scene3DRecord[]>([])
  const [creatingScene, setCreatingScene] = useState(false)

  const shotId = shot.shot_id
  const draft = getDraft(shotId)
  const design = draft?.shot_design ?? shot.shot_design
  const continuity = draft?.continuity ?? shot.continuity
  const sceneLabel = String(draft?.scene ?? shot.scene ?? '')
  const sceneId = String(draft?.scene_id ?? shot.scene_id ?? '')
  const description = draft?.description ?? shot.description
  const actionNote = draft?.action_note ?? shot.action_note
  const status = String(draft?.status ?? shot.status ?? 'Draft')
  const storyAndAction = design.story_beat || [description, actionNote]
    .map((value) => value.trim())
    .filter((value, index, values) => value && values.indexOf(value) === index)
    .join('\n\n')
  const assetHints = useMemo(() => keywordAssetHints(scene3dAssets), [scene3dAssets])
  const scene3dRevision = String(project?.settings?.scene3d?.updated_at ?? '')

  useEffect(() => {
    let cancelled = false
    Promise.all([listScene2D(), listScene3D()])
      .then(([scene2dResponse, scene3dResponse]) => {
        if (!cancelled) {
          setScenes(scene2dResponse.scenes)
          setScene3dAssets(scene3dResponse.scenes)
        }
      })
      .catch(reportError)
    return () => {
      cancelled = true
    }
  }, [project?.project_json_path, reportError, scene3dRevision])

  const updateDesign = <K extends keyof ShotDesign>(key: K, value: ShotDesign[K]) => {
    editShotField(shotId, 'shot_design', { ...design, [key]: value })
  }

  const updateScene = (value: string) => {
    const selected = scenes.find((scene) => scene.id === value)
    editShotField(shotId, 'scene_id', value)
    editShotField(shotId, 'scene', selected?.title ?? '')
  }

  const createAndLinkScene = async () => {
    setCreatingScene(true)
    try {
      const response = await createScene2D()
      setScenes(response.scenes)
      editShotField(shotId, 'scene_id', response.scene.id)
      editShotField(shotId, 'scene', response.scene.title)
    } catch (error) {
      reportError(error)
    } finally {
      setCreatingScene(false)
    }
  }

  const updateStoryAndAction = (value: string) => {
    editShotField(shotId, 'description', value)
    updateDesign('story_beat', value)
  }

  const updateContinuity = <K extends keyof ShotContinuity>(key: K, value: ShotContinuity[K]) => {
    editShotField(shotId, 'continuity', { ...continuity, [key]: value })
  }

  const onTagsChange = (value: string) => {
    setTagsText(value)
    editShotField(shotId, 'tags', fromCommaList(value))
  }

  const onDependenciesChange = (value: string) => {
    setDependencyText(value)
    updateContinuity('depends_on_shot_ids', fromCommaList(value))
  }

  const onPreserveChange = (value: string) => {
    setPreserveText(value)
    updateContinuity('preserve', fromLineList(value))
  }

  const onIntentionalChangesChange = (value: string) => {
    setIntentionalChangesText(value)
    updateContinuity('intentional_changes', fromLineList(value))
  }

  if (tab === 'shot') {
    return (
      <div className="inspector-body">
        <label className="field">
          <span className="field-label">Title</span>
          <input value={draft?.title ?? shot.title} onChange={(event) => editShotField(shotId, 'title', event.target.value)} placeholder="Untitled board" />
        </label>
        <label className="field">
          <span className="field-label-row"><span className="field-label">Story &amp; action</span><span className="field-flag">Feeds generation</span></span>
          <KeywordTextarea assets={assetHints} rows={4} value={storyAndAction} onValueChange={updateStoryAndAction} placeholder="What happens in this shot? Include the key movement in one clear description." />
        </label>
        <label className="field">
          <span className="field-label">Dialogue</span>
          <KeywordTextarea assets={assetHints} rows={2} value={draft?.dialogue ?? shot.dialogue} onValueChange={(value) => editShotField(shotId, 'dialogue', value)} />
        </label>
        <div className="field-grid">
          <label className="field">
            <span className="field-label">Scene</span>
            <span className="scene-picker-row">
              <select value={sceneId} onChange={(event) => updateScene(event.target.value)}>
                <option value="">{sceneLabel ? `Unlinked: ${sceneLabel}` : 'No scene'}</option>
                {scenes.map((scene) => <option key={scene.id} value={scene.id}>{scene.title}</option>)}
              </select>
              <button type="button" className="ghost" title="Create a new scene and link it" onClick={() => void createAndLinkScene()} disabled={creatingScene}>
                {creatingScene ? '…' : 'New'}
              </button>
            </span>
          </label>
          <label className="field">
            <span className="field-label">Status</span>
            <span className="status-select" style={statusStyle(status)}>
              <span className="status-dot" />
              <select value={status} onChange={(event) => editShotField(shotId, 'status', event.target.value)}>
                {statuses.map((option) => <option key={option} value={option}>{option}</option>)}
              </select>
            </span>
          </label>
          <label className="field">
            <span className="field-label">Duration</span>
            <span className="input-suffix">
              <input type="number" step="any" min="0.000001" value={String(draft?.duration_seconds ?? shot.duration_seconds ?? 3)} onChange={(event) => editShotField(shotId, 'duration_seconds', Number(event.target.value))} />
              <span>sec</span>
            </span>
          </label>
          <label className="field">
            <span className="field-label">Sequence</span>
            <input value={draft?.sequence ?? shot.sequence} onChange={(event) => editShotField(shotId, 'sequence', event.target.value)} />
          </label>
        </div>
        <label className="field">
          <span className="field-label">Characters</span>
          <KeywordTextarea assets={assetHints} rows={2} value={draft?.character_note ?? shot.character_note} onValueChange={(value) => editShotField(shotId, 'character_note', value)} placeholder="Who is visible, appearance, expression…" />
        </label>
        <label className="field">
          <span className="field-label">Transition</span>
          <input value={draft?.transition_note ?? shot.transition_note} onChange={(event) => editShotField(shotId, 'transition_note', event.target.value)} placeholder="Cut, dissolve, match cut…" />
        </label>
        <label className="field">
          <span className="field-label">Tags</span>
          <input value={tagsText} onChange={(event) => onTagsChange(event.target.value)} placeholder="Comma separated" />
        </label>
        <p className="inspector-intro">
          {shot.reference_image_paths.length} reference image{shot.reference_image_paths.length === 1 ? '' : 's'} attached · manage them in References.
        </p>
      </div>
    )
  }

  if (tab === 'camera') {
    const listId = (name: string) => `inspector-${name}-${shotId}`
    return (
      <div className="inspector-body">
        <p className="inspector-intro">Structured camera intent. Every field feeds the generation prompt; leave blank what doesn’t matter.</p>
        <div className="field-grid">
          <label className="field">
            <span className="field-label">Shot size</span>
            <input list={listId('size')} value={design.shot_size} onChange={(event) => updateDesign('shot_size', event.target.value)} />
            <Datalist id={listId('size')} options={SHOT_SIZES} />
          </label>
          <label className="field">
            <span className="field-label">Angle</span>
            <input list={listId('angle')} value={design.camera_angle} onChange={(event) => updateDesign('camera_angle', event.target.value)} />
            <Datalist id={listId('angle')} options={CAMERA_ANGLES} />
          </label>
          <label className="field">
            <span className="field-label">Height</span>
            <input list={listId('height')} value={design.camera_height} onChange={(event) => updateDesign('camera_height', event.target.value)} />
            <Datalist id={listId('height')} options={CAMERA_HEIGHTS} />
          </label>
          <label className="field">
            <span className="field-label">Movement</span>
            <input list={listId('move')} value={design.camera_movement} onChange={(event) => updateDesign('camera_movement', event.target.value)} />
            <Datalist id={listId('move')} options={CAMERA_MOVES} />
          </label>
          <label className="field">
            <span className="field-label">Lens</span>
            <input list={listId('lens')} value={design.lens_intent} onChange={(event) => updateDesign('lens_intent', event.target.value)} />
            <Datalist id={listId('lens')} options={LENSES} />
          </label>
          <label className="field">
            <span className="field-label">Position</span>
            <input value={design.camera_position} onChange={(event) => updateDesign('camera_position', event.target.value)} placeholder="e.g. doorway" />
          </label>
        </div>
        <label className="field">
          <span className="field-label">Composition</span>
          <textarea rows={2} value={design.composition} onChange={(event) => updateDesign('composition', event.target.value)} placeholder="Where things sit in frame" />
        </label>
        <div className="field-grid is-three">
          <label className="field">
            <span className="field-label">Foreground</span>
            <input value={design.foreground} onChange={(event) => updateDesign('foreground', event.target.value)} />
          </label>
          <label className="field">
            <span className="field-label">Midground</span>
            <input value={design.midground} onChange={(event) => updateDesign('midground', event.target.value)} />
          </label>
          <label className="field">
            <span className="field-label">Background</span>
            <input value={design.background} onChange={(event) => updateDesign('background', event.target.value)} />
          </label>
        </div>
        <div className="field-grid">
          <label className="field">
            <span className="field-label">Focal point</span>
            <input value={design.focal_point} onChange={(event) => updateDesign('focal_point', event.target.value)} />
          </label>
          <label className="field">
            <span className="field-label">Subject movement</span>
            <input value={design.subject_movement} onChange={(event) => updateDesign('subject_movement', event.target.value)} />
          </label>
        </div>
        <label className="field">
          <span className="field-label">Axis of action</span>
          <input value={design.axis_of_action} onChange={(event) => updateDesign('axis_of_action', event.target.value)} placeholder="Who looks at whom, and which side the camera stays on" />
        </label>
        <label className="check-field">
          <input type="checkbox" checked={!!design.intentional_axis_crossing} onChange={(event) => updateDesign('intentional_axis_crossing', event.target.checked)} />
          Intentional axis crossing
        </label>
        <label className="field">
          <span className="field-label">Camera notes</span>
          <KeywordTextarea assets={assetHints} rows={2} value={draft?.camera_note ?? shot.camera_note} onValueChange={(value) => editShotField(shotId, 'camera_note', value)} placeholder="Anything the fields above don’t capture" />
        </label>
        <label className="field">
          <span className="field-label">Lighting</span>
          <KeywordTextarea assets={assetHints} rows={2} value={draft?.lighting_note ?? shot.lighting_note} onValueChange={(value) => editShotField(shotId, 'lighting_note', value)} />
        </label>
      </div>
    )
  }

  if (tab === 'continuity') {
    return (
      <div className="inspector-body">
        <p className="inspector-intro">Expected is authored intent. Observed describes the generated image. Resolved is the canonical state inherited downstream.</p>
        <div className="field-grid">
          <label className="field">
            <span className="field-label">Mode</span>
            <select value={continuity.mode} onChange={(event) => updateContinuity('mode', event.target.value as ShotContinuity['mode'])}>
              {CONTINUITY_MODES.map((mode) => <option key={mode.value} value={mode.value}>{mode.label}</option>)}
            </select>
          </label>
          <label className="field">
            <span className="field-label">Primary source shot</span>
            <input className="is-mono" value={continuity.primary_continuity_source_shot_id} onChange={(event) => updateContinuity('primary_continuity_source_shot_id', event.target.value)} placeholder="Shot ID" />
          </label>
        </div>
        <label className="field">
          <span className="field-label">Depends on shot IDs</span>
          <input className="is-mono" value={dependencyText} onChange={(event) => onDependenciesChange(event.target.value)} placeholder="shot_a, shot_b" />
        </label>

        <div className="inspector-section-title"><span className="section-label">Authored</span><small>Intent before generation</small></div>
        <label className="field">
          <span className="field-label">Expected in</span>
          <KeywordTextarea assets={assetHints} rows={3} value={continuity.expected_in} onValueChange={(value) => updateContinuity('expected_in', value)} />
        </label>
        <label className="field">
          <span className="field-label">Expected out</span>
          <KeywordTextarea assets={assetHints} rows={3} value={continuity.expected_out} onValueChange={(value) => updateContinuity('expected_out', value)} />
        </label>
        <label className="field">
          <span className="field-label">Preserve · one per line</span>
          <KeywordTextarea assets={assetHints} rows={3} value={preserveText} onValueChange={onPreserveChange} />
        </label>
        <label className="field">
          <span className="field-label">Intentional changes · one per line</span>
          <KeywordTextarea assets={assetHints} rows={3} value={intentionalChangesText} onValueChange={onIntentionalChangesChange} />
        </label>

        <div className="inspector-section-title"><span className="section-label">Review &amp; canon</span><small>Observed drift never becomes canonical automatically</small></div>
        <label className="field">
          <span className="field-label">Observed output</span>
          <textarea rows={3} value={continuity.observed_out} onChange={(event) => updateContinuity('observed_out', event.target.value)} placeholder="What the generated candidate actually contains" />
        </label>
        <label className="field">
          <span className="field-label">Resolved canonical output</span>
          <textarea rows={3} value={continuity.resolved_out} onChange={(event) => updateContinuity('resolved_out', event.target.value)} placeholder="Approved state inherited by downstream shots" />
        </label>
      </div>
    )
  }

  if (tab === 'prompt') return <PromptPreview shot={shot} />
  return <ShotNotes shot={shot} />
}

function PromptPreview({ shot }: { shot: Shot }) {
  const { isShotDirty, saveShot, reportError } = useProject()
  const [preview, setPreview] = useState<ShotPromptPreview | null>(null)
  const [loading, setLoading] = useState(false)
  const [failed, setFailed] = useState('')
  const dirty = isShotDirty(shot.shot_id)

  const refresh = useCallback(async () => {
    setLoading(true)
    setFailed('')
    try {
      // The preview is compiled from saved fields, so persist pending edits first.
      if (dirty) await saveShot(shot.shot_id)
      setPreview(await previewShotPrompt(shot.shot_id))
    } catch (error) {
      setFailed(error instanceof Error ? error.message : 'The prompt could not be compiled.')
      reportError(error)
    } finally {
      setLoading(false)
    }
  }, [dirty, reportError, saveShot, shot.shot_id])

  useEffect(() => {
    let cancelled = false
    previewShotPrompt(shot.shot_id)
      .then((result) => { if (!cancelled) setPreview(result) })
      .catch((error) => { if (!cancelled) setFailed(error instanceof Error ? error.message : 'The prompt could not be compiled.') })
    return () => { cancelled = true }
  }, [shot.shot_id])

  const prompt = preview?.prompt
  return (
    <div className="inspector-body">
      <div className="inspector-section-title">
        <span className="section-label">Assembled prompt</span>
        <button type="button" className="ghost" onClick={() => void refresh()} disabled={loading}>
          <ArrowClockwise size={14} />{loading ? 'Compiling…' : dirty ? 'Save & refresh' : 'Refresh'}
        </button>
      </div>
      {failed ? <div className="notice is-danger">{failed}</div> : null}
      {prompt ? (
        <>
          <pre className="prompt-block">{prompt.compiled_prompt || 'Nothing to send yet — add story, camera or scene details.'}</pre>
          {prompt.negative_prompt ? (
            <div className="field">
              <span className="field-label">Negative</span>
              <pre className="prompt-block is-negative">{prompt.negative_prompt}</pre>
            </div>
          ) : null}
          <div className="prompt-facts">
            <span>Aspect <b>{prompt.aspect_ratio}</b></span>
            <span>Variants <b>{prompt.variant_count}</b></span>
            {prompt.layers?.scene ? <span>Scene <b>{prompt.layers.scene}</b></span> : null}
          </div>
          <p className="inspector-intro">This preview queues nothing. Use <b>Generate</b> in the board toolbar to send a request.</p>
        </>
      ) : !failed ? <p className="inspector-intro">Compiling…</p> : null}
    </div>
  )
}

function formatCommentDate(value: unknown): string {
  if (typeof value !== 'string' || !value) return ''
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

function ShotNotes({ shot }: { shot: Shot }) {
  const { replaceProject, reportError, selectedShotId } = useProject()
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const comments: ShotComment[] = [...(shot.comments ?? [])].sort((a, b) => Number(!!a.resolved) - Number(!!b.resolved) || b.id - a.id)

  const run = async (action: () => Promise<ProjectPayload>) => {
    setBusy(true)
    try {
      replaceProject(await action(), selectedShotId)
      return true
    } catch (error) {
      reportError(error)
      return false
    } finally {
      setBusy(false)
    }
  }

  const submit = async () => {
    const value = text.trim()
    if (!value || busy) return
    if (await run(() => addComment(shot.shot_id, { text: value }))) setText('')
  }

  return (
    <div className="inspector-body">
      <div className="note-composer">
        <textarea rows={2} value={text} onChange={(event) => setText(event.target.value)} placeholder="Add a review note…" aria-label="New note"
          onKeyDown={(event) => { if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) { event.preventDefault(); void submit() } }} />
        <button type="button" className="primary" onClick={() => void submit()} disabled={busy || !text.trim()}>Add note</button>
      </div>
      {comments.length ? (
        <ul className="note-list">
          {comments.map((comment) => {
            const when = formatCommentDate(comment.created_at)
            return (
              <li key={comment.id} className={'note' + (comment.resolved ? ' is-resolved' : '')}>
                <div className="note-meta">
                  <ChatCircle size={13} />
                  <span>{comment.resolved ? 'Resolved' : 'Open'}{when ? ` · ${when}` : ''}</span>
                </div>
                <p>{comment.text}</p>
                <button type="button" className="ghost" disabled={busy}
                  onClick={() => void run(() => resolveComment(shot.shot_id, comment.id, { resolved: !comment.resolved }))}>
                  {comment.resolved ? 'Reopen' : <><Check size={13} />Resolve</>}
                </button>
              </li>
            )
          })}
        </ul>
      ) : (
        <p className="inspector-intro">No notes on this board yet. Notes are review feedback; they never feed generation.</p>
      )}
    </div>
  )
}
