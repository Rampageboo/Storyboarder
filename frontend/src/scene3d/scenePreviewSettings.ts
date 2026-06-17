import type { ProjectSettings } from '../types/settings'
import {
  loadPreviewStyle,
  SCENE3D_WORKSPACE_BACKGROUND,
  type Scene3dPreviewSettings,
} from './previewStyleBridge'

export { SCENE3D_WORKSPACE_BACKGROUND }
export type { Scene3dPreviewSettings }

const DEFAULT_PREVIEW_SETTINGS: Scene3dPreviewSettings = {
  wireframeMode: 'off',
  objectColorPreview: true,
  sceneBackground: SCENE3D_WORKSPACE_BACKGROUND,
}

/** Read Scene3D workspace preview options for the reference GLB renderer. */
export async function resolveScene3dPreviewSettings(
  settings: ProjectSettings | null | undefined,
): Promise<Scene3dPreviewSettings> {
  const style = await loadPreviewStyle()
  const scene3d = (settings?.scene3d ?? {}) as Record<string, unknown>
  return style.resolvePreviewSettings(scene3d)
}

export function resolveScene3dPreviewSettingsSync(
  settings: ProjectSettings | null | undefined,
  style: Awaited<ReturnType<typeof loadPreviewStyle>>,
): Scene3dPreviewSettings {
  const scene3d = (settings?.scene3d ?? {}) as Record<string, unknown>
  return style.resolvePreviewSettings(scene3d)
}

export function defaultPreviewSettings(): Scene3dPreviewSettings {
  return { ...DEFAULT_PREVIEW_SETTINGS }
}
