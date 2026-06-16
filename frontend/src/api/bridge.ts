import { requestJson } from './client'

export interface BridgeStatusPayload {
  ok?: string
  status?: string
  bridge_url?: string
  server_port?: number
  plugin_last_seen?: number
  plugin_open_shot_ids?: string[]
  [key: string]: unknown
}

export function getBridgeStatus(): Promise<BridgeStatusPayload> {
  return requestJson<BridgeStatusPayload>('/api/bridge/status')
}

export function relinkBridge(): Promise<Record<string, unknown>> {
  return requestJson<Record<string, unknown>>('/api/bridge/relink', { method: 'POST' })
}

