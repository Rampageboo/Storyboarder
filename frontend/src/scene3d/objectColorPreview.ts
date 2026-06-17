/** Object-color palette/hash/key logic — kept in lockstep with scene3d.js workspace preview. */

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type ThreeMesh = any

export const VIEWPORT_OBJECT_PALETTE = [
  0xc87a6e, 0x6eb87a, 0x6e8ec8, 0xc8b06e, 0xb06ec8, 0x6ec8b8,
  0xc86e8a, 0x8ac86e, 0x6e6ec8, 0xc8946e, 0x6eb0c8, 0xa0c86e,
  0xc87878, 0x78c878, 0x7878c8, 0xc8c878,
]

export function hashString(value: string): number {
  let hash = 0
  for (let i = 0; i < value.length; i += 1) hash = (hash * 31 + value.charCodeAt(i)) | 0
  return Math.abs(hash)
}

export function objectColorKey(mesh: ThreeMesh, root: ThreeMesh): string {
  let node = mesh
  while (node.parent && node.parent !== root) {
    if (node.name) return node.name
    node = node.parent
  }
  return mesh.name || mesh.uuid
}

export function generateObjectColor(seed: string): number {
  return VIEWPORT_OBJECT_PALETTE[hashString(seed) % VIEWPORT_OBJECT_PALETTE.length]
}

/** Replace mesh materials with deterministic object-color preview materials. */
export function applyObjectColorPreviewMaterials(
  THREE: Record<string, any>,
  root: ThreeMesh,
  previewMaterials: ThreeMesh[] = [],
): void {
  const keys = new Set<string>()
  root.traverse((node: ThreeMesh) => {
    if (node?.isMesh) keys.add(objectColorKey(node, root))
  })
  const colorByKey = new Map<string, number>()
  for (const key of [...keys].sort()) colorByKey.set(key, generateObjectColor(key))
  root.traverse((node: ThreeMesh) => {
    if (!node?.isMesh) return
    const key = objectColorKey(node, root)
    const MeshBasicMaterial = THREE.MeshBasicMaterial as new (opts: { color: number }) => ThreeMesh
    const material = new MeshBasicMaterial({ color: colorByKey.get(key) ?? generateObjectColor(key) })
    previewMaterials.push(material)
    node.material = material
    node.frustumCulled = false
  })
}
