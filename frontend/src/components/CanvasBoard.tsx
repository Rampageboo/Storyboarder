import { useEffect, useMemo, useRef, useState, type CSSProperties } from 'react'
import {
  createShotCanvas,
  openShotPreview,
  openShotSource,
  recoverShotSource,
  relinkPreview,
  removeShotImage,
  removeShotLayer,
  shotBoardBackgroundUrl,
  shotCodexLayerUrl,
  shotImageUrl,
  syncShot,
  uploadShotImage,
  uploadShotSource,
} from '../api'
import { useProject } from '../state/useProject'
import { shotDisplayLabel } from '../utils/shotDisplay'
import { shotHasPreview, shotShouldOverlayPreview } from '../utils/shotPreview'
import './CanvasBoard.css'

type SyncResult = { synced?: boolean; message?: string }
type LayerId = 'background' | 'codex' | 'artwork'
const ALL_LAYERS_VISIBLE: Record<LayerId, boolean> = { background: true, codex: true, artwork: true }

export function CanvasBoard() {
  const { project, selectedShotId, setProject, flushDirtyShots, projectActionBusy, reportError, missingFiles } = useProject()
  const [bust, setBust] = useState(0)
  const [loadFailed, setLoadFailed] = useState(false)
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState('')
  const [relinkPath, setRelinkPath] = useState('')
  const [autoOpenPs, setAutoOpenPs] = useState<boolean>(() => {
    try {
      return localStorage.getItem('sb.autoOpenPsAfterCreate') === '1'
    } catch {
      return false
    }
  })
  const [previewZoom, setPreviewZoom] = useState(100)
  const [fitPreview, setFitPreview] = useState(true)
  const [layerVisibility, setLayerVisibility] = useState<Record<LayerId, boolean>>(ALL_LAYERS_VISIBLE)
  const imageInputRef = useRef<HTMLInputElement | null>(null)
  const sourceInputRef = useRef<HTMLInputElement | null>(null)
  const canvasBodyRef = useRef<HTMLDivElement | null>(null)
  const canWheelZoomRef = useRef(false)

  const shot = useMemo(() => {
    if (!project || !selectedShotId) return null
    return project.shots.find((s) => s.shot_id === selectedShotId) || null
  }, [project, selectedShotId])

  const sourcePath = shot?.source_file_path || ''
  const previewPath = shot?.preview_image_path || shot?.image_path || ''
  const hasSource = !!sourcePath
  const hasPreview = shot ? shotHasPreview(shot) : false
  const hasBoardBg = shot?.has_board_background === true
  const hasCodexLayer = shot?.has_codex_layer === true
  const hasArtworkImage = hasPreview
  const hasVisibleLayer = (
    (hasBoardBg && layerVisibility.background)
    || (hasCodexLayer && layerVisibility.codex)
    || (hasArtworkImage && layerVisibility.artwork)
  )
  const hasVisual = hasVisibleLayer && !loadFailed
  const canvasAspect = `${Number(project?.settings?.canvas_width || 1920)} / ${Number(project?.settings?.canvas_height || 1080)}`
  const linkedCount = [hasBoardBg, hasCodexLayer, hasPreview].filter(Boolean).length
  const linkedTotal = 3
  const linkedLabel = `Layers ${linkedCount}/${linkedTotal}`
  const linkedTitle = [
    hasPreview ? 'Artist artwork: linked' : 'Artist artwork: none',
    hasCodexLayer ? 'Codex image: linked' : 'Codex image: none',
    hasBoardBg ? 'Background: linked' : 'Background: none',
  ].join('\n')

  const artworkSrc = useMemo(() => {
    if (!shot || !layerVisibility.artwork) return ''
    if (!shotShouldOverlayPreview(shot)) return ''
    const v = shot.preview_disk_mtime || shot.thumbnail_disk_mtime || bust || 0
    return `${shotImageUrl(shot.shot_id)}?v=${encodeURIComponent(String(v))}`
  }, [shot, bust, layerVisibility.artwork])

  const backgroundSrc = useMemo(() => {
    if (!shot || shot.has_board_background !== true || !layerVisibility.background) return ''
    const v = shot.board_background_disk_mtime || shot.thumbnail_disk_mtime || bust || 0
    return `${shotBoardBackgroundUrl(shot.shot_id)}?v=${encodeURIComponent(String(v))}`
  }, [shot, bust, layerVisibility.background])

  const codexSrc = useMemo(() => {
    if (!shot || shot.has_codex_layer !== true || !layerVisibility.codex) return ''
    const v = shot.codex_layer_disk_mtime || shot.thumbnail_disk_mtime || bust || 0
    return `${shotCodexLayerUrl(shot.shot_id)}?v=${encodeURIComponent(String(v))}`
  }, [shot, bust, layerVisibility.codex])

  // Clear the failed-load flag when the visual source identity changes.
  const loadFailedKey = `${selectedShotId}:${shot?.image_path ?? ''}:${shot?.preview_image_path ?? ''}:${shot?.preview_disk_mtime ?? ''}:${shot?.board_background_disk_mtime ?? ''}:${shot?.codex_layer_disk_mtime ?? ''}:${shot?.preview_has_transparency ? '1' : '0'}:${hasBoardBg ? '1' : '0'}:${hasCodexLayer ? '1' : '0'}`
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
    setLayerVisibility(ALL_LAYERS_VISIBLE)
    setPreviewZoom(100)
    setFitPreview(true)
    const cur = project?.shots.find((s) => s.shot_id === selectedShotId)
    setRelinkPath(cur?.preview_image_path || cur?.image_path || '')
  }

  // Keep the zoom guard in sync with whether the canvas has something to zoom
  useEffect(() => {
    canWheelZoomRef.current = hasVisual
  }, [hasVisual])

  // Wheel-to-zoom on the canvas body
  useEffect(() => {
    const body = canvasBodyRef.current
    if (!body) return
    const onWheel = (e: WheelEvent) => {
      if (!canWheelZoomRef.current) return
      e.preventDefault()
      const step = e.deltaY > 0 ? -5 : 5
      setFitPreview(false)
      setPreviewZoom((prev) => Math.min(200, Math.max(25, prev + step)))
    }
    body.addEventListener('wheel', onWheel, { passive: false })
    return () => body.removeEventListener('wheel', onWheel)
  }, [])

  // Derive missing-file status from the shared context scan (no per-shot API call).
  const missing = useMemo(() => {
    if (!selectedShotId || !missingFiles) return null
    const rows = missingFiles.filter((r) => r.shot_id === selectedShotId)
    return {
      source: rows.some((r) => r.field === 'source_file_path'),
      preview: rows.some((r) => r.field === 'preview_image_path'),
      refs: rows.filter((r) => r.field === 'reference_image_paths').length,
    }
  }, [selectedShotId, missingFiles])

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

  const handleRemoveLayer = (layerId: 'background' | 'codex') => {
    if (!shot) return
    const label = layerId === 'codex' ? 'Codex image' : 'background'
    if (!window.confirm(`Delete the ${label} layer for this shot?`)) return
    const shotId = shot.shot_id
    void runReplacing(async () => {
      setProject(await removeShotLayer(shotId, layerId))
      setLoadFailed(false)
      setBust((x) => x + 1)
      setNote(`${layerId === 'codex' ? 'Codex' : 'Background'} layer deleted. Artist artwork was not changed.`)
    })
  }

  const toggleLayer = (layerId: LayerId) => {
    setLayerVisibility((current) => ({ ...current, [layerId]: !current[layerId] }))
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
        <div className="canvas-heading">
          <div className="canvas-title">Preview</div>
          <div className="canvas-subtitle">{shotDisplayLabel(shot)}</div>
        </div>
        <div className="canvas-toolbar" aria-label="Preview actions">
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
            Sync
          </button>
          <button
            type="button"
            onClick={() => handleOpenPreview()}
            disabled={disabled || !hasPreview}
            title="Open the preview image externally"
          >
            Preview
          </button>
          <button type="button" onClick={() => imageInputRef.current?.click()} disabled={disabled}>
            {busy ? 'Working...' : 'Upload'}
          </button>
          <button
            type="button"
            className="icon"
            onClick={() => {
              setLoadFailed(false)
              setBust((x) => x + 1)
            }}
            disabled={disabled || (!hasArtworkImage && !hasBoardBg)}
            title="Reload preview from server"
            aria-label="Refresh preview"
          >
            Refresh
          </button>
          <span
            className={`canvas-link-pill ${linkedCount === linkedTotal ? 'ok' : 'partial'}`}
            title={linkedTitle}
            aria-label={linkedTitle}
          >
            {linkedLabel}
          </span>
          <details className="canvas-more canvas-layers">
            <summary aria-label="Manage fixed layers">Layers</summary>
            <div className="canvas-more-menu canvas-layer-menu">
              <div className="canvas-layer-heading">
                <strong>Fixed layers</strong>
                <span>Top to bottom</span>
              </div>
              <div className="canvas-layer-row">
                <button
                  type="button"
                  className="canvas-layer-toggle"
                  aria-pressed={layerVisibility.artwork}
                  onClick={() => toggleLayer('artwork')}
                  disabled={!hasPreview}
                >
                  {layerVisibility.artwork ? 'On' : 'Off'}
                </button>
                <span className="canvas-layer-name">Artist artwork</span>
                <span className="canvas-layer-protected">Protected</span>
              </div>
              <div className="canvas-layer-row">
                <button
                  type="button"
                  className="canvas-layer-toggle"
                  aria-pressed={layerVisibility.codex}
                  onClick={() => toggleLayer('codex')}
                  disabled={!hasCodexLayer}
                >
                  {layerVisibility.codex ? 'On' : 'Off'}
                </button>
                <span className="canvas-layer-name">Codex image</span>
                {hasCodexLayer ? (
                  <button type="button" className="canvas-layer-delete" onClick={() => handleRemoveLayer('codex')} disabled={disabled}>
                    Delete
                  </button>
                ) : <span className="canvas-layer-empty">Empty</span>}
              </div>
              <div className="canvas-layer-row">
                <button
                  type="button"
                  className="canvas-layer-toggle"
                  aria-pressed={layerVisibility.background}
                  onClick={() => toggleLayer('background')}
                  disabled={!hasBoardBg}
                >
                  {layerVisibility.background ? 'On' : 'Off'}
                </button>
                <span className="canvas-layer-name">Background</span>
                {hasBoardBg ? (
                  <button type="button" className="canvas-layer-delete" onClick={() => handleRemoveLayer('background')} disabled={disabled}>
                    Delete
                  </button>
                ) : <span className="canvas-layer-empty">Empty</span>}
              </div>
              <p className="canvas-layer-note">Codex results replace only the Codex layer.</p>
            </div>
          </details>
          <details className="canvas-more">
            <summary aria-label="More preview actions">More</summary>
            <div className="canvas-more-menu">
              <button type="button" onClick={() => sourceInputRef.current?.click()} disabled={disabled}>
                Upload source PSD
              </button>
              <button type="button" onClick={() => handleCreateCanvas()} disabled={disabled}>
                Create blank canvas
              </button>
              <button type="button" className="danger" onClick={() => handleDelete()} disabled={disabled || !shot.image_path}>
                Delete image
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
                      /* localStorage unavailable - keep session-only */
                    }
                  }}
                />
                Open PS after create
              </label>
              {sourcePath || previewPath ? (
                <details className="canvas-file-details">
                  <summary>File details</summary>
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
                </details>
              ) : null}
            </div>
          </details>
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

      {(note || (missing && (missing.source || missing.preview || missing.refs > 0))) ? (
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

      <div
        ref={canvasBodyRef}
        className={`canvas-body${fitPreview ? '' : ' is-zoomed'}`}
      >
        {hasVisual ? (
          <div
            className={`canvas-media${fitPreview ? '' : ' is-zoomed'}`}
            style={fitPreview ? {} : ({ '--canvas-zoom': `${previewZoom}%` } as CSSProperties)}
          >
            <div className="canvas-composite" style={{ aspectRatio: canvasAspect }} aria-label={shotDisplayLabel(shot)}>
              {backgroundSrc ? (
                <img
                  className="canvas-image canvas-image-bg"
                  src={backgroundSrc}
                  alt=""
                  onError={() => {
                    if (!codexSrc && !artworkSrc) setLoadFailed(true)
                  }}
                  onLoad={() => setLoadFailed(false)}
                />
              ) : null}
              {codexSrc ? (
                <img
                  className="canvas-image canvas-image-codex"
                  src={codexSrc}
                  alt=""
                  onError={() => {
                    if (!backgroundSrc && !artworkSrc) setLoadFailed(true)
                  }}
                  onLoad={() => setLoadFailed(false)}
                />
              ) : null}
              {artworkSrc ? (
                <img
                  className="canvas-image canvas-image-artwork"
                  src={artworkSrc}
                  alt=""
                  onError={() => {
                    if (!backgroundSrc && !codexSrc) setLoadFailed(true)
                  }}
                  onLoad={() => setLoadFailed(false)}
                />
              ) : null}
            </div>
          </div>
        ) : (hasPreview || hasCodexLayer || hasBoardBg) && !hasVisibleLayer ? (
          <div className="canvas-placeholder">
            <p>All layers are hidden</p>
            <p className="canvas-empty-hint">Open Layers and turn on at least one layer.</p>
          </div>
        ) : !hasSource && !hasPreview && !hasCodexLayer && !hasBoardBg ? (
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

        {/* Zoom HUD — appears when not in fit mode */}
        {hasVisual && !fitPreview && (
          <div className="canvas-zoom-hud">
            <span className="canvas-zoom-hud-pct">{previewZoom}%</span>
            <button
              type="button"
              className="canvas-zoom-hud-fit"
              onClick={() => { setFitPreview(true); setPreviewZoom(100) }}
              aria-label="Reset to fit"
            >
              Fit
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
