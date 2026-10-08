import { requestJson } from './client'
import type { ProjectPayload, Shot } from '../types'
import type { StoryGraph } from '../types/storyGraph'

export function putStoryGraph(graph: StoryGraph): Promise<ProjectPayload> {
  return requestJson('/api/project/story-graph', { method: 'PUT', body: graph })
}

export function postStoryBranch(body: { route_id: string; from_shot_id: string; title: string }): Promise<ProjectPayload & { shot: Shot }> {
  return requestJson('/api/project/story-graph/branch', { method: 'POST', body })
}

