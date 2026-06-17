/**
 * Public bridge for incremental Scene3D workspace migration.
 * Scene3DEditor UI/DOM remains in scene3d.js until full parity.
 */

import { createWorkspaceOrbitControls, createWorkspaceTransformControls } from './workspaceControls'
import {
  createWorkspacePmremGenerator,
  createWorkspaceRenderer,
  createWorkspaceSceneGraph,
} from './workspaceScene'
import type { WorkspaceTransformMode } from './workspaceTypes'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type ThreeModule = Record<string, any>
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type ThreeObject = any

export type InitWorkspaceEditorThreeOptions = {
  mountEl: HTMLElement
  transformMode?: WorkspaceTransformMode
  onOrbitChange?: () => void
  onTransformDraggingChanged?: (dragging: boolean) => void
  onTransformObjectChange?: () => void
}

export type WorkspaceEditorThreeBoot = {
  renderer: ThreeObject
  scene: ThreeObject
  camera: ThreeObject
  defaultAmbient: ThreeObject
  defaultSun: ThreeObject
  programAmbient: ThreeObject
  programHemisphere: ThreeObject
  grid: ThreeObject
  axes: ThreeObject
  builtinBackground: ThreeObject
  pmremGenerator: ThreeObject
  orbit: ReturnType<typeof createWorkspaceOrbitControls>
  transform: ReturnType<typeof createWorkspaceTransformControls>
}

export function initWorkspaceEditorThree(
  THREE: ThreeModule,
  OrbitControlsCtor: new (camera: unknown, domElement: HTMLElement) => ReturnType<typeof createWorkspaceOrbitControls>,
  TransformControlsCtor: new (camera: unknown, domElement: HTMLElement) => ReturnType<typeof createWorkspaceTransformControls>,
  options: InitWorkspaceEditorThreeOptions,
): WorkspaceEditorThreeBoot {
  const renderer = createWorkspaceRenderer(THREE, options.mountEl)
  const graph = createWorkspaceSceneGraph(THREE)
  const pmremGenerator = createWorkspacePmremGenerator(THREE, renderer)

  const orbit = createWorkspaceOrbitControls(OrbitControlsCtor, graph.camera, renderer.domElement, {
    onChange: options.onOrbitChange,
  })

  const transform = createWorkspaceTransformControls(
    TransformControlsCtor,
    graph.camera,
    renderer.domElement,
    graph.scene,
    {
      mode: options.transformMode ?? 'translate',
      onDraggingChanged: options.onTransformDraggingChanged,
      onObjectChange: options.onTransformObjectChange,
    },
  )

  return { ...graph, renderer, pmremGenerator, orbit, transform }
}
