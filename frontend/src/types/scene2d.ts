export interface Scene2D {
  id: string
  title: string
  description: string
  source_file_path: string
  preview_image_path: string
  created_at: string
  updated_at: string
  can_be_reference: boolean
  preview_exists?: boolean
}

export interface Scene2DCreateRequest {
  title?: string
  description?: string
}

export interface Scene2DUpdateRequest {
  title?: string
  description?: string
  can_be_reference?: boolean
}
