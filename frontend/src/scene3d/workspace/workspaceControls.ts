/**
 * OrbitControls / TransformControls setup for the Scene3D workspace.
 */

import { DEFAULT_ORBIT_TARGET } from './workspaceScene'
import type { WorkspaceTransformMode, WorkspaceVec3 } from './workspaceTypes'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type ThreeObject = any

export type WorkspaceOrbitControls = {
  enabled: boolean
  target: { set(x: number, y: number, z: number): void; clone(): ThreeObject }
  update(): void
  addEventListener(type: string, listener: () => void): void
  dispose(): void
}

export type WorkspaceTransformControls = {
  setMode(mode: string): void
  attach(object: unknown): void
  detach(): void
  addEventListener(type: string, listener: (event: { value?: boolean }) => void): void
  updateMatrixWorld(): void
  dispose(): void
}

export type CreateOrbitControlsOptions = {
  target?: WorkspaceVec3
  onChange?: () => void
}

export function createWorkspaceOrbitControls(
  OrbitControlsCtor: new (camera: unknown, domElement: HTMLElement) => WorkspaceOrbitControls,
  camera: unknown,
  domElement: HTMLElement,
  options: CreateOrbitControlsOptions = {},
): WorkspaceOrbitControls {
  const orbit = new OrbitControlsCtor(camera, domElement) as ThreeObject & WorkspaceOrbitControls
  orbit.enableDamping = true
  const [tx, ty, tz] = options.target ?? DEFAULT_ORBIT_TARGET
  orbit.target.set(tx, ty, tz)
  if (options.onChange) {
    orbit.addEventListener('change', options.onChange)
  }
  return orbit
}

export type CreateTransformControlsOptions = {
  mode?: WorkspaceTransformMode
  onDraggingChanged?: (dragging: boolean) => void
  onObjectChange?: () => void
}

export function createWorkspaceTransformControls(
  TransformControlsCtor: new (camera: unknown, domElement: HTMLElement) => WorkspaceTransformControls,
  camera: unknown,
  domElement: HTMLElement,
  scene: { add(object: unknown): void },
  options: CreateTransformControlsOptions = {},
): WorkspaceTransformControls {
  const transform = new TransformControlsCtor(camera, domElement)
  transform.setMode(options.mode ?? 'translate')
  transform.addEventListener('dragging-changed', (event) => {
    options.onDraggingChanged?.(Boolean(event.value))
  })
  transform.addEventListener('objectChange', () => {
    options.onObjectChange?.()
  })
  scene.add(transform)
  return transform
}
