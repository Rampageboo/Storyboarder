import type { ProjectPayload } from './project'

export type GenerationDestination = 'queue' | 'codex'
export type GenerationRequestStatus = 'queued' | 'needs-review' | 'completed' | 'failed' | 'cancelled'

export interface GenerationArtifact {
  name: string
  project_relative_path: string
  absolute_path: string
  media_type: string
}

export interface GenerationResult {
  result_id: string
  request_id: string
  shot_id: string
  created_at: string
  summary: string
  artifacts: GenerationArtifact[]
}

export interface GenerationRequest {
  schema_version: number
  request_id: string
  shot_id: string
  destination: GenerationDestination
  status: GenerationRequestStatus
  created_at: string
  updated_at: string
  input_revision: string
  consistency_revision: string
  scene_bible?: {
    scene_id: string
    title: string
    environment_prompt: string
    consistency_anchors: string[]
    primary_perspective_id: string
    primary_reference_path: string
    updated_at: string
  } | null
  character_bible?: { prompt: string }
  prompt: {
    mode: 'auto' | 'manual'
    compiled_prompt: string
    negative_prompt: string
    style_profile_id: string
    aspect_ratio: string
    variant_count: number
    layers?: {
      scene: string
      characters: string
      shot: string
    }
  }
  result_count?: number
  latest_result?: GenerationResult
}

export interface GenerationRequestResponse {
  request: GenerationRequest
  requests: GenerationRequest[]
  project: ProjectPayload
  codex_prompt?: string
}

export interface GenerationReconcileResponse {
  updated_request_ids: string[]
  updated_shot_ids: string[]
  requests: GenerationRequest[]
  project: ProjectPayload
}

export interface GenerationCandidateAcceptRequest {
  request_id: string
  result_id: string
  artifact_path: string
}

export interface GenerationCandidateAcceptResponse {
  requests: GenerationRequest[]
  project: ProjectPayload
}
