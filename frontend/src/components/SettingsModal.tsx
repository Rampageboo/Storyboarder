import { useCallback, useEffect, useState } from 'react'
import { updateSettings } from '../api'
import { useProject } from '../state/useProject'
import './SettingsModal.css'

interface SettingsModalProps {
  open: boolean
  onClose: () => void
}

export function SettingsModal({ open, onClose }: SettingsModalProps) {
  const { project, setProject, flushDirtyShots, projectActionBusy, reportError } = useProject()
  const [canvasColor, setCanvasColor] = useState('#E8E8E8')
  const [preheatPhotoshop, setPreheatPhotoshop] = useState(false)
  const [characterBiblePrompt, setCharacterBiblePrompt] = useState('')
  const [saving, setSaving] = useState(false)
  const [note, setNote] = useState('')

  useEffect(() => {
    if (!project || !open) return
    setCanvasColor(String(project.settings?.canvas_background_color ?? '#E8E8E8'))
    setPreheatPhotoshop(Boolean(project.settings?.preheat_photoshop_on_open))
    setCharacterBiblePrompt(String(project.settings?.character_bible_prompt ?? ''))
  }, [project, open])

  const closeModal = useCallback(() => {
    setNote('')
    onClose()
  }, [onClose])

  const saveSettings = useCallback(async () => {
    if (!project) return
    const color = canvasColor.trim()
    if (!color) {
      window.alert('Canvas background color cannot be empty.')
      return
    }
    setSaving(true)
    try {
      await flushDirtyShots()
      setProject(
        await updateSettings({
          canvas_background_color: color,
          preheat_photoshop_on_open: preheatPhotoshop,
          character_bible_prompt: characterBiblePrompt,
        }),
      )
      setNote('Settings saved.')
    } catch (error) {
      reportError(error)
    } finally {
      setSaving(false)
    }
  }, [project, canvasColor, preheatPhotoshop, characterBiblePrompt, flushDirtyShots, setProject, reportError])

  if (!open || !project) return null

  const disabled = saving || projectActionBusy

  return (
    <div className="settings-modal-backdrop" role="presentation" onMouseDown={closeModal}>
      <section
        className="settings-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="settings-modal-title"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="settings-modal-header">
          <div>
            <h2 id="settings-modal-title">Settings</h2>
            <p>Project defaults, startup behavior, and global character identity.</p>
          </div>
          <button type="button" className="settings-modal-close" onClick={closeModal} aria-label="Close settings">
            x
          </button>
        </div>

        <div className="settings-modal-body">
          <label className="settings-field">
            <span>Canvas background color</span>
            <div className="settings-color-row">
              <input
                type="color"
                value={/^#[0-9a-fA-F]{6}$/.test(canvasColor) ? canvasColor : '#E8E8E8'}
                onChange={(event) => setCanvasColor(event.target.value)}
                disabled={disabled}
              />
              <input
                value={canvasColor}
                onChange={(event) => setCanvasColor(event.target.value)}
                placeholder="#E8E8E8"
                disabled={disabled}
              />
            </div>
          </label>

          <label className="settings-checkbox">
            <input
              type="checkbox"
              checked={preheatPhotoshop}
              onChange={(event) => setPreheatPhotoshop(event.target.checked)}
              disabled={disabled}
            />
            <span>Preheat Photoshop when Storyboarder opens</span>
          </label>

          <label className="settings-field">
            <span>Character Bible</span>
            <textarea
              value={characterBiblePrompt}
              onChange={(event) => setCharacterBiblePrompt(event.target.value)}
              rows={7}
              disabled={disabled}
              placeholder="Define stable identity and wardrobe for recurring characters. Example: MAYA — short black bob, amber coat, silver watch."
            />
            <small>Project-wide identity only. A shot still decides which characters appear, their action, and expression.</small>
          </label>
        </div>

        <div className="settings-modal-footer">
          {note ? <span className="settings-note">{note}</span> : null}
          <button type="button" onClick={closeModal} disabled={disabled}>
            Cancel
          </button>
          <button type="button" className="primary" onClick={() => void saveSettings()} disabled={disabled}>
            {saving ? 'Saving...' : 'Save settings'}
          </button>
        </div>
      </section>
    </div>
  )
}
