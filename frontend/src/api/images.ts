import { requestJson } from './client'
import type { ProjectPayload } from '../types'
import type { ComfyCloudStatus } from './video'

// Board image generation on Comfy Cloud. The job record mirrors the backend's
// `generation/image/<job_id>.json`; keep every field the UI reads in this one type.

export type ImageJobStatus = 'queued' | 'uploading' | 'running' | 'downloading' | 'succeeded' | 'failed'

/** 't2i' = text → image (Z-Image Turbo), 'edit' = reference(s) → image (Qwen-Image-Edit-2511). */
export type ImageJobMode = 't2i' | 'edit'

export type ImageJobReference = { id: string; kind: 'board' | 'reference'; path: string }

export type ImageJobOutput = { index: number; path: string; width: number; height: number; bytes: number }

export type ImageJob = {
  job_id: string
  shot_id: string
  status: ImageJobStatus
  mode: ImageJobMode
  prompt: string
  negative_prompt: string
  /** Boards (or project reference images) used as references. */
  references: ImageJobReference[]
  seed: number | null
  width: number
  height: number
  /** Output images; each is served by `imageJobOutputUrl(job, index)`. */
  outputs: ImageJobOutput[]
  applied_index: number | null
  error: string
  created_at: string
  updated_at?: string
}

export type CreateImageJobRequest = {
  prompt: string
  negative_prompt?: string
  references?: string[]
  seed?: number
  apply?: boolean
}

export const IMAGE_JOB_ACTIVE: ReadonlySet<string> = new Set(['queued', 'uploading', 'running', 'downloading'])

/** Reference → image accepts at most this many reference images. */
export const IMAGE_JOB_MAX_REFERENCES = 3

export const IMAGE_MODEL_LABEL: Record<ImageJobMode, string> = {
  t2i: 'Z-Image Turbo · text to image',
  edit: 'Qwen Image Edit · reference to image',
}

export function listImageJobs(shotId: string): Promise<{ jobs: ImageJob[] } & ComfyCloudStatus> {
  return requestJson(`/api/shots/${encodeURIComponent(shotId)}/image-jobs`)
}

export function createImageJob(shotId: string, body: CreateImageJobRequest): Promise<{ job: ImageJob }> {
  return requestJson(`/api/shots/${encodeURIComponent(shotId)}/image-jobs`, { method: 'POST', body })
}

/** Puts output `index` on the board through the normal import path; returns the updated project. */
export function applyImageJob(jobId: string, index: number): Promise<ProjectPayload & { job: ImageJob }> {
  return requestJson<ProjectPayload & { job: ImageJob }>(`/api/image-jobs/${encodeURIComponent(jobId)}/apply`, { method: 'POST', body: { index } })
}

export function deleteImageJob(jobId: string): Promise<{ deleted: string }> {
  return requestJson(`/api/image-jobs/${encodeURIComponent(jobId)}`, { method: 'DELETE' })
}

export function imageJobOutputUrl(job: ImageJob, index: number): string {
  return `/api/image-jobs/${encodeURIComponent(job.job_id)}/outputs/${index}?v=${encodeURIComponent(job.updated_at || job.created_at)}`
}
