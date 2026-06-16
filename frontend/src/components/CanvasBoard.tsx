import { useMemo, useRef, useState } from 'react'
import { removeShotImage, shotImageUrl, uploadShotImage } from '../api'
import { useProject } from '../state/ProjectContext'
import './CanvasBoard.css'

export function CanvasBoard() {
  const { project, selectedShotId, setProject, flushDirtyShots } = useProject()
  const [bust, setBust] = useState(0)
  const [loadFailed, setLoadFailed] = useState(false)
  const [busy, setBusy] = useState(false)
  const fileInputRef = useRef<HTMLInputElement | null>(null)

  const shot = useMemo(() => {
    if (!project || !selectedShotId) return null
    return project.shots.find((s) => s.shot_id === selectedShotId) || null
  }, [project, selectedShotId])

  const imgSrc = useMemo(() => {
    if (!shot) return ''
    const v = shot.preview_disk_mtime || shot.thumbnail_disk_mtime || bust || Date.now()
    return `${shotImageUrl(shot.shot_id)}?v=${encodeURIComponent(String(v))}`
  }, [shot, bust])

  const handleUpload = async (file: File | undefined) => {
    if (!shot || !file) return
    setBusy(true)
    try {
      await flushDirtyShots()
      const payload = await uploadShotImage(shot.shot_id, file)
      setProject(payload)
      setLoadFailed(false)
      setBust((x) => x + 1)
    } catch (error) {
      window.alert(error instanceof Error ? error.message : String(error))
    } finally {
      setBusy(false)
    }
  }

  const handleDelete = async () => {
    if (!shot) return
    if (!window.confirm('Delete the preview image for this shot?')) return
    setBusy(true)
    try {
      await flushDirtyShots()
      const payload = await removeShotImage(shot.shot_id)
      setProject(payload)
      setLoadFailed(false)
      setBust((x) => x + 1)
    } catch (error) {
      window.alert(error instanceof Error ? error.message : String(error))
    } finally {
      setBusy(false)
    }
  }

  if (!project) {
    return <div className="canvas-empty">No project open</div>
  }
  if (!shot) {
    return <div className="canvas-empty">No shot selected</div>
  }

  return (
    <div className="canvas">
      <div className="canvas-header">
        <div className="canvas-title">Canvas</div>
        <div className="canvas-actions">
          <button type="button" onClick={() => fileInputRef.current?.click()} disabled={busy}>
            Upload image
          </button>
          <button type="button" onClick={() => void handleDelete()} disabled={busy || !shot.image_path}>
            Delete image
          </button>
          <button
            type="button"
            onClick={() => {
              setLoadFailed(false)
              setBust((x) => x + 1)
            }}
          >
            Refresh
          </button>
        </div>
        <input
          ref={fileInputRef}
          type="file"
          accept="image/*"
          style={{ display: 'none' }}
          onChange={(e) => {
            const file = e.target.files?.[0]
            void handleUpload(file ?? undefined)
            e.target.value = ''
          }}
        />
      </div>
      <div className="canvas-body">
        {loadFailed || !shot.image_path ? (
          <div className="canvas-placeholder">No preview</div>
        ) : (
          <img
            className="canvas-image"
            src={imgSrc}
            alt=""
            onError={() => setLoadFailed(true)}
            onLoad={() => setLoadFailed(false)}
          />
        )}
      </div>
    </div>
  )
}
