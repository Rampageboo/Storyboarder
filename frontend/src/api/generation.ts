import { requestJson } from './client'
import type {
  GenerationCandidateAcceptRequest,
  GenerationCandidateAcceptResponse,
  GenerationBatchRequestResponse,
  GenerationDestination,
  GenerationMode,
  GenerationProvider,
  GenerationReconcileResponse,
  GenerationPullResponse,
  GenerationRequest,
  GenerationRequestDeleteResponse,
  GenerationRequestResponse,
} from '../types'

export interface CreateGenerationRequestOptions {
  provider?: GenerationProvider
  // Empty string lets the backend derive the mode from the shot's status.
  mode?: GenerationMode | ''
}

export function createGenerationRequest(
  shotId: string,
  destination: GenerationDestination,
  options: CreateGenerationRequestOptions = {},
): Promise<GenerationRequestResponse> {
  const body: {
    destination: GenerationDestination
    provider?: GenerationProvider
    mode?: GenerationMode
  } = { destination }
  if (options.provider) body.provider = options.provider
  if (options.mode) body.mode = options.mode
  return requestJson<GenerationRequestResponse>(
    `/api/shots/${encodeURIComponent(shotId)}/generation-requests`,
    { method: 'POST', body },
  )
}

export function createCodexBatchRequests(): Promise<GenerationBatchRequestResponse> {
  return requestJson<GenerationBatchRequestResponse>(
    '/api/generation/requests/codex-batch',
    { method: 'POST' },
  )
}

export function listGenerationRequests(shotId = ''): Promise<{ requests: GenerationRequest[] }> {
  const query = shotId ? `?shot_id=${encodeURIComponent(shotId)}` : ''
  return requestJson<{ requests: GenerationRequest[] }>(`/api/generation/requests${query}`)
}

export function deleteGenerationRequest(requestId: string): Promise<GenerationRequestDeleteResponse> {
  return requestJson<GenerationRequestDeleteResponse>(
    `/api/generation/requests/${encodeURIComponent(requestId)}`,
    { method: 'DELETE' },
  )
}

export function reconcileGenerationRequests(): Promise<GenerationReconcileResponse> {
  return requestJson<GenerationReconcileResponse>('/api/generation/reconcile', { method: 'POST' })
}

export function pullGenerationResults(): Promise<GenerationPullResponse> {
  return requestJson<GenerationPullResponse>('/api/generation/pull', { method: 'POST' })
}

export function acceptGenerationCandidate(
  shotId: string,
  body: GenerationCandidateAcceptRequest,
): Promise<GenerationCandidateAcceptResponse> {
  return requestJson<GenerationCandidateAcceptResponse>(
    `/api/shots/${encodeURIComponent(shotId)}/codex-layer/accept`,
    { method: 'POST', body },
  )
}
