/**
 * Primitive mesh factory — no preview-style dependencies (safe for static runtime bundle).
 */

import type { WorkspaceObjectSpec, WorkspacePrimitiveType, WorkspaceSceneData, WorkspaceVec3 } from './workspaceTypes'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type ThreeModule = Record<string, any>
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type ThreeObject = any

export const WORKSPACE_PRIMITIVE_TYPE_SET = new Set<string>([
  'cube',
  'sphere',
  'plane',
  'cylinder',
  'cone',
])

export function isWorkspacePrimitiveType(type: string): type is WorkspacePrimitiveType {
  return WORKSPACE_PRIMITIVE_TYPE_SET.has(type)
}

export function makeWorkspaceObjectId(): string {
  const c = globalThis.crypto as Crypto | undefined
  if (c && typeof c.randomUUID === 'function') {
    return c.randomUUID().replace(/-/g, '').slice(0, 12)
  }
  return `obj_${Date.now().toString(36)}${Math.floor(Math.random() * 1e6).toString(36)}`
}

export function vec3From(value: unknown, fallback: WorkspaceVec3 = [0, 0, 0]): WorkspaceVec3 {
  if (Array.isArray(value) && value.length >= 3) {
    return [Number(value[0]) || 0, Number(value[1]) || 0, Number(value[2]) || 0]
  }
  return [...fallback]
}

export function eulerFrom(value: unknown): WorkspaceVec3 {
  return vec3From(value)
}

export function colorFrom(THREE: ThreeModule, value: unknown, fallback = 0x808080): number {
  if (typeof value === 'string' && value.startsWith('#')) {
    return new THREE.Color(value).getHex()
  }
  return fallback
}

export function defaultBuiltinSceneData(): WorkspaceSceneData {
  return {
    source: 'builtin',
    objects: [
      {
        id: 'ground',
        name: 'Ground',
        type: 'plane',
        position: [0, 0, 0],
        rotation: [-Math.PI / 2, 0, 0],
        scale: [10, 10, 1],
        color: '#3a4048',
      },
      {
        id: 'cube1',
        name: 'Cube',
        type: 'cube',
        position: [0, 0.5, 0],
        rotation: [0, 0, 0],
        scale: [1, 1, 1],
        color: '#3d8bfd',
      },
    ],
  }
}

export function defaultAddObjectSpec(
  type: WorkspacePrimitiveType,
  objectCount: number,
  colorHex: string,
): WorkspaceObjectSpec {
  const labels: Record<WorkspacePrimitiveType, string> = {
    cube: 'Cube',
    sphere: 'Sphere',
    plane: 'Plane',
    cylinder: 'Cylinder',
    cone: 'Cone',
  }
  const name = `${labels[type] || 'Object'} ${objectCount + 1}`
  return {
    id: makeWorkspaceObjectId(),
    name,
    type,
    position: [0, type === 'plane' ? 0 : 0.5, 0],
    rotation: type === 'plane' ? [-Math.PI / 2, 0, 0] : [0, 0, 0],
    scale: type === 'plane' ? [4, 4, 1] : [1, 1, 1],
    color: colorHex,
  }
}

export function createPrimitiveMesh(THREE: ThreeModule, spec: WorkspaceObjectSpec): ThreeObject {
  const material = new THREE.MeshStandardMaterial({
    color: colorFrom(THREE, spec.color),
    roughness: 0.55,
    metalness: 0.05,
  })
  let geometry: ThreeObject
  switch (spec.type) {
    case 'sphere':
      geometry = new THREE.SphereGeometry(0.5, 32, 24)
      break
    case 'plane':
      geometry = new THREE.PlaneGeometry(1, 1)
      break
    case 'cylinder':
      geometry = new THREE.CylinderGeometry(0.5, 0.5, 1, 32)
      break
    case 'cone':
      geometry = new THREE.ConeGeometry(0.5, 1, 32)
      break
    default:
      geometry = new THREE.BoxGeometry(1, 1, 1)
      break
  }
  const mesh = new THREE.Mesh(geometry, material)
  mesh.castShadow = spec.type !== 'plane'
  mesh.receiveShadow = spec.type === 'plane'
  mesh.userData.objectId = spec.id
  mesh.userData.objectName = spec.name || spec.type
  mesh.userData.objectType = spec.type
  const [px, py, pz] = vec3From(spec.position, [0, 0.5, 0])
  const [rx, ry, rz] = eulerFrom(spec.rotation)
  const [sx, sy, sz] = vec3From(spec.scale, [1, 1, 1])
  mesh.position.set(px, py, pz)
  mesh.rotation.set(rx, ry, rz)
  mesh.scale.set(sx, sy, sz)
  return mesh
}
