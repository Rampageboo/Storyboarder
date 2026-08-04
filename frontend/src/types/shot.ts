export const SHOT_STATUSES = [
  'Draft',
  'In Progress',
  'Review',
  'Approved',
  'Final',
] as const

export type ShotStatus = (typeof SHOT_STATUSES)[number]

export interface ShotComment {
  id: number
  text: string
  resolved?: boolean
  created_at?: string
  [key: string]: unknown
}

export interface ShotDesign {
  story_beat: string
  shot_size: string
  camera_position: string
  camera_height: string
  camera_angle: string
  camera_direction: string
  camera_movement: string
  lens_intent: string
  subject_movement: string
  composition: string
  focal_point: string
  foreground: string
  midground: string
  background: string
  axis_of_action: string
  intentional_axis_crossing: boolean
}

export interface PromptConfig {
  mode: 'auto' | 'manual'
  manual_prompt: string
  prompt_extra: string
  negative_prompt: string
  style_profile_id: string
  aspect_ratio_override: string
  variant_count: number
  reference_bindings: Record<string, unknown>[]
}

export interface ShotContinuity {
  mode: 'continuous' | 'insert' | 'montage' | 'parallel' | 'time-jump' | 'reset'
  depends_on_shot_ids: string[]
  primary_continuity_source_shot_id: string
  expected_in: string
  expected_out: string
  observed_out: string
  resolved_out: string
  preserve: string[]
  intentional_changes: string[]
}

export interface GenerationState {
  execution_status: 'idle' | 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled'
  review_status: 'unreviewed' | 'needs-review' | 'accepted' | 'rejected'
  freshness_status: 'current' | 'stale'
  active_output_id: string
  approved_output_id: string
  latest_attempt_id: string
}

export interface Shot {
  shot_id: string
  title: string
  scene: string
  scene_id: string
  sequence: string
  description: string
  action_note: string
  camera_note: string
  character_note: string
  dialogue: string
  lighting_note: string
  transition_note: string
  duration_seconds: number
  camera_data: Record<string, unknown>
  tags: string[]
  comments: ShotComment[]
  status: ShotStatus | string
  image_path: string
  preview_image_path: string
  thumbnail_path: string
  source_file_path: string
  source_sync_mtime: number
  annotation_path: string
  reference_image_paths: string[]
  ref_video_path: string
  ref_video_time: number
  ref_segment_time: number
  shot_design: ShotDesign
  prompt_config: PromptConfig
  continuity: ShotContinuity
  generation_state: GenerationState
  preview_disk_mtime?: number
  thumbnail_disk_mtime?: number
  board_background_disk_mtime?: number
  codex_layer_disk_mtime?: number
  has_board_background?: boolean
  has_codex_layer?: boolean
  has_artwork_preview?: boolean
  preview_has_transparency?: boolean
  preview_analysis_state?: 'missing' | 'provisional' | 'cached'
}

export interface ShotUpdate {
  title?: string
  scene?: string
  scene_id?: string
  sequence?: string
  description?: string
  action_note?: string
  camera_note?: string
  character_note?: string
  dialogue?: string
  lighting_note?: string
  transition_note?: string
  duration_seconds?: number
  camera_data?: Record<string, unknown>
  tags?: string[]
  status?: ShotStatus | string
  shot_design?: ShotDesign
  prompt_config?: PromptConfig
  continuity?: ShotContinuity
}

export interface AddShotRequest {
  after_shot_id?: string | null
}

export interface RestoreShotRequest {
  shot: Shot
  index?: number
}

export interface ShotBatchUpdateRequest {
  updates: Array<{ shot_id: string; changes: ShotUpdate }>
}

export interface ShotBatchDeleteRequest {
  shot_ids: string[]
}

export interface ShotBatchRestoreRequest {
  items: Array<{ shot: Shot; index: number }>
}

export interface ReorderShotsRequest {
  shot_ids: string[]
}

export interface ImportImagePathRequest {
  source_path: string
}

export interface RemoveReferenceRequest {
  path: string
}

export interface SetReferencePathsRequest {
  paths: string[]
}

export interface CanvasRequest {
  width?: number
  height?: number
  background_color?: string | null
}

export interface DrawingSaveRequest {
  image_data: string
}

export interface CommentRequest {
  text: string
}

export interface CommentResolveRequest {
  resolved?: boolean
}

export interface AnnotationSaveRequest {
  annotations: Record<string, unknown>[]
}

export interface RelinkRequest {
  relative_path: string
}
