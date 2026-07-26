import { useEffect, useMemo, useState } from 'react'
import {
  createScene2D,
  listScene2D,
  listScene3D,
} from '../api'
import { useProject } from '../state/useProject'
import type { Scene2D, Scene3DRecord, Shot, ShotContinuity, ShotDesign } from '../types'
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

export function ShotInspector() {
  const { project, selectedShotId } = useProject()

  const shot = useMemo(() => {
    if (!project || !selectedShotId) return null
    return project.shots.find((candidate) => candidate.shot_id === selectedShotId) || null
  }, [project, selectedShotId])

  if (!project) return null

  if (!shot) {
    return (
      <section className="inspector">
        <div className="inspector-empty">
          <p>Select or add a shot</p>
          <p className="inspector-empty-hint">Storyboard details and continuity will appear here.</p>
        </div>
      </section>
    )
  }

  return (
    <ShotInspectorEditor
      key={shot.shot_id}
      shot={shot}
      statuses={project.statuses || []}
    />
  )
}

function ShotInspectorEditor({
  shot,
  statuses,
}: {
  shot: Shot
  statuses: string[]
}) {
  const { project, getDraft, editShotField, isShotDirty, savingShots, saveShot, reportError } = useProject()
  const [tagsText, setTagsText] = useState(() => toCommaList(shot.tags))
  const [dependencyText, setDependencyText] = useState(() => toCommaList(shot.continuity.depends_on_shot_ids))
  const [preserveText, setPreserveText] = useState(() => toLineList(shot.continuity.preserve))
  const [intentionalChangesText, setIntentionalChangesText] = useState(() => toLineList(shot.continuity.intentional_changes))
  const [scenes, setScenes] = useState<Scene2D[]>([])
  const [scene3dAssets, setScene3dAssets] = useState<Scene3DRecord[]>([])
  const [creatingScene, setCreatingScene] = useState(false)

  const shotId = shot.shot_id
  const draft = getDraft(shotId)
  const saving = !!savingShots[shotId]
  const dirty = isShotDirty(shotId)
  const design = draft?.shot_design ?? shot.shot_design
  const continuity = draft?.continuity ?? shot.continuity
  const sceneLabel = String(draft?.scene ?? shot.scene ?? '')
  const sceneId = String(draft?.scene_id ?? shot.scene_id ?? '')
  const description = draft?.description ?? shot.description
  const actionNote = draft?.action_note ?? shot.action_note
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

  return (
    <section className="inspector">
      <div className="inspector-header">
        <div>
          <div className="inspector-title">Shot Inspector</div>
          <div className="inspector-subtitle">
            {dirty ? 'Unsaved changes' : 'All changes saved'}
            {saving ? ' | Saving...' : ''}
          </div>
        </div>
        <div className="inspector-actions">
          <button type="button" onClick={() => void saveShot(shotId)} disabled={!dirty || saving}>
            {saving ? 'Saving...' : 'Save shot'}
          </button>
        </div>
      </div>

      <div className="inspector-body">
        <>
            <label className="shot-title-field">
              <div className="field-label">Title</div>
              <input value={draft?.title ?? shot.title} onChange={(event) => editShotField(shotId, 'title', event.target.value)} />
            </label>

            <div className="section-heading shot-detail-heading shot-content-heading">
              <span>Shot content</span>
              <small className="shot-detail-scope is-ai">Used for generation</small>
            </div>
            <label>
              <div className="field-label">Story &amp; action</div>
              <KeywordTextarea assets={assetHints} rows={4} value={storyAndAction} onValueChange={updateStoryAndAction} placeholder="What happens in this shot? Include the key movement in one clear description." />
              <span className="field-hint">Replaces separate Description, Story beat, and Action inputs.</span>
            </label>

            <details className="shot-details" open>
              <summary>Shot details</summary>
              <div className="field-grid shot-details-grid">
              <label>
                <div className="field-label">Scene</div>
                <div className="scene-picker-row">
                  <select value={sceneId} onChange={(event) => updateScene(event.target.value)}>
                    <option value="">{sceneLabel ? `Unlinked: ${sceneLabel}` : 'No scene'}</option>
                    {scenes.map((scene) => <option key={scene.id} value={scene.id}>{scene.title}</option>)}
                  </select>
                  <button type="button" onClick={() => void createAndLinkScene()} disabled={creatingScene}>
                    {creatingScene ? 'Creating...' : 'New'}
                  </button>
                </div>
              </label>
              <label>
                <div className="field-label">Sequence</div>
                <input value={draft?.sequence ?? shot.sequence} onChange={(event) => editShotField(shotId, 'sequence', event.target.value)} />
              </label>
              <label>
                <div className="field-label">Status</div>
                <select value={String(draft?.status ?? shot.status ?? 'Draft')} onChange={(event) => editShotField(shotId, 'status', event.target.value)}>
                  {statuses.map((status) => <option key={status} value={status}>{status}</option>)}
                </select>
              </label>
              <label>
                <div className="field-label">Duration (seconds)</div>
                <input type="number" step="0.1" min="0.1" value={String(draft?.duration_seconds ?? shot.duration_seconds ?? 3)} onChange={(event) => editShotField(shotId, 'duration_seconds', Number(event.target.value))} />
              </label>
              <label>
                <div className="field-label">Tags</div>
                <input value={tagsText} onChange={(event) => onTagsChange(event.target.value)} placeholder="tag1, tag2" />
              </label>
              </div>
            </details>

            <div className="field-grid">
              <label>
                <div className="field-label">Characters</div>
                <KeywordTextarea assets={assetHints} rows={3} value={draft?.character_note ?? shot.character_note} onValueChange={(value) => editShotField(shotId, 'character_note', value)} placeholder="Who is visible, appearance, expression..." />
              </label>
              <label>
                <div className="field-label">Dialogue</div>
                <KeywordTextarea assets={assetHints} rows={3} value={draft?.dialogue ?? shot.dialogue} onValueChange={(value) => editShotField(shotId, 'dialogue', value)} />
              </label>
              <label>
                <div className="field-label">Camera &amp; composition</div>
                <KeywordTextarea assets={assetHints} rows={3} value={draft?.camera_note ?? shot.camera_note} onValueChange={(value) => editShotField(shotId, 'camera_note', value)} placeholder="One clear visual direction for this shot." />
              </label>
              <label>
                <div className="field-label">Lighting</div>
                <KeywordTextarea assets={assetHints} rows={3} value={draft?.lighting_note ?? shot.lighting_note} onValueChange={(value) => editShotField(shotId, 'lighting_note', value)} />
              </label>
            </div>

            <div className="section-heading shot-detail-heading">
              <span>Production notes</span>
              <small className="shot-detail-scope is-project">Production only</small>
            </div>
            <div className="field-grid shot-detail-production">
              <label>
                <div className="field-label">Transition</div>
                <textarea rows={2} value={draft?.transition_note ?? shot.transition_note} onChange={(event) => editShotField(shotId, 'transition_note', event.target.value)} placeholder="Cut, dissolve, match cut, editorial note..." />
              </label>
              <label>
                <div className="field-label">Shot ID</div>
                <input value={shot.shot_id} readOnly />
              </label>
            </div>
            <div className="reference-summary">
              <span>{shot.reference_image_paths.length}</span>
              <div><strong>Shot references attached</strong><small>Reference images for this storyboard shot.</small></div>
            </div>
        </>

        <section className="inspector-section" aria-labelledby="continuity-section-title">
          <div className="section-heading inspector-section-heading">
            <span id="continuity-section-title">Continuity</span>
            <small>Connections between shots</small>
          </div>
            <div className="inspector-callout">
              Expected is authored intent. Observed describes the generated image. Resolved is the canonical state inherited downstream.
            </div>
            <div className="field-grid">
              <label>
                <div className="field-label">Continuity mode</div>
                <select value={continuity.mode} onChange={(event) => updateContinuity('mode', event.target.value as ShotContinuity['mode'])}>
                  {CONTINUITY_MODES.map((mode) => <option key={mode.value} value={mode.value}>{mode.label}</option>)}
                </select>
              </label>
              <label>
                <div className="field-label">Primary continuity source shot</div>
                <input value={continuity.primary_continuity_source_shot_id} onChange={(event) => updateContinuity('primary_continuity_source_shot_id', event.target.value)} placeholder="Shot ID" />
              </label>
            </div>
            <label>
              <div className="field-label">Depends on shot IDs</div>
              <input value={dependencyText} onChange={(event) => onDependenciesChange(event.target.value)} placeholder="shot_a, shot_b" />
            </label>

            <div className="section-heading"><span>Authored continuity</span><small>Intent before generation</small></div>
            <div className="field-grid">
              <label>
                <div className="field-label">Expected in</div>
                <KeywordTextarea assets={assetHints} rows={5} value={continuity.expected_in} onValueChange={(value) => updateContinuity('expected_in', value)} />
              </label>
              <label>
                <div className="field-label">Expected out</div>
                <KeywordTextarea assets={assetHints} rows={5} value={continuity.expected_out} onValueChange={(value) => updateContinuity('expected_out', value)} />
              </label>
              <label>
                <div className="field-label">Preserve (one per line)</div>
                <KeywordTextarea assets={assetHints} rows={5} value={preserveText} onValueChange={onPreserveChange} />
              </label>
              <label>
                <div className="field-label">Intentional changes (one per line)</div>
                <KeywordTextarea assets={assetHints} rows={5} value={intentionalChangesText} onValueChange={onIntentionalChangesChange} />
              </label>
            </div>

            <div className="section-heading"><span>Review and canon</span><small>Observed drift never becomes canonical automatically</small></div>
            <label>
              <div className="field-label">Observed output</div>
              <textarea rows={5} value={continuity.observed_out} onChange={(event) => updateContinuity('observed_out', event.target.value)} placeholder="What the generated candidate actually contains" />
            </label>
            <label>
              <div className="field-label">Resolved canonical output</div>
              <textarea rows={5} value={continuity.resolved_out} onChange={(event) => updateContinuity('resolved_out', event.target.value)} placeholder="Approved state inherited by downstream shots" />
            </label>
        </section>

      </div>
    </section>
  )
}
