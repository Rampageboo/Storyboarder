import { requestJson } from './client'
import type {
  GenerationCandidateAcceptRequest,
  GenerationCandidateAcceptResponse,
  GenerationDestination,
  GenerationReconcileResponse,
  GenerationRequest,
  GenerationRequestResponse,
} from '../types'

export function createGenerationRequest(
  shotId: string,
  destination: GenerationDestination,
): Promise<GenerationRequestResponse> {
  return requestJson<GenerationRequestResponse>(
    `/api/shots/${encodeURIComponent(shotId)}/generation-requests`,
    { method: 'POST', body: { destination } },
  )
}

export function listGenerationRequests(shotId = ''): Promise<{ requests: GenerationRequest[] }> {
  const query = shotId ? `?shot_id=${encodeURIComponent(shotId)}` : ''
  return requestJson<{ requests: GenerationRequest[] }>(`/api/generation/requests${query}`)
}

export function reconcileGenerationRequests(): Promise<GenerationReconcileResponse> {
  return requestJson<GenerationReconcileResponse>('/api/generation/reconcile', { method: 'POST' })
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
