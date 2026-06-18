/** Single source of truth for dynamic Three.js + GLTFLoader imports. */

// Dynamic vendor import — Three.js members cannot be statically typed from a URL import.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type ThreeModule = Record<string, any>

export type ThreeRuntime = {
  THREE: ThreeModule
  GLTFLoader: new () => {
    loadAsync(url: string): Promise<{
      scene: unknown
      animations?: unknown[]
    }>
  }
}

let runtimePromise: Promise<ThreeRuntime> | null = null

export function loadThreeRuntime(): Promise<ThreeRuntime> {
  if (!runtimePromise) {
    const threeUrl = '/static/vendor/three/three.module.js'
    const loaderUrl = '/static/vendor/three/GLTFLoader.js'
    runtimePromise = Promise.all([
      import(/* @vite-ignore */ threeUrl) as Promise<ThreeModule>,
      import(/* @vite-ignore */ loaderUrl) as Promise<ThreeModule>,
    ]).then(([THREE, loader]) => ({
      THREE,
      GLTFLoader: loader.GLTFLoader as ThreeRuntime['GLTFLoader'],
    }))
  }
  return runtimePromise
}
