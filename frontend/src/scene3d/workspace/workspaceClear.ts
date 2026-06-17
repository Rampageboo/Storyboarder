/**
 * Blender scene teardown state helpers (extracted from scene3d.js clearBlenderScene).
 */

import type { WorkspaceImportedCamera } from './workspaceGlb'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type ThreeObject = any

export type EmptyBlenderPlaybackState = {
  mixer: null
  mixerActions: ThreeObject[]
  importedCameras: WorkspaceImportedCamera[]
  activeCameraId: string
  importedLightCount: number
  animationDuration: number
  animationTime: number
  isPlaying: boolean
}

export function createEmptyBlenderPlaybackState(): EmptyBlenderPlaybackState {
  return {
    mixer: null,
    mixerActions: [],
    importedCameras: [],
    activeCameraId: '',
    importedLightCount: 0,
    animationDuration: 0,
    animationTime: 0,
    isPlaying: false,
  }
}

export function stopWorkspaceMixer(mixer: { stopAllAction(): void } | null | undefined): void {
  mixer?.stopAllAction?.()
}
