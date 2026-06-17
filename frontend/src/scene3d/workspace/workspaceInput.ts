/**
 * Keyboard shortcut resolution for the Scene3D workspace (extracted from scene3d.js).
 */

import type { WorkspaceTransformMode } from './workspaceTypes'

export type WorkspaceKeyboardAction =
  | { type: 'togglePlayback' }
  | { type: 'reloadGlb' }
  | { type: 'goToStart' }
  | { type: 'stepAnimation'; delta: number }
  | { type: 'setTransformMode'; mode: WorkspaceTransformMode }
  | { type: 'deleteSelected' }
  | { type: 'focusSelected' }

export function shouldIgnoreWorkspaceKeyboard(target: EventTarget | null): boolean {
  return Boolean(target && target instanceof Element && target.matches('input, textarea, select'))
}

export function resolveBlenderKeyboardAction(event: KeyboardEvent): WorkspaceKeyboardAction | null {
  if (event.code === 'Space') return { type: 'togglePlayback' }
  if (event.code === 'F5') return { type: 'reloadGlb' }
  if (event.key === 'Home') return { type: 'goToStart' }
  if (event.key === 'ArrowLeft') return { type: 'stepAnimation', delta: event.shiftKey ? -0.5 : -0.1 }
  if (event.key === 'ArrowRight') return { type: 'stepAnimation', delta: event.shiftKey ? 0.5 : 0.1 }
  return null
}

export function resolveBuiltinKeyboardAction(event: KeyboardEvent): WorkspaceKeyboardAction | null {
  const key = event.key.toLowerCase()
  if (key === 'g') return { type: 'setTransformMode', mode: 'translate' }
  if (key === 'r') return { type: 'setTransformMode', mode: 'rotate' }
  if (key === 's') return { type: 'setTransformMode', mode: 'scale' }
  if (key === 'delete') return { type: 'deleteSelected' }
  if (key === 'f') return { type: 'focusSelected' }
  return null
}

export function applyWorkspaceKeyboardAction(
  action: WorkspaceKeyboardAction,
  handlers: {
    togglePlayback(): void
    reloadGlb(): void
    goToStart(): void
    stepAnimation(delta: number): void
    setTransformMode(mode: WorkspaceTransformMode): void
    deleteSelected(): void
    focusSelected(): void
  },
): void {
  switch (action.type) {
    case 'togglePlayback':
      handlers.togglePlayback()
      break
    case 'reloadGlb':
      handlers.reloadGlb()
      break
    case 'goToStart':
      handlers.goToStart()
      break
    case 'stepAnimation':
      handlers.stepAnimation(action.delta)
      break
    case 'setTransformMode':
      handlers.setTransformMode(action.mode)
      break
    case 'deleteSelected':
      handlers.deleteSelected()
      break
    case 'focusSelected':
      handlers.focusSelected()
      break
  }
}
