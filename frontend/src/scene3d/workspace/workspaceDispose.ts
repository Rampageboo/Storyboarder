/**
 * Resource disposal helpers for the Scene3D workspace runtime.
 */

import {
  clearWireframeOverlays,
  disposePreviewMaterials as disposePreviewMaterialsViaBridge,
  type PreviewStyleModule,
  type WireframeOverlayResources,
} from '../previewStyleBridge'

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

export function disposePreviewMaterials(previewStyle: PreviewStyleModule, previewMaterials: Set<unknown>): void {
  disposePreviewMaterialsViaBridge(previewStyle, previewMaterials)
}

export function disposeWorkspaceWireframe(
  previewStyle: PreviewStyleModule,
  roots: unknown[] | unknown,
  resources: WireframeOverlayResources,
): void {
  clearWireframeOverlays(previewStyle, roots, resources)
}

export function disposePrimitiveMesh(mesh: ThreeObject | null | undefined): void {
  if (!mesh) return
  disposeGeometry(mesh.geometry)
  disposeMaterial(mesh.material)
}
