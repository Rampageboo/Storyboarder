/**
 * Imported GLB material cache helpers (extracted from scene3d.js).
 */

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type ThreeObject = any

export function cacheImportedMaterialsOnRoot(root: ThreeObject | null | undefined): void {
  root?.traverse?.((node: ThreeObject) => {
    if (!node.isMesh || node.userData.scene3dOriginalMaterial !== undefined) return
    node.userData.scene3dOriginalMaterial = node.material
  })
}

export function restoreImportedMaterialsOnRoot(root: ThreeObject | null | undefined): void {
  root?.traverse?.((node: ThreeObject) => {
    if (!node.isMesh || node.userData.scene3dOriginalMaterial === undefined) return
    node.material = node.userData.scene3dOriginalMaterial
  })
}

export function collectMeshObjectColorKeys(
  root: ThreeObject | null | undefined,
  objectColorKey: (mesh: ThreeObject) => string,
): string[] {
  const keys = new Set<string>()
  root?.traverse?.((node: ThreeObject) => {
    if (node.isMesh) keys.add(objectColorKey(node))
  })
  return [...keys].sort()
}
