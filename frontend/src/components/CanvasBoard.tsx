import { useEffect, useMemo, useRef, useState } from 'react'
import {
  createShotCanvas,
  getMissingFiles,
  openShotPreview,
  openShotSource,
  recoverShotSource,
  relinkPreview,
  removeShotImage,
  shotImageUrl,
  syncShot,
  uploadShotImage,
  uploadShotSource,
} from '../api'
import { useProject } from '../state/useProject'
import { shotDisplayLabel } from '../utils/shotDisplay'
import './CanvasBoard.css'

type SyncResult = { synced?: boolean; message?: string }

export function CanvasBoard() {
  const { project, selectedShotId, setProject, flushDirtyShots, projectActionBusy, reportError } = useProject()
  const [bust, setBust] = useState(0)
  const [loadFailed, setLoadFailed] = useState(false)
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState('')
  const [missing, setMissing] = useState<{ source: boolean; preview: boolean; refs: number } | null>(null)
  const [relinkPath, setRelinkPath] = useState('')
  const [autoOpenPs, setAutoOpenPs] = useState<boolean>(() => {
    try {
      return localStorage.getItem('sb.autoOpenPsAfterCreate') === '1'
    } catch {
      return false
    }
  })
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
    const v = shot.preview_disk_mtime || shot.thumbnail_disk_mtime || bust || 0
    return `${shotImageUrl(shot.shot_id)}?v=${encodeURIComponent(String(v))}`
  }, [shot, bust])

  // Clear the failed-load flag when the preview identity changes.
  const loadFailedKey = `${selectedShotId}:${shot?.image_path ?? ''}:${shot?.preview_disk_mtime ?? ''}`
  const [prevLoadFailedKey, setPrevLoadFailedKey] = useState(loadFailedKey)
  if (loadFailedKey !== prevLoadFailedKey) {
    setPrevLoadFailedKey(loadFailedKey)
    setLoadFailed(false)
  }

  // Action notes and relink path are per-shot.
  const [prevShotId, setPrevShotId] = useState(selectedShotId)
  if (selectedShotId !== prevShotId) {
    setPrevShotId(selectedShotId)
    setNote('')
    if (!selectedShotId) {
      setMissing(null)
    }
    const cur = project?.shots.find((s) => s.shot_id === selectedShotId)
    setRelinkPath(cur?.preview_image_path || cur?.image_path || '')
  }

  // On-disk missing-file status for the selected shot (metadata path present but file gone).
  // Stale-guarded and silent — an ordinary missing thumbnail must never raise the error banner.
  useEffect(() => {
    if (!selectedShotId) return
    let cancelled = false
    getMissingFiles()
      .then((payload) => {
        if (cancelled) return
        const rows = (payload.missing_files ?? []).filter((r) => r.shot_id === selectedShotId)
        setMissing({
          source: rows.some((r) => r.field === 'source_file_path'),
          preview: rows.some((r) => r.field === 'preview_image_path'),
          refs: rows.filter((r) => r.field === 'reference_image_paths').length,
        })
      })
      .catch(() => {
        if (!cancelled) setMissing(null)
      })
    return () => {
      cancelled = true
    }
  }, [selectedShotId, sourcePath, previewPath, shot?.preview_disk_mtime, shot?.reference_image_paths?.length])

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
      if (autoOpenPs) {
        const result = await openShotSource(shotId)
        setNote(
          result.switched === 'true'
            ? 'Canvas created; switched to the Photoshop tab.'
            : `Canvas created and opened in Photoshop: ${result.path ?? ''}`,
        )
      } else {
        setNote('Blank canvas created — source PSD is now linked.')
      }
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

  // Repair: point the preview at an existing project-relative file.
  const handleRelinkPreview = () => {
    if (!shot) return
    const rel = relinkPath.trim()
    if (!rel) {
      window.alert('Enter a project-relative preview path.')
      return
    }
    const shotId = shot.shot_id
    void runReplacing(async () => {
      setProject(await relinkPreview(shotId, { relative_path: rel }))
      setLoadFailed(false)
      setBust((x) => x + 1)
      setNote('Preview relinked.')
    })
  }

  // Repair: rebuild a missing/broken source PSD from its layers (no relink-source endpoint exists).
  const handleRecoverSource = () => {
    if (!shot) return
    if (!window.confirm('Rebuild the source PSD from its layers/history? A backup is saved to _history/.')) return
    const shotId = shot.shot_id
    void runReplacing(async () => {
      const payload = await recoverShotSource(shotId)
      setProject(payload)
      const result = (payload as unknown as { result?: { layers_recovered?: number } }).result
      setNote(`Recovered source: ${result?.layers_recovered ?? '?'} layer(s).`)
    })
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
        <p className="canvas-empty-hint">Choose a board from the strip below.</p>
      </div>
    )
  }

  return (
    <div className="canvas">
      <div className="canvas-header">
        <div>
          <div className="canvas-title">Preview</div>
          <div className="canvas-subtitle">{shotDisplayLabel(shot)}</div>
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
        <label className="canvas-autoopen" title="Open the new source in Photoshop right after creating a canvas">
          <input
            type="checkbox"
            checked={autoOpenPs}
            onChange={(e) => {
              const next = e.target.checked
              setAutoOpenPs(next)
              try {
                localStorage.setItem('sb.autoOpenPsAfterCreate', next ? '1' : '0')
              } catch {
                /* localStorage unavailable — keep session-only */
              }
            }}
          />
          Open PS after create
        </label>
        <div className="canvas-status-chips">
          <span className={`canvas-chip ${hasSource ? 'ok' : 'missing'}`}>Source: {hasSource ? 'linked' : 'missing'}</span>
          <span className={`canvas-chip ${hasPreview ? 'ok' : 'missing'}`}>Preview: {hasPreview ? 'linked' : 'missing'}</span>
        </div>
      </div>

      {(sourcePath || previewPath || note || (missing && (missing.source || missing.preview || missing.refs > 0))) ? (
        <div className="canvas-status-compact">
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
          {missing && (missing.source || missing.preview || missing.refs > 0) ? (
            <div className="canvas-missing">
              ⚠{' '}
              {[
                missing.source ? 'source file missing on disk' : null,
                missing.preview ? 'preview file missing on disk' : null,
                missing.refs > 0 ? `${missing.refs} reference file${missing.refs === 1 ? '' : 's'} missing` : null,
              ]
                .filter(Boolean)
                .join(' · ')}
            </div>
          ) : null}
          {missing?.preview ? (
            <div className="canvas-repair">
              <input
                className="canvas-repair-input"
                value={relinkPath}
                onChange={(e) => setRelinkPath(e.target.value)}
                placeholder="shots/shot_001/shot_001_preview.png"
              />
              <button type="button" onClick={() => handleRelinkPreview()} disabled={disabled || !relinkPath.trim()}>
                Relink preview
              </button>
            </div>
          ) : null}
          {missing?.source ? (
            <div className="canvas-repair">
              <button type="button" onClick={() => handleRecoverSource()} disabled={disabled}>
                Recover source
              </button>
              <span className="canvas-repair-hint">Rebuilds the PSD from its layers.</span>
            </div>
          ) : null}
          {missing && missing.refs > 0 ? (
            <div className="canvas-repair-hint">Remove missing reference images in the References panel.</div>
          ) : null}
        </div>
      ) : null}

      <div className="canvas-body">
        {hasImage ? (
          <div className="canvas-media">
            <img
              className="canvas-image"
              src={imgSrc}
              alt={shotDisplayLabel(shot)}
              onError={() => setLoadFailed(true)}
              onLoad={() => setLoadFailed(false)}
            />
          </div>
        ) : !hasSource && !hasPreview ? (
          <div className="canvas-placeholder">
            <p>Start drawing this shot</p>
            <p className="canvas-empty-hint">Create a blank PSD canvas, upload an image, or upload an existing PSD.</p>
            <p className="canvas-empty-hint">
              New canvases use {project.settings?.canvas_width ?? 1920}×{project.settings?.canvas_height ?? 1080},{' '}
              {project.settings?.canvas_background_color ?? '#E8E8E8'}.
            </p>
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
    </div>
  )
}
