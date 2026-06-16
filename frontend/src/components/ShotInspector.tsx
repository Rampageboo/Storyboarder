import { useCallback, useEffect, useMemo, useState } from 'react'
import { updateShot } from '../api'
import type { ShotUpdate } from '../types'
import { useProject } from '../state/ProjectContext'
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
  const { project, selectedShotId, setProject } = useProject()

  const shot = useMemo(() => {
    if (!project || !selectedShotId) return null
    return project.shots.find((s) => s.shot_id === selectedShotId) || null
  }, [project, selectedShotId])

  const [draft, setDraft] = useState<ShotUpdate | null>(null)
  const [tagsText, setTagsText] = useState<string>('')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (!shot) {
      setDraft(null)
      setTagsText('')
      return
    }
    setDraft({
      title: shot.title,
      scene: shot.scene,
      sequence: shot.sequence,
      status: shot.status,
      description: shot.description,
      action_note: shot.action_note,
      camera_note: shot.camera_note,
      character_note: shot.character_note,
      dialogue: shot.dialogue,
      lighting_note: shot.lighting_note,
      transition_note: shot.transition_note,
      duration_seconds: shot.duration_seconds,
      camera_data: shot.camera_data,
      tags: shot.tags,
    })
    setTagsText(toTagsString(shot.tags))
  }, [shot])

  const updateField = useCallback(<K extends keyof ShotUpdate>(key: K, value: ShotUpdate[K]) => {
    setDraft((prev) => ({ ...(prev || {}), [key]: value }))
  }, [])

  const save = useCallback(async () => {
    if (!shot || !draft) return
    setSaving(true)
    try {
      const payload = await updateShot(shot.shot_id, { ...draft, tags: fromTagsString(tagsText) })
      setProject(payload)
    } finally {
      setSaving(false)
    }
  }, [shot, draft, tagsText, setProject])

  if (!project) {
    return (
      <section className="inspector">
        <div className="inspector-empty">No project open</div>
      </section>
    )
  }

  if (!shot || !draft) {
    return (
      <section className="inspector">
        <div className="inspector-empty">No shot selected</div>
      </section>
    )
  }

  return (
    <section className="inspector">
      <div className="inspector-header">
        <div className="inspector-title">Shot Inspector</div>
        <div className="inspector-actions">
          <button type="button" onClick={save} disabled={saving}>
            {saving ? 'Saving…' : 'Save'}
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
            <input value={draft.title ?? ''} onChange={(e) => updateField('title', e.target.value)} />
          </label>
          <label>
            <div className="field-label">Scene</div>
            <input value={draft.scene ?? ''} onChange={(e) => updateField('scene', e.target.value)} />
          </label>
          <label>
            <div className="field-label">Sequence</div>
            <input value={draft.sequence ?? ''} onChange={(e) => updateField('sequence', e.target.value)} />
          </label>
          <label>
            <div className="field-label">Status</div>
            <select value={String(draft.status ?? 'Draft')} onChange={(e) => updateField('status', e.target.value)}>
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
            value={draft.description ?? ''}
            onChange={(e) => updateField('description', e.target.value)}
          />
        </label>

        <div className="field-grid">
          <label>
            <div className="field-label">Action note</div>
            <textarea
              rows={3}
              value={draft.action_note ?? ''}
              onChange={(e) => updateField('action_note', e.target.value)}
            />
          </label>
          <label>
            <div className="field-label">Camera note</div>
            <textarea
              rows={3}
              value={draft.camera_note ?? ''}
              onChange={(e) => updateField('camera_note', e.target.value)}
            />
          </label>
        </div>

        <div className="field-grid">
          <label>
            <div className="field-label">Character note</div>
            <textarea
              rows={3}
              value={draft.character_note ?? ''}
              onChange={(e) => updateField('character_note', e.target.value)}
            />
          </label>
          <label>
            <div className="field-label">Dialogue</div>
            <textarea rows={3} value={draft.dialogue ?? ''} onChange={(e) => updateField('dialogue', e.target.value)} />
          </label>
        </div>

        <div className="field-grid">
          <label>
            <div className="field-label">Lighting note</div>
            <textarea
              rows={3}
              value={draft.lighting_note ?? ''}
              onChange={(e) => updateField('lighting_note', e.target.value)}
            />
          </label>
          <label>
            <div className="field-label">Transition note</div>
            <textarea
              rows={3}
              value={draft.transition_note ?? ''}
              onChange={(e) => updateField('transition_note', e.target.value)}
            />
          </label>
        </div>

        <div className="field-grid">
          <label>
            <div className="field-label">Duration (seconds)</div>
            <input
              type="number"
              step="0.1"
              value={String(draft.duration_seconds ?? 3)}
              onChange={(e) => updateField('duration_seconds', Number(e.target.value))}
            />
          </label>
          <label>
            <div className="field-label">Tags</div>
            <input value={tagsText} onChange={(e) => setTagsText(e.target.value)} placeholder="tag1, tag2" />
          </label>
        </div>
      </div>
    </section>
  )
}

