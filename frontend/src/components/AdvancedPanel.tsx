import { useCallback, useEffect, useMemo, useState } from 'react'
import { getAnnotations, getBridgeStatus, openBlenderScene, saveAnnotations } from '../api'
import { useProject } from '../state/ProjectContext'
import './AdvancedPanel.css'

export function AdvancedPanel() {
  const { project, selectedShotId, setProject } = useProject()
  const [annotationsJson, setAnnotationsJson] = useState('')
  const [bridgeJson, setBridgeJson] = useState('')
  const [scene3dJson, setScene3dJson] = useState('')
  const [busy, setBusy] = useState(false)

  const hasShot = Boolean(project && selectedShotId)

  const refSegmentsCount = useMemo(() => {
    const segments = project?.settings?.ref_segments
    return Array.isArray(segments) ? segments.length : 0
  }, [project?.settings])

  useEffect(() => {
    setAnnotationsJson('')
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
    } catch (e) {
      window.alert('Annotations JSON 解析失败，请检查格式。')
      return
    }
    const annotations = (parsed as { annotations?: unknown }).annotations
    if (!Array.isArray(annotations)) {
      window.alert('Annotations JSON 必须包含 annotations: []')
      return
    }
    setBusy(true)
    try {
      const payload = await saveAnnotations(selectedShotId, { annotations: annotations as Record<string, unknown>[] })
      setProject(payload)
    } finally {
      setBusy(false)
    }
  }, [selectedShotId, annotationsJson, setProject])

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

  return (
    <section className="advanced">
      <div className="advanced-header">
        <div className="advanced-title">Advanced</div>
      </div>

      <div className="advanced-body">
        <div className="advanced-section">
          <div className="advanced-section-title">Annotations (basic JSON)</div>
          <div className="advanced-actions">
            <button type="button" onClick={loadAnnotations} disabled={!hasShot || busy}>
              Load
            </button>
            <button type="button" onClick={persistAnnotations} disabled={!hasShot || busy}>
              Save
            </button>
          </div>
          <textarea
            className="advanced-textarea"
            value={annotationsJson}
            onChange={(e) => setAnnotationsJson(e.target.value)}
            placeholder={hasShot ? 'Click Load to fetch /api/shots/{id}/annotations' : 'Select a shot first'}
          />
        </div>

        <div className="advanced-section">
          <div className="advanced-section-title">3D Scene</div>
          <div className="advanced-actions">
            <button type="button" onClick={openBlender} disabled={!project || busy}>
              Open Blender scene (API)
            </button>
          </div>
          <pre className="advanced-pre">{scene3dJson || '—'}</pre>
        </div>

        <div className="advanced-section">
          <div className="advanced-section-title">Reference segments</div>
          <div className="advanced-muted">ref_segments: {refSegmentsCount}</div>
        </div>

        <div className="advanced-section">
          <div className="advanced-section-title">Photoshop bridge (status)</div>
          <div className="advanced-actions">
            <button type="button" onClick={refreshBridge} disabled={busy}>
              Refresh status
            </button>
          </div>
          <pre className="advanced-pre">{bridgeJson || '—'}</pre>
        </div>
      </div>
    </section>
  )
}

