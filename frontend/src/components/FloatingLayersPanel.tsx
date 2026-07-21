import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import {
  acceptGenerationCandidate,
  createCodexBatchRequests,
  createGenerationRequest,
  deleteGenerationRequest,
  listGenerationRequests,
  projectFileUrl,
  reconcileGenerationRequests,
} from '../api'
import { useProject } from '../state/useProject'
import type { GenerationDestination, GenerationMode, GenerationProvider, GenerationRequest, Shot } from '../types'
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
  const [dispatchingAllToCodex, setDispatchingAllToCodex] = useState(false)
  const [provider, setProvider] = useState<GenerationProvider>('codex')
  // Empty string = let the backend derive the precision mode from the shot's status.
  const [mode, setMode] = useState<GenerationMode | ''>('')
  const [acceptingArtifact, setAcceptingArtifact] = useState('')
  const [deletingRequestId, setDeletingRequestId] = useState('')
  const [notice, setNotice] = useState('')
  const projectPath = project?.project_json_path ?? ''
  const selectedShotIdRef = useRef<string | null>(selectedShotId)
  const requestListRevisionRef = useRef(0)

  // Generation results arrive asynchronously while the user may be moving between
  // boards. Always preserve the selection at the moment a response is applied,
  // rather than the selection that existed when the request was started.
  useLayoutEffect(() => {
    selectedShotIdRef.current = selectedShotId
  }, [selectedShotId])
  const replaceWithCurrentSelection = useCallback((payload: typeof project) => {
    if (payload) replaceProject(payload, selectedShotIdRef.current)
  }, [replaceProject])

  const loadRequests = useCallback(async (quiet = false) => {
    const revision = ++requestListRevisionRef.current
    if (!quiet) setLoading(true)
    try {
      const response = await listGenerationRequests()
      if (revision !== requestListRevisionRef.current) return
      setRequests(response.requests)
      setLoadedProjectPath(projectPath)
    } catch (error) {
      if (revision === requestListRevisionRef.current) reportError(error)
    } finally {
      if (revision === requestListRevisionRef.current) setLoading(false)
    }
  }, [projectPath, reportError])

  useEffect(() => {
    if (!project) return
    void loadRequests()
    return () => {
      requestListRevisionRef.current += 1
    }
  }, [project, loadRequests])

  const visibleRequests = loadedProjectPath === projectPath ? requests : []
  const queueLoading = loading || loadedProjectPath !== projectPath
  const requestShotNumbers = useMemo(() => {
    const numbers = new Map<string, number>()
    const usedNumbers = new Set<number>()
    const currentShotNumbers = new Map<string, number>()
    for (const [index, candidate] of (project?.shots ?? []).entries()) {
      currentShotNumbers.set(candidate.shot_id, index + 1)
    }

    const orderedRequests = [...requests].sort((left, right) => left.created_at.localeCompare(right.created_at))
    for (const request of orderedRequests) {
      const snapshotNumber = Number(request.shot_number)
      const number = Number.isInteger(snapshotNumber) && snapshotNumber > 0
        ? snapshotNumber
        : currentShotNumbers.get(request.shot_id)
      if (number && !numbers.has(request.shot_id)) numbers.set(request.shot_id, number)
      if (number) usedNumbers.add(number)
    }

    let nextNumber = 1
    for (const request of orderedRequests) {
      if (numbers.has(request.shot_id)) continue
      while (usedNumbers.has(nextNumber)) nextNumber += 1
      numbers.set(request.shot_id, nextNumber)
      usedNumbers.add(nextNumber)
    }
    return numbers
  }, [project?.shots, requests])

  const requestShotLabel = (request: GenerationRequest) => {
    const snapshotNumber = Number(request.shot_number)
    const number = Number.isInteger(snapshotNumber) && snapshotNumber > 0
      ? snapshotNumber
      : requestShotNumbers.get(request.shot_id) ?? 1
    return `Shot ${number}`
  }

  const dispatchGeneration = async (destination: GenerationDestination) => {
    setDispatchingTo(destination)
    setNotice('')
    try {
      await flushDirtyShots()
      const response = await createGenerationRequest(shot.shot_id, destination, { provider, mode })
      replaceWithCurrentSelection(response.project)
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

  const dispatchAllToCodex = async () => {
    setDispatchingAllToCodex(true)
    setNotice('')
    try {
      await flushDirtyShots()
      const response = await createCodexBatchRequests()
      replaceWithCurrentSelection(response.project)
      setRequests(response.requests)
      setLoadedProjectPath(projectPath)
      const copied = await copyTextWithTimeout(response.codex_prompt)
      setNotice(
        copied
          ? `${response.created_request_ids.length} shot handoffs copied for Codex.`
          : `${response.created_request_ids.length} shot handoffs are ready for Codex.`,
      )
    } catch (error) {
      reportError(error)
    } finally {
      setDispatchingAllToCodex(false)
    }
  }

  const refreshResults = async () => {
    setLoading(true)
    setNotice('')
    try {
      const response = await reconcileGenerationRequests()
      replaceWithCurrentSelection(response.project)
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

  const deleteRequest = async (requestId: string) => {
    const previousRequests = requests
    requestListRevisionRef.current += 1
    setDeletingRequestId(requestId)
    setNotice('')
    setRequests((current) => current.filter((request) => request.request_id !== requestId))
    try {
      const response = await deleteGenerationRequest(requestId)
      if (response.requests.some((request) => request.request_id === requestId)) {
        throw new Error('Storyboarder could not remove this queue item.')
      }
      replaceWithCurrentSelection(response.project)
      setRequests(response.requests)
      setLoadedProjectPath(projectPath)
      setNotice('Queue item removed.')
    } catch (error) {
      setRequests(previousRequests)
      reportError(error)
    } finally {
      setDeletingRequestId('')
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
      replaceWithCurrentSelection(response.project)
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
        <div className="floating-queue-config">
          <label>
            <span>Backend</span>
            <select
              value={provider}
              disabled={disabled || dispatchingTo !== null || dispatchingAllToCodex}
              onChange={(event) => setProvider(event.target.value as GenerationProvider)}
            >
              <option value="codex">Codex</option>
              <option value="stable_diffusion">Stable Diffusion</option>
            </select>
          </label>
          <label>
            <span>Mode</span>
            <select
              value={mode}
              disabled={disabled || dispatchingTo !== null || dispatchingAllToCodex}
              onChange={(event) => setMode(event.target.value as GenerationMode | '')}
            >
              <option value="">Auto (by status)</option>
              <option value="draft">Draft</option>
              <option value="clean">Clean</option>
              <option value="final">Final</option>
            </select>
          </label>
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
          <button
            type="button"
            className="queue-batch-codex"
            disabled={disabled || dispatchingTo !== null || dispatchingAllToCodex}
            onClick={() => void dispatchAllToCodex()}
          >
            {dispatchingAllToCodex ? 'Preparing all...' : 'Send All to Codex'}
          </button>
        </div>
        {notice ? <div className="floating-queue-notice" role="status">{notice}</div> : null}
        <div className="floating-queue-list">
          {visibleRequests.length > 0 ? visibleRequests.map((request) => (
            <article className="floating-queue-row" key={request.request_id}>
              <div className="floating-queue-topline">
                <span className={`floating-status status-${request.status}`} aria-hidden="true" />
                <strong>{requestShotLabel(request)}</strong>
                <span className={`floating-destination is-${request.destination}`}>
                  {request.destination === 'codex' ? 'Codex' : 'Queue'}
                </span>
                <button
                  type="button"
                  className="floating-queue-delete"
                  disabled={deletingRequestId === request.request_id}
                  onClick={() => void deleteRequest(request.request_id)}
                  title="Remove from queue"
                >
                  {deletingRequestId === request.request_id ? 'Removing...' : 'Remove'}
                </button>
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
