export interface Scene2DPerspective {
  id: string
  title: string
  type: 'psd' | 'image' | string
  source_file_path: string
  preview_image_path: string
  linked_scene3d_id: string
  linked_scene3d_view: Record<string, unknown> | null
  created_at: string
  updated_at: string
}

export interface Scene2D {
  id: string
  title: string
  description: string
  location: string
  time_of_day: string
  environment_prompt: string
  consistency_anchors: string[]
  linked_scene3d_id: string
  primary_perspective_id: string
  source_file_path: string
  preview_image_path: string
  created_at: string
  updated_at: string
  can_be_reference: boolean
  perspectives: Scene2DPerspective[]
  preview_exists?: boolean
}

export interface Scene2DCreateRequest {
  title?: string
  description?: string
  location?: string
  time_of_day?: string
  environment_prompt?: string
  consistency_anchors?: string[]
}

export interface Scene2DUpdateRequest {
  title?: string
  description?: string
  location?: string
  time_of_day?: string
  environment_prompt?: string
  consistency_anchors?: string[]
  linked_scene3d_id?: string
  can_be_reference?: boolean
}

export interface Scene2DPerspectiveCreateRequest {
  title?: string
  type?: 'psd' | string
  linked_scene3d_id?: string
  linked_scene3d_view?: Record<string, unknown> | null
}

export interface Scene2DPerspectiveUpdateRequest {
  title?: string
  linked_scene3d_id?: string
  linked_scene3d_view?: Record<string, unknown> | null
}

export interface Scene2DPerspectiveMoveRequest {
  target_scene_id: string
}

export interface Scene2DPerspectiveReorderRequest {
  perspective_ids: string[]
}
