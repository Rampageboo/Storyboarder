import type { ProjectSettings } from '../types/settings'
import {
  resolvePreviewSettings,
  SCENE3D_WORKSPACE_BACKGROUND,
  type Scene3dPreviewSettings,
} from './previewStyle'

export { SCENE3D_WORKSPACE_BACKGROUND }
export type { Scene3dPreviewSettings }

const DEFAULT_PREVIEW_SETTINGS: Scene3dPreviewSettings = {
  wireframeMode: 'off',
  objectColorPreview: true,
  sceneBackground: SCENE3D_WORKSPACE_BACKGROUND,
}

/** Read Scene3D workspace preview options for the reference GLB renderer. */
export function resolveScene3dPreviewSettings(
  settings: ProjectSettings | null | undefined,
): Scene3dPreviewSettings {
  const scene3d = (settings?.scene3d ?? {}) as Record<string, unknown>
  return resolvePreviewSettings(scene3d)
}

export function defaultPreviewSettings(): Scene3dPreviewSettings {
  return { ...DEFAULT_PREVIEW_SETTINGS }
}
