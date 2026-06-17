/**
 * Three.js + workspace controls loader (OrbitControls, TransformControls, RoomEnvironment).
 * Extends the shared reference-pipeline runtime with editor-specific modules.
 */

import { loadThreeRuntime, type ThreeRuntime } from '../threeRuntime'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type ThreeModule = Record<string, any>

export type WorkspaceThreeRuntime = ThreeRuntime & {
  OrbitControls: new (camera: unknown, domElement: HTMLElement) => {
    enabled: boolean
    update(): void
    dispose(): void
  }
  TransformControls: new (camera: unknown, domElement: HTMLElement) => {
    setMode(mode: string): void
    attach(object: unknown): void
    detach(): void
    dispose(): void
  }
  RoomEnvironment: new () => unknown
}

let workspaceRuntimePromise: Promise<WorkspaceThreeRuntime> | null = null

export function loadWorkspaceThreeRuntime(): Promise<WorkspaceThreeRuntime> {
  if (!workspaceRuntimePromise) {
    const orbitUrl = '/static/vendor/three/OrbitControls.js'
    const transformUrl = '/static/vendor/three/TransformControls.js'
    const roomEnvUrl = '/static/vendor/three/RoomEnvironment.js'
    workspaceRuntimePromise = Promise.all([
      loadThreeRuntime(),
      import(/* @vite-ignore */ orbitUrl) as Promise<ThreeModule>,
      import(/* @vite-ignore */ transformUrl) as Promise<ThreeModule>,
      import(/* @vite-ignore */ roomEnvUrl) as Promise<ThreeModule>,
    ]).then(([base, orbit, transform, room]) => ({
      ...base,
      OrbitControls: orbit.OrbitControls as WorkspaceThreeRuntime['OrbitControls'],
      TransformControls: transform.TransformControls as WorkspaceThreeRuntime['TransformControls'],
      RoomEnvironment: room.RoomEnvironment as WorkspaceThreeRuntime['RoomEnvironment'],
    }))
  }
  return workspaceRuntimePromise
}
