import { useEffect, useRef, useState, type PropsWithChildren } from 'react'
import { getBridgeStatus, publishLiveBridge, type BridgeStatusPayload } from '../api'
import { apiBase } from '../api/base'
import { useProject } from './useProject'
import { BridgeStatusContext } from './liveBridgeUtils'

const HEARTBEAT_MS = 1500
const STATUS_POLL_MS = 2500

export function LiveBridgeProvider({ children }: PropsWithChildren) {
  const { project, selectedShotId, refreshProjectFromBridge, refreshProjectFromGeneration, refreshPreviewFields } = useProject()
  const [bridgeStatus, setBridgeStatus] = useState<BridgeStatusPayload | null>(null)
  const lastPluginProjectRevisionByProjectRef = useRef(new Map<string, number>())
  const lastPreviewRevisionByProjectRef = useRef(new Map<string, number>())
  const lastGenerationRevisionByProjectRef = useRef(new Map<string, number>())
  const projectPath = project?.project_path ?? ''

  useEffect(() => {
    if (!projectPath) return
    const events = new EventSource(`${apiBase()}/api/generation/events`)
    const onGenerationResult = () => {
      void refreshProjectFromGeneration()
    }
    events.addEventListener('generation-result', onGenerationResult)
    return () => {
      events.removeEventListener('generation-result', onGenerationResult)
      events.close()
    }
  }, [projectPath, refreshProjectFromGeneration])

  useEffect(() => {
    if (!project) {
      return
    }

    let cancelled = false

    const publish = async () => {
      try {
        await publishLiveBridge(selectedShotId || '')
      } catch {
        // Heartbeat failures are transient; plugin will retry on its poll.
      }
    }

    const refreshStatus = async () => {
      try {
        const status = await getBridgeStatus()
        if (cancelled) return
        setBridgeStatus(status)

        const revision = Number(status.plugin_project_revision ?? 0)
        const projectPath = project.project_path
        if (revision > 0 && revision !== lastPluginProjectRevisionByProjectRef.current.get(projectPath)) {
          lastPluginProjectRevisionByProjectRef.current.set(projectPath, revision)
          if (status.plugin_change?.kind !== 'scene2d') {
            await refreshProjectFromBridge(status.plugin_selected_shot_id)
          }
        }

        const generationRevision = Number(status.generation_result_revision ?? 0)
        if (generationRevision > 0 && generationRevision !== lastGenerationRevisionByProjectRef.current.get(projectPath)) {
          lastGenerationRevisionByProjectRef.current.set(projectPath, generationRevision)
          await refreshProjectFromGeneration()
        }

        const pa = status.preview_analysis
        if (
          pa &&
          pa.state === 'complete' &&
          pa.decoded_count > 0 &&
          pa.project_path === project.project_path
        ) {
          const lastRev = lastPreviewRevisionByProjectRef.current.get(project.project_path)
          if (lastRev === undefined || pa.revision > lastRev) {
            lastPreviewRevisionByProjectRef.current.set(project.project_path, pa.revision)
            await refreshPreviewFields()
          }
        }
      } catch {
        if (!cancelled) setBridgeStatus(null)
      }
    }

    void publish()
    void refreshStatus()

    const heartbeatTimer = window.setInterval(() => void publish(), HEARTBEAT_MS)
    const statusTimer = window.setInterval(() => void refreshStatus(), STATUS_POLL_MS)

    return () => {
      cancelled = true
      window.clearInterval(heartbeatTimer)
      window.clearInterval(statusTimer)
    }
  }, [project, selectedShotId, refreshProjectFromBridge, refreshProjectFromGeneration, refreshPreviewFields])

  return <BridgeStatusContext.Provider value={project ? bridgeStatus : null}>{children}</BridgeStatusContext.Provider>
}
