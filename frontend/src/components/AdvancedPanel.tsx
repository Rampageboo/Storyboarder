import { useCallback, useMemo, useRef, useState } from 'react'
import {
  getBridgeStatus,
  recoverShotSource,
  relinkPreview,
  updateSettings,
  uploadShotSource,
} from '../api'
import { useProject } from '../state/useProject'
import { AnnotationList } from './AnnotationList'
import './AdvancedPanel.css'

export function AdvancedPanel() {
  const { project, selectedShotId, setProject, flushDirtyShots, projectActionBusy, reportError } = useProject()
  const [open, setOpen] = useState(false)
  const [bridgeJson, setBridgeJson] = useState('')
  const [busy, setBusy] = useState(false)
  const [sourceNote, setSourceNote] = useState('')
  const [relinkPath, setRelinkPath] = useState('')
  const [canvasW, setCanvasW] = useState('1920')
  const [canvasH, setCanvasH] = useState('1080')
  const [canvasColor, setCanvasColor] = useState('#E8E8E8')
  const [canvasNote, setCanvasNote] = useState('')
  const sourceInputRef = useRef<HTMLInputElement | null>(null)

  // Reset per-shot form fields when the selected shot changes.
  const [prevShotId, setPrevShotId] = useState(selectedShotId)
  if (selectedShotId !== prevShotId) {
    setPrevShotId(selectedShotId)
    setSourceNote('')
    const cur = project?.shots.find((s) => s.shot_id === selectedShotId)
    setRelinkPath(cur?.preview_image_path || cur?.image_path || '')
  }

  // Re-seed canvas defaults when project settings change on disk.
  const settingsKey = `${project?.settings?.canvas_width}:${project?.settings?.canvas_height}:${project?.settings?.canvas_background_color}`
  const [prevSettingsKey, setPrevSettingsKey] = useState(settingsKey)
  if (settingsKey !== prevSettingsKey) {
    setPrevSettingsKey(settingsKey)
    const s = project?.settings
    setCanvasW(String(s?.canvas_width ?? 1920))
    setCanvasH(String(s?.canvas_height ?? 1080))
    setCanvasColor(String(s?.canvas_background_color ?? '#E8E8E8'))
  }

  const shot = useMemo(() => {
    if (!project || !selectedShotId) return null
    return project.shots.find((s) => s.shot_id === selectedShotId) || null
  }, [project, selectedShotId])

  const hasShot = Boolean(project && selectedShotId)
  const disabled = busy || projectActionBusy

  const refSegmentsCount = useMemo(() => {
    const segments = project?.settings?.ref_segments
    return Array.isArray(segments) ? segments.length : 0
  }, [project?.settings])

  const refreshBridge = useCallback(async () => {
    setBusy(true)
    try {
      const payload = await getBridgeStatus()
      setBridgeJson(JSON.stringify(payload, null, 2))
    } finally {
      setBusy(false)
    }
  }, [])

  const uploadSource = useCallback(
    async (file?: File) => {
      if (!selectedShotId || !file) return
      setBusy(true)
      try {
        await flushDirtyShots()
        setProject(await uploadShotSource(selectedShotId, file))
      } catch (error) {
        reportError(error)
      } finally {
        setBusy(false)
      }
    },
    [selectedShotId, setProject, flushDirtyShots, reportError],
  )

  const recoverSource = useCallback(async () => {
    if (!selectedShotId) return
    if (!window.confirm('Rebuild the source PSD from its layers? A backup is saved to _history/.')) return
    setBusy(true)
    try {
      await flushDirtyShots()
      const payload = await recoverShotSource(selectedShotId)
      setProject(payload)
      const result = (payload as unknown as { result?: { layers_recovered?: number } }).result
      setSourceNote(`Recovered: ${result?.layers_recovered ?? '?'} layer(s). Backup in _history/.`)
    } catch (error) {
      reportError(error)
    } finally {
      setBusy(false)
    }
  }, [selectedShotId, setProject, flushDirtyShots, reportError])

  const doRelinkPreview = useCallback(async () => {
    if (!selectedShotId) return
    const relative = relinkPath.trim()
    if (!relative) return
    setBusy(true)
    try {
      await flushDirtyShots()
      setProject(await relinkPreview(selectedShotId, { relative_path: relative }))
      setSourceNote('Preview relinked.')
    } catch (error) {
      reportError(error)
    } finally {
      setBusy(false)
    }
  }, [selectedShotId, relinkPath, setProject, flushDirtyShots, reportError])

  // Edit the project-wide canvas defaults used by "Create blank canvas". Basic guards only.
  const saveCanvasDefaults = useCallback(async () => {
    const w = Number(canvasW)
    const h = Number(canvasH)
    const color = canvasColor.trim()
    if (!Number.isInteger(w) || w <= 0 || !Number.isInteger(h) || h <= 0) {
      window.alert('Canvas width and height must be positive whole numbers.')
      return
    }
    if (!color) {
      window.alert('Canvas background color cannot be empty.')
      return
    }
    setBusy(true)
    try {
      await flushDirtyShots()
      setProject(await updateSettings({ canvas_width: w, canvas_height: h, canvas_background_color: color }))
      setCanvasNote(`Saved: ${w}×${h}, ${color}`)
    } catch (error) {
      reportError(error)
    } finally {
      setBusy(false)
    }
  }, [canvasW, canvasH, canvasColor, flushDirtyShots, setProject, reportError])

  if (!project) return null

  return (
    <section className={`advanced ${open ? 'is-open' : ''}`}>
      <button type="button" className="advanced-toggle" onClick={() => setOpen((v) => !v)}>
        <span>Advanced</span>
        <span className="advanced-toggle-icon">{open ? '▾' : '▸'}</span>
      </button>

      {open ? (
        <div className="advanced-body">
          <div className="advanced-section">
            <div className="advanced-section-title">Shot files</div>
            <div className="advanced-actions">
              <button type="button" onClick={() => sourceInputRef.current?.click()} disabled={!hasShot || disabled}>
                Upload PSD/source
              </button>
            </div>
            <input
              ref={sourceInputRef}
              type="file"
              hidden
              accept=".psd,image/*"
              onChange={(e) => {
                const file = e.target.files?.[0]
                void uploadSource(file ?? undefined)
                e.target.value = ''
              }}
            />
          </div>

          <details className="advanced-details">
            <summary>Canvas defaults</summary>
            <div className="advanced-fields">
              <label className="advanced-field">
                <span>Width</span>
                <input
                  className="advanced-input"
                  type="number"
                  min="1"
                  step="1"
                  value={canvasW}
                  onChange={(e) => setCanvasW(e.target.value)}
                />
              </label>
              <label className="advanced-field">
                <span>Height</span>
                <input
                  className="advanced-input"
                  type="number"
                  min="1"
                  step="1"
                  value={canvasH}
                  onChange={(e) => setCanvasH(e.target.value)}
                />
              </label>
              <label className="advanced-field">
                <span>Background</span>
                <input
                  className="advanced-input"
                  value={canvasColor}
                  onChange={(e) => setCanvasColor(e.target.value)}
                  placeholder="#E8E8E8"
                />
              </label>
            </div>
            <div className="advanced-actions">
              <button type="button" onClick={() => void saveCanvasDefaults()} disabled={disabled}>
                Save canvas defaults
              </button>
            </div>
            <div className="advanced-muted">Used when creating a new blank canvas for a shot.</div>
            {canvasNote ? <div className="advanced-muted">{canvasNote}</div> : null}
          </details>

          <details className="advanced-details">
            <summary>Annotations</summary>
            <AnnotationList key={selectedShotId ?? 'none'} shotId={selectedShotId} />
          </details>

          <details className="advanced-details">
            <summary>Photoshop source repair</summary>
            <div className="advanced-actions">
              <button
                type="button"
                onClick={() => void recoverSource()}
                disabled={!hasShot || disabled || !shot?.source_file_path}
                title="Rebuild a Photoshop-unopenable source PSD from its layers"
              >
                Recover source
              </button>
            </div>
            <input
              className="advanced-input"
              value={relinkPath}
              onChange={(e) => setRelinkPath(e.target.value)}
              placeholder="shots/shot_001/shot_001_preview.png"
            />
            <div className="advanced-actions">
              <button
                type="button"
                onClick={() => void doRelinkPreview()}
                disabled={!hasShot || disabled || !relinkPath.trim()}
                title="Point this shot's preview at a project-relative file"
              >
                Relink preview
              </button>
            </div>
            {sourceNote ? <div className="advanced-muted">{sourceNote}</div> : null}
          </details>

          <div className="advanced-muted">Reference segments: {refSegmentsCount}</div>

          <details className="advanced-details">
            <summary>Photoshop bridge status</summary>
            <div className="advanced-actions">
              <button type="button" onClick={() => void refreshBridge()} disabled={disabled}>
                Refresh
              </button>
            </div>
            {bridgeJson ? <pre className="advanced-pre">{bridgeJson}</pre> : null}
          </details>
        </div>
      ) : null}
    </section>
  )
}
