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

export interface Shot {
  shot_id: string
  title: string
  scene: string
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
  preview_disk_mtime?: number
  thumbnail_disk_mtime?: number
  board_background_disk_mtime?: number
  has_board_background?: boolean
  has_artwork_preview?: boolean
  preview_has_transparency?: boolean
  preview_analysis_state?: 'missing' | 'provisional' | 'cached'
}

export interface ShotUpdate {
  title?: string
  scene?: string
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
}

export interface AddShotRequest {
  after_shot_id?: string | null
}

export interface RestoreShotRequest {
  shot: Shot
  index?: number
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
