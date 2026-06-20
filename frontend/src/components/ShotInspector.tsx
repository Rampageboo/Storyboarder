import { useMemo, useState } from 'react'
import { useProject } from '../state/useProject'
import './ShotInspector.css'

function toTagsString(tags: string[] | undefined) {
  return (tags || []).join(', ')
}

function fromTagsString(value: string) {
  return value
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean)
}

export function ShotInspector() {
  const { project, selectedShotId, getDraft, editShotField, isShotDirty, savingShots, saveShot } = useProject()

  const shot = useMemo(() => {
    if (!project || !selectedShotId) return null
    return project.shots.find((s) => s.shot_id === selectedShotId) || null
  }, [project, selectedShotId])

  const [prevShotId, setPrevShotId] = useState(selectedShotId)
  const [tagsText, setTagsText] = useState<string>('')
  if (selectedShotId !== prevShotId) {
    setPrevShotId(selectedShotId)
    if (!selectedShotId) {
      setTagsText('')
    } else {
      const current = project?.shots.find((s) => s.shot_id === selectedShotId)
      const draftTags = getDraft(selectedShotId)?.tags
      setTagsText(toTagsString(draftTags ?? current?.tags))
    }
  }

  if (!project) return null

  if (!shot) {
    return (
      <section className="inspector">
        <div className="inspector-empty">
          <p>Select or add a shot</p>
          <p className="inspector-empty-hint">Shot metadata will appear here.</p>
        </div>
      </section>
    )
  }

  const shotId = shot.shot_id
  const draft = getDraft(shotId)
  const saving = !!savingShots[shotId]
  const dirty = isShotDirty(shotId)

  const onTagsChange = (value: string) => {
    setTagsText(value)
    editShotField(shotId, 'tags', fromTagsString(value))
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
        <div className="field-row">
          <label>
            <div className="field-label">Shot ID</div>
            <input value={shot.shot_id} readOnly />
          </label>
        </div>

        <div className="field-grid">
          <label>
            <div className="field-label">Title</div>
            <input value={draft?.title ?? shot.title} onChange={(e) => editShotField(shotId, 'title', e.target.value)} />
          </label>
          <label>
            <div className="field-label">Scene</div>
            <input value={draft?.scene ?? shot.scene} onChange={(e) => editShotField(shotId, 'scene', e.target.value)} />
          </label>
          <label>
            <div className="field-label">Sequence</div>
            <input
              value={draft?.sequence ?? shot.sequence}
              onChange={(e) => editShotField(shotId, 'sequence', e.target.value)}
            />
          </label>
          <label>
            <div className="field-label">Status</div>
            <select
              value={String(draft?.status ?? shot.status ?? 'Draft')}
              onChange={(e) => editShotField(shotId, 'status', e.target.value)}
            >
              {(project.statuses || []).map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </label>
        </div>

        <label>
          <div className="field-label">Description</div>
          <textarea
            rows={3}
            value={draft?.description ?? shot.description}
            onChange={(e) => editShotField(shotId, 'description', e.target.value)}
          />
        </label>

        <div className="field-grid">
          <label>
            <div className="field-label">Action note</div>
            <textarea
              rows={3}
              value={draft?.action_note ?? shot.action_note}
              onChange={(e) => editShotField(shotId, 'action_note', e.target.value)}
            />
          </label>
          <label>
            <div className="field-label">Camera note</div>
            <textarea
              rows={3}
              value={draft?.camera_note ?? shot.camera_note}
              onChange={(e) => editShotField(shotId, 'camera_note', e.target.value)}
            />
          </label>
        </div>

        <div className="field-grid">
          <label>
            <div className="field-label">Character note</div>
            <textarea
              rows={3}
              value={draft?.character_note ?? shot.character_note}
              onChange={(e) => editShotField(shotId, 'character_note', e.target.value)}
            />
          </label>
          <label>
            <div className="field-label">Dialogue</div>
            <textarea
              rows={3}
              value={draft?.dialogue ?? shot.dialogue}
              onChange={(e) => editShotField(shotId, 'dialogue', e.target.value)}
            />
          </label>
        </div>

        <div className="field-grid">
          <label>
            <div className="field-label">Lighting note</div>
            <textarea
              rows={3}
              value={draft?.lighting_note ?? shot.lighting_note}
              onChange={(e) => editShotField(shotId, 'lighting_note', e.target.value)}
            />
          </label>
          <label>
            <div className="field-label">Transition note</div>
            <textarea
              rows={3}
              value={draft?.transition_note ?? shot.transition_note}
              onChange={(e) => editShotField(shotId, 'transition_note', e.target.value)}
            />
          </label>
        </div>

        <div className="field-grid">
          <label>
            <div className="field-label">Duration (seconds)</div>
            <input
              type="number"
              step="0.1"
              min="0"
              value={String(draft?.duration_seconds ?? shot.duration_seconds ?? 3)}
              onChange={(e) => editShotField(shotId, 'duration_seconds', Number(e.target.value))}
            />
          </label>
          <label>
            <div className="field-label">Tags</div>
            <input value={tagsText} onChange={(e) => onTagsChange(e.target.value)} placeholder="tag1, tag2" />
          </label>
        </div>
      </div>
    </section>
  )
}
