/**
 * Builtin-scene selection helpers (extracted from scene3d.js).
 */

import { DEFAULT_CAMERA_POSITION, DEFAULT_ORBIT_TARGET } from './workspaceScene'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type ThreeObject = any

export function canDeleteWorkspaceObject(selectedId: string | null | undefined): boolean {
  return Boolean(selectedId && selectedId !== 'ground')
}

export function shouldAttachTransformToSelection(
  mode: 'builtin' | 'blender',
  mesh: ThreeObject | null | undefined,
): boolean {
  return Boolean(mesh && mode === 'builtin')
}

export function getWorkspaceFocusTarget(
  mesh: ThreeObject | null | undefined,
  orbit: { target: ThreeObject },
): ThreeObject {
  return mesh ? mesh.position.clone() : orbit.target.clone()
}

export function resetBuiltinCameraView(
  camera: ThreeObject,
  orbit: { target: ThreeObject; update(): void },
): void {
  const [px, py, pz] = DEFAULT_CAMERA_POSITION
  const [tx, ty, tz] = DEFAULT_ORBIT_TARGET
  camera.position.set(px, py, pz)
  orbit.target.set(tx, ty, tz)
  orbit.update()
}
