/**
 * Resource disposal helpers for the Scene3D workspace runtime.
 */

import type { PreviewStyleModule, WireframeOverlayResources } from '../previewStyleBridge'

import { clearWorkspaceWireframeOverlays } from './workspaceObjects'

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

/** Traverse and dispose mesh geometries/materials (mirrors scene3d.js blenderRoot cleanup). */
export function disposeObject3DRoot(root: ThreeObject | null | undefined): void {
  root?.traverse?.((node: ThreeObject) => {
    const original = node.userData?.scene3dOriginalMaterial
    if (original) {
      disposeMaterial(original)
      return
    }
    disposeObject3DNode(node)
  })
}

export function disposePreviewMaterials(previewStyle: PreviewStyleModule, previewMaterials: Set<unknown>): void {
  previewStyle.disposePreviewMaterials(previewMaterials)
}

export function disposeWorkspaceWireframe(
  previewStyle: PreviewStyleModule,
  roots: unknown[] | unknown,
  resources: WireframeOverlayResources,
): void {
  clearWorkspaceWireframeOverlays(previewStyle, roots, resources)
}

export function disposePrimitiveMesh(mesh: ThreeObject | null | undefined): void {
  if (!mesh) return
  disposeGeometry(mesh.geometry)
  disposeMaterial(mesh.material)
}
