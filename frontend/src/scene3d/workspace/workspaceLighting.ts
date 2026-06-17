/**
 * Program lighting state machine for GLB workspace mode.
 */

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type ThreeObject = any

export type ProgramLightingMode = 'auto' | 'on' | 'off'

export type ProgramLightingContext = {
  mode: ProgramLightingMode
  workspaceMode: 'builtin' | 'blender'
  importedLightCount: number
  objectColorPreview: boolean
}

export function normalizeProgramLightingMode(mode: unknown): ProgramLightingMode {
  return mode === 'on' || mode === 'off' ? mode : 'auto'
}

export function shouldUseProgramIbl(ctx: ProgramLightingContext): boolean {
  if (ctx.workspaceMode !== 'blender') return false
  if (ctx.mode === 'off') return false
  return true
}

export function shouldUseProgramFill(ctx: ProgramLightingContext): boolean {
  if (ctx.workspaceMode !== 'blender') return false
  if (ctx.mode === 'off') return false
  if (ctx.mode === 'on') return ctx.importedLightCount === 0
  return ctx.importedLightCount === 0
}

export function shouldUseProgramWeakFill(ctx: ProgramLightingContext): boolean {
  if (ctx.workspaceMode !== 'blender') return false
  if (ctx.mode === 'off') return false
  if (ctx.objectColorPreview) return false
  if (ctx.mode === 'on') return ctx.importedLightCount > 0
  return ctx.importedLightCount > 0
}

export function getEnvMapIntensity(ctx: ProgramLightingContext): number {
  if (!shouldUseProgramIbl(ctx)) return 0
  if (ctx.importedLightCount > 0) return 0.35
  return 1.0
}

export function programLightingReason(ctx: ProgramLightingContext): string {
  if (ctx.mode === 'on') return '手动：环境 + 柔光'
  if (ctx.mode === 'off') return '手动：仅 GLB 灯光'
  if (ctx.importedLightCount > 0) return `自动：GLB ${ctx.importedLightCount} 盏灯 + 弱环境反射`
  return '自动：GLB 无灯，全程序补光'
}

export function programLightingModeLabel(mode: ProgramLightingMode): string {
  switch (mode) {
    case 'on':
      return '始终开启'
    case 'off':
      return '关闭'
    default:
      return '自动'
  }
}

export function buildLightStatusText(ctx: ProgramLightingContext): string {
  const exported =
    ctx.importedLightCount > 0
      ? `GLB 已导出 ${ctx.importedLightCount} 盏灯`
      : 'GLB 未导出灯光（导出时请勾选 Punctual Lights）'
  const ibl = shouldUseProgramIbl(ctx) && !ctx.objectColorPreview ? '环境反射：开' : '环境反射：关'
  const fill = shouldUseProgramFill(ctx)
    ? '柔光补光：开'
    : shouldUseProgramWeakFill(ctx)
      ? '柔光补光：弱'
      : '柔光补光：关'
  const colors = ctx.objectColorPreview ? '对象色：开（不受灯光影响）' : '对象色：关'
  return `${exported} · ${programLightingModeLabel(ctx.mode)} · ${ibl} · ${fill} · ${colors}`
}

export type ProgramLightingTargets = {
  scene: ThreeObject
  programAmbient: ThreeObject
  programHemisphere: ThreeObject
  builtinBackground: ThreeObject
  blenderEnvMap: ThreeObject | null
  ensureBlenderEnvMap: () => ThreeObject
  setImportedLightsVisible: (visible: boolean) => void
}

export function applyWorkspaceProgramLighting(
  THREE: Record<string, unknown>,
  ctx: ProgramLightingContext,
  targets: ProgramLightingTargets,
): void {
  if (ctx.workspaceMode !== 'blender') return
  const useIbl = shouldUseProgramIbl(ctx) && !ctx.objectColorPreview
  const useFill = shouldUseProgramFill(ctx)
  const useWeakFill = shouldUseProgramWeakFill(ctx)
  if (useIbl) {
    targets.scene.environment = targets.ensureBlenderEnvMap()
    targets.scene.background = new (THREE.Color as new (hex: number) => ThreeObject)(0x303030)
  } else if (ctx.objectColorPreview) {
    targets.scene.environment = null
    targets.scene.background = new (THREE.Color as new (hex: number) => ThreeObject)(0x3a3a3a)
  } else {
    targets.scene.environment = null
    targets.scene.background = targets.builtinBackground.clone()
  }
  targets.programAmbient.intensity = useFill ? 0.1 : 0.22
  targets.programAmbient.visible = useFill || useWeakFill
  targets.programHemisphere.visible = useFill
  targets.setImportedLightsVisible(!ctx.objectColorPreview)
}

export function createBlenderEnvMap(
  RoomEnvironment: new () => ThreeObject,
  pmremGenerator: { fromScene(scene: ThreeObject, sigma: number): { texture: ThreeObject } },
): ThreeObject {
  const room = new RoomEnvironment()
  const texture = pmremGenerator.fromScene(room, 0.04).texture
  room.dispose?.()
  return texture
}
