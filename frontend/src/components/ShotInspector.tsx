import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  acceptGenerationCandidate,
  createGenerationRequest,
  listGenerationRequests,
  listScene2D,
  projectFileUrl,
  reconcileGenerationRequests,
} from '../api'
import { useProject } from '../state/useProject'
import type { GenerationDestination, GenerationRequest, PromptConfig, Scene2D, Shot, ShotContinuity, ShotDesign } from '../types'
import './ShotInspector.css'

type InspectorTab = 'shot' | 'prompt' | 'continuity' | 'generation'

const INSPECTOR_TABS: { id: InspectorTab; label: string }[] = [
  { id: 'shot', label: 'Shot' },
  { id: 'prompt', label: 'Prompt' },
  { id: 'continuity', label: 'Continuity' },
  { id: 'generation', label: 'Generation' },
]

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

function formatGenerationTime(value: string) {
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString([], { dateStyle: 'short', timeStyle: 'short' })
}

async function copyTextWithTimeout(value: string, timeoutMs = 1200) {
  if (!navigator.clipboard?.writeText) return false
  let timeoutId: number | undefined
  try {
    return await Promise.race([
      navigator.clipboard.writeText(value).then(() => true, () => false),
      new Promise<boolean>((resolve) => {
        timeoutId = window.setTimeout(() => resolve(false), timeoutMs)
      }),
    ])
  } finally {
    if (timeoutId !== undefined) window.clearTimeout(timeoutId)
  }
}

function buildSkillInputPreview(shot: Shot, design: ShotDesign, prompt: PromptConfig, continuity: ShotContinuity) {
  const storyAndAction = design.story_beat || shot.description
  const actionNote = shot.action_note.trim()
  const lines = [
    ['Story beat', storyAndAction],
    ['Action', actionNote && !storyAndAction.toLocaleLowerCase().includes(actionNote.toLocaleLowerCase()) ? actionNote : ''],
    ['Camera note', shot.camera_note],
    ['Shot size', design.shot_size],
    ['Camera', [design.camera_position, design.camera_height, design.camera_angle, design.camera_direction].filter(Boolean).join(', ')],
    ['Camera movement', design.camera_movement],
    ['Lens / FOV intent', design.lens_intent],
    ['Composition', design.composition],
    ['Focal point', design.focal_point],
    ['Character notes', shot.character_note],
    ['Lighting', shot.lighting_note],
    ['Continuity in', continuity.expected_in],
    ['Continuity out', continuity.expected_out],
    ['Preserve', continuity.preserve.join('; ')],
    ['Intentional changes', continuity.intentional_changes.join('; ')],
    ['Extra instruction', prompt.prompt_extra],
  ].filter(([, value]) => value)
  return lines.length > 0
    ? lines.map(([label, value]) => `${label}: ${value}`).join('\n')
    : 'Add shot details to build the skill input package.'
}

function buildLayeredPromptPreview(
  shot: Shot,
  design: ShotDesign,
  prompt: PromptConfig,
  continuity: ShotContinuity,
  scene: Scene2D | null,
  characterBiblePrompt: string,
) {
  const sections: string[] = []
  if (scene && (scene.environment_prompt.trim() || scene.consistency_anchors.length > 0)) {
    sections.push([
      'SCENE BIBLE',
      `Scene: ${scene.title}`,
      scene.environment_prompt.trim() ? `Environment: ${scene.environment_prompt.trim()}` : '',
      scene.consistency_anchors.length > 0 ? `Locked anchors: ${scene.consistency_anchors.join('; ')}` : '',
    ].filter(Boolean).join('\n'))
  }
  if (characterBiblePrompt.trim()) {
    sections.push(`CHARACTER BIBLE\n${characterBiblePrompt.trim()}`)
  }
  sections.push(`SHOT OVERRIDE\n${buildSkillInputPreview(shot, design, prompt, continuity)}`)
  return sections.join('\n\n')
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
          <p className="inspector-empty-hint">Shot metadata, prompts, and continuity will appear here.</p>
        </div>
      </section>
    )
  }

  return (
    <ShotInspectorEditor
      key={shot.shot_id}
      shot={shot}
      statuses={project.statuses || []}
      characterBiblePrompt={String(project.settings.character_bible_prompt ?? '')}
    />
  )
}

function ShotInspectorEditor({
  shot,
  statuses,
  characterBiblePrompt,
}: {
  shot: Shot
  statuses: string[]
  characterBiblePrompt: string
}) {
  const { getDraft, editShotField, isShotDirty, savingShots, saveShot, replaceProject, reportError } = useProject()
  const [activeTab, setActiveTab] = useState<InspectorTab>('shot')
  const [tagsText, setTagsText] = useState(() => toCommaList(shot.tags))
  const [dependencyText, setDependencyText] = useState(() => toCommaList(shot.continuity.depends_on_shot_ids))
  const [preserveText, setPreserveText] = useState(() => toLineList(shot.continuity.preserve))
  const [intentionalChangesText, setIntentionalChangesText] = useState(() => toLineList(shot.continuity.intentional_changes))
  const [generationRequests, setGenerationRequests] = useState<GenerationRequest[]>([])
  const [generationLoading, setGenerationLoading] = useState(false)
  const [dispatchingTo, setDispatchingTo] = useState<GenerationDestination | null>(null)
  const [generationNotice, setGenerationNotice] = useState('')
  const [scenes, setScenes] = useState<Scene2D[]>([])
  const [acceptingArtifact, setAcceptingArtifact] = useState('')

  const shotId = shot.shot_id
  const draft = getDraft(shotId)
  const saving = !!savingShots[shotId]
  const dirty = isShotDirty(shotId)
  const design = draft?.shot_design ?? shot.shot_design
  const prompt = draft?.prompt_config ?? shot.prompt_config
  const continuity = draft?.continuity ?? shot.continuity
  const generation = shot.generation_state
  const sceneId = String(draft?.scene_id ?? shot.scene_id ?? '')
  const sceneLabel = String(draft?.scene ?? shot.scene ?? '')
  const selectedScene = useMemo(
    () => scenes.find((scene) => scene.id === sceneId)
      ?? scenes.find((scene) => scene.title.trim().toLocaleLowerCase() === sceneLabel.trim().toLocaleLowerCase())
      ?? null,
    [sceneId, sceneLabel, scenes],
  )

  const loadSceneBibles = useCallback(async () => {
    try {
      const response = await listScene2D()
      setScenes(response.scenes)
    } catch (error) {
      reportError(error)
    }
  }, [reportError])

  useEffect(() => {
    let cancelled = false
    listScene2D()
      .then((response) => {
        if (!cancelled) setScenes(response.scenes)
      })
      .catch(reportError)
    return () => {
      cancelled = true
    }
  }, [reportError])
  const description = draft?.description ?? shot.description
  const actionNote = draft?.action_note ?? shot.action_note
  const storyAndAction = design.story_beat || [description, actionNote]
    .map((value) => value.trim())
    .filter((value, index, values) => value && values.indexOf(value) === index)
    .join('\n\n')

  const loadGenerationRequests = useCallback(async () => {
    setGenerationLoading(true)
    try {
      const response = await listGenerationRequests(shotId)
      setGenerationRequests(response.requests)
    } catch (error) {
      reportError(error)
    } finally {
      setGenerationLoading(false)
    }
  }, [reportError, shotId])

  const selectInspectorTab = (tab: InspectorTab) => {
    setActiveTab(tab)
    if (tab === 'prompt') void loadSceneBibles()
    if (tab === 'generation') void loadGenerationRequests()
  }

  const dispatchGeneration = async (destination: GenerationDestination) => {
    setDispatchingTo(destination)
    setGenerationNotice('')
    try {
      if (dirty) await saveShot(shotId)
      const response = await createGenerationRequest(shotId, destination)
      replaceProject(response.project, shotId)
      setGenerationRequests(response.requests)
      if (destination === 'codex' && response.codex_prompt) {
        const copied = await copyTextWithTimeout(response.codex_prompt)
        setGenerationNotice(
          copied
            ? `Codex handoff ${response.request.request_id} is ready. The Codex instruction was copied.`
            : `Codex handoff ${response.request.request_id} is ready. Copy its request ID into Codex.`,
        )
      } else {
        setGenerationNotice(`Request ${response.request.request_id} was added to the queue.`)
      }
    } catch (error) {
      reportError(error)
    } finally {
      setDispatchingTo(null)
    }
  }

  const refreshGenerationResults = async () => {
    setGenerationLoading(true)
    setGenerationNotice('')
    try {
      const response = await reconcileGenerationRequests()
      replaceProject(response.project, shotId)
      setGenerationRequests(response.requests.filter((request) => request.shot_id === shotId))
      setGenerationNotice(
        response.updated_request_ids.length > 0
          ? `${response.updated_request_ids.length} returned request${response.updated_request_ids.length === 1 ? '' : 's'} imported for review.`
          : 'No new Codex results were found.',
      )
    } catch (error) {
      reportError(error)
    } finally {
      setGenerationLoading(false)
    }
  }

  const handleUseAsCodexLayer = async (request: GenerationRequest, artifactPath: string) => {
    const resultId = request.latest_result?.result_id
    if (!resultId) return
    setAcceptingArtifact(artifactPath)
    setGenerationNotice('')
    try {
      const response = await acceptGenerationCandidate(shotId, {
        request_id: request.request_id,
        result_id: resultId,
        artifact_path: artifactPath,
      })
      replaceProject(response.project, shotId)
      setGenerationRequests(response.requests)
      setGenerationNotice('Candidate accepted as the Codex layer. Artist artwork was not changed.')
    } catch (error) {
      reportError(error)
    } finally {
      setAcceptingArtifact('')
    }
  }

  const updateDesign = <K extends keyof ShotDesign>(key: K, value: ShotDesign[K]) => {
    editShotField(shotId, 'shot_design', { ...design, [key]: value })
  }

  const onSceneBibleChange = (nextSceneId: string) => {
    editShotField(shotId, 'scene_id', nextSceneId)
    const nextScene = scenes.find((scene) => scene.id === nextSceneId)
    editShotField(shotId, 'scene', nextScene?.title ?? '')
  }

  const updateStoryAndAction = (value: string) => {
    editShotField(shotId, 'description', value)
    updateDesign('story_beat', value)
  }

  const updatePrompt = <K extends keyof PromptConfig>(key: K, value: PromptConfig[K]) => {
    editShotField(shotId, 'prompt_config', { ...prompt, [key]: value })
  }

  const onPromptModeChange = (mode: PromptConfig['mode']) => {
    editShotField(shotId, 'prompt_config', {
      ...prompt,
      mode,
      manual_prompt:
        mode === 'manual' && !prompt.manual_prompt.trim()
          ? buildSkillInputPreview(shot, design, prompt, continuity)
          : prompt.manual_prompt,
    })
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

      <div className="inspector-tabs" role="tablist" aria-label="Shot inspector sections">
        {INSPECTOR_TABS.map((tab) => (
          <button
            key={tab.id}
            type="button"
            role="tab"
            aria-selected={activeTab === tab.id}
            className={activeTab === tab.id ? 'is-active' : ''}
            onClick={() => selectInspectorTab(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div className="inspector-body">
        {activeTab === 'shot' ? (
          <>
            <div className="shot-detail-guide">
              <span><i className="shot-detail-dot is-project" />Not included in AI prompt</span>
              <span><i className="shot-detail-dot is-ai" />Included in AI prompt</span>
            </div>

            <div className="section-heading shot-detail-heading">
              <span>Basic information</span>
              <small className="shot-detail-scope is-project">Not in prompt</small>
            </div>
            <div className="field-grid">
              <label>
                <div className="field-label">Title</div>
                <input value={draft?.title ?? shot.title} onChange={(event) => editShotField(shotId, 'title', event.target.value)} />
              </label>
              <label>
                <div className="field-label">Scene Bible</div>
                <select value={sceneId} onChange={(event) => onSceneBibleChange(event.target.value)}>
                  <option value="">No linked Scene Bible</option>
                  {scenes.map((scene) => (
                    <option key={scene.id} value={scene.id}>{scene.title}</option>
                  ))}
                </select>
              </label>
              <label>
                <div className="field-label">Scene label</div>
                <input
                  value={sceneLabel}
                  onChange={(event) => editShotField(shotId, 'scene', event.target.value)}
                  placeholder="Legacy/free-text scene label"
                  disabled={!!sceneId}
                />
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

            <div className="section-heading shot-detail-heading">
              <span>Shot content</span>
              <small className="shot-detail-scope is-ai">In AI prompt</small>
            </div>
            <label>
              <div className="field-label">Story &amp; action</div>
              <textarea rows={4} value={storyAndAction} onChange={(event) => updateStoryAndAction(event.target.value)} placeholder="What happens in this shot? Include the key movement in one clear description." />
              <span className="field-hint">Replaces separate Description, Story beat, and Action inputs.</span>
            </label>

            <div className="field-grid">
              <label>
                <div className="field-label">Characters</div>
                <textarea rows={3} value={draft?.character_note ?? shot.character_note} onChange={(event) => editShotField(shotId, 'character_note', event.target.value)} placeholder="Who is visible, appearance, expression..." />
              </label>
              <label>
                <div className="field-label">Dialogue</div>
                <textarea rows={3} value={draft?.dialogue ?? shot.dialogue} onChange={(event) => editShotField(shotId, 'dialogue', event.target.value)} />
              </label>
              <label>
                <div className="field-label">Camera &amp; composition</div>
                <textarea rows={3} value={draft?.camera_note ?? shot.camera_note} onChange={(event) => editShotField(shotId, 'camera_note', event.target.value)} placeholder="One plain-language direction; detailed controls are in Prompt." />
              </label>
              <label>
                <div className="field-label">Lighting</div>
                <textarea rows={3} value={draft?.lighting_note ?? shot.lighting_note} onChange={(event) => editShotField(shotId, 'lighting_note', event.target.value)} />
              </label>
            </div>

            <div className="section-heading shot-detail-heading">
              <span>Production notes</span>
              <small className="shot-detail-scope is-project">Not in prompt</small>
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
          </>
        ) : null}

        {activeTab === 'prompt' ? (
          <>
            <div className="inspector-callout">
              Prompt order is fixed: Scene Bible → Character Bible → Shot Override. Scene controls the environment; this shot controls framing, action, and performance.
            </div>
            <div className="prompt-layer-status">
              <span className={selectedScene?.environment_prompt ? 'is-ready' : ''}>Scene {selectedScene?.environment_prompt ? 'linked' : 'missing'}</span>
              <span className={characterBiblePrompt.trim() ? 'is-ready' : ''}>Characters {characterBiblePrompt.trim() ? 'defined' : 'missing'}</span>
              <span className="is-ready">Shot ready</span>
            </div>
            <div className="field-grid">
              <label>
                <div className="field-label">Prompt mode</div>
                <select value={prompt.mode} onChange={(event) => onPromptModeChange(event.target.value as PromptConfig['mode'])}>
                  <option value="auto">Auto — compile from shot details</option>
                  <option value="manual">Manual — write the Shot Override</option>
                </select>
              </label>
              <label>
                <div className="field-label">Style profile</div>
                <input value={prompt.style_profile_id} onChange={(event) => updatePrompt('style_profile_id', event.target.value)} placeholder="Project default" />
              </label>
            </div>

            {prompt.mode === 'manual' ? (
              <label>
                <div className="field-label">Manual Shot Override</div>
                <textarea className="prompt-editor" rows={9} value={prompt.manual_prompt} onChange={(event) => updatePrompt('manual_prompt', event.target.value)} placeholder="Describe only this shot. Scene and Character Bibles will still be added above it." />
              </label>
            ) : (
              <>
                <label>
                  <div className="field-label">Layered prompt preview</div>
                  <textarea
                    className="prompt-preview"
                    rows={15}
                    value={buildLayeredPromptPreview(shot, design, prompt, continuity, selectedScene, characterBiblePrompt)}
                    readOnly
                  />
                </label>
                <label>
                  <div className="field-label">Additional prompt instruction</div>
                  <textarea rows={3} value={prompt.prompt_extra} onChange={(event) => updatePrompt('prompt_extra', event.target.value)} placeholder="Add an instruction without replacing structured shot data" />
                </label>
              </>
            )}

            {prompt.mode === 'auto' ? (
              <details className="prompt-advanced">
                <summary>
                  <span>Advanced framing controls</span>
                  <small>Optional camera, staging, and continuity details</small>
                </summary>
                <div className="prompt-advanced-body">
                  <div className="field-grid">
                    <label>
                      <div className="field-label">Shot size</div>
                      <input value={design.shot_size} onChange={(event) => updateDesign('shot_size', event.target.value)} placeholder="Wide, medium, close-up..." />
                    </label>
                    <label>
                      <div className="field-label">Lens / FOV intent</div>
                      <input value={design.lens_intent} onChange={(event) => updateDesign('lens_intent', event.target.value)} placeholder="Compressed, neutral, expansive..." />
                    </label>
                    <label>
                      <div className="field-label">Camera position</div>
                      <input value={design.camera_position} onChange={(event) => updateDesign('camera_position', event.target.value)} />
                    </label>
                    <label>
                      <div className="field-label">Camera height</div>
                      <input value={design.camera_height} onChange={(event) => updateDesign('camera_height', event.target.value)} placeholder="Eye level, floor level..." />
                    </label>
                    <label>
                      <div className="field-label">Camera angle</div>
                      <input value={design.camera_angle} onChange={(event) => updateDesign('camera_angle', event.target.value)} placeholder="Low, high, Dutch..." />
                    </label>
                    <label>
                      <div className="field-label">Camera direction</div>
                      <input value={design.camera_direction} onChange={(event) => updateDesign('camera_direction', event.target.value)} />
                    </label>
                    <label>
                      <div className="field-label">Camera movement</div>
                      <input value={design.camera_movement} onChange={(event) => updateDesign('camera_movement', event.target.value)} placeholder="Static, pan, dolly..." />
                    </label>
                    <label>
                      <div className="field-label">Subject movement</div>
                      <textarea rows={2} value={design.subject_movement} onChange={(event) => updateDesign('subject_movement', event.target.value)} />
                    </label>
                  </div>

                  <label>
                    <div className="field-label">Composition</div>
                    <textarea rows={2} value={design.composition} onChange={(event) => updateDesign('composition', event.target.value)} />
                  </label>
                  <input className="compact-followup" value={design.focal_point} onChange={(event) => updateDesign('focal_point', event.target.value)} placeholder="Dominant focal point" aria-label="Dominant focal point" />

                  <div className="field-grid field-grid-three">
                    <label>
                      <div className="field-label">Foreground</div>
                      <textarea rows={2} value={design.foreground} onChange={(event) => updateDesign('foreground', event.target.value)} />
                    </label>
                    <label>
                      <div className="field-label">Midground</div>
                      <textarea rows={2} value={design.midground} onChange={(event) => updateDesign('midground', event.target.value)} />
                    </label>
                    <label>
                      <div className="field-label">Background</div>
                      <textarea rows={2} value={design.background} onChange={(event) => updateDesign('background', event.target.value)} />
                    </label>
                  </div>

                  <label>
                    <div className="field-label">Axis of action</div>
                    <textarea rows={2} value={design.axis_of_action} onChange={(event) => updateDesign('axis_of_action', event.target.value)} />
                    <span className="inline-check"><input type="checkbox" checked={design.intentional_axis_crossing} onChange={(event) => updateDesign('intentional_axis_crossing', event.target.checked)} /> Intentional axis crossing</span>
                  </label>
                </div>
              </details>
            ) : null}

            <label>
              <div className="field-label">Negative prompt / exclusions</div>
              <textarea rows={3} value={prompt.negative_prompt} onChange={(event) => updatePrompt('negative_prompt', event.target.value)} />
            </label>

            <div className="field-grid">
              <label>
                <div className="field-label">Aspect ratio override</div>
                <input value={prompt.aspect_ratio_override} onChange={(event) => updatePrompt('aspect_ratio_override', event.target.value)} placeholder="Use project ratio" />
              </label>
              <label>
                <div className="field-label">Variants</div>
                <input type="number" min="1" max="8" value={prompt.variant_count} onChange={(event) => updatePrompt('variant_count', Number(event.target.value))} />
              </label>
            </div>

            <div className="reference-summary">
              <span>{shot.reference_image_paths.length}</span>
              <div><strong>Shot references attached</strong><small>Reference roles and locked bindings are stored separately from prompt prose.</small></div>
            </div>
          </>
        ) : null}

        {activeTab === 'continuity' ? (
          <>
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
                <textarea rows={5} value={continuity.expected_in} onChange={(event) => updateContinuity('expected_in', event.target.value)} />
              </label>
              <label>
                <div className="field-label">Expected out</div>
                <textarea rows={5} value={continuity.expected_out} onChange={(event) => updateContinuity('expected_out', event.target.value)} />
              </label>
              <label>
                <div className="field-label">Preserve (one per line)</div>
                <textarea rows={5} value={preserveText} onChange={(event) => onPreserveChange(event.target.value)} />
              </label>
              <label>
                <div className="field-label">Intentional changes (one per line)</div>
                <textarea rows={5} value={intentionalChangesText} onChange={(event) => onIntentionalChangesChange(event.target.value)} />
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
          </>
        ) : null}

        {activeTab === 'generation' ? (
          <>
            <div className="generation-status-grid">
              <div><small>Execution</small><span className={`status-chip status-${generation.execution_status}`}>{generation.execution_status}</span></div>
              <div><small>Review</small><span className={`status-chip status-${generation.review_status}`}>{generation.review_status}</span></div>
              <div><small>Freshness</small><span className={`status-chip status-${generation.freshness_status}`}>{generation.freshness_status}</span></div>
            </div>
            <div className="inspector-callout generation-boundary">
              Queue execution, retries, approvals, and stale propagation belong to Storyboarder. Codex reads an immutable handoff through MCP and returns candidates for review.
            </div>
            <div className="generation-actions">
              <button
                type="button"
                className="generation-action-primary"
                disabled={dispatchingTo !== null || saving}
                onClick={() => void dispatchGeneration('queue')}
              >
                {dispatchingTo === 'queue' ? 'Adding…' : 'Send to Queue'}
              </button>
              <button
                type="button"
                className="generation-action-codex"
                disabled={dispatchingTo !== null || saving}
                onClick={() => void dispatchGeneration('codex')}
              >
                {dispatchingTo === 'codex' ? 'Preparing…' : 'Send to Codex'}
              </button>
            </div>
            {dirty ? <div className="generation-save-note">Unsaved shot edits will be saved before dispatch.</div> : null}
            {generationNotice ? <div className="generation-notice" role="status">{generationNotice}</div> : null}
            <div className="generation-identifiers">
              <label><span>Latest attempt</span><input value={generation.latest_attempt_id || '—'} readOnly /></label>
              <label><span>Active output</span><input value={generation.active_output_id || '—'} readOnly /></label>
              <label><span>Approved output</span><input value={generation.approved_output_id || '—'} readOnly /></label>
            </div>
            <div className="generation-history-heading">
              <div><strong>Request history</strong><small>Immutable snapshots for this shot</small></div>
              <button type="button" onClick={() => void refreshGenerationResults()} disabled={generationLoading}>
                {generationLoading ? 'Refreshing…' : 'Refresh results'}
              </button>
            </div>
            {generationRequests.length > 0 ? (
              <div className="generation-request-list">
                {generationRequests.map((request) => (
                  <article className="generation-request-row" key={request.request_id}>
                    <div className="generation-request-topline">
                      <span className={`generation-destination generation-destination-${request.destination}`}>
                        {request.destination === 'codex' ? 'Codex' : 'Queue'}
                      </span>
                      <span className={`status-chip status-${request.status}`}>{request.status}</span>
                      <time>{formatGenerationTime(request.created_at)}</time>
                    </div>
                    <code>{request.request_id}</code>
                    <div className="generation-request-meta">
                      <span>{request.scene_bible?.title || 'No Scene Bible'}</span>
                      <span>{request.prompt.variant_count} variant{request.prompt.variant_count === 1 ? '' : 's'}</span>
                      <span>{request.prompt.aspect_ratio}</span>
                      <span>{request.result_count ?? 0} result{request.result_count === 1 ? '' : 's'}</span>
                    </div>
                    {request.latest_result?.artifacts?.length ? (
                      <div className="generation-artifacts">
                        {request.latest_result.artifacts.map((artifact) => (
                          <div className="generation-artifact" key={artifact.project_relative_path}>
                            <a
                              href={projectFileUrl(artifact.project_relative_path)}
                              target="_blank"
                              rel="noreferrer"
                            >
                              {artifact.name}
                            </a>
                            <button
                              type="button"
                              disabled={acceptingArtifact !== ''}
                              onClick={() => void handleUseAsCodexLayer(request, artifact.project_relative_path)}
                            >
                              {acceptingArtifact === artifact.project_relative_path ? 'Using…' : 'Use as Codex layer'}
                            </button>
                          </div>
                        ))}
                      </div>
                    ) : null}
                  </article>
                ))}
              </div>
            ) : (
              <div className="generation-empty-state">
                <strong>No generation requests yet</strong>
                <p>Send this shot to the local queue or create a Codex MCP handoff.</p>
              </div>
            )}
          </>
        ) : null}
      </div>
    </section>
  )
}
