/**
 * Resource disposal helpers for the Scene3D workspace runtime.
 */

import {
  clearWireframeOverlays,
  disposePreviewMaterials as disposePreviewMaterialsImpl,
  type WireframeOverlayResources,
} from '../previewStyle'

import { disposeGeometry, disposeMaterial, disposeObject3DNode } from '../dispose'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type ThreeObject = any

export { disposeGeometry, disposeMaterial, disposeObject3DNode } from '../dispose'

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

export function disposePreviewMaterials(previewMaterials: Set<unknown>): void {
  disposePreviewMaterialsImpl(previewMaterials)
}

export function disposeWorkspaceWireframe(
  roots: unknown[] | unknown,
  resources: WireframeOverlayResources,
): void {
  clearWireframeOverlays(roots, resources)
}

export function disposePrimitiveMesh(mesh: ThreeObject | null | undefined): void {
  if (!mesh) return
  disposeGeometry(mesh.geometry)
  disposeMaterial(mesh.material)
}
