import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  getAnnotations,
  getBridgeStatus,
  openBlenderScene,
  recoverShotSource,
  relinkPreview,
  saveAnnotations,
  uploadShotReference,
  uploadShotSource,
} from '../api'
import { useProject } from '../state/ProjectContext'
import './AdvancedPanel.css'

export function AdvancedPanel() {
  const { project, selectedShotId, setProject, flushDirtyShots, projectActionBusy, reportError } = useProject()
  const [open, setOpen] = useState(false)
  const [annotationsJson, setAnnotationsJson] = useState('')
  const [bridgeJson, setBridgeJson] = useState('')
  const [scene3dJson, setScene3dJson] = useState('')
  const [busy, setBusy] = useState(false)
  const [sourceNote, setSourceNote] = useState('')
  const [relinkPath, setRelinkPath] = useState('')
  const sourceInputRef = useRef<HTMLInputElement | null>(null)
  const referenceInputRef = useRef<HTMLInputElement | null>(null)

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

  useEffect(() => {
    setAnnotationsJson('')
    setSourceNote('')
    const current = project?.shots.find((s) => s.shot_id === selectedShotId)
    setRelinkPath(current?.preview_image_path || current?.image_path || '')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedShotId])

  const loadAnnotations = useCallback(async () => {
    if (!selectedShotId) return
    setBusy(true)
    try {
      const payload = await getAnnotations(selectedShotId)
      setAnnotationsJson(JSON.stringify(payload, null, 2))
    } finally {
      setBusy(false)
    }
  }, [selectedShotId])

  const persistAnnotations = useCallback(async () => {
    if (!selectedShotId) return
    let parsed: unknown
    try {
      parsed = annotationsJson ? JSON.parse(annotationsJson) : {}
    } catch {
      window.alert('Invalid annotations JSON.')
      return
    }
    const annotations = (parsed as { annotations?: unknown }).annotations
    if (!Array.isArray(annotations)) {
      window.alert('JSON must include annotations: []')
      return
    }
    setBusy(true)
    try {
      const saved = await saveAnnotations(selectedShotId, { annotations: annotations as Record<string, unknown>[] })
      setAnnotationsJson(JSON.stringify(saved, null, 2))
    } finally {
      setBusy(false)
    }
  }, [selectedShotId, annotationsJson])

  const refreshBridge = useCallback(async () => {
    setBusy(true)
    try {
      const payload = await getBridgeStatus()
      setBridgeJson(JSON.stringify(payload, null, 2))
    } finally {
      setBusy(false)
    }
  }, [])

  const openBlender = useCallback(async () => {
    setBusy(true)
    try {
      const payload = await openBlenderScene()
      setScene3dJson(JSON.stringify(payload, null, 2))
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
        const payload = await uploadShotSource(selectedShotId, file)
        setProject(payload)
      } catch (error) {
        reportError(error)
      } finally {
        setBusy(false)
      }
    },
    [selectedShotId, setProject, flushDirtyShots],
  )

  const uploadReference = useCallback(
    async (file?: File) => {
      if (!selectedShotId || !file) return
      setBusy(true)
      try {
        await flushDirtyShots()
        const payload = await uploadShotReference(selectedShotId, file)
        setProject(payload)
      } catch (error) {
        reportError(error)
      } finally {
        setBusy(false)
      }
    },
    [selectedShotId, setProject, flushDirtyShots],
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
      const payload = await relinkPreview(selectedShotId, { relative_path: relative })
      setProject(payload)
      setSourceNote('Preview relinked.')
    } catch (error) {
      reportError(error)
    } finally {
      setBusy(false)
    }
  }, [selectedShotId, relinkPath, setProject, flushDirtyShots, reportError])

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
              <button type="button" onClick={() => referenceInputRef.current?.click()} disabled={!hasShot || disabled}>
                Add reference
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
            <input
              ref={referenceInputRef}
              type="file"
              accept="image/*"
              hidden
              onChange={(e) => {
                const file = e.target.files?.[0]
                void uploadReference(file ?? undefined)
                e.target.value = ''
              }}
            />
          </div>

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

          <details className="advanced-details">
            <summary>Annotations JSON</summary>
            <div className="advanced-actions">
              <button type="button" onClick={() => void loadAnnotations()} disabled={!hasShot || disabled}>
                Load
              </button>
              <button type="button" onClick={() => void persistAnnotations()} disabled={!hasShot || disabled}>
                Save
              </button>
            </div>
            <textarea
              className="advanced-textarea"
              rows={6}
              value={annotationsJson}
              onChange={(e) => setAnnotationsJson(e.target.value)}
              placeholder={hasShot ? 'Load annotations from server' : 'Select a shot first'}
            />
          </details>

          <details className="advanced-details">
            <summary>3D / Blender</summary>
            <div className="advanced-actions">
              <button type="button" onClick={() => void openBlender()} disabled={disabled}>
                Open Blender scene
              </button>
            </div>
            {scene3dJson ? <pre className="advanced-pre">{scene3dJson}</pre> : null}
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
