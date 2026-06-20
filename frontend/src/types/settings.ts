export interface RefSegmentVideoSettings {
  path?: string
  time?: number
  [key: string]: unknown
}

export interface RefSegmentSettings {
  [key: string]: unknown
}

export type ReferenceMediaType = 'image' | 'video' | 'model' | 'scene2d'

export interface ReferenceLink {
  id: string
  path: string
  type: ReferenceMediaType | string
  title?: string
  source_scene2d_id?: string
  source_scene2d_perspective_id?: string
  [key: string]: unknown
}

export interface ProjectSettings {
  photoshop_path?: string
  blender_path?: string
  canvas_background_color?: string
  canvas_width?: number
  canvas_height?: number
  apply_canvas_size_to_blank_shots?: boolean
  preheat_photoshop_on_open?: boolean
  scene3d?: Record<string, unknown>
  reference_video_path?: string
  reference_model_path?: string
  reference_image_path?: string
  reference_segment_mode?: string
  reference_links?: ReferenceLink[]
  ref_segment?: RefSegmentSettings
  ref_segments?: RefSegmentSettings[]
  active_ref_segment_id?: string
  ref_segment_video?: RefSegmentVideoSettings
  recent_projects?: string[]
  [key: string]: unknown
}

/** PATCH /api/project/settings body (all fields optional). */
export interface SettingsUpdate {
  photoshop_path?: string | null
  blender_path?: string | null
  canvas_background_color?: string | null
  canvas_width?: number | null
  canvas_height?: number | null
  apply_canvas_size_to_blank_shots?: boolean | null
  preheat_photoshop_on_open?: boolean | null
  scene3d?: Record<string, unknown> | null
  reference_video_path?: string | null
  reference_model_path?: string | null
  reference_image_path?: string | null
  reference_segment_mode?: string | null
  reference_links?: ReferenceLink[] | null
  ref_segment?: RefSegmentSettings | null
  ref_segments?: RefSegmentSettings[] | null
  active_ref_segment_id?: string | null
  ref_segment_video?: RefSegmentVideoSettings | null
}
