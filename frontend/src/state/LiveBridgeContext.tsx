import { useEffect, useRef, useState, type PropsWithChildren } from 'react'
import { getBridgeStatus, getProject, publishLiveBridge, type BridgeStatusPayload } from '../api'
import { useProject } from './useProject'
import { BridgeStatusContext } from './liveBridgeUtils'

const HEARTBEAT_MS = 1500
const STATUS_POLL_MS = 2500

export function LiveBridgeProvider({ children }: PropsWithChildren) {
  const { project, selectedShotId, setProject, setSelectedShotId } = useProject()
  const [bridgeStatus, setBridgeStatus] = useState<BridgeStatusPayload | null>(null)
  const lastPluginProjectRevisionRef = useRef<number | null>(null)

  const [prevProject, setPrevProject] = useState(project)
  if (project !== prevProject) {
    setPrevProject(project)
    if (!project) setBridgeStatus(null)
  }

  useEffect(() => {
    if (!project) {
      lastPluginProjectRevisionRef.current = null
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
        if (revision > 0 && revision !== lastPluginProjectRevisionRef.current) {
          lastPluginProjectRevisionRef.current = revision
          const payload = await getProject()
          if (cancelled) return
          setProject(payload)
          const pluginShotId = status.plugin_selected_shot_id
          if (pluginShotId && payload.shots.some((shot) => shot.shot_id === pluginShotId)) {
            setSelectedShotId(pluginShotId)
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
  }, [project, selectedShotId, setProject, setSelectedShotId])

  return <BridgeStatusContext.Provider value={bridgeStatus}>{children}</BridgeStatusContext.Provider>
}

