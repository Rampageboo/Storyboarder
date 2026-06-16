import { createContext, useContext, useEffect, useState, type PropsWithChildren } from 'react'
import { getBridgeStatus, publishLiveBridge, type BridgeStatusPayload } from '../api'
import { useProject } from './ProjectContext'

const BridgeStatusContext = createContext<BridgeStatusPayload | null>(null)

const HEARTBEAT_MS = 1500
const STATUS_POLL_MS = 2500

export function LiveBridgeProvider({ children }: PropsWithChildren) {
  const { project, selectedShotId } = useProject()
  const [bridgeStatus, setBridgeStatus] = useState<BridgeStatusPayload | null>(null)

  useEffect(() => {
    if (!project) {
      setBridgeStatus(null)
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
        if (!cancelled) setBridgeStatus(status)
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
  }, [project, selectedShotId])

  return <BridgeStatusContext.Provider value={bridgeStatus}>{children}</BridgeStatusContext.Provider>
}

export function useBridgeStatus() {
  return useContext(BridgeStatusContext)
}

export function bridgeStatusLabel(status: BridgeStatusPayload | null, projectOpen: boolean): string {
  if (!projectOpen) return 'PS: no project'
  if (!status) return 'PS: …'
  if (status.plugin_linked) return 'PS: linked'
  return 'PS: waiting for plugin'
}
