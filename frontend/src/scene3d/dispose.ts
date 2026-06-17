/**
 * Shared Three.js resource disposal helpers for Scene3D workspace and reference GLB loader.
 */

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type ThreeObject = any

function disposeTextureValue(value: unknown): void {
  if (!value || typeof value !== 'object') return
  const item = value as { dispose?: () => void }
  try {
    item.dispose?.()
  } catch {
    // best effort
  }
}

export function disposeMaterial(material: unknown): void {
  const materials = Array.isArray(material) ? material : [material]
  for (const item of materials) {
    if (!item || typeof item !== 'object') continue
    const mat = item as Record<string, unknown>
    for (const key of Object.keys(mat)) {
      disposeTextureValue(mat[key])
    }
    try {
      (mat.dispose as (() => void) | undefined)?.()
    } catch {
      // best effort
    }
  }
}

export function disposeGeometry(geometry: unknown): void {
  try {
    (geometry as { dispose?: () => void } | null | undefined)?.dispose?.()
  } catch {
    // best effort
  }
}

export function disposeObject3DNode(node: ThreeObject): void {
  try {
    disposeGeometry(node.geometry)
    disposeMaterial(node.material)
  } catch {
    // best effort
  }
}

/** Traverse and dispose mesh geometries/materials on a GLB root. */
export function disposeGlbObject(root: ThreeObject | null | undefined): void {
  root?.traverse?.((node: ThreeObject) => {
    disposeObject3DNode(node)
  })
}
