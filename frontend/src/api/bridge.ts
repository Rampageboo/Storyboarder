import { requestJson } from './client'

export interface BridgeStatusPayload {
  app_running?: boolean
  project_open?: boolean
  plugin_linked?: boolean
  plugin_last_seen_seconds_ago?: number | null
  plugin_selected_shot_id?: string
  plugin_open_shot_ids?: string[]
  plugin_last_exported_preview?: Record<string, number>
  plugin_project_revision?: number
  bridge_url?: string
  global_bridge_path?: string
  shared_bridge_path?: string
  plugin_heartbeat_path?: string
  server_port?: number
  live?: Record<string, unknown>
  [key: string]: unknown
}

export interface LiveBridgeUpdate {
  selected_shot_id?: string | null
}

/** Publish live bridge state so the Photoshop plugin can link (writes JSON + HTTP). */
export function publishLiveBridge(selectedShotId = ''): Promise<Record<string, unknown>> {
  return requestJson<Record<string, unknown>>('/api/bridge/live', {
    method: 'PUT',
    body: { selected_shot_id: selectedShotId },
  })
}

export function getBridgeStatus(): Promise<BridgeStatusPayload> {
  return requestJson<BridgeStatusPayload>('/api/bridge/status')
}

export function relinkBridge(): Promise<Record<string, unknown>> {
  return requestJson<Record<string, unknown>>('/api/bridge/relink', { method: 'POST' })
}
