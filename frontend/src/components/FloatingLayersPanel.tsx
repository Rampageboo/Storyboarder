import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  acceptGenerationCandidate,
  createGenerationRequest,
  listGenerationRequests,
  projectFileUrl,
  reconcileGenerationRequests,
} from '../api'
import { useProject } from '../state/useProject'
import type { GenerationDestination, GenerationRequest, Shot } from '../types'
import { shotDisplayLabel } from '../utils/shotDisplay'
import './FloatingLayersPanel.css'

export type CanvasLayerId = 'background' | 'codex' | 'artwork'

interface FloatingLayersPanelProps {
  shot: Shot
  layerVisibility: Record<CanvasLayerId, boolean>
  hasArtwork: boolean
  hasCodexLayer: boolean
  hasBackground: boolean
  disabled: boolean
  onToggleLayer: (layerId: CanvasLayerId) => void
  onRemoveLayer: (layerId: 'background' | 'codex') => void
  onClose: () => void
}

function formatTime(value: string) {
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime())
    ? value
    : parsed.toLocaleString([], { dateStyle: 'short', timeStyle: 'short' })
}

async function copyTextWithTimeout(value: string, timeoutMs = 1200) {
  if (!navigator.clipboard?.writeText) return false
  let timeoutId: number | undefined
  try {
    return await Promise.race([
      navigator.clipboard.writeText(value).then(() => true, () => false),
      new Promise<boolean>((resolve) => {
        timeoutId = window.setTimeout(() => resolve(false), timeoutMs)
      }),
    ])
  } finally {
    if (timeoutId !== undefined) window.clearTimeout(timeoutId)
  }
}

function LayerRow({
  id,
  name,
  visible,
  available,
  protectedLayer = false,
  disabled,
  onToggle,
  onRemove,
}: {
  id: CanvasLayerId
  name: string
  visible: boolean
  available: boolean
  protectedLayer?: boolean
  disabled: boolean
  onToggle: () => void
  onRemove?: () => void
}) {
  return (
    <div className={`floating-layer-row${available ? '' : ' is-empty'}`}>
      <button
        type="button"
        className="floating-layer-eye"
        aria-label={`${visible ? 'Hide' : 'Show'} ${name}`}
        aria-pressed={visible}
        disabled={!available}
        onClick={onToggle}
      >
        <span aria-hidden="true">{visible && available ? 'Eye' : 'Off'}</span>
      </button>
      <span className={`floating-layer-thumb layer-${id}`} aria-hidden="true" />
      <span className="floating-layer-name">{name}</span>
      {protectedLayer ? (
        <span className="floating-layer-lock" title="Artist artwork is protected">Lock</span>
      ) : available ? (
        <button
          type="button"
          className="floating-layer-remove"
          onClick={onRemove}
          disabled={disabled}
          aria-label={`Delete ${name}`}
          title={`Delete ${name}`}
        >
          Del
        </button>
      ) : (
        <span className="floating-layer-empty">Empty</span>
      )}
    </div>
  )
}

export function FloatingLayersPanel({
  shot,
  layerVisibility,
  hasArtwork,
  hasCodexLayer,
  hasBackground,
  disabled,
  onToggleLayer,
  onRemoveLayer,
  onClose,
}: FloatingLayersPanelProps) {
  const { project, selectedShotId, flushDirtyShots, replaceProject, reportError } = useProject()
  const [requests, setRequests] = useState<GenerationRequest[]>([])
  const [loadedProjectPath, setLoadedProjectPath] = useState('')
  const [loading, setLoading] = useState(true)
  const [dispatchingTo, setDispatchingTo] = useState<GenerationDestination | null>(null)
  const [acceptingArtifact, setAcceptingArtifact] = useState('')
  const [notice, setNotice] = useState('')
  const projectPath = project?.project_json_path ?? ''

  const loadRequests = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true)
    try {
      const response = await listGenerationRequests()
      setRequests(response.requests)
      setLoadedProjectPath(projectPath)
    } catch (error) {
      reportError(error)
    } finally {
      setLoading(false)
    }
  }, [projectPath, reportError])

  useEffect(() => {
    let cancelled = false
    listGenerationRequests()
      .then((response) => {
        if (!cancelled) {
          setRequests(response.requests)
          setLoadedProjectPath(projectPath)
          setLoading(false)
        }
      })
      .catch((error) => {
        if (!cancelled) {
          reportError(error)
          setLoading(false)
        }
      })
    return () => {
      cancelled = true
    }
  }, [projectPath, reportError])

  const visibleRequests = loadedProjectPath === projectPath ? requests : []
  const queueLoading = loading || loadedProjectPath !== projectPath
  const hasQueuedRequests = visibleRequests.some((request) => request.status === 'queued')
  useEffect(() => {
    if (!hasQueuedRequests) return
    const timer = window.setInterval(() => void loadRequests(true), 4000)
    return () => window.clearInterval(timer)
  }, [hasQueuedRequests, loadRequests])

  const shotLabels = useMemo(() => {
    const labels = new Map<string, string>()
    for (const candidate of project?.shots ?? []) {
      labels.set(candidate.shot_id, shotDisplayLabel(candidate))
    }
    return labels
  }, [project?.shots])

  const dispatchGeneration = async (destination: GenerationDestination) => {
    setDispatchingTo(destination)
    setNotice('')
    try {
      await flushDirtyShots()
      const response = await createGenerationRequest(shot.shot_id, destination)
      replaceProject(response.project, selectedShotId)
      await loadRequests(true)
      if (destination === 'codex' && response.codex_prompt) {
        const copied = await copyTextWithTimeout(response.codex_prompt)
        setNotice(copied ? 'Codex handoff ready and copied.' : `Codex handoff ready: ${response.request.request_id}`)
      } else {
        setNotice('Queue updated for this shot.')
      }
    } catch (error) {
      reportError(error)
    } finally {
      setDispatchingTo(null)
    }
  }

  const refreshResults = async () => {
    setLoading(true)
    setNotice('')
    try {
      const response = await reconcileGenerationRequests()
      replaceProject(response.project, selectedShotId)
      setRequests(response.requests)
      setLoadedProjectPath(projectPath)
      setNotice(
        response.updated_request_ids.length > 0
          ? `${response.updated_request_ids.length} returned result${response.updated_request_ids.length === 1 ? '' : 's'} imported.`
          : 'Queue is up to date.',
      )
    } catch (error) {
      reportError(error)
    } finally {
      setLoading(false)
    }
  }

  const acceptAsCodexLayer = async (request: GenerationRequest, artifactPath: string) => {
    const resultId = request.latest_result?.result_id
    if (!resultId) return
    setAcceptingArtifact(artifactPath)
    setNotice('')
    try {
      const response = await acceptGenerationCandidate(request.shot_id, {
        request_id: request.request_id,
        result_id: resultId,
        artifact_path: artifactPath,
      })
      replaceProject(response.project, selectedShotId)
      await loadRequests(true)
      setNotice('Result placed on the shot Codex layer.')
    } catch (error) {
      reportError(error)
    } finally {
      setAcceptingArtifact('')
    }
  }

  return (
    <aside className="floating-layers-panel" aria-label="Layers and generation queue">
      <header className="floating-panel-header">
        <div>
          <strong>Layers &amp; Queue</strong>
          <span title={shot.shot_id}>{shotDisplayLabel(shot)}</span>
        </div>
        <button type="button" onClick={onClose} aria-label="Close Layers and Queue" title="Close panel">Close</button>
      </header>

      <section className="floating-panel-section" aria-labelledby="floating-layers-heading">
        <div className="floating-section-heading">
          <span id="floating-layers-heading">Layers</span>
          <small>Top to bottom</small>
        </div>
        <div className="floating-layer-list">
          <LayerRow
            id="artwork"
            name="Artist artwork"
            visible={layerVisibility.artwork}
            available={hasArtwork}
            protectedLayer
            disabled={disabled}
            onToggle={() => onToggleLayer('artwork')}
          />
          <LayerRow
            id="codex"
            name="Codex image"
            visible={layerVisibility.codex}
            available={hasCodexLayer}
            disabled={disabled}
            onToggle={() => onToggleLayer('codex')}
            onRemove={() => onRemoveLayer('codex')}
          />
          <LayerRow
            id="background"
            name="Background"
            visible={layerVisibility.background}
            available={hasBackground}
            disabled={disabled}
            onToggle={() => onToggleLayer('background')}
            onRemove={() => onRemoveLayer('background')}
          />
        </div>
      </section>

      <section className="floating-panel-section floating-queue-section" aria-labelledby="floating-queue-heading">
        <div className="floating-section-heading floating-queue-heading">
          <span id="floating-queue-heading">Queue</span>
          <button type="button" onClick={() => void refreshResults()} disabled={queueLoading}>
            {queueLoading ? 'Refreshing...' : 'Refresh'}
          </button>
        </div>
        <div className="floating-queue-actions">
          <button
            type="button"
            className="queue-primary"
            disabled={disabled || dispatchingTo !== null}
            onClick={() => void dispatchGeneration('queue')}
          >
            {dispatchingTo === 'queue' ? 'Updating...' : 'Send to Queue'}
          </button>
          <button
            type="button"
            disabled={disabled || dispatchingTo !== null}
            onClick={() => void dispatchGeneration('codex')}
          >
            {dispatchingTo === 'codex' ? 'Preparing...' : 'Send to Codex'}
          </button>
        </div>
        {notice ? <div className="floating-queue-notice" role="status">{notice}</div> : null}
        <div className="floating-queue-list">
          {visibleRequests.length > 0 ? visibleRequests.map((request) => (
            <article className="floating-queue-row" key={request.request_id}>
              <div className="floating-queue-topline">
                <span className={`floating-status status-${request.status}`} aria-hidden="true" />
                <strong title={request.shot_id}>{shotLabels.get(request.shot_id) || request.shot_id}</strong>
                <span className={`floating-destination is-${request.destination}`}>
                  {request.destination === 'codex' ? 'Codex' : 'Queue'}
                </span>
              </div>
              <div className="floating-queue-meta">
                <span className="floating-status-label">{request.status}</span>
                <time>{formatTime(request.created_at)}</time>
                <span>{request.result_count ?? 0} result{request.result_count === 1 ? '' : 's'}</span>
              </div>
              {request.keyword_assets?.length ? (
                <div className="floating-queue-assets">
                  <span>3D</span>
                  {request.keyword_assets.map((asset) => (
                    <span key={asset.scene3d_id} title={asset.blend_file_path || asset.file_path}>
                      {asset.title || asset.matched_keywords.join(', ')}
                    </span>
                  ))}
                </div>
              ) : null}
              {request.latest_result?.artifacts?.length ? (
                <div className="floating-artifact-list">
                  {request.latest_result.artifacts.map((artifact) => (
                    <div className="floating-artifact-row" key={artifact.project_relative_path}>
                      <a href={projectFileUrl(artifact.project_relative_path)} target="_blank" rel="noreferrer" title={artifact.name}>
                        {artifact.name}
                      </a>
                      <button
                        type="button"
                        disabled={acceptingArtifact !== ''}
                        onClick={() => void acceptAsCodexLayer(request, artifact.project_relative_path)}
                      >
                        {acceptingArtifact === artifact.project_relative_path ? 'Using...' : 'Use layer'}
                      </button>
                    </div>
                  ))}
                </div>
              ) : null}
            </article>
          )) : (
            <div className="floating-queue-empty">Nothing has been sent yet.</div>
          )}
        </div>
      </section>
    </aside>
  )
}
