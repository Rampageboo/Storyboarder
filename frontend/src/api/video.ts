import { requestJson } from './client'

export type ComfyCloudStatus = { configured: boolean; template: string; provider: string }

export type ComfyCloudCheck = {
  ok: boolean
  template: string
  node_count: number
  missing_nodes: string[]
  missing_models: string[]
  invalid_values: string[]
}

export type VideoTakeStatus = 'queued' | 'uploading' | 'running' | 'downloading' | 'succeeded' | 'failed'

export type VideoTake = {
  take_id: string
  shot_id: string
  status: VideoTakeStatus
  template: string
  mode?: 'i2v' | 'flf'
  end_shot_id?: string
  prompt: string
  negative_prompt: string
  seconds: number
  frames: number
  width: number
  height: number
  error: string
  video_path: string
  created_at: string
  updated_at?: string
}

export type VideoPromptDraft = { prompt: string; negative_prompt: string; seconds: number }

export const VIDEO_TAKE_ACTIVE: ReadonlySet<string> = new Set(['queued', 'uploading', 'running', 'downloading'])

export function getComfyCloudStatus(): Promise<ComfyCloudStatus> {
  return requestJson<ComfyCloudStatus>('/api/comfy-cloud')
}

/** Stores the key in the OS credential store; the response never contains it. */
export function setComfyCloudKey(apiKey: string): Promise<ComfyCloudStatus> {
  return requestJson<ComfyCloudStatus>('/api/comfy-cloud/key', { method: 'PUT', body: { api_key: apiKey } })
}

export function clearComfyCloudKey(): Promise<ComfyCloudStatus> {
  return requestJson<ComfyCloudStatus>('/api/comfy-cloud/key', { method: 'DELETE' })
}

export function checkComfyCloud(): Promise<ComfyCloudCheck> {
  return requestJson<ComfyCloudCheck>('/api/comfy-cloud/check', { method: 'POST' })
}

export function getVideoPromptDraft(shotId: string): Promise<VideoPromptDraft> {
  return requestJson<VideoPromptDraft>(`/api/shots/${encodeURIComponent(shotId)}/video-prompt`)
}

export function listVideoTakes(shotId: string): Promise<{ takes: VideoTake[] } & ComfyCloudStatus> {
  return requestJson(`/api/shots/${encodeURIComponent(shotId)}/video-takes`)
}

export function createVideoTake(
  shotId: string,
  body: { prompt: string; negative_prompt: string; seconds: number; end_shot_id?: string },
): Promise<{ take: VideoTake }> {
  return requestJson(`/api/shots/${encodeURIComponent(shotId)}/video-takes`, { method: 'POST', body })
}

export function deleteVideoTake(takeId: string): Promise<{ deleted: string }> {
  return requestJson(`/api/video-takes/${encodeURIComponent(takeId)}`, { method: 'DELETE' })
}

export function videoTakeUrl(take: VideoTake): string {
  return `/api/video-takes/${encodeURIComponent(take.take_id)}/video?v=${encodeURIComponent(take.updated_at || take.created_at)}`
}
