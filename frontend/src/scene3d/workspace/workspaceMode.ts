/**
 * Workspace display mode switching (extracted from scene3d.js setMode).
 */

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type ThreeObject = any

export type WorkspaceSceneModeTargets = {
  grid: ThreeObject
  axes: ThreeObject
  defaultAmbient: ThreeObject
  defaultSun: ThreeObject
  programAmbient: ThreeObject
  programHemisphere: ThreeObject
  scene: ThreeObject
  builtinBackground: ThreeObject
}

export function applyWorkspaceModeUi(rootEl: HTMLElement, mode: 'builtin' | 'blender'): void {
  rootEl.classList.toggle('scene3d-mode-blender', mode === 'blender')
  rootEl.classList.toggle('scene3d-mode-builtin', mode === 'builtin')
  rootEl.querySelectorAll('.scene3d-blender-only').forEach((node) => {
    ;(node as HTMLElement).hidden = mode !== 'blender'
  })
  rootEl.querySelectorAll('.scene3d-builtin-only').forEach((node) => {
    ;(node as HTMLElement).hidden = mode === 'blender'
  })
}

export function applyWorkspaceSceneModeFlags(
  mode: 'builtin' | 'blender',
  targets: WorkspaceSceneModeTargets,
): void {
  const builtin = mode === 'builtin'
  targets.grid.visible = builtin
  targets.axes.visible = builtin
  targets.defaultAmbient.visible = builtin
  targets.defaultSun.visible = builtin
  if (!builtin) return
  targets.scene.environment = null
  targets.scene.background = targets.builtinBackground.clone()
  targets.programAmbient.visible = false
  targets.programHemisphere.visible = false
}

export function shouldUseOrbitControls(mode: 'builtin' | 'blender', followCamera: boolean): boolean {
  return !(followCamera && mode === 'blender')
}
