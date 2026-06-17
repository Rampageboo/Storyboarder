/**
 * Serialize / deserialize Scene3D workspace scene metadata.
 */

import type { WorkspaceObjectSpec, WorkspaceSceneData } from './workspaceTypes'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type ThreeObject = any

export function formatWorkspaceTime(seconds: number): string {
  const value = Math.max(0, Number(seconds) || 0)
  const mins = Math.floor(value / 60)
  const secs = (value % 60).toFixed(1).padStart(mins > 0 ? 4 : 1, '0')
  return mins > 0 ? `${mins}:${secs}` : `${secs}s`
}

export function meshToObjectSpec(id: string, mesh: ThreeObject): WorkspaceObjectSpec {
  return {
    id,
    name: String(mesh.userData?.objectName || mesh.userData?.objectType || id),
    type: String(mesh.userData?.objectType || 'cube'),
    position: mesh.position.toArray(),
    rotation: mesh.rotation.toArray().slice(0, 3),
    scale: mesh.scale.toArray(),
    color: `#${mesh.material.color.getHexString()}`,
  }
}

export function exportBuiltinSceneObjects(
  objects: Iterable<[string, ThreeObject]>,
): WorkspaceObjectSpec[] {
  const out: WorkspaceObjectSpec[] = []
  for (const [id, mesh] of objects) {
    out.push(meshToObjectSpec(id, mesh))
  }
  return out
}

export function exportBuiltinSceneData(
  objects: Iterable<[string, ThreeObject]>,
  wireframeMode: string,
  objectColorPreview: boolean,
): WorkspaceSceneData {
  return {
    source: 'builtin',
    objects: exportBuiltinSceneObjects(objects),
    wireframe_mode: wireframeMode,
    object_color_preview: objectColorPreview,
  }
}

export type BlenderSceneExportState = {
  sceneMeta: Record<string, unknown>
  activeCameraName: string
  followCamera: boolean
  animationTime: number
  programLightingMode: string
  importedLightCount: number
  objectColorPreview: boolean
  wireframeMode: string
}

export function exportBlenderSceneData(state: BlenderSceneExportState): Record<string, unknown> {
  return {
    ...state.sceneMeta,
    source: 'blender',
    camera_name: state.activeCameraName,
    follow_camera: state.followCamera,
    animation_time: state.animationTime,
    program_lighting: state.programLightingMode,
    imported_light_count: state.importedLightCount,
    object_color_preview: state.objectColorPreview,
    wireframe_mode: state.wireframeMode,
  }
}

export function normalizeWorkspaceSceneMeta(settings: unknown): Record<string, unknown> {
  return settings && typeof settings === 'object' ? { ...(settings as Record<string, unknown>) } : {}
}
