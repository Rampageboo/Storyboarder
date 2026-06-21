import { requestJson } from './client'

export interface PluginChange {
  revision: number
  kind: 'shot' | 'scene2d'
  scene_id?: string
  perspective_id?: string
}

export interface WorkContext {
  kind?: 'shot' | 'scene2d'
  key?: string
  shot_id?: string
  scene_id?: string
  perspective_id?: string
  scene_title?: string
  perspective_title?: string
  perspective_type?: string
  source_file_path?: string
  preview_image_path?: string
  index?: number
  count?: number
  previous_key?: string
  next_key?: string
}

export interface BridgeStatusPayload {
  app_running?: boolean
  project_open?: boolean
  plugin_linked?: boolean
  plugin_last_seen_seconds_ago?: number | null
  plugin_selected_shot_id?: string
  plugin_open_shot_ids?: string[]
  plugin_last_exported_preview?: Record<string, number>
  plugin_project_revision?: number
  work_context?: WorkContext
  plugin_active_work_key?: string
  plugin_open_work_keys?: string[]
  plugin_change?: PluginChange
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
