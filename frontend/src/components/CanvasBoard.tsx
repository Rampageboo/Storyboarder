import { useEffect, useMemo, useRef, useState } from 'react'
import {
  createShotCanvas,
  openShotPreview,
  openShotSource,
  removeShotImage,
  shotImageUrl,
  syncShot,
  uploadShotImage,
} from '../api'
import { useProject } from '../state/ProjectContext'
import './CanvasBoard.css'

type SyncResult = { synced?: boolean; message?: string }

export function CanvasBoard() {
  const { project, selectedShotId, setProject, flushDirtyShots, projectActionBusy, reportError } = useProject()
  const [bust, setBust] = useState(0)
  const [loadFailed, setLoadFailed] = useState(false)
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState('')
  const fileInputRef = useRef<HTMLInputElement | null>(null)

  const shot = useMemo(() => {
    if (!project || !selectedShotId) return null
    return project.shots.find((s) => s.shot_id === selectedShotId) || null
  }, [project, selectedShotId])

  const hasImage = !!shot?.image_path && !loadFailed
  const hasSource = !!shot?.source_file_path
  const hasPreview = !!(shot?.preview_image_path || shot?.image_path)

  const imgSrc = useMemo(() => {
    if (!shot || !shot.image_path) return ''
    const v = shot.preview_disk_mtime || shot.thumbnail_disk_mtime || bust || Date.now()
    return `${shotImageUrl(shot.shot_id)}?v=${encodeURIComponent(String(v))}`
  }, [shot, bust])

  // Clear the failed-load flag whenever the preview identity changes — a new shot, or the preview
  // being replaced by sync/upload/recover/relink elsewhere — so the fresh image gets a chance to load.
  useEffect(() => {
    setLoadFailed(false)
  }, [selectedShotId, shot?.image_path, shot?.preview_disk_mtime])

  // Action notes are per-shot; drop them when the selection changes.
  useEffect(() => {
    setNote('')
  }, [selectedShotId])

  const disabled = busy || projectActionBusy

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
      reportError(error)
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
      reportError(error)
    } finally {
      setBusy(false)
    }
  }

  // --- Photoshop / source-preview workflow -------------------------------------------

  // Open the shot's source in Photoshop. Mirrors the legacy flow: if no source is linked yet,
  // create a blank canvas first so there is something to open.
  const handleOpenInPhotoshop = async () => {
    if (!shot) return
    const shotId = shot.shot_id
    setBusy(true)
    try {
      await flushDirtyShots()
      if (!shot.source_file_path) {
        setProject(await createShotCanvas(shotId, {}))
      }
      const result = await openShotSource(shotId)
      setNote(
        result.switched === 'true'
          ? 'Switched to the tab already open in Photoshop.'
          : `Opened in Photoshop: ${result.path ?? ''}`,
      )
    } catch (error) {
      reportError(error)
    } finally {
      setBusy(false)
    }
  }

  // Pull the latest preview from the linked source (replaces project state → flush first).
  const handleSync = async () => {
    if (!shot) return
    setBusy(true)
    try {
      await flushDirtyShots()
      const payload = await syncShot(shot.shot_id)
      setProject(payload)
      setLoadFailed(false)
      setBust((x) => x + 1)
      const result = (payload as unknown as { result?: SyncResult }).result
      setNote(result?.message || (result?.synced ? 'Synced preview from Photoshop.' : 'No changes to sync.'))
    } catch (error) {
      reportError(error)
    } finally {
      setBusy(false)
    }
  }

  const handleOpenPreview = async () => {
    if (!shot) return
    setBusy(true)
    try {
      const result = await openShotPreview(shot.shot_id)
      setNote(`Opened: ${result.path ?? ''}`)
    } catch (error) {
      reportError(error)
    } finally {
      setBusy(false)
    }
  }

  const handleCreateCanvas = async () => {
    if (!shot) return
    setBusy(true)
    try {
      await flushDirtyShots()
      const payload = await createShotCanvas(shot.shot_id, {})
      setProject(payload)
      setLoadFailed(false)
      setBust((x) => x + 1)
      setNote('Blank canvas created.')
    } catch (error) {
      reportError(error)
    } finally {
      setBusy(false)
    }
  }

  if (!project) {
    return (
      <div className="canvas canvas-empty-state">
        <p>No project open</p>
      </div>
    )
  }

  if (!shot) {
    return (
      <div className="canvas canvas-empty-state">
        <p>Select or add a shot</p>
        <p className="canvas-empty-hint">Choose a shot from the list on the left.</p>
      </div>
    )
  }

  return (
    <div className="canvas">
      <div className="canvas-header">
        <div>
          <div className="canvas-title">Preview</div>
          <div className="canvas-subtitle">{shot.title || shot.shot_id}</div>
        </div>
        <div className="canvas-actions">
          <button type="button" className="primary" onClick={() => fileInputRef.current?.click()} disabled={disabled}>
            {busy ? 'Working…' : 'Upload image'}
          </button>
          <button type="button" onClick={() => void handleDelete()} disabled={disabled || !shot.image_path}>
            Delete image
          </button>
          <button
            type="button"
            className="subtle"
            onClick={() => {
              setLoadFailed(false)
              setBust((x) => x + 1)
            }}
            disabled={disabled || !shot.image_path}
            title="Reload preview from server"
          >
            Refresh
          </button>
        </div>
        <input
          ref={fileInputRef}
          type="file"
          accept="image/*"
          hidden
          onChange={(e) => {
            const file = e.target.files?.[0]
            void handleUpload(file ?? undefined)
            e.target.value = ''
          }}
        />
      </div>

      <div className="canvas-actions canvas-actions-ps">
        <button
          type="button"
          onClick={() => void handleOpenInPhotoshop()}
          disabled={disabled}
          title="Open the shot's source in Photoshop (creates a blank canvas if none exists)"
        >
          Open in Photoshop
        </button>
        <button
          type="button"
          onClick={() => void handleSync()}
          disabled={disabled || !hasSource}
          title="Sync the preview from the linked source file"
        >
          Sync
        </button>
        <button
          type="button"
          onClick={() => void handleOpenPreview()}
          disabled={disabled || !hasPreview}
          title="Open the preview image externally"
        >
          Open preview
        </button>
      </div>
      {note ? <div className="canvas-note">{note}</div> : null}

      <div className="canvas-body">
        {hasImage ? (
          <img
            className="canvas-image"
            src={imgSrc}
            alt={shot.title || shot.shot_id}
            onError={() => setLoadFailed(true)}
            onLoad={() => setLoadFailed(false)}
          />
        ) : (
          <div className="canvas-placeholder">
            <p>No preview image</p>
            <div className="canvas-actions">
              <button type="button" className="primary" onClick={() => fileInputRef.current?.click()} disabled={disabled}>
                Upload image
              </button>
              {!hasSource ? (
                <button type="button" onClick={() => void handleCreateCanvas()} disabled={disabled}>
                  Create blank canvas
                </button>
              ) : null}
            </div>
          </div>
        )}
      </div>
      {shot.source_file_path ? (
        <div className="canvas-footer">Source: {shot.source_file_path.split(/[/\\]/).pop()}</div>
      ) : null}
    </div>
  )
}
