/**
 * GLB load orchestration helpers (extracted from scene3d.js _loadBlenderUrl).
 */

import { computeClipDuration, selectAnimationClips } from './workspaceAnimation'
import type { WorkspaceImportedCamera } from './workspaceGlb'
import { diagnoseMissingCameras } from './workspaceGlb'
import type { ProgramLightingMode } from './workspaceLighting'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type ThreeObject = any
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type AnimationClip = any

export type WorkspaceAnimationMixerBoot = {
  mixer: ThreeObject
  mixerActions: ThreeObject[]
  animationDuration: number
}

export function createWorkspaceAnimationMixer(
  THREE: Record<string, unknown>,
  scene: ThreeObject,
  animations: AnimationClip[] | null | undefined,
): WorkspaceAnimationMixerBoot {
  const clipsToPlay = selectAnimationClips(animations || [])
  const Mixer = THREE.AnimationMixer as new (root: ThreeObject) => ThreeObject
  const mixer = new Mixer(scene)
  const mixerActions: ThreeObject[] = []
  const LoopOnce = THREE.LoopOnce as number
  for (const clip of clipsToPlay) {
    const action = mixer.clipAction(clip)
    action.setLoop(LoopOnce, 1)
    action.play()
    mixerActions.push(action)
  }
  const animationDuration = computeClipDuration(clipsToPlay.length ? clipsToPlay : animations)
  return { mixer, mixerActions, animationDuration }
}

export type GlbLoadNotificationInput = {
  gltf: {
    animations?: AnimationClip[]
    cameras?: unknown[]
    parser?: { json?: { nodes?: { camera?: number }[] } }
  }
  importedCameras: WorkspaceImportedCamera[]
  animationDuration: number
  importedLightCount: number
  programLightingMode: ProgramLightingMode
}

/** User-facing messages after a GLB workspace load (empty = no toast). */
export function buildGlbLoadNotifications(input: GlbLoadNotificationInput): string[] {
  const { gltf, importedCameras, animationDuration, importedLightCount, programLightingMode } = input
  const messages: string[] = []

  if (importedCameras.length === 0) {
    messages.push(diagnoseMissingCameras(gltf))
    return messages
  }

  if (importedCameras.some((item) => item.orphan)) {
    messages.push(`已找到 ${importedCameras.length} 个相机（部分未挂到场景树，已自动修复）。`)
  } else if (!(gltf.animations || []).length) {
    messages.push('场景已加载，但未找到动画。请在 Blender 导出时勾选 Animation。')
  } else if (animationDuration <= 0) {
    messages.push('已找到动画轨道，但时长为 0。请检查 Blender 时间轴范围与关键帧。')
  } else if (programLightingMode === 'auto') {
    if (importedLightCount > 0) {
      messages.push(
        `检测到 GLB 含 ${importedLightCount} 盏灯，已校准强度并启用弱环境反射（模拟 Blender World）。`,
      )
    } else {
      messages.push('GLB 无导出灯光，已自动开启全程序补光。')
    }
  }

  return messages
}

export function resolveInitialAnimationTime(
  meta: { animation_time?: unknown },
  shotTime: unknown,
): number | null {
  if (shotTime != null && !Number.isNaN(Number(shotTime))) {
    return Number(shotTime)
  }
  const fromMeta = Number(meta.animation_time)
  if (!Number.isNaN(fromMeta) && fromMeta >= 0) return fromMeta
  return null
}

export function resolveReloadAnimationTime(savedTime: number, animationDuration: number): number {
  if (savedTime <= 0) return 0
  return Math.min(savedTime, animationDuration || savedTime)
}

export function formatWorkspaceFileName(
  mode: 'builtin' | 'blender',
  sceneMeta: { blend_file_path?: string; file_name?: string; file_path?: string },
): string {
  const blendPath = sceneMeta.blend_file_path || 'scene3d/scene.blend'
  const glbName = sceneMeta.file_name || sceneMeta.file_path || ''
  if (mode === 'blender' && glbName) {
    return `GLB: ${String(glbName).split('/').pop()}`
  }
  return blendPath.split('/').pop() || 'scene.blend'
}

export function getWireframeRoots(
  blenderRoot: ThreeObject | null | undefined,
  objectMeshes: Iterable<ThreeObject>,
): ThreeObject[] {
  const roots: ThreeObject[] = []
  if (blenderRoot) roots.push(blenderRoot)
  for (const mesh of objectMeshes) roots.push(mesh)
  return roots
}

export function filterBuiltinObjectSpecs(
  sceneMeta: { objects?: { type?: string }[] } | null | undefined,
  defaultSceneData: () => { objects: { type?: string }[] },
  primitiveTypes: Set<string>,
): { objects: { type?: string }[] } {
  const sceneData =
    sceneMeta?.objects?.length ? sceneMeta : defaultSceneData()
  const objects = (sceneData.objects || []).filter((spec) => primitiveTypes.has(String(spec.type || '')))
  return { ...sceneData, objects }
}
