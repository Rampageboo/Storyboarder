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
  if (ctx.mode === 'on') return 'Manual: environment + fill'
  if (ctx.mode === 'off') return 'Manual: Blender lights only'
  if (ctx.importedLightCount > 0) return `Auto: ${ctx.importedLightCount} Blender light(s) + soft reflection`
  return 'Auto: no Blender lights, full fill'
}

export function programLightingModeLabel(mode: ProgramLightingMode): string {
  switch (mode) {
    case 'on':
      return 'Always on'
    case 'off':
      return 'Off'
    default:
      return 'Auto'
  }
}

export function buildLightStatusText(ctx: ProgramLightingContext): string {
  const exported =
    ctx.importedLightCount > 0
      ? `${ctx.importedLightCount} Blender light(s)`
      : 'No Blender lights'
  const ibl = shouldUseProgramIbl(ctx) && !ctx.objectColorPreview ? 'Reflection on' : 'Reflection off'
  const fill = shouldUseProgramFill(ctx)
    ? 'Fill on'
    : shouldUseProgramWeakFill(ctx)
      ? 'Fill soft'
      : 'Fill off'
  const colors = ctx.objectColorPreview ? 'Object colours on' : 'Object colours off'
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
