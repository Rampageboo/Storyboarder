import { useEffect, useRef, useState, type PropsWithChildren } from 'react'
import { getBridgeStatus, publishLiveBridge, type BridgeStatusPayload } from '../api'
import { useProject } from './useProject'
import { BridgeStatusContext } from './liveBridgeUtils'

const HEARTBEAT_MS = 1500
const STATUS_POLL_MS = 2500

export function LiveBridgeProvider({ children }: PropsWithChildren) {
  const { project, selectedShotId, refreshProjectFromBridge, refreshPreviewFields } = useProject()
  const [bridgeStatus, setBridgeStatus] = useState<BridgeStatusPayload | null>(null)
  const lastPluginProjectRevisionRef = useRef<number | null>(null)
  const lastPreviewRevisionRef = useRef<number | null>(null)

  useEffect(() => {
    if (!project) {
      lastPluginProjectRevisionRef.current = null
      lastPreviewRevisionRef.current = null
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

        // Plugin project-revision change → reload shot data (except scene2d, handled locally)
        const revision = Number(status.plugin_project_revision ?? 0)
        if (revision > 0 && revision !== lastPluginProjectRevisionRef.current) {
          lastPluginProjectRevisionRef.current = revision
          if (status.plugin_change?.kind !== 'scene2d') {
            await refreshProjectFromBridge(status.plugin_selected_shot_id)
          }
        }

        // Preview-analysis completion → narrow merge of preview fields only.
        // Only react when: project matches, state is complete, decoded_count > 0,
        // and revision is newer than the last one we handled.
        const pa = status.preview_analysis
        if (
          pa &&
          pa.state === 'complete' &&
          pa.decoded_count > 0 &&
          pa.project_path === project.project_path
        ) {
          const lastRev = lastPreviewRevisionRef.current
          if (lastRev === null || pa.revision > lastRev) {
            lastPreviewRevisionRef.current = pa.revision
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
  }, [project, selectedShotId, refreshProjectFromBridge, refreshPreviewFields])

  return <BridgeStatusContext.Provider value={project ? bridgeStatus : null}>{children}</BridgeStatusContext.Provider>
}

