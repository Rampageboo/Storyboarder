import { useEffect, useRef, useState } from 'react'
import { projectFileUrl } from '../api'
import './ReferenceModelPreview.css'

type OrbitControlsInstance = {
  target: { set: (x: number, y: number, z: number) => void; copy: (v: unknown) => void }
  enableDamping: boolean
  update: () => void
  dispose?: () => void
}

type OrbitControlsCtor = new (...args: unknown[]) => OrbitControlsInstance

type GltfLoaderCtor = new () => {
  loadAsync: (url: string) => Promise<{ scene: unknown }>
}

type ThreeLike = Record<string, any>

type ModuleWithOrbit = { OrbitControls: OrbitControlsCtor }
type ModuleWithLoader = { GLTFLoader: GltfLoaderCtor }

export function ReferenceModelPreview({ path, label }: { path: string; label: string }) {
  const rootRef = useRef<HTMLDivElement | null>(null)
  const [message, setMessage] = useState('Loading 3D preview…')

  useEffect(() => {
    let cancelled = false
    let cleanup = () => {}

    async function load() {
      const root = rootRef.current
      if (!root || !path) return
      root.innerHTML = ''
      setMessage('Loading 3D preview…')

      try {
        const THREE = (await import(/* @vite-ignore */ '/static/vendor/three/three.module.js')) as ThreeLike
        const { OrbitControls } = (await import(/* @vite-ignore */ '/static/vendor/three/OrbitControls.js')) as ModuleWithOrbit
        const { GLTFLoader } = (await import(/* @vite-ignore */ '/static/vendor/three/GLTFLoader.js')) as ModuleWithLoader
        if (cancelled) return

        const scene = new THREE.Scene()
        scene.background = new THREE.Color(0x1a1a1a)
        const camera = new THREE.PerspectiveCamera(45, 16 / 9, 0.01, 1000)
        camera.position.set(3, 2, 4)
        const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false })
        renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2))
        renderer.outputColorSpace = THREE.SRGBColorSpace
        root.appendChild(renderer.domElement)

        const controls = new OrbitControls(camera, renderer.domElement)
        controls.enableDamping = true
        controls.target.set(0, 0, 0)

        scene.add(new THREE.AmbientLight(0xffffff, 0.7))
        const key = new THREE.DirectionalLight(0xffffff, 1.2)
        key.position.set(4, 6, 5)
        scene.add(key)
        const fill = new THREE.HemisphereLight(0xdde8ff, 0x303030, 0.45)
        scene.add(fill)

        const loader = new GLTFLoader()
        const gltf = await loader.loadAsync(`${projectFileUrl(path)}&t=${Date.now()}`)
        if (cancelled) return
        const model = gltf.scene
        scene.add(model)

        const box = new THREE.Box3().setFromObject(model)
        if (!box.isEmpty()) {
          const size = box.getSize(new THREE.Vector3())
          const center = box.getCenter(new THREE.Vector3())
          const radius = Math.max(size.x, size.y, size.z) || 1
          controls.target.copy(center)
          camera.position.copy(center.clone().add(new THREE.Vector3(radius * 1.6, radius * 1.1, radius * 1.8)))
          camera.near = Math.max(0.01, radius / 100)
          camera.far = Math.max(100, radius * 30)
          camera.updateProjectionMatrix()
          controls.update()
        }

        const resize = () => {
          const rect = root.getBoundingClientRect()
          const width = Math.max(1, Math.floor(rect.width))
          const height = Math.max(1, Math.floor(rect.height))
          renderer.setSize(width, height, false)
          camera.aspect = width / height
          camera.updateProjectionMatrix()
        }
        const observer = new ResizeObserver(resize)
        observer.observe(root)
        resize()

        let frame = 0
        const animate = () => {
          if (cancelled) return
          controls.update()
          renderer.render(scene, camera)
          frame = window.requestAnimationFrame(animate)
        }
        animate()
        setMessage('')

        cleanup = () => {
          observer.disconnect()
          window.cancelAnimationFrame(frame)
          controls.dispose?.()
          scene.traverse((node: unknown) => {
            const obj = node as { geometry?: { dispose?: () => void }; material?: unknown }
            obj.geometry?.dispose?.()
            const materials = Array.isArray(obj.material) ? obj.material : obj.material ? [obj.material] : []
            for (const material of materials) {
              ;(material as { dispose?: () => void }).dispose?.()
            }
          })
          renderer.dispose()
          renderer.domElement.remove()
        }
      } catch (error) {
        if (!cancelled) setMessage(error instanceof Error ? error.message : '3D preview unavailable')
      }
    }

    void load()
    return () => {
      cancelled = true
      cleanup()
    }
  }, [path])

  return (
    <div className="ref-model-preview" ref={rootRef} aria-label={`3D preview: ${label}`}>
      {message ? <div className="ref-model-preview-message">{message}</div> : null}
    </div>
  )
}
