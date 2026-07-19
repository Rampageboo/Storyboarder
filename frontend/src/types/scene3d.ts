export interface Scene3DRecord {
  id: string
  title: string
  description: string
  source_type: string
  file_path: string
  file_name: string
  blend_file_path: string
  keywords: string[]
  reference_view: Record<string, unknown>
  display_settings: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface Scene3DListResponse {
  active_scene3d_id: string
  scenes: Scene3DRecord[]
}

export interface Scene3DSceneResponse extends Scene3DListResponse {
  scene: Scene3DRecord
}

export interface Scene3DCreateRequest {
  title?: string
  description?: string
  keywords?: string[]
}

export interface Scene3DUpdateRequest {
  title?: string
  description?: string
  keywords?: string[]
  reference_view?: Record<string, unknown> | null
  display_settings?: Record<string, unknown> | null
}
