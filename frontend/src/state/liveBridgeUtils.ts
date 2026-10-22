import { createContext, useContext } from 'react'
import type { BridgeStatusPayload } from '../api'

export const BridgeStatusContext = createContext<BridgeStatusPayload | null>(null)

export function useBridgeStatus() {
  return useContext(BridgeStatusContext)
}

export function bridgeStatusLabel(status: BridgeStatusPayload | null, projectOpen: boolean): string {
  if (!projectOpen) return 'Photoshop: no project'
  if (!status) return 'PS: …'
  if (status.plugin_linked) return 'Photoshop Connected'
  return 'Photoshop Disconnected'
}

/** True when a finished preview analysis decoded new previews since the revision this window last applied. */
export function shouldRefreshPreviews(analysis: BridgeStatusPayload['preview_analysis'], lastRevision: number | undefined): boolean {
  if (!analysis || analysis.state !== 'complete' || !(analysis.decoded_count > 0)) return false
  return lastRevision === undefined || analysis.revision > lastRevision
}
