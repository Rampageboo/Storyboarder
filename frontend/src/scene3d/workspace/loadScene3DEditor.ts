/**
 * Dynamic loader for the Scene3D workspace editor (still served as scene3d.js until full TS port).
 */

export type Scene3DEditorInstance = {
  loadSceneData: (settings: Record<string, unknown> | null) => Promise<void>
  applyDisplaySettings?: (settings: Record<string, unknown> | null) => void
  setBlendFilePath?: (path?: unknown) => void
  setAnimationTime?: (time: number) => void
  refreshBoardPreview?: () => void
  reloadBlenderScene?: () => Promise<void>
  captureFrameDataUrl?: () => string
  getAnimationState?: () => { time?: number; camera_name?: string; duration?: number }
  getViewState?: () => Record<string, unknown> | null
  exportSceneData?: () => Record<string, unknown>
  pauseAnimation?: () => void
  setFollowCamera?: (enabled: boolean, options?: Record<string, unknown>) => void
  setActiveCamera?: (cameraId: string, showMessage?: boolean) => void
  _resize?: () => void
}

export type Scene3DEditorConstructor = new (
  rootEl: HTMLElement,
  callbacks: Record<string, unknown>,
) => Scene3DEditorInstance

export async function loadScene3DEditorClass(): Promise<Scene3DEditorConstructor> {
  const module = (await import(/* @vite-ignore */ `/static/runtime/scene3d.js?v=${Date.now()}`)) as {
    Scene3DEditor?: Scene3DEditorConstructor
  }
  if (!module.Scene3DEditor) {
    throw new Error('Scene3DEditor export not found in /static/runtime/scene3d.js')
  }
  return module.Scene3DEditor
}
