import { requestJson } from './client'
import type { ProjectPayload, SettingsUpdate } from '../types'

export function updateSettings(body: SettingsUpdate): Promise<ProjectPayload> {
  return requestJson<ProjectPayload>('/api/project/settings', {
    method: 'PATCH',
    body,
  })
}
