/**
 * Builtin-scene transform input sync (extracted from scene3d.js).
 */

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type ThreeObject = any

export type WorkspaceTransformInputs = Record<string, { value: string; disabled: boolean }>

export function applyTransformFromInputs(
  THREE: Record<string, unknown>,
  mesh: ThreeObject,
  inputs: WorkspaceTransformInputs,
  changedKey?: string,
  transform?: { updateMatrixWorld(): void },
): void {
  const read = (key: string, fallback: number) => Number(inputs[key]?.value) || fallback
  const MathUtils = THREE.MathUtils as {
    degToRad(deg: number): number
    radToDeg(rad: number): number
  }
  mesh.position.set(read('px', mesh.position.x), read('py', mesh.position.y), read('pz', mesh.position.z))
  mesh.rotation.set(
    MathUtils.degToRad(read('rx', MathUtils.radToDeg(mesh.rotation.x))),
    MathUtils.degToRad(read('ry', MathUtils.radToDeg(mesh.rotation.y))),
    MathUtils.degToRad(read('rz', MathUtils.radToDeg(mesh.rotation.z))),
  )
  mesh.scale.set(
    Math.max(0.01, read('sx', mesh.scale.x)),
    Math.max(0.01, read('sy', mesh.scale.y)),
    Math.max(0.01, read('sz', mesh.scale.z)),
  )
  if (changedKey) {
    transform?.updateMatrixWorld()
  }
}

export function syncTransformInputsFromMesh(
  THREE: Record<string, unknown>,
  mesh: ThreeObject | null | undefined,
  inputs: WorkspaceTransformInputs,
): void {
  const disabled = !mesh
  for (const input of Object.values(inputs)) {
    input.disabled = disabled
  }
  if (!mesh) return
  const MathUtils = THREE.MathUtils as { radToDeg(rad: number): number }
  inputs.px.value = mesh.position.x.toFixed(2)
  inputs.py.value = mesh.position.y.toFixed(2)
  inputs.pz.value = mesh.position.z.toFixed(2)
  inputs.rx.value = MathUtils.radToDeg(mesh.rotation.x).toFixed(1)
  inputs.ry.value = MathUtils.radToDeg(mesh.rotation.y).toFixed(1)
  inputs.rz.value = MathUtils.radToDeg(mesh.rotation.z).toFixed(1)
  inputs.sx.value = mesh.scale.x.toFixed(2)
  inputs.sy.value = mesh.scale.y.toFixed(2)
  inputs.sz.value = mesh.scale.z.toFixed(2)
}

export const WIREFRAME_MODE_LABELS: Record<string, string> = {
  off: '关闭',
  on: '标准',
  strong: '强化',
}
