import { useEffect, useMemo, useRef, useState } from 'react'
import {
  createShotCanvas,
  openShotPreview,
  openShotSource,
  removeShotImage,
  shotImageUrl,
  syncShot,
  uploadShotImage,
  uploadShotSource,
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
  const imageInputRef = useRef<HTMLInputElement | null>(null)
  const sourceInputRef = useRef<HTMLInputElement | null>(null)

  const shot = useMemo(() => {
    if (!project || !selectedShotId) return null
    return project.shots.find((s) => s.shot_id === selectedShotId) || null
  }, [project, selectedShotId])

  const sourcePath = shot?.source_file_path || ''
  const previewPath = shot?.preview_image_path || shot?.image_path || ''
  const hasSource = !!sourcePath
  const hasPreview = !!previewPath
  const hasImage = !!shot?.image_path && !loadFailed

  const imgSrc = useMemo(() => {
    if (!shot || !shot.image_path) return ''
    const v = shot.preview_disk_mtime || shot.thumbnail_disk_mtime || bust || Date.now()
    return `${shotImageUrl(shot.shot_id)}?v=${encodeURIComponent(String(v))}`
  }, [shot, bust])

  // Clear the failed-load flag when the preview identity changes (new shot, or preview replaced by
  // sync/upload/recover/relink elsewhere) so the fresh image gets a chance to load.
  useEffect(() => {
    setLoadFailed(false)
  }, [selectedShotId, shot?.image_path, shot?.preview_disk_mtime])

  // Action notes are per-shot.
  useEffect(() => {
    setNote('')
  }, [selectedShotId])

  const disabled = busy || projectActionBusy

  // Wrap a state-replacing action: flush dirty edits first, then apply the returned payload.
  const runReplacing = async (fn: () => Promise<void>) => {
    setBusy(true)
    try {
      await flushDirtyShots()
      await fn()
    } catch (error) {
      reportError(error)
    } finally {
      setBusy(false)
    }
  }

  const handleUploadImage = (file: File | undefined) => {
    if (!shot || !file) return
    const shotId = shot.shot_id
    void runReplacing(async () => {
      setProject(await uploadShotImage(shotId, file))
      setLoadFailed(false)
      setBust((x) => x + 1)
      setNote('Image uploaded.')
    })
  }

  const handleUploadSource = (file: File | undefined) => {
    if (!shot || !file) return
    const shotId = shot.shot_id
    void runReplacing(async () => {
      setProject(await uploadShotSource(shotId, file))
      setNote('Source PSD uploaded.')
    })
  }

  const handleDelete = () => {
    if (!shot) return
    if (!window.confirm('Delete the preview image for this shot?')) return
    const shotId = shot.shot_id
    void runReplacing(async () => {
      setProject(await removeShotImage(shotId))
      setLoadFailed(false)
      setBust((x) => x + 1)
      setNote('Preview image deleted.')
    })
  }

  const handleCreateCanvas = () => {
    if (!shot) return
    const shotId = shot.shot_id
    void runReplacing(async () => {
      setProject(await createShotCanvas(shotId, {}))
      setLoadFailed(false)
      setBust((x) => x + 1)
      setNote('Blank canvas created — source PSD is now linked.')
    })
  }

  // Open the shot's source in Photoshop. If no source is linked yet, create a blank canvas first.
  const handleOpenInPhotoshop = () => {
    if (!shot) return
    const shotId = shot.shot_id
    const needsCanvas = !shot.source_file_path
    void runReplacing(async () => {
      if (needsCanvas) setProject(await createShotCanvas(shotId, {}))
      const result = await openShotSource(shotId)
      setNote(
        result.switched === 'true'
          ? 'Switched to the tab already open in Photoshop.'
          : `Opened in Photoshop: ${result.path ?? ''}`,
      )
    })
  }

  const handleSync = () => {
    if (!shot) return
    const shotId = shot.shot_id
    void runReplacing(async () => {
      const payload = await syncShot(shotId)
      setProject(payload)
      setLoadFailed(false)
      setBust((x) => x + 1)
      const result = (payload as unknown as { result?: SyncResult }).result
      setNote(result?.message || (result?.synced ? 'Synced preview from Photoshop.' : 'No changes to sync.'))
    })
  }

  const handleOpenPreview = () => {
    if (!shot) return
    const shotId = shot.shot_id
    setBusy(true)
    openShotPreview(shotId)
      .then((result) => setNote(`Opened: ${result.path ?? ''}`))
      .catch((error) => reportError(error))
      .finally(() => setBusy(false))
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
          <button type="button" className="primary" onClick={() => imageInputRef.current?.click()} disabled={disabled}>
            {busy ? 'Working…' : 'Upload image'}
          </button>
          <button type="button" onClick={() => handleDelete()} disabled={disabled || !shot.image_path}>
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
          ref={imageInputRef}
          type="file"
          accept="image/*"
          hidden
          onChange={(e) => {
            handleUploadImage(e.target.files?.[0] ?? undefined)
            e.target.value = ''
          }}
        />
        <input
          ref={sourceInputRef}
          type="file"
          accept=".psd,image/*"
          hidden
          onChange={(e) => {
            handleUploadSource(e.target.files?.[0] ?? undefined)
            e.target.value = ''
          }}
        />
      </div>

      <div className="canvas-actions canvas-actions-ps">
        <button
          type="button"
          className="primary"
          onClick={() => handleOpenInPhotoshop()}
          disabled={disabled}
          title="Open the shot's source in Photoshop (creates a blank canvas if none exists)"
        >
          Open in Photoshop
        </button>
        <button
          type="button"
          onClick={() => handleSync()}
          disabled={disabled || !hasSource}
          title="Sync the preview from the linked source file"
        >
          Sync from Photoshop
        </button>
        <button
          type="button"
          onClick={() => handleOpenPreview()}
          disabled={disabled || !hasPreview}
          title="Open the preview image externally"
        >
          Open preview
        </button>
      </div>

      <div className="canvas-body">
        {hasImage ? (
          <img
            className="canvas-image"
            src={imgSrc}
            alt={shot.title || shot.shot_id}
            onError={() => setLoadFailed(true)}
            onLoad={() => setLoadFailed(false)}
          />
        ) : !hasSource && !hasPreview ? (
          <div className="canvas-placeholder">
            <p>Start drawing this shot</p>
            <p className="canvas-empty-hint">Create a blank PSD canvas, upload an image, or upload an existing PSD.</p>
            <div className="canvas-actions">
              <button type="button" className="primary" onClick={() => handleCreateCanvas()} disabled={disabled}>
                Create blank canvas
              </button>
              <button type="button" onClick={() => imageInputRef.current?.click()} disabled={disabled}>
                Upload image
              </button>
              <button type="button" onClick={() => sourceInputRef.current?.click()} disabled={disabled}>
                Upload source PSD
              </button>
            </div>
          </div>
        ) : (
          <div className="canvas-placeholder">
            <p>No preview image</p>
            {hasSource ? (
              <p className="canvas-empty-hint">Open in Photoshop and draw, then Sync to generate a preview.</p>
            ) : null}
            <div className="canvas-actions">
              <button type="button" className="primary" onClick={() => imageInputRef.current?.click()} disabled={disabled}>
                Upload image
              </button>
              {hasSource ? (
                <button type="button" onClick={() => handleSync()} disabled={disabled}>
                  Sync from Photoshop
                </button>
              ) : null}
            </div>
          </div>
        )}
      </div>

      <div className="canvas-status">
        <div className="canvas-status-chips">
          <span className={`canvas-chip ${hasSource ? 'ok' : 'missing'}`}>Source: {hasSource ? 'linked' : 'missing'}</span>
          <span className={`canvas-chip ${hasPreview ? 'ok' : 'missing'}`}>Preview: {hasPreview ? 'linked' : 'missing'}</span>
        </div>
        {sourcePath ? (
          <div className="canvas-status-path" title={sourcePath}>
            Source: {sourcePath}
          </div>
        ) : null}
        {previewPath ? (
          <div className="canvas-status-path" title={previewPath}>
            Preview: {previewPath}
          </div>
        ) : null}
        {note ? <div className="canvas-note">{note}</div> : null}
      </div>
    </div>
  )
}
